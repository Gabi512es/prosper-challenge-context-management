import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pipecat.frames.frames import TranscriptionFrame
from voice_support import VOICE_MIN_WORDS, RealWordsStartStrategy, tool_trace_wrapper


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

    async def test_short_real_answer_while_agent_speaks_starts_a_turn(self):
        for answer in ("No", "Stop.", "Midtown", "Yes!", "no..."):
            strategy = RealWordsStartStrategy(min_words=VOICE_MIN_WORDS)
            strategy._bot_speaking = True  # e.g. mid slot read-back
            strategy.trigger_user_turn_started = AsyncMock()
            strategy.trigger_reset_aggregation = AsyncMock()
            await strategy._handle_transcription(TranscriptionFrame(answer, "", ""))
            strategy.trigger_user_turn_started.assert_awaited_once()
            strategy.trigger_reset_aggregation.assert_not_awaited()

    async def test_fillers_and_noise_while_agent_speaks_do_not_interrupt(self):
        for noise in ("。 。", "um", "Mm-hmm.", "uh huh", "hmm..."):
            strategy = RealWordsStartStrategy(min_words=VOICE_MIN_WORDS)
            strategy._bot_speaking = True
            strategy.trigger_user_turn_started = AsyncMock()
            strategy.trigger_reset_aggregation = AsyncMock()
            await strategy._handle_transcription(TranscriptionFrame(noise, "", ""))
            strategy.trigger_user_turn_started.assert_not_awaited()

    async def test_trace_records_actual_tool_result_and_arguments(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "trace.jsonl"
            wrapped = tool_trace_wrapper("call", SimpleNamespace(current_node="scheduling"), path)(
                "resolve_options", AsyncMock(return_value={"status": "blocked"}))
            await wrapped({"location_query": "Midtown"}, None)
            row = json.loads(path.read_text())
            self.assertEqual(row["arguments"], {"location_query": "Midtown"})
            self.assertEqual(row["result"], {"status": "blocked"})
            self.assertRegex(row["git_commit"], r"^[a-f0-9]{40}$")
            self.assertEqual(row["code_version"], "scheduling-booking-v4")
            self.assertRegex(row["code_revision"], r"^[a-f0-9]{64}$")
