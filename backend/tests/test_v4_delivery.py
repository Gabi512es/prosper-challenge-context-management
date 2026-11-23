"""Offline playback tests through installed transport chunking and output queues.

Only the network/audio device write is simulated. BaseOutputTransport, its
resampler, MediaSender chunking, queue and post-write frame forwarding are real.
"""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pipecat.frames.frames import StartFrame,TTSAudioRawFrame,InterruptionFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker,PipelineParams
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import TransportParams
from pipecat.workers.runner import WorkerRunner

from tests import test_v4_reducer as fixtures
from v4.pipeline import PlaybackDelivery,PlaybackMarker,AudioAttemptTagger
from v4.session import Session


class DeviceOutput(BaseOutputTransport):
    """Run installed transport code; gate only the final device/network write."""
    def __init__(self):
        super().__init__(TransportParams(audio_out_enabled=True,audio_out_sample_rate=24000,
            audio_out_10ms_chunks=1,audio_out_end_silence_secs=0))
        self.writes=[];self.write_started=asyncio.Event();self.allow_write=asyncio.Event()
        self.allow_write.set()

    async def start(self,frame):
        await super().start(frame)
        await self.set_transport_ready(frame)

    async def write_audio_frame(self,frame):
        self.write_started.set()
        await self.allow_write.wait()
        self.writes.append(frame)
        return True


