"""Durable per-LLM-call metrics logging for the voice pipeline."""

import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from pipecat.frames.frames import (
    FunctionCallResultFrame,
    MetricsFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import (
    LLMUsageMetricsData,
    ProcessingMetricsData,
    TTFBMetricsData,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed


class TurnMetricsObserver(BaseObserver):
    """Combine Pipecat metric frames into one append-only JSONL record per LLM call."""

    def __init__(
        self,
        *,
        call_id: str,
        run_id: str,
        node_name: Callable[[], str | None],
        default_model: str,
        output_path: Path,
    ):
        super().__init__()
        self._call_id = call_id
        self._run_id = run_id
        self._node_name = node_name
        self._default_model = default_model
        self._output_path = output_path
        self._frames_seen: set[int] = set()
        self._attribution_frames_seen: set[int] = set()
        self._pending: dict[str, dict] = {}
        self._turn_index = 0
        self._patient_turn = 0
        self._trigger = "startup"

    async def on_push_frame(self, data: FramePushed):
        frame = data.frame
        self._update_attribution(frame)
        if not isinstance(frame, MetricsFrame) or frame.id in self._frames_seen:
            return

        self._frames_seen.add(frame.id)
        for metric in frame.data:
            if not self._is_llm_processor(metric.processor):
                continue

            pending = self._pending.setdefault(
                metric.processor,
                {
                    "node": self._node_name(),
                    "patient_turn": self._patient_turn,
                    "trigger": self._trigger,
                    "model": metric.model or self._default_model,
                    "prompt_tokens": None,
                    "cached_tokens": None,
                    "completion_tokens": None,
                    "ttfb_ms": None,
                },
            )
            if metric.model:
                pending["model"] = metric.model

            if isinstance(metric, TTFBMetricsData):
                pending["ttfb_ms"] = self._milliseconds(metric.value)
            elif isinstance(metric, LLMUsageMetricsData):
                pending["prompt_tokens"] = metric.value.prompt_tokens
                pending["cached_tokens"] = metric.value.cache_read_input_tokens
                pending["completion_tokens"] = metric.value.completion_tokens
            elif isinstance(metric, ProcessingMetricsData):
                if self._is_initial_placeholder(pending, metric.value):
                    self._pending.pop(metric.processor)
                else:
                    self._write_turn(metric.processor, metric.value)

    @staticmethod
    def _is_llm_processor(processor: str) -> bool:
        return "llm" in processor.lower()

    @staticmethod
    def _milliseconds(seconds: float) -> float:
        return round(seconds * 1000, 3)

    @staticmethod
    def _is_initial_placeholder(pending: dict, processing_seconds: float) -> bool:
        """Ignore Pipecat's synthetic zero-valued startup metrics frame."""
        return (
            processing_seconds == 0
            and pending["ttfb_ms"] == 0
            and pending["prompt_tokens"] is None
        )

    def _update_attribution(self, frame) -> None:
        if frame.id in self._attribution_frames_seen:
            return
        if isinstance(frame, UserStoppedSpeakingFrame):
            self._attribution_frames_seen.add(frame.id)
            self._patient_turn += 1
            self._trigger = "patient"
        elif isinstance(frame, FunctionCallResultFrame):
            self._attribution_frames_seen.add(frame.id)
            self._trigger = "tool_result"

    def _write_turn(self, processor: str, processing_seconds: float) -> None:
        pending = self._pending.pop(processor)
        self._turn_index += 1
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self._run_id,
            "call_id": self._call_id,
            "turn": self._turn_index,
            "patient_turn": pending["patient_turn"],
            "trigger": pending["trigger"],
            "node": pending["node"],
            "model": pending["model"],
            "prompt_tokens": pending["prompt_tokens"],
            "cached_tokens": pending["cached_tokens"],
            "completion_tokens": pending["completion_tokens"],
            "usage_status": (
                "reported" if pending["prompt_tokens"] is not None else "unavailable"
            ),
            "latency_ms": self._milliseconds(processing_seconds),
            "ttfb_ms": pending["ttfb_ms"],
        }
        self._append_jsonl(record)

    def _append_jsonl(self, record: dict) -> None:
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        line = (json.dumps(record, separators=(",", ":")) + "\n").encode()
        descriptor = os.open(
            self._output_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, line)
        finally:
            os.close(descriptor)
