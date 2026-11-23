"""v2-line parity checklist, replayed offline through the v4 candidate.

One test per checklist item (P-numbers follow the parity checklist built from
the DEV runs, the a-l smoke cases, call-anatomy/voice-findings demo calls and
the v2.1 transcripts). Scripted acts stand in for the interpreter; the real
core, catalog, demo availability, reducer, composer and session run unchanged.
"""
from tempfile import TemporaryDirectory
import unittest

from tests.test_v4_reducer import act, delta
from tests.v4_parity import (BOOKED, IDENTITY, OPENING, TO_READBACK, TO_SLOTS, acts, answer, choose,
                             correct, info, repeat, run, yes)

INTERNAL = ('could not apply', 'stale', 'rejected', 'appointment type', 'its name', 'Mon-Fri', ':00-')
from v4.composer import GOODBYES
SLOTS = ('For your Annual Physical with Nurse practitioner Maria Garcia at Midtown Medical Group, '
         'I have Monday November 23 at 4:20 PM or Monday November 30 at 4:20 PM. Which works for you?')


class ParityTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.sessions = []

    async def asyncTearDown(self):
        for session in self.sessions:
            await session.close()
        self.temp.cleanup()

    async def call(self, steps, *, readback_repeat=False, **kwargs):
        s, replies = await run(steps, self.temp.name, self.sessions, **kwargs)
        spoken = [text for text in replies if text is not None]
        for previous, current in zip(spoken, spoken[1:]):
            # The one allowed exception: a canonical read-back repeated on request.
            if not (readback_repeat and current.endswith('Shall I book it?')):
                self.assertNotEqual(previous, current)
        for text in spoken:
            for internal in INTERNAL:
                self.assertNotIn(internal, text)
            if s.r.control == 'active' and text not in GOODBYES:
                self.assertTrue(text.endswith('?'), text)
        return s, replies

    async def test_p01_greeting(self):
        s, replies = await self.call([])
        self.assertEqual(replies[0], 'Hi, I’m an AI scheduling assistant. How can I help you today?')

    async def test_p02_p04_p18_happy_path_books_once_with_contextual_slots(self):
        s, replies = await self.call(BOOKED)
        self.assertEqual(replies[4], SLOTS)
        self.assertEqual(replies[5], "I'll book an Annual Physical with Nurse practitioner Maria Garcia at Midtown "
                                     'Medical Group, Monday November 23 at 4:20 PM. Shall I book it?')
        self.assertEqual(replies[6], "You're all set for Monday, November 23 at 4:20 PM at Midtown Medical Group. "
                                     'Is there anything else I can help with?')
        self.assertEqual(len(s.r.engine.bookings), 1)

    async def test_p03_identity_readback(self):
        s, replies = await self.call(TO_SLOTS[:3])
        self.assertEqual(replies[3], 'Alex Morgan, born April 12, 1990, is that right?')

    async def test_p06_anything_else_no_says_goodbye_without_question(self):
        s, replies = await self.call(BOOKED + [('No, thank you.', answer('deny'))])
        self.assertEqual(replies[-1], "You're welcome. Have a great day.")

    async def test_p07_anything_else_yes_starts_a_new_request(self):
        s, replies = await self.call(BOOKED + [('Yes.', answer('affirm')),
                                               ('A flu shot as well.', acts(delta('service', 'flu shot')))])
        self.assertEqual(replies[-2], 'What else can I help you with?')
        # Step 3: an open provider is offered by name, with anyone available.
        self.assertEqual(replies[-1], 'A Flu Shot is offered by Dr. Maria Garcia in Pediatrics, Nurse practitioner '
                                      'Maria Garcia in Family Medicine, and Dr. Wei Chen in Internal Medicine, among '
                                      'others. Which would you like, or shall I look for anyone available?')
        self.assertEqual(len(s.r.engine.bookings), 1)

    async def test_p08_thanks_mid_flow_then_goodbye_after_cancel(self):
        s, replies = await self.call(TO_SLOTS[:1] + [('Thanks.', acts(act('acknowledge')))])
        # Step 4: the same site question again is asked in short form.
        self.assertEqual(replies[-1], "You're welcome. North Beach Specialty Center, Midtown Medical Group or "
                                      'Richmond Care Center?')
        s, replies = await self.call(TO_SLOTS[:2] + [
            ('Never mind, I have to go.', acts(act('cancel', scope='pending_request'))),
            ('Bye, thanks.', acts(act('acknowledge')))])
        self.assertIn('No appointment was booked.', replies[-2])
        self.assertEqual(replies[-1], "You're welcome. Have a great day.")

    async def test_p09_side_questions_before_service(self):
        s, replies = await self.call([('Hours and phone for Mission District Family Clinic?', acts(
            info('location', 'Mission District Family Clinic', 'hours'),
            info('location', 'Mission District Family Clinic', 'phone')))])
        self.assertTrue(replies[1].startswith('Mission District Family Clinic is open Monday to Friday, 8 AM to 5 PM. '
                                              'The phone number for Mission District Family Clinic is 4 1 5, 5 5 5,'))
        self.assertFalse(s.r.engine.state.location_id)

    async def test_p10_side_question_at_site_choice_keeps_the_choice(self):
        s, replies = await self.call(TO_SLOTS[:1] + [('Hours of Mission District?',
                                                      acts(info('location', 'Mission District', 'hours')))])
        self.assertTrue(replies[-1].startswith('Mission District Family Clinic is open'))
        self.assertTrue(replies[-1].endswith(replies[1]))
        self.assertFalse(s.r.engine.state.location_id)

    async def test_p11_side_question_at_slot_choice_repeats_choice_once(self):
        s, replies = await self.call(TO_SLOTS + [('Phone of the Mission District clinic?',
                                                  acts(info('location', 'Mission District clinic', 'phone')))])
        self.assertTrue(replies[-1].startswith('The phone number for Mission District Family Clinic is'))
        self.assertEqual(replies[-1].count('Which works for you?'), 1)
        self.assertEqual(s.r.engine.state.location_id, 'loc_005')

    async def test_p12_side_question_at_readback_keeps_the_booking_site(self):
        s, replies = await self.call(TO_READBACK + [('Hours of the Mission District clinic?',
                                                     acts(info('location', 'Mission District clinic', 'hours')))])
        self.assertTrue(replies[-1].endswith('Shall I book it?'))
        self.assertEqual(s.r.engine.state.location_id, 'loc_005')

    async def test_p13_address_services_and_provider_details_at_any_stage(self):
        s, replies = await self.call(TO_SLOTS[:2] + [('Where is Midtown Medical Group?',
                                                      acts(info('location', 'Midtown Medical Group', 'address')))])
        self.assertTrue(replies[-1].startswith('Midtown Medical Group is at 2099 Market Street, San Francisco.'))
        self.assertTrue(replies[-1].endswith('What is your full name and date of birth?'))
        s, replies = await self.call(TO_SLOTS + [('What services does Midtown offer?',
                                                  acts(info('location', 'Midtown', 'services')))])
        self.assertRegex(replies[-1], r'^Midtown Medical Group offers \d+ services, including ')
        self.assertLess(len(replies[-1]), 400)
        s, replies = await self.call([('Where does Dr. David Chen practice, and his specialty?', acts(
            info('provider', 'David Chen', 'locations'), info('provider', 'David Chen', 'specialty')))])
        self.assertIn('Downtown Health Center, and Richmond Care Center.', replies[-1])
        self.assertIn("Dr. David Chen's specialty is Cardiology.", replies[-1])
        s, replies = await self.call(BOOKED + [('Hours of Midtown?', acts(info('location', 'Midtown', 'hours')))])
        self.assertEqual(replies[-1], 'Midtown Medical Group is open Monday to Friday, 8 AM to 5 PM. '
                                      'Is there anything else I can help with?')

    async def test_p14_p16_repeat_requests_replay_the_choice(self):
        s, replies = await self.call(TO_SLOTS + [('What did you say?', repeat), ('Say that again?', repeat)])
        self.assertEqual(replies[-2], 'To repeat: ' + SLOTS)
        self.assertEqual(replies[-1], SLOTS)
        s, replies = await self.call(TO_READBACK + [('Can you repeat that?', repeat)], readback_repeat=True)
        self.assertEqual(replies[-1], replies[-2])  # The canonical read-back, repeated on request.

    async def test_p20_split_consent_books_once(self):
        s, replies = await self.call(BOOKED + [('Please.', acts(act('acknowledge')))])
        self.assertEqual(len(s.r.engine.bookings), 1)
        # Step 3: no thanks in the caller's words, so the goodbye thanks them.
        self.assertEqual(replies[-1], 'Thank you for calling. Have a great day.')

    async def test_p21_cancel_at_readback(self):
        s, replies = await self.call(TO_READBACK + [('Never mind, cancel that.',
                                                     acts(act('cancel', scope='pending_request')))])
        self.assertEqual(replies[-1], 'I have stopped that booking request. No appointment was booked. '
                                      'What service would you like to book?')
        self.assertFalse(s.r.engine.bookings)

    async def test_p22_provider_change_by_specialty_before_site(self):
        s, replies = await self.call([
            ('Annual physical with Dr. Maria Garcia in Pediatrics. New patient.', acts(
                delta('service', 'annual physical'), delta('provider', 'Dr. Maria Garcia'),
                delta('provider_specialty', 'Pediatrics'), delta('new_patient', True))),
            ('Actually Dr. Maria Garcia in Family Medicine instead.', acts(
                correct('provider', 'Dr. Maria Garcia'), correct('provider_specialty', 'Family Medicine')))])
        self.assertEqual(s.r.engine.state.provider_id, 'prov_003')
        self.assertIn('North Beach Specialty Center, Midtown Medical Group, and Richmond Care Center', replies[-1])

    async def test_p23_provider_change_during_site_choice_keeps_identity(self):
        s, replies = await self.call(TO_SLOTS[:1] + [
            ('Alex Morgan, April 12, 1990.', IDENTITY),
            ('Actually Dr. Maria Garcia in Pediatrics.', acts(correct('provider_specialty', 'Pediatrics')))])
        self.assertIn('Mission Bay Health Center', replies[-1])
        self.assertEqual(s.r.engine.state.patient_facts.name, 'Alex Morgan')

    async def test_p24_site_change_at_slot_choice(self):
        s, replies = await self.call(TO_SLOTS + [('Actually, Richmond instead.', acts(correct('location', 'Richmond')))])
        self.assertTrue(replies[-1].startswith('For your Annual Physical with Nurse practitioner Maria Garcia at '
                                               'Richmond Care Center, I have'))
        self.assertEqual(s.r.identity_confirmed, ('Alex Morgan', '1990-04-12'))

    async def test_p25_service_change_at_slot_choice(self):
        s, replies = await self.call(TO_SLOTS + [('A New Patient Consultation instead.',
                                                  acts(correct('service', 'New Patient Consultation')))])
        self.assertTrue(replies[-1].startswith('For your New Patient Consultation with Nurse practitioner Maria '
                                               'Garcia at Midtown Medical Group, I have'))

    async def test_p26_p51_capability_gate_names_a_site_that_can(self):
        s, replies = await self.call([('Knee MRI at Mission Bay only. Existing patient, referral on file.', acts(
            delta('service', 'MRI - Knee'), delta('location', 'Mission Bay'),
            delta('hard_constraint', {'field': 'location', 'enabled': True}),
            delta('new_patient', False), delta('referral', True)))])
        # Policy messages speak the service name (v1.5): 'MRI - Knee' -> 'a knee MRI'.
        # Step 8: the stated on-file referral is already recorded. Explain the
        # actual missing capability, without inventing a missing referral.
        self.assertEqual(replies[-1], 'Mission Bay Health Center cannot provide a knee MRI because it lacks imaging. '
                                      'A knee MRI is available at Downtown Health Center and Midtown Medical Group. '
                                      # Step 3: no clinic phone when an alternative can be booked here.
                                      'Which would you like, or something else?')

    async def test_p27_p28_duplicate_provider_name_is_explained(self):
        s, replies = await self.call([('An appointment with Dr. Maria Garcia.', acts(delta('provider', 'Dr. Maria Garcia'))),
                                      ('What do you mean?', acts(act('unclear', subject='meaning')))])
        self.assertEqual(replies[1], 'I found Dr. Maria Garcia in Pediatrics and Nurse practitioner Maria Garcia '
                                     'in Family Medicine. Which provider did you mean?')
        self.assertTrue(replies[2].startswith('There is more than one provider with that name.'))

    async def test_p29_duplicate_name_keeps_the_service(self):
        s, replies = await self.call([('An appointment with Dr. Maria Garcia.', acts(delta('provider', 'Dr. Maria Garcia'))),
                                      ('An annual physical. New patient.', acts(delta('service', 'annual physical'),
                                                                                delta('new_patient', True))),
                                      ('Uh-', acts(act('unclear', subject='meaning')))])
        self.assertIn('You asked for an Annual Physical and you are a new patient.', replies[-1])

    async def test_p30_combined_answer_skips_the_site_question(self):
        s, replies = await self.call([
            ('Annual physical with Dr. Maria Garcia. New patient.', acts(
                delta('service', 'annual physical'), delta('provider', 'Dr. Maria Garcia'), delta('new_patient', True))),
            ('The Family Medicine one, Midtown.', acts(delta('provider_specialty', 'Family Medicine'),
                                                       delta('location', 'Midtown')))])
        self.assertEqual(replies[-1], 'What is your full name and date of birth?')

    async def test_p31_p32_misspelled_provider_gets_closest_matches(self):
        s, replies = await self.call([('Annual physical with Dr. Mario Garcia.', acts(
            delta('service', 'annual physical'), delta('provider', 'Dr. Mario Garcia'))),
            ('Hello?', acts(act('unclear', subject='meaning')))])
        self.assertIn('The closest catalog matches are Dr. Maria Garcia in Pediatrics, Nurse practitioner Maria '
                      'Garcia in Family Medicine, and Dr. Carlos Garcia in Family Medicine.', replies[1])

    async def test_p33_p34_unknown_provider_then_insisted(self):
        s, replies = await self.call([
            ('Annual physical, only with Dr. Zephyr Imaginary.', acts(
                delta('service', 'annual physical'), delta('provider', 'Dr. Zephyr Imaginary'))),
            ('Z E P H Y R Imaginary.', acts(correct('provider', 'Zephyr Imaginary')))])
        self.assertEqual(replies[1], 'I could not find a provider by that name. Could you spell the first name '
                                     'and surname, or say any available provider?')
        self.assertTrue(replies[2].startswith('I still could not find a provider by that name.'))
        self.assertTrue(replies[2].endswith('Would you like a different provider, or any available provider?'))
        self.assertIsNone(s.r.engine.state.provider_id)

    async def test_p35_unknown_provider_then_self_correction(self):
        s, replies = await self.call([
            ('Annual physical with Dr. Zephyr Imaginary. New patient.', acts(
                delta('service', 'annual physical'), delta('provider', 'Dr. Zephyr Imaginary'), delta('new_patient', True))),
            ('Sorry, Dr. Maria Garcia in Family Medicine.', acts(
                correct('provider', 'Dr. Maria Garcia'), delta('provider_specialty', 'Family Medicine')))])
        self.assertEqual(replies[-1], 'For your Annual Physical, Nurse practitioner Maria Garcia sees patients at '
                                      'North Beach Specialty Center, Midtown Medical Group, and Richmond Care Center. '
                                      'Which location works best for you?')

    async def test_p36_misspelled_clinic_lists_the_valid_sites(self):
        # v1.6: a small speech-to-text distortion of a site name resolves to that site.
        s, replies = await self.call(TO_SLOTS[:1] + [('Midtwon.', acts(delta('location', 'Midtwon')))])
        self.assertEqual(s.r.engine._location().name, 'Midtown Medical Group')
        self.assertEqual(replies[-1], 'What is your full name and date of birth?')
        s, replies = await self.call(TO_SLOTS[:1] + [('Northgait.', acts(delta('location', 'Northgait clinic')))])
        self.assertTrue(replies[-1].startswith('I could not find a clinic by that name.'), replies[-1])

    async def test_p37_vague_service_offers_catalog_suggestions(self):
        s, replies = await self.call([('I need a full skin check.', acts(delta('service', 'full skin check'))),
                                      ('The first one.', choose(1))])
        self.assertTrue(replies[1].startswith('I could not find a service by that name. The closest services are '
                                              'Full Body Skin Exam, Skin Cancer Screening'), replies[1])
        self.assertEqual(s.r.engine._appointment_type().name, 'Full Body Skin Exam')

    async def test_p38_unknown_service(self):
        s, replies = await self.call([('I want acupuncture.', acts(delta('service', 'acupuncture')))])
        self.assertEqual(replies[1], 'I could not find a service by that name. What service would you like to book?')

    async def test_p39_split_identity_and_partial_dob(self):
        s, replies = await self.call(TO_SLOTS[:2] + [
            ('Alex Morgan.', acts(delta('name', 'Alex Morgan'))),
            ('April 1990.', acts(delta('date_of_birth', {'year': 1990, 'month': 4, 'day': None}))),
            ('The 12th.', acts(delta('date_of_birth', {'year': None, 'month': None, 'day': 12})))])
        self.assertEqual(replies[3:], ['And your date of birth?', 'Which day in April 1990?',
                                       'Alex Morgan, born April 12, 1990, is that right?'])

    async def test_p40_p41_identity_corrections_reread(self):
        s, replies = await self.call(TO_SLOTS[:3] + [('Actually 1991, not 1990.', acts(
            correct('date_of_birth', {'year': 1991, 'month': 4, 'day': 12})))])
        self.assertEqual(replies[-1], 'Alex Morgan, born April 12, 1991, is that right?')
        s, replies = await self.call(TO_SLOTS[:3] + [('No, Alexa Morgan.', acts(correct('name', 'Alexa Morgan')))])
        self.assertEqual(replies[-1], 'Alexa Morgan, born April 12, 1990, is that right?')

    async def test_p42_p43_sole_site_is_stated_and_yes_continues(self):
        s, replies = await self.call([
            ('Flu shot with Dr. Maria Garcia the pediatrician. Existing patient. Alex Morgan, April 12, 1990.', acts(
                delta('service', 'flu shot'), delta('provider', 'Dr. Maria Garcia'),
                delta('provider_specialty', 'Pediatrics'), delta('new_patient', False), *IDENTITY['acts'])),
            ('Yes.', answer('affirm'))])
        self.assertEqual(replies[1], 'For your Flu Shot, Dr. Maria Garcia practices only at Mission Bay Health Center. '
                                     'Shall I look for appointments there?')
        self.assertEqual(replies[2], 'Alex Morgan, born April 12, 1990, is that right?')
        self.assertEqual(s.r.engine.state.location_id, 'loc_000')

    async def test_p44_p45_human_help_is_honest_and_does_not_loop(self):
        s, replies = await self.call(TO_SLOTS[:2] + [('Can I speak to a person?', acts(act('human_request', action='request'))),
                                                     ("Let's just continue.", acts(act('acknowledge')))])
        self.assertEqual(replies[-2], 'I cannot transfer this call or arrange a callback. '
                                      'You can call Midtown Medical Group at 4 1 5, 5 5 5, 5 9 1 9. '
                                      'Is there anything else I can help with?')
        # Step 3: never the dead end "I cannot continue scheduling on this call". Step 8: an okay
        # after the honest answer resumes the request where it was (f17), not the facts again.
        self.assertTrue(replies[-1].endswith('What is your full name and date of birth?'), replies[-1])
        self.assertEqual(s.r.control, 'active')

    async def test_p46_p47_emergency_at_any_stage(self):
        urgent = ('My chest hurts a lot.', acts(act('urgent_escalation')))
        for prefix in ([], TO_SLOTS, BOOKED):
            s, replies = await self.call(prefix + [urgent])
            self.assertEqual(replies[-1], 'Please call emergency services right now. I cannot provide medical advice.')
            self.assertEqual(s.r.control, 'urgent')

    async def test_p48_p49_p50_policy_refusals_ask_one_question(self):
        cases = [
            (acts(delta('new_patient', True), delta('service', 'MRI - Knee'), delta('provider', 'Linda Ramirez'),
                  delta('location', 'Downtown')), 'A knee MRI is only for existing patients, so I cannot book it '
                                                  'for a new patient. As a new patient, you could book'),
            (acts(delta('new_patient', True), delta('service', 'Cardiology Consultation'), delta('provider', 'David Chen'),
                  delta('location', 'Downtown'), delta('hard_constraint', {'field': 'provider', 'enabled': True})),
             'Dr. David Chen is not accepting new patients.'),
            (acts(delta('service', 'Dermatology Consultation'), delta('new_patient', False), delta('referral', False)),
             'A Dermatology Consultation needs a referral on file, so I cannot book it without one. '
             'Once your referral is on file, you can book it.')]
        for raw, message in cases:
            s, replies = await self.call([('Request.', raw)])
            self.assertTrue(replies[1].startswith(message), replies[1])
            # Step 3: a block names its alternatives and asks about them, never "change the request".
            self.assertTrue(replies[1].endswith(('Would you like that, or something else?', 'Which would you like, or '
                                                 'something else?', 'Is there anything else I can help with?')), replies[1])
            self.assertNotIn('change the request', replies[1])
            self.assertEqual(replies[1].count('?'), 1)

    async def test_p52_p53_p54_valid_requests_proceed(self):
        s, replies = await self.call([('Flu shot with Dr. Maria Garcia the pediatrician at Mission Bay.', acts(
            delta('service', 'flu shot'), delta('provider', 'Dr. Maria Garcia'), delta('provider_specialty', 'Pediatrics'),
            delta('location', 'Mission Bay'), delta('new_patient', False)))])
        self.assertEqual(replies[1], 'What is your full name and date of birth?')
        s, replies = await self.call([('Annual physical, new patient, any clinician, any site.', acts(
            delta('service', 'annual physical'), delta('new_patient', True), delta('any_provider', True),
            delta('any_location', True))), ('Alex Morgan, April 12, 1990.', IDENTITY), ('Yes.', yes)])
        self.assertTrue(replies[-1].startswith('For your Annual Physical, I have'))
        self.assertEqual(replies[-1].count(' with '), 3)

    async def test_p56_p58_no_availability_on_a_requested_date(self):
        s, replies = await self.call(TO_SLOTS + [('Sunday November 22?', acts(delta('appointment_date', '2026-11-22')))])
        self.assertEqual(replies[-1], 'I have no appointments on Sunday, November 22 for this request. You can call '
                                      'Midtown Medical Group at 4 1 5, 5 5 5, 5 9 1 9. '
                                      'Would you like to change the date or location?')

    async def test_p60_pause_then_resume(self):
        s, replies = await self.call([('Wait, let me check.', acts(act('pause'))), ('Annual physical...', OPENING)])
        self.assertEqual(replies[1], 'Take your time. What would you like to check before we continue?')
        self.assertTrue(replies[2].startswith('For your Annual Physical'))

    async def test_extra_thanks_during_readback_and_assistant_identity(self):
        s, replies = await self.call(TO_READBACK + [('Thanks.', acts(act('acknowledge')))])
        # v1.5: thanks keeps the open read-back (same proposal, no new one) and asks again.
        self.assertEqual(replies[-1], "You're welcome. Shall I book it?")
        bookings = [p for p in s.r.proposals.values() if p.kind == 'booking']
        self.assertEqual([p.status for p in bookings], ['open'])
        self.assertFalse(s.r.engine.bookings)
        s, replies = await self.call([('Am I talking to a real person?', acts(info('assistant', None, 'identity')))])
        self.assertEqual(replies[1], "I'm an AI scheduling assistant, not a person. What service would you like to book?")

    async def test_p39b_split_name_parts_complete_the_name(self):
        s, replies = await self.call(TO_SLOTS[:2] + [
            ('April 12, 1990.', acts(delta('date_of_birth', {'year': 1990, 'month': 4, 'day': 12}))),
            ('Alex.', acts(delta('name', 'Alex'))),
            ('Morgan.', acts(correct('name', 'Morgan')))])
        self.assertEqual(replies[3:], ['And your full name?', 'And your last name?',
                                       'Alex Morgan, born April 12, 1990, is that right?'])

    async def test_p39c_generic_request_asks_what_kind(self):
        s, replies = await self.call([('I would like to schedule an appointment.',
                                       acts(delta('service', 'appointment')))])
        self.assertEqual(replies[1], 'What kind of appointment would you like?')


if __name__ == '__main__':
    unittest.main()
