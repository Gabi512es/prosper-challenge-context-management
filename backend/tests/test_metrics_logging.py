import json
import tempfile
import unittest
from pathlib import Path

from pipecat.frames.frames import (
    FunctionCallResultFrame,
    MetricsFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import (
    LLMTokenUsage,
    LLMUsageMetricsData,
    ProcessingMetricsData,
    TTFBMetricsData,
)
from pipecat.observers.base_observer import FramePushed

from metrics_logging import TurnMetricsObserver


class TurnMetricsObserverTest(unittest.IsolatedAsyncioTestCase):
    async def test_combines_llm_metrics_into_one_line(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "turns.jsonl"
            active_node = "greeting"
            observer = TurnMetricsObserver(
                call_id="call-123",
                run_id="run-abc",
                node_name=lambda: active_node,
                default_model="gpt-4o",
                output_path=output_path,
            )

            ttfb = MetricsFrame(
                data=[
                    TTFBMetricsData(
                        processor="OpenAILLMService#0",
                        model="gpt-4o-2024-11-20",
                        value=0.1234,
                    )
                ]
            )
            usage = MetricsFrame(
                data=[
                    LLMUsageMetricsData(
                        processor="OpenAILLMService#0",
                        model="gpt-4o-2024-11-20",
                        value=LLMTokenUsage(
                            prompt_tokens=100,
                            cache_read_input_tokens=80,
                            completion_tokens=20,
                            total_tokens=120,
                        ),
                    )
                ]
            )
            processing = MetricsFrame(
                data=[
                    ProcessingMetricsData(
                        processor="OpenAILLMService#0",
                        model="gpt-4o-2024-11-20",
                        value=0.4567,
                    )
                ]
            )

            await observer.on_push_frame(self._event(ttfb))
            await observer.on_push_frame(self._event(ttfb))
            await observer.on_push_frame(self._event(usage))
            active_node = "collect_details"
            await observer.on_push_frame(self._event(processing))

            records = [json.loads(line) for line in output_path.read_text().splitlines()]
            self.assertEqual(len(records), 1)
            self.assertEqual(
                {
                    key: records[0][key]
                    for key in (
                        "call_id",
                        "run_id",
                        "turn",
                        "patient_turn",
                        "trigger",
                        "node",
                        "model",
                        "prompt_tokens",
                        "cached_tokens",
                        "completion_tokens",
                        "usage_status",
                        "latency_ms",
                        "ttfb_ms",
                    )
                },
                {
                    "call_id": "call-123",
                    "run_id": "run-abc",
                    "turn": 1,
                    "patient_turn": 0,
                    "trigger": "startup",
                    "node": "greeting",
                    "model": "gpt-4o-2024-11-20",
                    "prompt_tokens": 100,
                    "cached_tokens": 80,
                    "completion_tokens": 20,
                    "usage_status": "reported",
                    "latency_ms": 456.7,
                    "ttfb_ms": 123.4,
                },
            )

    async def test_unknown_cached_usage_is_null(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "turns.jsonl"
            observer = TurnMetricsObserver(
                call_id="call-456",
                run_id="run-456",
                node_name=lambda: "greeting",
                default_model="gpt-4o",
                output_path=output_path,
            )
            usage = MetricsFrame(
                data=[
                    LLMUsageMetricsData(
                        processor="OpenAILLMService#0",
                        value=LLMTokenUsage(
                            prompt_tokens=10,
                            completion_tokens=2,
                            total_tokens=12,
                        ),
                    )
                ]
            )
            processing = MetricsFrame(
                data=[ProcessingMetricsData(processor="OpenAILLMService#0", value=0.1)]
            )

            await observer.on_push_frame(self._event(usage))
            await observer.on_push_frame(self._event(processing))

            record = json.loads(output_path.read_text())
            self.assertIsNone(record["cached_tokens"])
            self.assertEqual(record["usage_status"], "reported")

    async def test_marks_missing_llm_usage_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "turns.jsonl"
            observer = TurnMetricsObserver(
                call_id="call-interrupted",
                run_id="run-interrupted",
                node_name=lambda: "collect_details",
                default_model="gpt-4o",
                output_path=output_path,
            )
            ttfb = MetricsFrame(
                data=[TTFBMetricsData(processor="OpenAILLMService#0", value=0.2)]
            )
            processing = MetricsFrame(
                data=[ProcessingMetricsData(processor="OpenAILLMService#0", value=0.3)]
            )

            await observer.on_push_frame(self._event(ttfb))
            await observer.on_push_frame(self._event(processing))

            record = json.loads(output_path.read_text())
            self.assertEqual(record["usage_status"], "unavailable")
            self.assertIsNone(record["prompt_tokens"])

    async def test_ignores_pipecat_initial_zero_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "turns.jsonl"
            observer = TurnMetricsObserver(
                call_id="call-789",
                run_id="run-789",
                node_name=lambda: "greeting",
                default_model="gpt-4o",
                output_path=output_path,
            )
            initial = MetricsFrame(
                data=[
                    TTFBMetricsData(processor="OpenAILLMService#0", value=0.0),
                    ProcessingMetricsData(processor="OpenAILLMService#0", value=0.0),
                ]
            )

            await observer.on_push_frame(self._event(initial))

            self.assertFalse(output_path.exists())

    async def test_attributes_patient_and_post_tool_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "turns.jsonl"
            observer = TurnMetricsObserver(
                call_id="call-attribution",
                run_id="run-attribution",
                node_name=lambda: "collect_details",
                default_model="gpt-4o",
                output_path=output_path,
            )

            await observer.on_push_frame(self._event(UserStoppedSpeakingFrame()))
            await observer.on_push_frame(self._event(self._processing(0.2)))
            await observer.on_push_frame(
                self._event(
                    FunctionCallResultFrame(
                        "record_details",
                        "tool-1",
                        {"full_name": "Ana Torres"},
                        {"status": "success"},
                    )
                )
            )
            await observer.on_push_frame(self._event(self._processing(0.3)))

            records = [json.loads(line) for line in output_path.read_text().splitlines()]
            self.assertEqual(
                [(r["patient_turn"], r["trigger"]) for r in records],
                [(1, "patient"), (1, "tool_result")],
            )

    @staticmethod
    def _processing(value: float) -> MetricsFrame:
        return MetricsFrame(
            data=[ProcessingMetricsData(processor="OpenAILLMService#0", value=value)]
        )

    @staticmethod
    def _event(frame) -> FramePushed:
        return FramePushed(
            source=None,
            destination=None,
            frame=frame,
            direction=None,
            timestamp=0,
        )
