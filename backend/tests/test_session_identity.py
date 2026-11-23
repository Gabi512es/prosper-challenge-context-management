"""Every session log names the agent revision and availability source it ran."""

import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pipecat.frames.frames import MetricsFrame
from pipecat.metrics.metrics import (
    LLMTokenUsage,
    LLMUsageMetricsData,
    ProcessingMetricsData,
)
from pipecat.observers.base_observer import FramePushed

from metrics_logging import TurnMetricsObserver
from scheduling import SchedulingEngine, load_catalog
from scheduling_agent import DEFAULT_SCHEDULING_AGENT_PATH, build_scheduling_agent
from scheduling_runtime import load_selected_scheduling_agent
from voice_support import tool_trace_wrapper


BACKEND_DIR = Path(__file__).parents[1]
NOW = datetime.fromisoformat("2026-11-07T00:00:00-08:00")


class SessionIdentityTest(unittest.IsolatedAsyncioTestCase):
    def test_text_and_voice_loaders_report_same_revision_of_same_json(self):
        catalog = load_catalog(BACKEND_DIR / "data" / "catalog.json")
        text_builder = build_scheduling_agent(
            SchedulingEngine(catalog, [], now=NOW), catalog, availability_mode="eval_fixture"
        )
        voice_builder, _engine = load_selected_scheduling_agent(
            flow_path=DEFAULT_SCHEDULING_AGENT_PATH, now=NOW
        )
        expected = hashlib.sha256(DEFAULT_SCHEDULING_AGENT_PATH.read_bytes()).hexdigest()

        self.assertEqual(text_builder.session_metadata["agent_id"], "catalog_scheduler")
        self.assertEqual(text_builder.session_metadata["agent_revision"], expected)
        self.assertEqual(voice_builder.session_metadata["agent_id"], "catalog_scheduler")
        self.assertEqual(voice_builder.session_metadata["agent_revision"], expected)
        self.assertEqual(text_builder.session_metadata["availability_mode"], "eval_fixture")
        self.assertEqual(voice_builder.session_metadata["availability_mode"], "demo_generated")

    def test_any_edit_changes_the_revision(self):
        catalog = load_catalog(BACKEND_DIR / "data" / "catalog.json")
        data = json.loads(DEFAULT_SCHEDULING_AGENT_PATH.read_text())
        data["nodes"][0]["task_messages"][0]["content"] += " Edited."
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog_scheduler.json"
            path.write_text(json.dumps(data))
            edited = build_scheduling_agent(
                SchedulingEngine(catalog, [], now=NOW),
                catalog,
                flow_path=path,
                availability_mode="eval_fixture",
            )
        original = hashlib.sha256(DEFAULT_SCHEDULING_AGENT_PATH.read_bytes()).hexdigest()
        self.assertEqual(edited.session_metadata["agent_id"], "catalog_scheduler")
        self.assertNotEqual(edited.session_metadata["agent_revision"], original)

    async def test_metrics_rows_carry_identity_and_unknown_stays_null(self):
        metadata = {
            "agent_id": "catalog_scheduler",
            "agent_revision": "abc123",
            "availability_mode": "demo_generated",
        }
        with tempfile.TemporaryDirectory() as directory:
            for given, expected in ((metadata, metadata), (None, dict.fromkeys(metadata))):
                path = Path(directory) / f"turns-{given is None}.jsonl"
                observer = TurnMetricsObserver(
                    call_id="call",
                    run_id="run",
                    node_name=lambda: "scheduling",
                    default_model="gpt-4o",
                    output_path=path,
                    session_metadata=given,
                )
                for data in (
                    LLMUsageMetricsData(
                        processor="OpenAILLMService#0",
                        model="gpt-4o",
                        value=LLMTokenUsage(
                            prompt_tokens=10, completion_tokens=2, total_tokens=12
                        ),
                    ),
                    ProcessingMetricsData(
                        processor="OpenAILLMService#0", model="gpt-4o", value=0.2
                    ),
                ):
                    frame = MetricsFrame(data=[data])
                    await observer.on_push_frame(
                        FramePushed(
                            source=None,
                            destination=None,
                            frame=frame,
                            direction=None,
                            timestamp=0,
                        )
                    )
                row = json.loads(path.read_text().splitlines()[0])
                self.assertEqual({key: row[key] for key in metadata}, expected)

    async def test_voice_tool_trace_rows_carry_identity(self):
        metadata = {
            "agent_id": "catalog_scheduler",
            "agent_revision": "abc123",
            "availability_mode": "demo_generated",
        }
        builder = SimpleNamespace(current_node="scheduling", session_metadata=metadata)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voice-tools.jsonl"
            traced = tool_trace_wrapper("call", builder, path)(
                "resolve_options", AsyncMock(return_value={"status": "ok"})
            )
            await traced({}, None)
            row = json.loads(path.read_text())
        self.assertEqual({key: row[key] for key in metadata}, metadata)


if __name__ == "__main__":
    unittest.main()
