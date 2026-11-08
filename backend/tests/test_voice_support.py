import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pipecat.frames.frames import TranscriptionFrame
from voice_support import RealWordsStartStrategy, tool_trace_wrapper


class VoiceSupportTest(unittest.IsolatedAsyncioTestCase):
    async def test_noise_punctuation_does_not_interrupt_but_two_words_do(self):
        strategy = RealWordsStartStrategy(min_words=2)
        strategy._bot_speaking = True
        strategy.trigger_user_turn_started = AsyncMock()
        strategy.trigger_reset_aggregation = AsyncMock()
        await strategy._handle_transcription(TranscriptionFrame("。 。", "", ""))
        strategy.trigger_user_turn_started.assert_not_awaited()
        await strategy._handle_transcription(TranscriptionFrame("Mission Bay", "", ""))
        strategy.trigger_user_turn_started.assert_awaited_once()

    async def test_trace_records_actual_tool_result_and_arguments(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "trace.jsonl"
            wrapped = tool_trace_wrapper("call", SimpleNamespace(current_node="scheduling"), path)(
                "resolve_options", AsyncMock(return_value={"status": "blocked"}))
            await wrapped({"location_query": "Midtown"}, None)
            row = json.loads(path.read_text())
            self.assertEqual(row["arguments"], {"location_query": "Midtown"})
            self.assertEqual(row["result"], {"status": "blocked"})
