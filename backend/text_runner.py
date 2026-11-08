"""Programmatic and interactive text access to the same configured agent."""

import asyncio
import copy
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallsStartedFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    StopFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregatorParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies
from pipecat.utils.time import time_now_iso8601
from pipecat.workers.runner import WorkerRunner

from agent_builder import AgentBuilder
from agent_runtime import DEFAULT_AGENT_FLOW, AgentRuntime, build_agent_runtime
from scheduling_runtime import load_selected_scheduling_agent


@dataclass(frozen=True)
class CapturedTurn:
    assistant_text: str
    tool_calls: tuple[str, ...]
    model_calls: int


@dataclass(frozen=True)
class TextTurnResult:
    """One completed patient turn, including all tools and follow-up generation."""

    assistant_text: str
    node: str
    state: dict
    tool_calls: tuple[str, ...]
    model_calls: int
    call_id: str
    run_id: str
    ended: bool


class FaultConfigurationError(ValueError):
    """A scenario fault is malformed or unsupported."""


@dataclass
class _FaultState:
    mode: str
    tool: str
    code: str
    message: str
    slot_id: str | None = None
    attempts: int = 0
    calls: int = 0
    activated: bool = False


class TextToolFaultInjector:
    """Session-local tool faults supplied by an evaluation scenario."""

    def __init__(
        self,
        faults: list[dict] | None,
        *,
        on_slot_taken: Callable[[str], None] | None = None,
    ):
        self._faults = [self._parse_fault(value) for value in (faults or [])]
        self._on_slot_taken = on_slot_taken

    @property
    def tool_names(self) -> set[str]:
        return {fault.tool for fault in self._faults}

    def wrap(self, tool_name: str, handler: Callable) -> Callable:
        matching = [fault for fault in self._faults if fault.tool == tool_name]
        if not matching:
            return handler

        async def wrapped(args: dict, flow_manager):
            for fault in matching:
                if fault.mode == "error":
                    return self._error_result(fault)
                if args.get("slot_id") != fault.slot_id:
                    continue

                fault.calls += 1
                if not fault.activated:
                    fault.activated = True
                    if self._on_slot_taken:
                        self._on_slot_taken(fault.slot_id)
                if fault.calls <= fault.attempts or self._on_slot_taken is None:
                    return self._error_result(fault)

            return await self._invoke(handler, args, flow_manager)

        return wrapped

    @staticmethod
    async def _invoke(handler: Callable, args: dict, flow_manager):
        parameter_count = len(inspect.signature(handler).parameters)
        if parameter_count == 0:
            return await handler()
        if parameter_count == 1:
            return await handler(args)
        return await handler(args, flow_manager)

    @staticmethod
    def _error_result(fault: _FaultState) -> dict:
        result = {
            "status": "error",
            "code": fault.code,
            "message": fault.message,
            "tool": fault.tool,
            "retryable": False,
        }
        if fault.slot_id:
            result["slot_id"] = fault.slot_id
        return result

    @staticmethod
    def _parse_fault(value: dict) -> _FaultState:
        if not isinstance(value, dict):
            raise FaultConfigurationError("Each scenario fault must be an object.")
        mode = str(value.get("mode", "")).strip().casefold().replace(" ", "_")
        tool = value.get("tool")
        if mode not in {"error", "slot_taken"}:
            raise FaultConfigurationError(f"Unsupported fault mode: {value.get('mode')!r}")
        if not isinstance(tool, str) or not tool:
            raise FaultConfigurationError("Each scenario fault needs a non-empty tool name.")
        if mode == "error":
            return _FaultState(
                mode=mode,
                tool=tool,
                code=value.get("code", "injected_tool_error"),
                message=value.get("message", f"{tool} is unavailable."),
            )

        slot_id = value.get("slot_id")
        attempts = value.get("attempts", 1)
        if not isinstance(slot_id, str) or not slot_id:
            raise FaultConfigurationError("slot_taken faults need a non-empty slot_id.")
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
            raise FaultConfigurationError("slot_taken attempts must be a positive integer.")
        return _FaultState(
            mode=mode,
            tool=tool,
            code="slot_taken",
            message=value.get("message", f"Slot {slot_id} is no longer available."),
            slot_id=slot_id,
            attempts=attempts,
        )


