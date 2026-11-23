"""M2 offline integration: real core/reducer, fake interpretation and playback."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock,patch

from pipecat.frames.frames import (StartFrame,TranscriptionFrame,UserStartedSpeakingFrame,BotStoppedSpeakingFrame,
    UserStoppedSpeakingFrame,InterruptionFrame,TTSAudioRawFrame,TTSStoppedFrame,LLMContextFrame)
from pipecat.processors.frame_processor import FrameProcessor,FrameDirection
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregatorParams
from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies
from pipecat.pipeline.worker import PipelineWorker,PipelineParams
from pipecat.workers.runner import WorkerRunner

from tests import test_v4_reducer as reducer_fixtures
from tests.test_v4_reducer import act,delta
from v4.interpreter import Interpretation,InterpretationError,OpenAIInterpreter,assets,MODEL
from v4.session import Session
from v4.speech import spoken_phone
from v4.pipeline import PlaybackDelivery,PlaybackMarker,ReplySource,SpeakAttempt,AudioAttemptBoundary
from v4_text import V4TextSession
from v4_bot import build_pipeline

DOWN=FrameDirection.DOWNSTREAM


def answer(envelope,kind='affirm'):
    return {'acts':[act(kind,target={'type':'proposal','id':envelope['context']['proposal']['id']})]}


def choose(envelope,index=1):
    p=envelope['context']['presentations'][-1]
    return {'acts':[act('select_option',presentation_id=p['id'],selector={'by':'ordinal','ordinal':index})]}


def opening(envelope):
    return {'acts':[delta('service','Annual Physical'),delta('provider','Maria Garcia'),
        delta('provider_specialty','Family Medicine'),delta('location','Midtown'),
        delta('new_patient',True),delta('name','Alex Morgan'),
        delta('date_of_birth',{'year':1990,'month':4,'day':12})]}


class FakeInterpreter:
    def __init__(self,steps):
        self.steps=list(steps);self.calls=[];self.started=asyncio.Event();self.release=None;self.cancelled=False

    async def interpret(self,envelope,record):
        self.calls.append(deepcopy(envelope));self.started.set()
        if self.release is not None and len(self.calls)==1:
            try:await self.release.wait()
            except asyncio.CancelledError:self.cancelled=True;raise
        step=self.steps.pop(0)
        raw=step(envelope) if callable(step) else step
        record('fake_interpretation',raw=raw)
        return Interpretation(raw,prompt_tokens=100,cached_tokens=0,completion_tokens=20,latency_ms=1)


class V4SessionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reducer_fixtures.ReducerTest.setUpClass();self.fixture=reducer_fixtures.ReducerTest()
        self.temp=TemporaryDirectory();self.sessions=[]

    async def asyncTearDown(self):
        for session in self.sessions:await session.close()
        self.temp.cleanup()

    def make(self,steps,*,empty=False):
        engine=self.fixture.make(None,None).engine if empty else self.fixture.make().engine
        fake=FakeInterpreter(steps)
        session=Session(engine,fake,run_id=f'offline-{len(self.sessions)}',log_dir=self.temp.name)
        self.sessions.append(session)
        return session,fake

    async def send(self,s,text='Yes.',*,delivered=True):
        # Scripted finals are spoken as "Yes.": booking consent needs an acceptance
        # in the caller's words (v1.6+); the scripted acts carry the meaning.
        result=await asyncio.wait_for(s.receive(f'caller-{len(s.events)}',text),2)
        if delivered and result:s.delivery(result.attempt_id,'completed')
        return result

    async def booking_ready(self,s):
        first=await s._reply(s.composer._next(s.r.engine.resolve_options()));s.delivery(first.attempt_id,'completed')
        await self.send(s)  # Identity yes -> slots, or full opening -> identity.
        await self.send(s)  # Slot choice -> canonical read-back.
        return s.replies[-1]

    async def test_complete_text_path_reuses_core_and_records_full_evidence(self):
        s,fake=self.make([opening,answer,choose,answer],empty=True)
        text=V4TextSession(engine=s.r.engine._engine,interpreter=fake,run_id='text-path',log_dir=self.temp.name)
        self.sessions.append(text.session)
        reply=await text.start();self.assertIn('AI scheduling assistant',reply.text)
        reply=await text.send('Full opening');self.assertIn('Alex Morgan, born April 12, 1990',reply.text)
        reply=await text.send('Yes');self.assertIn('Which works for you?',reply.text)  # v1.8 slot choice
        reply=await text.send('The first one');self.assertIn('Shall I book it?',reply.text)
        self.assertEqual(len(text.session.r.engine.bookings),0)
        reply=await text.send('Yes, please');self.assertIn("You're all set",reply.text)
        self.assertEqual(len(text.session.r.engine.bookings),1);self.assertEqual(len(fake.calls),4)
        self.assertEqual(len(text.session.replies),5)
        rows=[json.loads(line) for line in (Path(self.temp.name)/'text-path.events.jsonl').read_text().splitlines()]
        self.assertEqual(len([r for r in rows if r['event']=='raw_acts']),4)
        tools=[r for r in rows if r['event']=='tool_finished']
        self.assertEqual(len([r for r in tools if r['tool']=='book_appointment']),1)
        self.assertTrue(any(r['tool']=='confirm_selected_slot' for r in tools))
        metrics=[json.loads(line) for line in (Path(self.temp.name)/'text-path.jsonl').read_text().splitlines()]
        self.assertEqual(len(metrics),4);self.assertEqual(metrics[-1]['prompt_tokens'],100)
        self.assertFalse(text.session.respond_immediately);self.assertFalse(text.session.tool_followup_inference)

    async def test_complete_question_target_booking_with_information_and_retired_question(self):
        def question_yes(e):
            return {'acts':[act('affirm',target={'type':'question','id':e['context']['question']['id']})]}
        def opening_request(e):
            return {'acts':[delta('service','Annual Physical'),delta('provider','Maria Garcia'),
                delta('provider_specialty','Family Medicine'),delta('new_patient',True)]}
        def identity(e):
            return {'acts':[delta('name','Alex Morgan'),
                delta('date_of_birth',{'year':1990,'month':4,'day':12})]}
        def information(e):
            return {'acts':[act('information_question',entity='location',name='Mission District',
                reference_id=None,attribute='hours')]}
        retired_question=None
        def retired_yes(e):
            return {'acts':[act('affirm',target={'type':'question','id':retired_question})]}
        s,fake=self.make([opening_request,lambda e:choose(e,2),identity,question_yes,
            choose,information,retired_yes,question_yes,question_yes],empty=True)
        greeting=await s.start();s.delivery(greeting.attempt_id,'completed')
        locations=await self.send(s,'Annual physical with Maria Garcia, Family Medicine; new patient.')
        self.assertEqual(s.r.presentations[locations.presentation_ids[0]].option_ids,
                         ('loc_002','loc_005','loc_007'))
        await self.send(s,'The second one.')
        self.assertEqual(s.r.engine.state.location_id,'loc_005')
        identity_reply=await self.send(s,'Alex Morgan, born April 12, 1990.')
        identity_pid=identity_reply.proposal_ids[0]
        identity_question=identity_reply.question_id
        await self.send(s,'Yes.')
        self.assertEqual(fake.calls[-1]['context']['question']['id'],identity_question)
        self.assertTrue(fake.calls[-1]['context']['proposal']['delivered_before_reply'])
        self.assertEqual(s.r.proposals[identity_pid].status,'accepted')
        self.assertEqual(s.r.identity_confirmed,('Alex Morgan','1990-04-12'))
        self.assertFalse(s.r.engine.bookings)  # Identity yes never books.
        old=await self.send(s,'The first one.')
        retired_question=old.question_id;old_pid=old.proposal_ids[0]
        self.assertEqual(s.r.proposals[old_pid].kind,'booking')
        before=deepcopy(s.r.engine.state)
        fresh=await self.send(s,'What are the opening hours of Mission District Family Clinic?')
        self.assertEqual(s.r.engine.state,before)
        self.assertEqual(s.r.identity_confirmed,('Alex Morgan','1990-04-12'))
        self.assertEqual(s.r.proposals[old_pid].status,'revoked')
        self.assertNotEqual(fresh.question_id,retired_question)
        self.assertNotEqual(fresh.proposal_ids[0],old_pid)
        # The session's own composer renders the catalog hours (literal in base v4, spoken in the candidate).
        hours=s.composer.details_text('location','loc_001','hours')
        self.assertIn(hours,fresh.text)
        self.assertIn('Midtown Medical Group',fresh.text)
        self.assertLess(fresh.text.index(hours),fresh.text.index("I'll book"))
        self.assertFalse(s.r.engine.bookings)
        stale_event=f'caller-{len(s.events)}'
        recovery=await self.send(s,'Yes.',delivered=False)  # Delivered NEW proposal, OLD question target.
        self.assertEqual(s.r.processed[stale_event][1].errors,('stale_question',))
        self.assertFalse(s.r.engine.bookings)
        self.assertNotEqual(recovery.question_id,retired_question)
        early_event=f'caller-{len(s.events)}'
        current=await self.send(s,'Yes.',delivered=False)  # Current target, before its own delivery.
        self.assertEqual(s.r.processed[early_event][1].status,'rejected')
        self.assertFalse(s.r.engine.bookings)
        self.assertFalse(s.r.proposals[current.proposal_ids[0]].delivered)
        self.assertFalse(s.delivery(recovery.attempt_id,'completed'))  # Interrupted old attempt stays retired.
        s.delivery(current.attempt_id,'completed')  # Simulated matching transport drain, not TTS completion.
        final_event=f'caller-{len(s.events)}'
        booked=await self.send(s,'Yes, please.')
        self.assertIn("You're all set",booked.text)
        self.assertEqual(fake.calls[-1]['context']['question']['id'],current.question_id)
        self.assertEqual(s.r.consent_ledger[-1]['target'],{'type':'question','id':current.question_id})
        self.assertEqual(len(s.r.engine.bookings),1)
        count=len(fake.calls)
        self.assertIs(await s.receive(final_event,'Yes, please.'),booked)
        self.assertEqual(len(fake.calls),count);self.assertEqual(len(s.r.engine.bookings),1)
        self.assertFalse(s.respond_immediately);self.assertFalse(s.tool_followup_inference)

    async def test_location_choice_speech_and_order_match_real_engine_options(self):
        for ordinal in (1,2,3):
            with self.subTest(ordinal=ordinal):
                s,fake=self.make([])
                rows=s.r.engine.resolve_options({'location_id':None})['eligible_locations']
                ids=tuple(row['id'] for row in rows)
                self.assertEqual(ids,('loc_002','loc_005','loc_007'))
                before=deepcopy(s.r.engine.state)
                reply=await s._reply(s.composer._options('location',rows))
                # v1.8: a site choice names the requested service first.
                self.assertEqual(reply.text,
                    'For your Annual Physical, Nurse practitioner Maria Garcia sees patients at North Beach Specialty Center, '
                    'Midtown Medical Group, and Richmond Care Center. Which location works best for you?')
                self.assertNotIn(';',reply.text);self.assertNotRegex(reply.text,r'\b\d+:')
                self.assertEqual(reply.text.count('?'),1)
                self.assertNotIn('available',reply.text.lower());self.assertNotIn('booked',reply.text.lower())
                self.assertEqual(s.r.engine.state,before)
                presentation=s.r.presentations[reply.presentation_ids[0]]
                self.assertEqual(presentation.option_ids,ids)
                positions=[reply.text.index(row['name']) for row in rows]
                self.assertEqual(positions,sorted(positions))
                s.delivery(reply.attempt_id,'completed')  # Simulated display, not live audio.
                result=self.fixture.send(s.r,act('select_option',presentation_id=presentation.id,
                    selector={'by':'ordinal','ordinal':ordinal}),words=f'the {ordinal} option')
                self.assertEqual(result.status,'accepted',result)
                self.assertEqual(s.r.engine.state.location_id,ids[ordinal-1])
                self.assertEqual(s.r.engine.state.provider_id,'prov_003')
                self.assertEqual(s.r.engine.state.appointment_type_id,'appt_002')
                self.assertFalse(s.r.engine.bookings);self.assertEqual(fake.calls,[])

    async def test_location_intro_requires_supported_provider_relationship(self):
        for resolved_provider in (True,False):
            with self.subTest(resolved_provider=resolved_provider):
                s,fake=self.make([])
                provider=s.r.engine._provider()
                if resolved_provider:
                    site=next(loc for loc in s.r.engine.catalog.locations if loc.id not in provider.location_ids)
                    rows=[s.r.engine.catalog.summary('location',site.id)]
                else:
                    rows=s.r.engine.resolve_options({'location_id':None})['eligible_locations']
                    s.r.engine.resolve_options({'provider_id':None})
                text,*_=s.composer._options('location',rows)
                self.assertNotIn('Dr. Maria Garcia',text)
                self.assertNotIn('sees patients',text)
                self.assertNotIn(';',text);self.assertNotRegex(text,r'\b\d+:')
                self.assertEqual(text.count('?'),1)

    async def test_spoken_provider_title_uses_catalog_role_without_mutating_it(self):
        s,_=self.make([])
        provider=s.r.engine.catalog.providers_by_id['prov_003']
        before=deepcopy(s.r.engine.state)
        self.assertEqual(provider.name,'Dr. Maria Garcia');self.assertEqual(provider.title,'NP')
        self.assertEqual(s.composer.provider_name(provider),'Nurse practitioner Maria Garcia')
        slots=s.r.engine.find_slots(30)['slots']
        text=s.composer.slot_text(slots[0]['slot_id'])
        self.assertIn('Nurse practitioner Maria Garcia',text);self.assertNotIn('Dr. Maria Garcia',text)
        physician=next(p for p in s.r.engine.catalog.providers if p.title=='MD')
        self.assertEqual(s.composer.provider_name(physician),physician.name)
        self.assertEqual(provider.name,'Dr. Maria Garcia');self.assertEqual(provider.title,'NP')
        self.assertEqual(s.r.engine.state.patient_facts,before.patient_facts)
        self.assertIsNone(s.r.engine.state.confirmation);self.assertFalse(s.r.engine.bookings)

    async def test_split_yes_please_is_ordered_and_books_once(self):
        s,fake=self.make([answer,choose,answer,answer])
        await self.booking_ready(s)
        s.endpoint(False)
        first=s.receive('yes','Yes.');second=s.receive('please','Please.')
        s.endpoint(True)
        replies=await asyncio.gather(first,second)
        self.assertIs(replies[0],replies[1]);self.assertIn("You're all set",replies[-1].text)
        # Step 6: both finals of the held turn are one utterance, interpreted once.
        self.assertEqual(len(s.r.engine.bookings),1);self.assertEqual(len(fake.calls),3)  # Was 4: one call per final.
        self.assertEqual(fake.calls[-1]['caller_text'],'Yes. Please.')

    async def test_queued_veto_does_not_cancel_running_inference_or_write(self):
        s,fake=self.make([answer,choose,answer,lambda e:answer(e,'deny')])
        await self.booking_ready(s)
        # Hold the actual booking-affirm interpretation while a veto arrives.
        original=fake.interpret;entered=asyncio.Event();release=asyncio.Event()
        async def delayed(envelope,record):
            if envelope['turn_id']=='yes':entered.set();await release.wait()
            return await original(envelope,record)
        fake.interpret=delayed
        yes=s.receive('yes','Yes');await entered.wait()
        veto=s.receive('veto',"No, do not book it")
        self.assertFalse(yes.done());self.assertEqual(len(s.r.engine.bookings),0)
        release.set();await asyncio.gather(yes,veto)
        self.assertEqual(len(s.r.engine.bookings),0);self.assertFalse(fake.cancelled)
        self.assertEqual([e['turn_id'] for e in fake.calls][-2:],['yes','veto'])

    async def test_state_for_second_queued_turn_comes_from_first_and_duplicate_is_free(self):
        s,fake=self.make([{'acts':[delta('name','Alex Morgan')]},{'acts':[delta('date_of_birth',{'year':1990,'month':4,'day':12})]}],empty=True)
        fake.release=asyncio.Event()
        # Step 3: the patient name comes from the identity question or "my name is".
        first=s.receive('name','My name is Alex Morgan');await fake.started.wait()
        duplicate=s.receive('name','My name is Alex Morgan');self.assertIs(first,duplicate)
        second=s.receive('dob','April 12, 1990');fake.release.set()
        await asyncio.gather(first,second)
        self.assertEqual(fake.calls[1]['context']['known']['identity']['name'],'Alex Morgan')
        self.assertEqual(len(fake.calls),2);self.assertEqual(len(s.replies),1)
        self.assertIs(s.receive('name','My name is Alex Morgan'),first);self.assertEqual(len(fake.calls),2)

    async def test_playback_interruption_and_late_completion_cannot_revive_proposal(self):
        s,fake=self.make([answer,choose,answer,answer])
        first=await s._reply(s.composer._next(s.r.engine.resolve_options()));s.delivery(first.attempt_id,'completed')
        await self.send(s)
        interrupted=await self.send(s,delivered=False);old=s.r.proposals[interrupted.proposal_ids[0]]
        s.delivery(interrupted.attempt_id,'interrupted')
        self.assertFalse(s.delivery(interrupted.attempt_id,'completed'))
        self.assertEqual(s.r.proposals[old.id].status,'revoked')
        # Simulate a model incorrectly affirming the interrupted old reference.
        fake.steps[0]={'acts':[act('affirm',target={'type':'proposal','id':old.id})]}
        fresh=await self.send(s);self.assertIn('Shall I book it?',fresh.text)
        self.assertNotEqual(fresh.proposal_ids[0],old.id);self.assertFalse(s.r.engine.bookings)
        booked=await self.send(s);self.assertIn("You're all set",booked.text)

    async def test_selection_plus_information_answers_then_reads_back_and_requires_fresh_yes(self):
        def pick_and_ask(e):
            raw=choose(e,2)
            raw['acts'].append(act('information_question',entity='location',name='Mission District',reference_id=None,attribute='phone'))
            return raw
        s,fake=self.make([answer,pick_and_ask,answer])
        first=await s._reply(s.composer._next(s.r.engine.resolve_options()));s.delivery(first.attempt_id,'completed')
        await self.send(s);reply=await self.send(s)
        # v1.8: catalog phone numbers are spoken digit by digit.
        phone=spoken_phone(s.r.engine.catalog.locations_by_id['loc_001'].phone)
        self.assertIn(phone,reply.text);self.assertIn('Shall I book it?',reply.text)
        self.assertLess(reply.text.index(phone),reply.text.index("I'll book"))
        self.assertEqual(s.r.engine.state.location_id,'loc_005');self.assertFalse(s.r.engine.bookings)
        booked=await self.send(s);self.assertIn("You're all set",booked.text)
        self.assertEqual(len(s.r.engine.bookings),1)

    async def test_endpoint_must_close_and_evidence_precedes_dispatch(self):
        s,fake=self.make([answer,choose,answer]);await self.booking_ready(s)
        s.endpoint(False);future=s.receive('yes','Yes')
        for _ in range(20):
            await asyncio.sleep(0)
        # Step 6: finals wait while the caller's turn is open (they are joined when it
        # ends); nothing is interpreted, answered or booked before the endpoint closes.
        self.assertNotIn('yes',s.r.processed);self.assertFalse(future.done());self.assertFalse(s.r.engine.bookings)
        s.endpoint(True);reply=await future
        self.assertIn("You're all set",reply.text)

    async def test_information_pause_terminal_and_interpreter_failure_no_reply_loops(self):
        for control in (act('pause'),act('human_request',action='request'),act('urgent_escalation')):
            s,fake=self.make([{'acts':[control]},{'acts':[act('acknowledge')]}])
            # Step 3: a request for a person needs a person named in the caller's words.
            words='Can I talk to a person?' if control['kind']=='human_request' else 'Yes.'
            reply=await self.send(s,words)
            # Step 8: the honest handoff keeps the call open ("anything else?"); pause and urgent ask nothing.
            self.assertEqual(bool(reply.question_id),control['kind']=='human_request')
            await asyncio.sleep(0.01);self.assertEqual(len(fake.calls),1);self.assertEqual(len(s.replies),1)
            await self.send(s);self.assertFalse(s.r.engine.bookings)
        # Step 2b: an interpreter failure never kills the session. The turn is
        # retried once, then asked again; the second lost turn ends the call.
        s,fake=self.make([]);s.retry_backoff_s=0
        async def broken(*args):raise ValueError('synthetic interpreter failure')
        fake.interpret=broken
        reply=await self.send(s);self.assertEqual(reply.text,"Sorry, I didn't catch that, could you say it again?")
        self.assertFalse(s.ended);self.assertEqual(s.model_calls,2)
        goodbye=await self.send(s);self.assertIn('I cannot transfer this call',goodbye.text);self.assertTrue(s.ended)
        self.assertIsNone(await self.send(s));self.assertEqual(len(s.replies),2)
        metric=json.loads((Path(self.temp.name)/(s.run_id+'.jsonl')).read_text().splitlines()[0])
        self.assertIsNone(metric['prompt_tokens']);self.assertIsNone(metric['cached_tokens'])

    async def test_tts_synthesis_and_bot_stop_are_not_delivery(self):
        s,fake=self.make([answer,choose]);await self.booking_ready(s)
        # A fresh undelivered canonical attempt.
        p=s.r.prepare_booking(s.r.engine.state.selected_slot_id)
        reply=await s._reply(s.composer._readback(p))
        delivery=PlaybackDelivery(s);delivery.push_frame=AsyncMock()
        # No matching transported audio, even a synthesis stop or marker cannot deliver.
        await delivery.process_frame(TTSStoppedFrame(context_id='ctx'),DOWN)
        await delivery.process_frame(BotStoppedSpeakingFrame(),DOWN)
        await delivery.process_frame(PlaybackMarker(reply.attempt_id),DOWN)
        self.assertFalse(s.r.proposals[p.id].delivered)
        delivery.bind_context('ctx',reply.attempt_id)
        await delivery.process_frame(AudioAttemptBoundary(reply.attempt_id),DOWN)
        await delivery.process_frame(TTSAudioRawFrame(b'\x00\x01'*240,24000,1,context_id='ctx'),DOWN)
        self.assertFalse(s.r.proposals[p.id].delivered)
        await delivery.process_frame(PlaybackMarker(reply.attempt_id),DOWN)
        self.assertTrue(s.r.proposals[p.id].delivered)


class FakeTTS(FrameProcessor):
    def __init__(self):
        super().__init__();self._register_event_handler('on_tts_request');self.current_attempt=None
    async def process_frame(self,frame,direction):
        await super().process_frame(frame,direction)
        if isinstance(frame,SpeakAttempt):
            self.current_attempt=frame.attempt_id
            self.context_created(frame.attempt_id,self.current_attempt)
            await self.push_frame(TTSAudioRawFrame(b'\x00\x01'*240,24000,1,context_id=frame.attempt_id))
            await self.push_frame(TTSStoppedFrame(context_id=frame.attempt_id))
            self.current_attempt=None
        else:await self.push_frame(frame,direction)


class PassOutput(FrameProcessor):
    async def process_frame(self,frame,direction):
        await super().process_frame(frame,direction);await self.push_frame(frame,direction)


class V4QueuedPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_queued_pipeline_single_interpretation_and_speech_owner_no_old_planner(self):
        reducer_fixtures.ReducerTest.setUpClass();engine=reducer_fixtures.ReducerTest().make(None,None).engine
        fake=FakeInterpreter([opening,answer,choose,answer])
        with TemporaryDirectory() as temp,patch('agent_runtime.build_agent_runtime',side_effect=AssertionError('old planner')):
            s=Session(engine,fake,run_id='queued-pipeline',log_dir=temp)
            pipeline=build_pipeline(s,input_processors=[],tts=FakeTTS(),output=PassOutput(),
                user_params=LLMUserAggregatorParams(user_turn_strategies=ExternalUserTurnStrategies()))
            worker=PipelineWorker(pipeline,params=PipelineParams(enable_metrics=False))
            runner=WorkerRunner(handle_sigint=False,handle_sigterm=False);ready=asyncio.Event()
            @runner.event_handler('on_ready')
            async def on_ready(runner):ready.set()
            await runner.add_workers(worker);task=asyncio.create_task(runner.run())
            try:
                await asyncio.wait_for(ready.wait(),5)
                await s.start()
                final=TranscriptionFrame('Full opening','patient','')
                await worker.queue_frames([UserStartedSpeakingFrame(),final,UserStoppedSpeakingFrame()])
                for _ in range(100):
                    await asyncio.sleep(.01)
                    if str(final.id) in s.events and s.events[str(final.id)][1].done():break
                try:reply=await asyncio.wait_for(asyncio.shield(s.events[str(final.id)][1]),2)
                except TimeoutError:
                    print('PIPELINE DIAGNOSTIC',s.endpoint_closed,s.failed,s.pending_events,s.r.pending_inputs,
                          [(r['event'],r.get('closed')) for r in map(json.loads,s.journal.path.read_text().splitlines())])
                    raise
                for _ in range(100):
                    if s.attempts[reply.attempt_id]=='completed':break
                    await asyncio.sleep(.01)
                self.assertEqual(len(fake.calls),1);self.assertEqual(len(s.replies),2)
                self.assertEqual(s.attempts[reply.attempt_id],'completed')
                self.assertTrue(s.r.proposals[reply.proposal_ids[0]].delivered)
                self.assertEqual(s.r.engine.state.provider_id,'prov_003')
                self.assertFalse(s.respond_immediately);self.assertFalse(s.tool_followup_inference)
                for words in ('Yes, that is correct.','The first one.','Yes, please.'):
                    final=TranscriptionFrame(words,'patient','')
                    await worker.queue_frames([UserStartedSpeakingFrame(),final,UserStoppedSpeakingFrame()])
                    for _ in range(200):
                        await asyncio.sleep(.01)
                        if str(final.id) in s.events and s.events[str(final.id)][1].done():break
                    reply=await asyncio.wait_for(asyncio.shield(s.events[str(final.id)][1]),2)
                    for _ in range(100):
                        if s.attempts[reply.attempt_id]=='completed':break
                        await asyncio.sleep(.01)
                self.assertIn("You're all set",reply.text)
                self.assertEqual(len(s.r.engine.bookings),1)
                self.assertEqual(len(fake.calls),4);self.assertEqual(len(s.replies),5)
            finally:
                await s.close();await runner.cancel();await task


class V4InterpreterTest(unittest.IsolatedAsyncioTestCase):
    async def test_pinned_request_receipt_precedes_parse_and_no_retry_or_extra_call(self):
        from openai.types.chat import ChatCompletion
        from types import SimpleNamespace
        raw={'acts':[act('acknowledge')]}
        response=ChatCompletion.model_validate(dict(id='offline',object='chat.completion',created=1,model=MODEL,
            choices=[dict(index=0,message=dict(role='assistant',content=json.dumps(raw)),finish_reason='stop')],
            usage=dict(prompt_tokens=100,completion_tokens=20,total_tokens=120,prompt_tokens_details=dict(cached_tokens=0))))
        create=AsyncMock(return_value=response)
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        interpreter=OpenAIInterpreter(client,request_limit=1);events=[]
        def record(event,**values):events.append((event,values))
        result=await interpreter.interpret(dict(turn_id='one',state_version=0,caller_text='Thanks',context={}),record)
        self.assertEqual(result.raw,raw);self.assertEqual(result.cached_tokens,0)
        params=create.call_args.kwargs
        self.assertEqual(params['model'],MODEL);self.assertEqual(params['max_completion_tokens'],1024)
        self.assertNotIn('tools',params);self.assertNotIn('parallel_tool_calls',params)
        self.assertEqual(params['response_format']['json_schema']['schema'],assets()[0])
        self.assertEqual(params['messages'][0]['content'],assets()[1])
        self.assertEqual(events[1][0],'response_received')
        with self.assertRaises(InterpretationError):
            await interpreter.interpret(dict(turn_id='two',state_version=0,caller_text='Please',context={}),record)
        self.assertEqual(create.await_count,1)

    async def test_missing_usage_remains_unknown_and_receipt_is_preserved(self):
        from openai.types.chat import ChatCompletion
        from types import SimpleNamespace
        response=ChatCompletion.model_validate(dict(id='offline',object='chat.completion',created=1,model=MODEL,
            choices=[dict(index=0,message=dict(role='assistant',content='{"acts":[]}'),finish_reason='stop')]))
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response))))
        events=[]
        with self.assertRaises(InterpretationError) as caught:
            await OpenAIInterpreter(client).interpret(dict(turn_id='one',state_version=0,caller_text='Thanks',context={}),
                lambda event,**values:events.append((event,values)))
        self.assertEqual(caught.exception.code,'usage_unknown')
        self.assertIsNone(caught.exception.receipt.prompt_tokens)
        self.assertIsNone(caught.exception.receipt.cached_tokens)
        self.assertEqual(events[1][0],'response_received')