class V4DeliveryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fixtures.ReducerTest.setUpClass()
        self.temp=TemporaryDirectory();self.sessions=[]

    async def asyncTearDown(self):
        for session in self.sessions:await session.close()
        self.temp.cleanup()

    def session(self):
        engine=fixtures.ReducerTest().make().engine
        engine.resolve_options({'location_id':None})
        session=Session(engine,None,run_id=f'transport-{len(self.sessions)}',log_dir=self.temp.name)
        self.sessions.append(session)
        return session

    async def presentation(self,session):
        rows=session.r.engine.resolve_options()['eligible_locations']
        reply=await session._reply(session.composer._options('location',rows))
        return reply,session.r.presentations[reply.presentation_ids[0]]

    @asynccontextmanager
    async def transport(self,session,*,tagger=None):
        output=DeviceOutput();delivery=PlaybackDelivery(session)
        processors=([tagger(delivery)] if tagger else [])+[output,delivery]
        worker=PipelineWorker(Pipeline(processors),params=PipelineParams(enable_metrics=False))
        runner=WorkerRunner(handle_sigint=False,handle_sigterm=False);ready=asyncio.Event()
        @worker.event_handler('on_pipeline_started')
        async def started(worker,frame):ready.set()
        await runner.add_workers(worker);task=asyncio.create_task(runner.run())
        try:
            await asyncio.wait_for(ready.wait(),5)
            yield worker,output,delivery
        finally:
            output.allow_write.set()
            await runner.cancel();await task

    async def until(self,predicate):
        async with asyncio.timeout(2):
            while not predicate():await asyncio.sleep(.005)

    async def test_installed_transport_rechunks_audio_and_loses_context_id(self):
        session=self.session();reply,presentation=await self.presentation(session)
        async with self.transport(session) as (worker,output,delivery):
            delivery.bind_context('original-context',reply.attempt_id)
            # Three 10ms chunks, through the actual resampler/MediaSender.
            await worker.queue_frames([TTSAudioRawFrame(b'\x01\x00'*720,24000,1,context_id='original-context'),
                PlaybackMarker(reply.attempt_id)])
            await self.until(lambda:len(output.writes)==3)
            self.assertTrue(all(type(frame) is TTSAudioRawFrame for frame in output.writes))
            self.assertTrue(all(frame.context_id is None for frame in output.writes))
            await self.until(lambda:'playback_unverified' in session.journal.path.read_text())
            self.assertFalse(session.r.presentations[presentation.id].delivered)

    async def test_boundary_survives_real_rechunking_and_ordinals_require_drained_audio(self):
        for ordinal in (1,2,3):
            with self.subTest(ordinal=ordinal):
                session=self.session();reply,presentation=await self.presentation(session)
                before=deepcopy(session.r.engine.state)
                async with self.transport(session,tagger=AudioAttemptTagger) as (worker,output,delivery):
                    output.allow_write.clear();delivery.bind_context('original-context',reply.attempt_id)
                    await worker.queue_frames([TTSAudioRawFrame(b'\x01\x00'*720,24000,1,context_id='original-context'),
                        PlaybackMarker(reply.attempt_id)])
                    await asyncio.wait_for(output.write_started.wait(),2)
                    self.assertFalse(session.r.presentations[presentation.id].delivered)
                    choice=fixtures.act('select_option',presentation_id=presentation.id,
                        selector={'by':'ordinal','ordinal':ordinal})
                    rejected=fixtures.ReducerTest().send(session.r,choice,event='before',words='the first one')
                    self.assertEqual(rejected.errors,('stale_presentation',))
                    self.assertEqual(session.r.engine.state,before)
                    output.allow_write.set()
                    await self.until(lambda:session.attempts[reply.attempt_id]=='completed')
                    self.assertEqual(len(output.writes),3)
                    self.assertTrue(all(frame.context_id is None for frame in output.writes))
                    self.assertTrue(session.r.presentations[presentation.id].delivered)
                    accepted=fixtures.ReducerTest().send(session.r,choice,event='after',words='the first one')
                    self.assertEqual(accepted.status,'accepted',accepted)
                    self.assertEqual(session.r.engine.state.location_id,presentation.option_ids[ordinal-1])
                    self.assertEqual(presentation.option_ids,('loc_002','loc_005','loc_007'))
                    self.assertFalse(session.r.engine.bookings)

    async def test_marker_without_matching_audio_cannot_acknowledge(self):
        session=self.session();reply,presentation=await self.presentation(session)
        async with self.transport(session,tagger=AudioAttemptTagger) as (worker,output,delivery):
            await worker.queue_frames([PlaybackMarker(reply.attempt_id)])
            await self.until(lambda:'playback_unverified' in session.journal.path.read_text())
            self.assertEqual(output.writes,[])
            self.assertEqual(session.attempts[reply.attempt_id],'pending')
            self.assertFalse(session.r.presentations[presentation.id].delivered)

    async def test_interrupted_readback_cannot_be_revived_by_late_marker(self):
        session=self.session();proposal=session.r.propose_identity()
        reply=await session._reply(session.composer._readback(proposal))
        async with self.transport(session,tagger=AudioAttemptTagger) as (worker,output,delivery):
            delivery.bind_context('readback-context',reply.attempt_id)
            await worker.queue_frames([TTSAudioRawFrame(b'\x01\x00'*720,24000,1,context_id='readback-context')])
            await self.until(lambda:len(output.writes)==3)
            await worker.queue_frames([InterruptionFrame()])
            await self.until(lambda:session.attempts[reply.attempt_id]=='interrupted')
            await worker.queue_frames([PlaybackMarker(reply.attempt_id)])
            await self.until(lambda:'playback_unverified' in session.journal.path.read_text())
            self.assertEqual(session.attempts[reply.attempt_id],'interrupted')
            self.assertFalse(session.r.proposals[proposal.id].delivered)
            self.assertEqual(session.r.proposals[proposal.id].status,'revoked')

    async def test_stale_marker_does_not_acknowledge_or_clear_newer_attempt(self):
        session=self.session();old,old_presentation=await self.presentation(session)
        async with self.transport(session,tagger=AudioAttemptTagger) as (worker,output,delivery):
            delivery.bind_context('old',old.attempt_id)
            await worker.queue_frames([TTSAudioRawFrame(b'\x01\x00'*720,24000,1,context_id='old')])
            await self.until(lambda:len(output.writes)==3)
            new,new_presentation=await self.presentation(session)
            self.assertEqual(session.attempts[old.attempt_id],'interrupted')
            delivery.bind_context('new',new.attempt_id)
            await worker.queue_frames([TTSAudioRawFrame(b'\x02\x00'*720,24000,1,context_id='new'),
                PlaybackMarker(old.attempt_id)])
            await self.until(lambda:'playback_unverified' in session.journal.path.read_text())
            self.assertEqual(session.attempts[new.attempt_id],'pending')
            self.assertFalse(session.r.presentations[new_presentation.id].delivered)
            await worker.queue_frames([PlaybackMarker(new.attempt_id)])
            await self.until(lambda:session.attempts[new.attempt_id]=='completed')
            self.assertFalse(session.r.presentations[old_presentation.id].delivered)
            self.assertTrue(session.r.presentations[new_presentation.id].delivered)

    async def test_old_or_unknown_audio_is_never_credited_to_new_attempt(self):
        for context in ('old','unknown'):
            with self.subTest(context=context):
                session=self.session();old,_=await self.presentation(session)
                new,presentation=await self.presentation(session)
                async with self.transport(session,tagger=AudioAttemptTagger) as (worker,output,delivery):
                    delivery.bind_context('old',old.attempt_id)
                    await worker.queue_frames([TTSAudioRawFrame(b'\x01\x00'*720,24000,1,context_id=context),
                        PlaybackMarker(new.attempt_id)])
                    await self.until(lambda:'playback_unverified' in session.journal.path.read_text())
                    self.assertEqual(session.attempts[new.attempt_id],'pending')
                    self.assertFalse(session.r.presentations[presentation.id].delivered)
                    delivery.bind_context('new',new.attempt_id)
                    await worker.queue_frames([TTSAudioRawFrame(b'\x02\x00'*720,24000,1,context_id='new'),
                        PlaybackMarker(new.attempt_id)])
                    await self.until(lambda:session.attempts[new.attempt_id]=='completed')

    async def test_failed_transport_write_is_not_delivery(self):
        session=self.session();reply,presentation=await self.presentation(session)
        async with self.transport(session,tagger=AudioAttemptTagger) as (worker,output,delivery):
            async def failed_write(frame):return False
            output.write_audio_frame=failed_write
            delivery.bind_context('context',reply.attempt_id)
            await worker.queue_frames([TTSAudioRawFrame(b'\x01\x00'*720,24000,1,context_id='context'),
                PlaybackMarker(reply.attempt_id)])
            await self.until(lambda:'playback_unverified' in session.journal.path.read_text())
            self.assertFalse(session.r.presentations[presentation.id].delivered)