class TextTurnCollector(FrameProcessor):
    """Complete only after a final, tool-free assistant response is downstream."""

    def __init__(self):
        super().__init__(enable_direct_mode=True)
        self._event = asyncio.Event()
        self._collecting = False
        self._text: list[str] = []
        self._tool_calls: list[str] = []
        self._tool_call_ids: set[str] = set()
        self._model_calls = 0
        self._response_has_text = False
        self._response_has_tools = False
        self._error: str | None = None

    def begin_turn(self) -> None:
        if self._collecting and not self._event.is_set():
            raise RuntimeError("A text turn is already in progress.")
        self._event.clear()
        self._collecting = True
        self._text = []
        self._tool_calls = []
        self._tool_call_ids = set()
        self._model_calls = 0
        self._response_has_text = False
        self._response_has_tools = False
        self._error = None

    async def wait(self, timeout: float) -> CapturedTurn:
        await asyncio.wait_for(self._event.wait(), timeout=timeout)
        self._collecting = False
        if self._error:
            raise RuntimeError(self._error)
        return CapturedTurn(
            assistant_text="".join(self._text).strip(),
            tool_calls=tuple(self._tool_calls),
            model_calls=self._model_calls,
        )

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        should_complete = False
        if self._collecting and direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, LLMFullResponseStartFrame):
                self._model_calls += 1
                self._response_has_text = False
                self._response_has_tools = False
            elif isinstance(frame, LLMTextFrame):
                self._text.append(frame.text)
                self._response_has_text = True
            elif isinstance(frame, FunctionCallsStartedFrame):
                self._response_has_tools = True
                for call in frame.function_calls:
                    self._add_tool_call(call.tool_call_id, call.function_name)
            elif isinstance(frame, FunctionCallInProgressFrame):
                self._response_has_tools = True
                self._add_tool_call(frame.tool_call_id, frame.function_name)
            elif isinstance(frame, LLMFullResponseEndFrame):
                should_complete = self._response_has_text and not self._response_has_tools
            elif isinstance(frame, ErrorFrame):
                self._error = frame.error
                should_complete = True
            elif isinstance(frame, (EndFrame, CancelFrame, StopFrame)):
                should_complete = True

        # Forward first. When the waiter resumes, the assistant aggregator has
        # already committed the final text to the shared conversation context.
        await self.push_frame(frame, direction)
        if should_complete:
            self._event.set()

    def _add_tool_call(self, tool_call_id: str, function_name: str) -> None:
        if tool_call_id not in self._tool_call_ids:
            self._tool_call_ids.add(tool_call_id)
            self._tool_calls.append(function_name)


