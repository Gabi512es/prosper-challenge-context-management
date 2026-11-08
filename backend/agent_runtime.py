"""Shared construction for every way of running the configured agent."""

import os
import re
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
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport
from pipecat_flows import FlowManager

from agent_builder import AgentBuilder
from metrics_logging import TurnMetricsObserver


BACKEND_DIR = Path(__file__).parent
DEFAULT_AGENT_FLOW = BACKEND_DIR / "example_flow.json"
DEFAULT_METRICS_LOG = BACKEND_DIR / "logs" / "turns.jsonl"
DEFAULT_EVAL_LOG_DIR = BACKEND_DIR / "logs" / "evals"

# Keep key loading identical for voice, text, tests, and future harnesses.
load_dotenv(BACKEND_DIR / ".env", override=True)


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

    llm = OpenAILLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAILLMService.Settings(model=builder.config.model),
    )
    context = LLMContext()
    context_aggregator = LLMContextAggregatorPair(context, user_params=user_params)

    pipeline = Pipeline(
        [
            *(input_processors or []),
            context_aggregator.user(),
            llm,
            *(output_processors or []),
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
