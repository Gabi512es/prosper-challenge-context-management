"""Location-only regressions ported from 70ade3a. No external calls.

The control-call patient lines follow its archived reconstruction; the failing
resolve_options arguments are exact. This is not a new live voice recording.
"""
import copy
from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from pipecat.frames.frames import (LLMFullResponseEndFrame,
    LLMFullResponseStartFrame, LLMTextFrame, TranscriptionFrame)
from pipecat.processors.frame_processor import FrameDirection

from scheduling import SchedulingEngine, load_catalog
from scheduling_agent import build_scheduling_agent
from scheduling_dialogue import BookingSpeech, PatientInput

DOWN = FrameDirection.DOWNSTREAM
CATALOG = load_catalog(Path(__file__).parents[1] / 'data/catalog.json')
PROVIDER_ARGS = dict(provider_id='prov_003', appointment_type_id='appt_002', is_new_patient=True)


def builder():
    engine = SchedulingEngine(CATALOG, [dict(slot_id='demo-offer', provider_id='prov_003',
        appointment_type_id='appt_002', location_id='loc_005', start='2026-11-16T10:00:00-08:00',
        end='2026-11-16T10:30:00-08:00')], now=datetime.fromisoformat('2026-11-13T08:00:00-08:00'))
    return build_scheduling_agent(engine, CATALOG, availability_mode='unit_fixture'), engine


class LocalRegressionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.builder, self.engine = builder()
        self.d = self.builder.dialogue
        self.tools = {t.name: t for t in self.builder.build_initial_node()['functions']}
        self.input = PatientInput(self.d)
        self.input.push_frame = AsyncMock()
        self.output = BookingSpeech(self.d)
        self.output.push_frame = AsyncMock()

    async def patient(self, text):
        await self.input.process_frame(TranscriptionFrame(text, 'patient', ''), DOWN)

    async def reply(self, text=''):
        before = self.output.push_frame.call_count
        await self.output.process_frame(LLMFullResponseStartFrame(), DOWN)
        if text:
            await self.output.process_frame(LLMTextFrame(text), DOWN)
        await self.output.process_frame(LLMFullResponseEndFrame(), DOWN)
        texts = [c.args[0].text for c in self.output.push_frame.call_args_list[before:]
                 if isinstance(c.args[0], LLMTextFrame)]
        self.assertTrue(texts)
        self.assertTrue(all(t.strip() for t in texts))
        return ''.join(texts)

    async def test_transcript_mentions_never_write_a_booking_location(self):
        for words in ('What are the opening hours of the Mission District clinic?',
                      "Mission Bay only. I can't go downtown", 'Midtown or Richmond?', 'Midtown, please'):
            with self.subTest(words=words):
                await self.patient(words)
                self.assertIsNone(self.engine.state.location_id)
                with patch.object(self.engine, 'resolve_options', wraps=self.engine.resolve_options) as applied:
                    result = await self.tools['resolve_options'].handler(PROVIDER_ARGS, None)
                for invocation in applied.call_args_list:
                    updates = invocation.args[0] if invocation.args else {}
                    self.assertNotIn('location_id', updates)
                    self.assertNotIn('location_query', updates)
                self.assertIsNone(result['resolved']['location_id'])
                self.assertFalse(self.d.location_conflict)
                self.assertNotEqual(result['status'], 'blocked')

    async def test_only_explicit_model_location_can_conflict_or_apply(self):
        await self.patient("Mission Bay only. I can't go downtown")
        result = await self.tools['resolve_options'].handler({'location_id': 'loc_004'}, None)
        self.assertEqual(result['code'], 'location_conflict')
        self.assertIsNone(self.engine.state.location_id)
        result = await self.tools['resolve_options'].handler({'location_query': 'Mission Bay'}, None)
        self.assertEqual(result['resolved']['location_id'], 'loc_000')
        self.assertIsNone(self.d.location_conflict)
        await self.patient('What are the hours at Midtown?')
        await self.tools['get_details'].handler({'entity': 'location', 'id': 'loc_005'}, None)
        result = await self.tools['resolve_options'].handler({}, None)
        self.assertEqual(result['resolved']['location_id'], 'loc_000')
        self.assertFalse(self.d.location_conflict)

    async def test_pending_booking_survives_another_sites_hours_question(self):
        await self.tools['resolve_options'].handler({**PROVIDER_ARGS, 'location_id': 'loc_005',
            'patient_name': 'Alex Morgan', 'date_of_birth': '1990-04-12'}, None)
        await self.reply()
        await self.patient('Yes')
        found = await self.tools['find_slots'].handler({'horizon_days': 14}, None)
        offer = await self.reply()
        self.assertIn('Shall I book it?', offer)
        selected = self.engine.state.selected_slot_id
        proposal = copy.deepcopy(self.engine._present_slot(self.engine._slots[selected]))
        before = copy.deepcopy(self.engine.state)
        await self.patient('What are the opening hours of the Mission District clinic?')
        details = await self.tools['get_details'].handler({'entity': 'location', 'id': 'loc_001'}, None)
        answer = await self.reply('Mission District Family Clinic is open Monday to Friday, 8 AM to 5 PM.')
        self.assertEqual(details['details']['id'], 'loc_001')
        self.assertIn('8 AM to 5 PM', answer)
        self.assertNotIn('Shall I book', answer)
        self.assertEqual(self.engine.state, before)
        self.assertEqual(self.engine.state.location_id, 'loc_005')
        self.assertEqual(self.engine.state.selected_slot_id, selected)
        self.assertEqual(self.engine._present_slot(self.engine._slots[selected]), proposal)
        self.assertEqual(self.d.render(proposal), offer)
        self.assertTrue(found['slots'])
        # The question preserved the proposal, but did not grant booking consent.
        self.assertIsNone(self.engine.state.confirmation)
        self.assertFalse(self.engine.bookings)





