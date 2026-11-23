"""Pipecat I/O only: raw finals in, one code-composed speech attempt out."""
import asyncio
from dataclasses import dataclass

from pipecat.frames.frames import (DataFrame, TTSSpeakFrame, TTSAudioRawFrame, InterruptionFrame,
    TranscriptionFrame, UserStartedSpeakingFrame, UserStoppedSpeakingFrame, LLMContextFrame,
    CancelFrame, EndFrame)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregator


@dataclass
class SpeakAttempt(TTSSpeakFrame):
    attempt_id: str = ''


@dataclass
class PlaybackMarker(DataFrame):
    attempt_id: str


@dataclass
class AudioAttemptBoundary(DataFrame):
    """Ordered beside audio; survives the transport's audio re-chunking."""
    attempt_id: str | None


class AudioAttemptTagger(FrameProcessor):
    """Before transport: resolve context IDs while they are still present."""
    def __init__(self,delivery):
        super().__init__()
        self.delivery=delivery

    async def process_frame(self,frame,direction):
        await super().process_frame(frame,direction)
        if direction==FrameDirection.DOWNSTREAM and isinstance(frame,TTSAudioRawFrame):
            attempt=self.delivery.context_attempt.get(frame.context_id)
            if self.delivery.session.attempts.get(attempt)!='pending':attempt=None
            boundary=AudioAttemptBoundary(attempt)
            boundary.transport_destination=frame.transport_destination
            # The installed output transport queues this DataFrame before
            # chunks produced from the following audio. Unknown/stale audio
            # gets an explicit null boundary, never the newer active attempt.
            await self.push_frame(boundary)
        await self.push_frame(frame,direction)


class EndpointAggregator(LLMUserAggregator):
    """VAD/turn detection only; endpoint changes inline, not delayed callbacks."""
    def __init__(self,context,session,*,params):
        super().__init__(context,params=params)
        self.session=session

    async def _on_user_turn_started(self,*args):
        self.session.endpoint(False)
        await super()._on_user_turn_started(*args)

    async def _on_user_turn_stopped(self,*args):
        epoch=self.session.input_epoch
        await super()._on_user_turn_stopped(*args)
        if epoch==self.session.input_epoch:
            self.session.endpoint(True)


class FinalInput(FrameProcessor):
    """Before the user aggregator: no final waits for its context aggregation."""
    def __init__(self, session):
        super().__init__()
        self.session = session

    def _capture(self,frame,direction):
        if isinstance(frame,InterruptionFrame):
            self.session.interrupt()
        elif isinstance(frame,UserStartedSpeakingFrame):
            self.session.endpoint(False)
        elif isinstance(frame,TranscriptionFrame) and direction==FrameDirection.DOWNSTREAM:
            if str(frame.id) not in self.session.events:
                self.session.endpoint(False)
                future=self.session.receive(str(frame.id),frame.text)
                future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)

    async def queue_frame(self,frame,direction=FrameDirection.DOWNSTREAM,callback=None):
        # Capture at ingress, before priority SystemFrames can overtake a final
        # in this processor's queued processing. No await precedes receive().
        self._capture(frame,direction)
        await super().queue_frame(frame,direction,callback)

    async def process_frame(self, frame, direction):
        # System events can cancel this processor's frame task, never the
        # independent session interpretation task.
        self._capture(frame,direction)
        await super().process_frame(frame,direction)
        await self.push_frame(frame,direction)


class ReplySource(FrameProcessor):
    """The sole speech owner. Aggregator inference frames are explicitly sunk."""
    def __init__(self, session):
        super().__init__()
        self.session=session
        self.ready=asyncio.Event()
        session.emit=self.speak

    async def speak(self, reply):
        await self.ready.wait()
        await self.push_frame(SpeakAttempt(reply.text,append_to_context=False,attempt_id=reply.attempt_id))
        # Installed TTS serialization places this behind the entire audio
        # context; the output transport then places it behind paced audio output.
        await self.push_frame(PlaybackMarker(reply.attempt_id))

    async def process_frame(self, frame, direction):
        await super().process_frame(frame,direction)
        from pipecat.frames.frames import StartFrame
        if isinstance(frame,StartFrame):self.ready.set()
        if isinstance(frame, LLMContextFrame):
            self.session.record('planner_inference_suppressed',source='user_aggregator')
            return
        if isinstance(frame, (CancelFrame,EndFrame)):
            await self.session.close()
        await self.push_frame(frame,direction)


class PlaybackDelivery(FrameProcessor):
    """After output transport. Neither TTSStopped nor generated text is delivery.

    The available observable is ordered, paced transport audio drain, not the
    remote speaker hardware. No browser playback-ack protocol is claimed.
    """
    def __init__(self, session):
        super().__init__()
        self.session=session
        self.context_attempt={};self.audio_seen=set();self.active_attempt={}

    def bind_context(self, context_id, attempt_id):
        self.context_attempt[context_id]=attempt_id
        self.session.record('tts_context',context_id=context_id,attempt_id=attempt_id)

    async def process_frame(self, frame, direction):
        if isinstance(frame, InterruptionFrame):
            self.session.interrupt()
            self.active_attempt.clear();self.audio_seen.clear()
        await super().process_frame(frame,direction)
        if direction==FrameDirection.DOWNSTREAM:
            destination=frame.transport_destination
            if isinstance(frame,AudioAttemptBoundary):
                attempt=frame.attempt_id
                self.active_attempt[destination]=attempt if self.session.attempts.get(attempt)=='pending' else None
                return
            if isinstance(frame, TTSAudioRawFrame):
                # This frame is downstream only after a successful transport
                # write. Its context_id may have been lost during re-chunking.
                attempt=self.active_attempt.get(destination)
                if attempt and frame.audio and self.session.attempts.get(attempt)=='pending':
                    self.audio_seen.add((destination,attempt))
            elif isinstance(frame, PlaybackMarker):
                key=(destination,frame.attempt_id)
                if (self.active_attempt.get(destination)==frame.attempt_id
                        and key in self.audio_seen and self.session.attempts.get(frame.attempt_id)=='pending'):
                    self.session.delivery(frame.attempt_id,'completed')
                else:
                    self.session.record('playback_unverified',attempt_id=frame.attempt_id,reason='no_transported_audio')
                self.audio_seen.discard(key)
                if self.active_attempt.get(destination)==frame.attempt_id:
                    self.active_attempt.pop(destination,None)
                return
        await self.push_frame(frame,direction)
