"""Offline information-question and stale-site regressions at the voice boundary."""
import copy
import unittest
from unittest.mock import AsyncMock, patch

from pipecat.frames.frames import (LLMFullResponseEndFrame,
    LLMFullResponseStartFrame, LLMTextFrame, TranscriptionFrame)
from pipecat.processors.frame_processor import FrameDirection

from tests.test_transcript_location import builder, PROVIDER_ARGS
from scheduling_dialogue import BookingSpeech, PatientInput

DOWN = FrameDirection.DOWNSTREAM


class CatalogInformationTest(unittest.IsolatedAsyncioTestCase):
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
        return ''.join(c.args[0].text for c in self.output.push_frame.call_args_list[before:]
                       if isinstance(c.args[0], LLMTextFrame))

    async def test_call_9661f589_exact_resolve_calls_recover_from_information_site(self):
        await self.patient("I'd like to book with Dr. Garcia.")
        await self.tools['resolve_options'].handler({'provider_query': 'Dr. Garcia'}, None)
        await self.reply('Which Dr. Garcia would you like to book with?')
        await self.patient('What are the opening hours of the Mission District clinic?')
        # The original model misused the booking tool for this question.
        await self.tools['resolve_options'].handler({'location_query': 'Mission District'}, None)
        self.assertEqual(self.engine.state.location_id, 'loc_001')
        await self.reply('Mission District Family Clinic is open Monday to Friday, 8 AM to 5 PM.')

        await self.patient("Uh, Maria Garcia, the Family Medicine one. Uh, I want an annual physical. I'm a new patient.")
        result = await self.tools['resolve_options'].handler(PROVIDER_ARGS, None)
        self.assertNotEqual(result['status'], 'blocked')
        self.assertFalse(result['blocked_options'])
        self.assertIsNone(self.engine.state.location_id)
        self.assertEqual(self.engine.state.provider_id, 'prov_003')
        self.assertEqual(self.engine.state.appointment_type_id, 'appt_002')
        # The voice processor replaces even the original false-refusal draft.
        question = await self.reply('This request is blocked: provider not at location.')
        provider = self.engine.catalog.providers_by_id['prov_003']
        self.assertIn(f'{provider.name} ({provider.specialty}) practices at ', question)
        for site_id in provider.location_ids:
            self.assertIn(self.engine.catalog.locations_by_id[site_id].name, question)
        self.assertIn('Which would you prefer?', question)
        self.assertNotIn('blocked', question)
        self.assertNotIn('555-', question)

        await self.patient('Midtown, please.')
        result = await self.tools['resolve_options'].handler({'location_id': 'loc_005'}, None)
        self.assertEqual(result['resolved']['location_id'], 'loc_005')
        self.assertIsNone(self.d.location_intent_question)
        self.assertEqual(result['dialogue_step']['stage'], 'identity')

    async def test_hours_by_name_preserves_pending_location_slot_and_proposal(self):
        await self.tools['resolve_options'].handler({**PROVIDER_ARGS, 'location_id': 'loc_005',
            'patient_name': 'Alex Morgan', 'date_of_birth': '1990-04-12'}, None)
        await self.reply()
        await self.patient('Yes')
        await self.tools['find_slots'].handler({'horizon_days': 14}, None)
        offer = await self.reply()
        self.assertIn('Shall I book it?', offer)
        before = copy.deepcopy(self.engine.state)
        selected = before.selected_slot_id
        proposal = copy.deepcopy(self.engine._present_slot(self.engine._slots[selected]))

        await self.patient('What are the opening hours of the Mission District clinic?')
        details = await self.tools['get_details'].handler(
            {'entity': 'location', 'query': 'Mission District clinic'}, None)
        self.assertEqual(details['details']['id'], 'loc_001')
        self.assertEqual(details['details']['hours'], self.engine.catalog.locations_by_id['loc_001'].hours)
        answer = await self.reply('Mission District Family Clinic is open Monday to Friday, 8 AM to 5 PM. Shall I book the pending appointment?')
        self.assertIn('8 AM to 5 PM', answer)
        self.assertIn('pending appointment?', answer)
        self.assertEqual(self.engine.state, before)
        self.assertEqual(self.engine._present_slot(self.engine._slots[selected]), proposal)
        self.assertEqual(self.d.render(proposal), offer)
        self.assertFalse(self.engine.bookings)

    async def test_information_lookup_never_accesses_booking_state(self):
        class ForbiddenState:
            def __getattr__(self, name):
                raise AssertionError('Information lookup read booking state: ' + name)

            def __setattr__(self, name, value):
                raise AssertionError('Information lookup wrote booking state: ' + name)

        with patch.object(self.engine, 'state', ForbiddenState()), \
             patch.object(self.engine, 'get_details', side_effect=AssertionError('Use catalog directly')), \
             patch.object(self.engine, 'resolve_options', side_effect=AssertionError('No booking resolution')):
            for args, entity_id in (
                ({'entity': 'location', 'query': 'Mission District clinic'}, 'loc_001'),
                ({'entity': 'location', 'id': 'loc_001'}, 'loc_001'),
                ({'entity': 'provider', 'query': 'Dr. David Chen'}, 'prov_000'),
                ({'entity': 'appointment_type', 'query': 'Annual Physical'}, 'appt_002'),
            ):
                with self.subTest(args=args):
                    result = await self.tools['get_details'].handler(args, None)
                    self.assertEqual(result['status'], 'ok', result)
                    self.assertEqual(result['details']['id'], entity_id)

    async def test_information_ambiguity_and_errors_do_not_select_a_booking_entity(self):
        before = copy.deepcopy(self.engine.state)
        for args, status in (
            ({'entity': 'provider', 'query': 'Maria Garcia'}, 'clarify'),
            ({'entity': 'location', 'query': 'Mission clinic'}, 'clarify'),
            ({'entity': 'location', 'query': 'Nonexistent Clinic'}, 'no_match'),
            ({'entity': 'location'}, 'error'),
            ({'entity': 'location', 'id': 'missing'}, 'error'),
        ):
            with self.subTest(args=args):
                result = await self.tools['get_details'].handler(args, None)
                self.assertEqual(result['status'], status, result)
                self.assertEqual(self.engine.state, before)

    async def test_provider_details_include_catalog_site_and_service_names(self):
        result = await self.tools['get_details'].handler({'entity': 'provider', 'id': 'prov_003'}, None)
        details = result['details']
        self.assertEqual([s['id'] for s in details['locations']], details['location_ids'])
        self.assertEqual([s['id'] for s in details['services']], details['appointment_type_ids'])
        self.assertTrue(all(s['name'] for s in details['locations'] + details['services']))

    async def test_capability_block_at_providers_actual_site_is_preserved(self):
        result = await self.tools['resolve_options'].handler(dict(appointment_type_id='appt_065',
            provider_id='prov_014', location_id='loc_000', is_new_patient=True), None)
        self.assertEqual(self.engine.state.location_id, 'loc_000')
        self.assertIn('location_missing_capability', {i['code'] for i in result['blocked_options']})
        self.assertIn('lacks imaging', await self.reply())

    async def test_site_repair_invalidates_a_stale_proposal_without_auto_selecting(self):
        self.engine.resolve_options({**PROVIDER_ARGS, 'location_id': 'loc_005',
            'name': 'Alex Morgan', 'date_of_birth': '1990-04-12'})
        self.engine.find_slots(14)
        self.engine.select_slot('demo-offer')
        # Simulate an incompatible stored site without asking the tool to fix it.
        self.engine.state.location_id = 'loc_001'
        step = self.d.next_step()
        self.assertEqual(step['stage'], 'location')
        self.assertIsNone(self.engine.state.location_id)
        self.assertIsNone(self.engine.state.selected_slot_id)
        self.assertIsNone(self.engine.state.confirmation)
        self.assertFalse(self.engine.state.offered_slot_ids)
        self.assertFalse(self.engine.bookings)

    def test_information_schema_allows_a_query_without_an_id(self):
        tool = self.tools['get_details']
        self.assertIn('query', tool.properties)
        self.assertEqual(tool.required, ['entity'])
        self.assertIn('hours, phone, address and services', tool.description)
        self.assertIn('Never use for information questions', self.tools['resolve_options'].description)
