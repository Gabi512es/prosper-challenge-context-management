"""Shared construction for every way of running the configured agent."""

import os
import re
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (InterruptionFrame, LLMFullResponseStartFrame,
                                  LLMFullResponseEndFrame, LLMTextFrame)
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport
from pipecat_flows import FlowManager

from agent_builder import AgentBuilder
from metrics_logging import TurnMetricsObserver
from scheduling_dialogue import PatientInput, BookingSpeech, ReadbackDelivery


BACKEND_DIR = Path(__file__).parent
DEFAULT_AGENT_FLOW = BACKEND_DIR / "example_flow.json"
DEFAULT_METRICS_LOG = BACKEND_DIR / "logs" / "turns.jsonl"
DEFAULT_EVAL_LOG_DIR = BACKEND_DIR / "logs" / "evals"

# Keep key loading identical for voice, text, tests, and future harnesses.
load_dotenv(BACKEND_DIR / ".env", override=True)


class ToolAwareOpenAILLMService(OpenAILLMService):
    """Keep tool-only request parameters out of nodes without tools."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._response = ContextVar('scheduling_response', default=None)
        self._interruption_epoch = 0

    async def process_frame(self, frame, direction):
        if isinstance(frame, InterruptionFrame):
            # Advance before the base class cancels the old request. Its finally
            # block still emits an end frame, but that is not an empty reply.
            self._interruption_epoch += 1
        await super().process_frame(frame, direction)

    def build_chat_completion_params(self, params_from_context):
        params = super().build_chat_completion_params(params_from_context)
        if not params.get("tools"):
            params.pop("parallel_tool_calls", None)
        return params

    async def run_function_calls(self, function_calls):
        response = self._response.get()
        if function_calls and response is not None:
            response['has_tools'] = True
        await super().run_function_calls(function_calls)

    async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        # FunctionCallsStartedFrame is a priority system frame: it can overtake
        # response-start and then be forgotten by downstream response filters.
        # Attach the producer's decision to the ordered response-end instead.
        if isinstance(frame, LLMFullResponseStartFrame):
            self._response.set(dict(id=frame.id, has_tools=False, epoch=self._interruption_epoch))
        response = self._response.get()
        if response is not None and isinstance(frame, (LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame)):
            frame.response_id = response['id']
            if isinstance(frame, LLMFullResponseEndFrame):
                frame.has_tool_calls = response['has_tools']
                frame.interrupted = response['epoch'] != self._interruption_epoch
        await super().push_frame(frame, direction)


@dataclass
class AgentRuntime:
    """The shared agent core plus its Pipecat execution objects."""

    builder: AgentBuilder
    call_id: str
    run_id: str
    metrics_log: Path
    context: LLMContext
    context_aggregator: LLMContextAggregatorPair
    llm: OpenAILLMService
    worker: PipelineWorker
    flow_manager: FlowManager

    async def initialize(self) -> None:
        """Start the configured graph without manufacturing a user message."""
        await self.flow_manager.initialize(self.builder.build_initial_node())


def build_agent_runtime(
    *,
    builder: AgentBuilder,
    user_params: LLMUserAggregatorParams,
    input_processors: list[FrameProcessor] | None = None,
    output_processors: list[FrameProcessor] | None = None,
    transport: BaseTransport | None = None,
    call_id: str | None = None,
    run_id: str | None = None,
    metrics_log: Path | None = None,
    idle_timeout_secs: float | None = None,
) -> AgentRuntime:
    """Build one agent pipeline while allowing only I/O processors to vary."""
    if {"find_slots", "book_appointment"}.intersection(builder.function_names) and not hasattr(builder, "dialogue"):
        raise ValueError("Scheduling tools require their policy-bearing registry; refusing an unguarded runtime.")
    call_id = call_id or str(uuid4())
    requested_run_id = run_id or os.getenv("EVAL_RUN_ID")
    run_id = requested_run_id or call_id
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise ValueError("run_id may contain only letters, numbers, '.', '_' and '-'.")
    if metrics_log is None:
        configured_log = os.getenv("METRICS_LOG_PATH")
        if configured_log:
            metrics_log = Path(configured_log)
        elif requested_run_id:
            metrics_log = DEFAULT_EVAL_LOG_DIR / f"{run_id}.jsonl"
        else:
            metrics_log = DEFAULT_METRICS_LOG

    llm = ToolAwareOpenAILLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAILLMService.Settings(model=builder.config.model, extra={"parallel_tool_calls": False}),
    )
    context = LLMContext()
    context_aggregator = LLMContextAggregatorPair(context, user_params=user_params)

    pipeline = Pipeline(
        [
            *(input_processors or []),
            *([PatientInput(builder.dialogue)] if hasattr(builder, "dialogue") else []),
            context_aggregator.user(),
            llm,
            *([BookingSpeech(builder.dialogue, audio_delivery=transport is not None)] if hasattr(builder, "dialogue") else []),
            *(output_processors or []),
            *([ReadbackDelivery(builder.dialogue)] if hasattr(builder, "dialogue") and transport is not None else []),
            context_aggregator.assistant(),
        ]
    )
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        observers=[
            TurnMetricsObserver(
                call_id=call_id,
                run_id=run_id,
                node_name=lambda: builder.current_node,
                default_model=builder.config.model,
                output_path=metrics_log,
                session_metadata=getattr(builder, "session_metadata", None),
            )
        ],
        conversation_id=call_id,
        idle_timeout_secs=idle_timeout_secs,
    )
    flow_manager = FlowManager(
        llm=llm,
        context_aggregator=context_aggregator,
        worker=worker,
        transport=transport,
    )
    return AgentRuntime(
        builder=builder,
        call_id=call_id,
        run_id=run_id,
        metrics_log=metrics_log,
        context=context,
        context_aggregator=context_aggregator,
        llm=llm,
        worker=worker,
        flow_manager=flow_manager,
    )