class ControlCallReplayTest(unittest.IsolatedAsyncioTestCase):
    setUp = LocalRegressionTest.setUp
    patient = LocalRegressionTest.patient
    reply = LocalRegressionTest.reply

    async def test_nov_13_control_call_with_original_wrong_hours_lookup(self):
        # Retain the model's original Mission Bay lookup. This location-only
        # port does not fix wrong model-supplied IDs or speech-frame ordering.
        await self.replay_control_call('loc_000')

    async def test_nov_13_control_call_with_correct_hours_lookup(self):
        await self.replay_control_call('loc_001')

    async def replay_control_call(self, lookup_id):
        # Replay at the voice processor/tool boundary to isolate the location
        # defect from 70ade3a's unrelated empty-reply/frame-order changes.
        await self.patient("I'd like to book with Dr. Garcia.")
        await self.tools['resolve_options'].handler({'provider_query': 'Dr. Garcia'}, None)
        await self.reply('Which Dr. Garcia would you like to book with?')

        await self.patient('What are the opening hours of the Mission District clinic?')
        details = await self.tools['get_details'].handler({'entity': 'location', 'id': lookup_id}, None)
        site = details['details']['name']
        answer = await self.reply(site+' is open Monday to Friday, 8 AM to 5 PM.')
        self.assertIn('8 AM to 5 PM', answer)
        self.assertIn(site, answer)
        self.assertIsNone(self.engine.state.location_id)

        await self.patient("Uh, Maria Garcia, the Family Medicine one. Uh, I want an annual physical. I'm a new patient.")
        result = await self.tools['resolve_options'].handler(PROVIDER_ARGS, None)
        self.assertEqual(self.engine.state.provider_id, 'prov_003')
        self.assertIsNone(result['resolved']['location_id'])
        self.assertFalse(result['blocked_options'])
        self.assertNotEqual(result['status'], 'blocked')
        self.assertIn('Which', await self.reply('Which clinic would you prefer?'))
        for words in ('What do you mean blocked? I never confirmed any location.',
                      'No, no, no, no, no, no. Stop.',
                      'I want to book an appointment with Dr. Maria Garcia.',
                      'What details are you missing?', 'Hello?'):
            await self.patient(words)
            self.assertTrue((await self.reply('Please choose a clinic.')).strip())
            self.assertIsNone(self.engine.state.location_id)
        self.assertFalse(self.engine.bookings)
