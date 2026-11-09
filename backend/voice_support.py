"""Voice-only turn protection and auditable session tool traces."""

import asyncio
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from code_identity import GIT_COMMIT, CODE_VERSION, CODE_REVISION

from pipecat.frames.frames import (InterruptionFrame, TranscriptionFrame,
    InterimTranscriptionFrame, TTSSpeakFrame, EndFrame, CancelFrame)
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy


# Hesitation and backchannel sounds carry no answer. Everything else, including
# one-word replies such as "No", "Stop", "Yes" or "Midtown", is a real answer.
FILLER_WORDS = frozenset(
    {"uh", "um", "umm", "uhm", "er", "erm", "ah", "eh", "hm", "hmm", "mm", "mmm", "mhm", "huh"}
)


# Used by bot.py. Any higher value silently drops shorter replies while the
# agent is speaking, because Pipecat resets the aggregation below the threshold.
VOICE_MIN_WORDS = 1


def real_words(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:[/:.-]\d+)*(?:st|nd|rd|th)?", text)
    return [word for word in words if word.casefold() not in FILLER_WORDS]


class RealWordsStartStrategy(MinWordsUserTurnStartStrategy):
    """Start a user turn on real words only.

    Below ``min_words`` Pipecat resets the user aggregation, which discards the
    transcript, so the voice entrypoint uses ``VOICE_MIN_WORDS`` (1): a single real word
    interrupts, while punctuation noise and filler sounds never do.
    """

    async def _handle_transcription(self, frame):
        clean = copy.copy(frame)
        clean.text = " ".join(real_words(frame.text))
        return await super()._handle_transcription(clean)


class InterruptedSilenceRecovery(FrameProcessor):
    def __init__(self):
        super().__init__()
        self.pending = None
        self.last_words_at = float("-inf")

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame)) and re.search(r"[A-Za-z]", frame.text):
            self.last_words_at = monotonic()
            if self.pending:
                self.pending.cancel()
                self.pending = None
        elif isinstance(frame, InterruptionFrame):
            if self.pending:
                self.pending.cancel()
            # A transcript-triggered interruption already has meaningful speech.
            # Recover only a cut-off without a recent real transcription.
            if monotonic() - self.last_words_at > 1.0:
                self.pending = asyncio.create_task(self._recover())
        elif isinstance(frame, (EndFrame, CancelFrame)) and self.pending:
            self.pending.cancel()
        await self.push_frame(frame, direction)

    async def _recover(self):
        await asyncio.sleep(2.5)
        await self.push_frame(TTSSpeakFrame("Sorry, I think I got cut off, how can I help?"))


def tool_trace_wrapper(call_id, builder, output_path: Path):
    def wrap(name, handler):
        async def traced(args, manager):
            started = monotonic()
            result = None
            error = None
            try:
                result = await handler(args, manager)
                return result
            except Exception as exc:
                error = repr(exc)
                raise
            finally:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                metadata = getattr(builder, "session_metadata", None) or {}
                row = dict(timestamp=datetime.now(timezone.utc).isoformat(), call_id=call_id,
                    git_commit=GIT_COMMIT, code_version=CODE_VERSION, code_revision=CODE_REVISION,
                    agent_id=metadata.get("agent_id"),
                    agent_revision=metadata.get("agent_revision"),
                    availability_mode=metadata.get("availability_mode"),
                    node=builder.current_node, tool=name, arguments=args,
                    result=result[0] if isinstance(result, tuple) else result,
                    error=error, latency_ms=round((monotonic()-started)*1000, 3))
                with output_path.open("a") as stream:
                    stream.write(json.dumps(row, default=str) + "\n")
        return traced
    return wrap
