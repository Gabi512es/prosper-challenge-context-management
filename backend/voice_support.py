"""Voice-only turn protection and auditable session tool traces."""

import asyncio
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from pipecat.frames.frames import (InterruptionFrame, TranscriptionFrame,
    InterimTranscriptionFrame, TTSSpeakFrame, EndFrame, CancelFrame)
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy


class RealWordsStartStrategy(MinWordsUserTurnStartStrategy):
    async def _handle_transcription(self, frame):
        clean = copy.copy(frame)
        clean.text = " ".join(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", frame.text))
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
                row = dict(timestamp=datetime.now(timezone.utc).isoformat(), call_id=call_id,
                    node=builder.current_node, tool=name, arguments=args,
                    result=result[0] if isinstance(result, tuple) else result,
                    error=error, latency_ms=round((monotonic()-started)*1000, 3))
                with output_path.open("a") as stream:
                    stream.write(json.dumps(row, default=str) + "\n")
        return traced
    return wrap