class TextAgentSession:
    """Evaluation-facing interface for a single controlled text conversation."""

    def __init__(
        self,
        *,
        flow_path: Path = DEFAULT_AGENT_FLOW,
        builder: AgentBuilder | None = None,
        metrics_log: Path | None = None,
        call_id: str | None = None,
        run_id: str | None = None,
        faults: list[dict] | None = None,
        on_slot_taken: Callable[[str], None] | None = None,
        turn_timeout: float = 30.0,
    ):
        builder = builder or AgentBuilder.from_json(flow_path)
        self._fault_injector = TextToolFaultInjector(
            faults,
            on_slot_taken=on_slot_taken,
        )
        if faults:
            unknown_tools = self._fault_injector.tool_names - builder.function_names
            if unknown_tools:
                raise FaultConfigurationError(
                    f"Scenario faults reference unknown tools: {sorted(unknown_tools)}"
                )
            builder.set_function_handler_wrapper(self._fault_injector.wrap)
        self._collector = TextTurnCollector()
        self._runtime: AgentRuntime = build_agent_runtime(
            builder=builder,
            user_params=LLMUserAggregatorParams(
                user_turn_strategies=ExternalUserTurnStrategies()
            ),
            output_processors=[self._collector],
            call_id=call_id,
            run_id=run_id,
            metrics_log=metrics_log,
        )
        self._runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)
        self._runner_task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._runner_error: str | None = None
        self._turn_timeout = turn_timeout
        self._started = False
        self._closed = False
        self._turn_lock = asyncio.Lock()

        @self._runner.event_handler("on_ready")
        async def on_ready(runner):
            self._ready.set()

        @self._runner.event_handler("on_error")
        async def on_error(runner, error):
            self._runner_error = str(error)
            self._ready.set()

    @property
    def call_id(self) -> str:
        return self._runtime.call_id

    @property
    def run_id(self) -> str:
        return self._runtime.run_id

    @property
    def metrics_log(self) -> Path:
        return self._runtime.metrics_log

    @property
    def context_messages(self) -> list[dict]:
        """A snapshot suitable for evaluation assertions."""
        return copy.deepcopy(self._runtime.flow_manager.get_current_context())

    async def start(self) -> TextTurnResult:
        """Start the pipeline and return its real initial assistant turn."""
        async with self._turn_lock:
            if self._started:
                raise RuntimeError("The text session has already started.")
            if self._closed:
                raise RuntimeError("The text session is closed.")

            await self._runner.add_workers(self._runtime.worker)
            self._runner_task = asyncio.create_task(self._runner.run())
            await asyncio.wait_for(self._ready.wait(), timeout=10.0)
            if self._runner_error:
                raise RuntimeError(f"Text pipeline failed to start: {self._runner_error}")

            self._started = True
            self._collector.begin_turn()
            await self._runtime.initialize()
            captured = await self._collector.wait(self._turn_timeout)
            return self._result(captured)

    async def send(self, patient_text: str) -> TextTurnResult:
        """Send one patient turn and wait through tools, transitions, and reply."""
        if not patient_text.strip():
            raise ValueError("patient_text must not be blank.")

        async with self._turn_lock:
            if not self._started:
                raise RuntimeError("Call start() before send().")
            if self._closed or self._runtime.worker.has_finished():
                raise RuntimeError("The text session has ended.")

            self._collector.begin_turn()
            await self._runtime.worker.queue_frames(
                [
                    UserStartedSpeakingFrame(),
                    TranscriptionFrame(
                        patient_text,
                        "text-patient",
                        time_now_iso8601(),
                    ),
                    UserStoppedSpeakingFrame(),
                ]
            )
            captured = await self._collector.wait(self._turn_timeout)
            return self._result(captured)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._started or not self._runner_task:
            return
        if not self._runtime.worker.has_finished():
            await self._runner.stop_when_done()
        try:
            await asyncio.wait_for(asyncio.shield(self._runner_task), timeout=5.0)
        except TimeoutError:
            await self._runner.cancel("text session close timeout")
            await self._runner_task

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        await self.close()

    def _result(self, captured: CapturedTurn) -> TextTurnResult:
        node = self._runtime.flow_manager.current_node or self._runtime.builder.current_node
        return TextTurnResult(
            assistant_text=captured.assistant_text,
            node=node,
            state=dict(self._runtime.flow_manager.state),
            tool_calls=captured.tool_calls,
            model_calls=captured.model_calls,
            call_id=self.call_id,
            run_id=self.run_id,
            ended=self._runtime.builder.current_node_is_terminal,
        )


async def _interactive() -> None:
    builder, _engine = load_selected_scheduling_agent()
    session = TextAgentSession(builder=builder)
    try:
        result = await session.start()
        print(f"Assistant: {result.assistant_text}")
        while not result.ended:
            try:
                patient_text = await asyncio.to_thread(input, "Patient: ")
            except EOFError:
                break
            if patient_text.strip().lower() in {"quit", "exit"}:
                break
            result = await session.send(patient_text)
            print(f"Assistant: {result.assistant_text}")
    finally:
        await session.close()


if __name__ == "__main__":
    try:
        asyncio.run(_interactive())
    except KeyboardInterrupt:
        pass
