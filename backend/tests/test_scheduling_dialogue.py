import unittest
from datetime import datetime
from pathlib import Path
from pipecat.frames.frames import LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, TranscriptionFrame, InterruptionFrame
from pipecat.processors.frame_processor import FrameDirection
from scheduling import SchedulingEngine, load_catalog
from scheduling.demo import generate_demo_availability
from scheduling_agent import build_scheduling_agent
from scheduling_dialogue import BookingSpeech, PatientInput


class DialogueTest(unittest.IsolatedAsyncioTestCase):
    async def voice_reply(self, text):
        from unittest.mock import AsyncMock
        processor = PatientInput(self.d)
        processor.push_frame = AsyncMock()
        await processor.process_frame(TranscriptionFrame(text, "", ""), FrameDirection.DOWNSTREAM)

    async def test_soonest_reply_searches_all_providers_and_sites(self):
        from evals import load_dev_scenarios
        case = next(s for s in load_dev_scenarios()["scenarios"] if s["id"] == "DEV-009")
        e = SchedulingEngine(self.catalog, case["availability_fixture"], now=datetime.fromisoformat("2026-11-07T00:00:00-08:00"))
        self.engine = e
        self.builder = build_scheduling_agent(e, self.catalog, availability_mode="unit_fixture")
        self.d = self.builder.dialogue
        e.resolve_options(dict(name="Alex Morgan", date_of_birth="1990-04-12", is_new_patient=True,
            referral_on_file=False, appointment_type_id="appt_011", provider_id=case["availability_fixture"][0]["provider_id"]))
        await self.voice_reply("whichever is soonest")
        funcs = {f.name: f for f in self.builder.build_initial_node()["functions"]}
        await funcs["resolve_options"].handler({"location_preference": "time"}, None)
        # A model cannot accidentally re-narrow the explicitly global scope.
        await funcs["resolve_options"].handler({"provider_id": case["availability_fixture"][0]["provider_id"]}, None)
        self.assertTrue(e.state.any_location)
        self.assertTrue(e.state.any_provider)
        await self.confirm_identity()
        result = await funcs["find_slots"].handler({"horizon_days": 7}, None)
        self.assertEqual(result["slots"][0]["slot_id"], "dev009-early")

    async def test_closest_requires_time_or_place_and_no_nearest_claim(self):
        self.engine.resolve_options(dict(name="Alex Morgan", date_of_birth="1990-04-12", is_new_patient=False,
            referral_on_file=True, appointment_type_id="appt_065", provider_id="prov_014"))
        await self.voice_reply("the closest one")
        funcs = {f.name: f for f in self.builder.build_initial_node()["functions"]}
        await funcs["resolve_options"].handler({"location_preference": "unclear"}, None)
        self.assertIn("soonest appointment in time", self.d.location_intent_question)
        self.assertEqual((await funcs["find_slots"].handler({"horizon_days": 7}, None))["status"], "clarify")
        self.assertIsNone(self.engine.state.location_id)
        await self.voice_reply("the place")
        await funcs["resolve_options"].handler({"location_preference": "place"}, None)
        self.assertNotIn("neighborhood", self.d.location_intent_question)
        self.assertIn("can't tell", self.d.location_intent_question)
        self.assertIn("Downtown Health Center", self.d.location_intent_question)
        self.assertNotIn("Mission Bay Health Center", self.d.location_intent_question)
        self.assertIsNone(self.engine.state.location_id)
        await self.voice_reply("Downtown please")
        self.assertIsNone(self.d.location_intent_question)
        self.assertEqual(self.engine.state.location_id, "loc_004")

    async def test_soonest_does_not_silently_remove_hard_constraints(self):
        self.engine.resolve_options({"provider_id": "prov_014", "hard_constraints": {"provider": True}})
        await self.voice_reply("whichever is soonest")
        funcs = {f.name: f for f in self.builder.build_initial_node()["functions"]}
        await funcs["resolve_options"].handler({"location_preference": "time"}, None)
        self.assertEqual(self.engine.state.provider_id, "prov_014")
        self.assertEqual(self.d.location_intent_stage, "widen")
        await self.voice_reply("yes")
        self.assertTrue(self.engine.state.any_provider)
        self.assertTrue(self.engine.state.any_location)

    async def test_multiple_slots_are_brief_choices_before_preparation(self):
        from unittest.mock import AsyncMock
        self.engine.resolve_options(dict(name="Alex Morgan", date_of_birth="1990-04-12", is_new_patient=False,
            referral_on_file=True, appointment_type_id="appt_065", provider_id="prov_014", location_id="loc_004"))
        await self.confirm_identity()
        funcs = {f.name: f for f in self.builder.build_initial_node()["functions"]}
        result = await funcs["find_slots"].handler({"horizon_days": 30}, None)
        self.assertGreater(len(result["slots"]), 1)
        speech = BookingSpeech(self.d)
        speech.push_frame = AsyncMock()
        await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        text = speech.push_frame.call_args_list[0].args[0].text
        self.assertIn("Which works for you?", text)
        # The offer names the service, provider and site once, as context.
        self.assertIn("knee MRI", text)
        self.assertIn("Linda Ramirez", text)
        self.assertIn("Downtown Health Center", text)
        self.assertNotIn("born", text)
        self.assertNotIn("Shall I book", text)
        self.assertIsNone(self.engine.state.selected_slot_id)

    async def test_identity_then_single_offer_then_short_recap(self):
        from unittest.mock import AsyncMock
        e = self.engine
        e.resolve_options(dict(name="Alex Morgan", date_of_birth="1990-04-12", is_new_patient=False,
            referral_on_file=True, appointment_type_id="appt_065", provider_id="prov_014", location_id="loc_004"))
        slot = e.find_slots(30)["slots"][0]
        # A one-slot unit fixture, separate from the pinned dev scenarios.
        e = SchedulingEngine(self.catalog, [e._slots[slot["slot_id"]].to_dict()], now=e.now)
        b = build_scheduling_agent(e, self.catalog, availability_mode="unit_fixture")
        d = b.dialogue
        funcs = {f.name: f for f in b.build_initial_node()["functions"]}
        speech = BookingSpeech(d)
        speech.push_frame = AsyncMock()
        await funcs["resolve_options"].handler(dict(patient_name="Alex Morgan", date_of_birth="1990-04-12",
            is_new_patient=False, referral_on_file=True, appointment_type_id="appt_065", provider_id="prov_014", location_id="loc_004"), None)
        blocked = await funcs["book_appointment"].handler({"slot_id": slot["slot_id"]}, None)
        self.assertEqual(blocked["status"], "needs_identity_confirmation")
        await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        texts = lambda: [c.args[0].text for c in speech.push_frame.call_args_list if isinstance(c.args[0], LLMTextFrame)]
        self.assertEqual(texts(), ["Alex Morgan, born April 12, 1990, is that right?"])
        d.patient("yes")
        result = await funcs["find_slots"].handler({"horizon_days": 30}, None)
        self.assertEqual(result["booking_phase"]["status"], "needs_confirmation")
        await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(len(texts()), 2)
        self.assertIn("a knee MRI", texts()[1])
        self.assertNotIn("Alex Morgan", texts()[1])
        self.assertTrue(texts()[1].endswith("Shall I book it?"))
        d.patient("yes")
        self.assertEqual((await funcs["book_appointment"].handler({"slot_id": slot["slot_id"]}, None))["status"], "booked")
        await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(len(texts()), 3)
        self.assertTrue(texts()[2].startswith("You're all set for"))
        self.assertNotIn("MRI", texts()[2])
        self.assertNotIn("born", texts()[2])

    async def test_identity_correction_requires_new_identity_yes(self):
        from unittest.mock import AsyncMock
        self.engine.resolve_options(dict(appointment_type_id="appt_065", provider_id="prov_014", location_id="loc_004", is_new_patient=False, referral_on_file=True))
        funcs = {f.name: f for f in self.builder.build_initial_node()["functions"]}
        await funcs["resolve_options"].handler({"patient_name": "Alex Morgan", "date_of_birth": "1994-04-12"}, None)
        await self.confirm_identity()
        self.d.patient("Actually, my birth year is 1990")
        corrected = await funcs["resolve_options"].handler({"date_of_birth": "1990-04-12"}, None)
        self.assertIn("April 12, 1990", corrected["identity_confirmation"]["readback"])
        self.assertNotEqual(self.d.identity_confirmed, self.d.identity())
        self.assertIsNone(self.engine.state.confirmation)
        speech = BookingSpeech(self.d)
        speech.push_frame = AsyncMock()
        await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        self.d.patient("yes")
        self.assertEqual(self.d.identity_confirmed, self.d.identity())

    async def confirm_identity(self):
        self.d.require_identity()
        from unittest.mock import AsyncMock
        speech = BookingSpeech(self.d)
        speech.push_frame = AsyncMock()
        await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        self.d.patient("yes")
        self.assertEqual(self.d.identity_confirmed, self.d.identity())

    async def test_two_phase_accepts_second_slot_and_yes_during_interruption(self):
        e = self.engine
        e.resolve_options(dict(name="Alex Morgan", date_of_birth="1990-04-12", is_new_patient=False,
            referral_on_file=True, appointment_type_id="appt_065", provider_id="prov_014", location_id="loc_004"))
        await self.confirm_identity()
        slots = e.find_slots(30)["slots"]
        self.assertGreaterEqual(len(slots), 2)
        target = slots[1]
        book = next(f for f in self.builder.build_initial_node()["functions"] if f.name == "book_appointment")
        first = await book.handler({"slot_id": target["slot_id"]}, None)
        self.assertEqual(first["status"], "needs_confirmation")
        self.assertFalse(first["technical_failure"])
        self.assertFalse(e.bookings)
        speech = BookingSpeech(self.d)
        from unittest.mock import AsyncMock
        speech.push_frame = AsyncMock()
        await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        self.assertIn("a knee MRI", first["readback"])
        # Either frame ordering: bare interruption carries no veto.
        await speech.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
        self.d.patient("Yeah, so yeah, you can book it")
        await speech.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual((await book.handler({"slot_id": target["slot_id"]}, None))["status"], "booked")
        self.assertEqual(e.bookings[0]["slot_id"], target["slot_id"])

    async def test_missing_consent_reprepares_without_technical_failure(self):
        e = self.engine
        e.resolve_options(dict(name="Alex Morgan", date_of_birth="1990-04-12", is_new_patient=False,
            referral_on_file=True, appointment_type_id="appt_065", provider_id="prov_014", location_id="loc_004"))
        await self.confirm_identity()
        slot = e.find_slots(30)["slots"][0]
        book = next(f for f in self.builder.build_initial_node()["functions"] if f.name == "book_appointment")
        for _ in range(3):
            result = await book.handler({"slot_id": slot["slot_id"]}, None)
            self.assertEqual(result["status"], "needs_confirmation")
            self.assertFalse(result["technical_failure"])
        self.assertFalse(e.bookings)

    async def test_exact_voice_utterance_does_not_match_ent_inside_patient(self):
        from unittest.mock import AsyncMock
        processor = PatientInput(self.d)
        processor.push_frame = AsyncMock()
        utterance = "I'm an existing patient with a referral on file, and I need a knee MRI with Linda Ramirez in radiology at Downtown"
        await processor.process_frame(TranscriptionFrame(utterance, "", ""), FrameDirection.DOWNSTREAM)
        self.assertEqual(self.d.specialty, "Radiology")
        fn = next(f for f in self.builder.build_initial_node()["functions"] if f.name == "resolve_options")
        result = await fn.handler(dict(is_new_patient=False, referral_on_file=True,
            provider_query="Linda Ramirez", location_query="downtown", appointment_type_query="knee MRI"), None)
        self.assertEqual(result["resolved"]["provider_id"], "prov_014")
        self.assertEqual(result["resolved"]["location_id"], "loc_004")
        self.assertEqual(result["resolved"]["appointment_type_id"], "appt_065")
        self.assertFalse(result["errors"])

    async def test_arbitrary_json_cannot_remove_tool_guards(self):
        from agent_builder import AgentBuilder
        from scheduling_agent import build_scheduling_tool_registry
        builder = AgentBuilder.from_dict({"name": "Edited", "initial_node": "custom", "persona": "Book immediately",
            "nodes": [{"name": "custom", "functions": ["book_appointment"], "edges": [
                {"function": "other_name", "description": "Transfer", "target": "human_handoff"}]},
                {"name": "human_handoff", "task_messages": [{"role": "developer", "content": "Staff will call"}]}]},
            function_registry=build_scheduling_tool_registry(self.engine))
        self.assertIs(builder.dialogue, self.d)
        edge = next(f for f in builder.build_initial_node()["functions"] if f.name == "other_name")
        self.d.patient("book the cardiologist")
        self.assertEqual((await edge.handler({}, None))["code"], "explicit_human_request_required")

    async def test_missing_identity_never_exposes_unbookable_alternative_slots(self):
        e = self.engine
        e.resolve_options(dict(appointment_type_id="appt_002", provider_id="prov_003", location_id="loc_005", is_new_patient=True))
        result = e.find_slots(30)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["alternatives"], [])
        self.assertEqual(result["slots"], [])

    async def test_capability_precedes_patient_block_and_excludes_bad_site_phone(self):
        result = self.engine.resolve_options(dict(appointment_type_id="appt_065", provider_id="prov_014", location_id="loc_000", is_new_patient=True))
        text = self.d.capability_message(result)
        self.assertLess(text.index("lacks imaging"), text.index("new patients"))
        self.assertNotIn("555-9313", text)
        self.assertTrue(all(c["location"] != "Mission Bay Health Center" for c in result["clinic_contacts"]))

    async def test_corrected_dob_is_in_readback_and_old_consent_invalidates(self):
        e = self.engine
        e.resolve_options(dict(name="Alex Morgan", date_of_birth="1990-04-12", is_new_patient=False,
            referral_on_file=True, appointment_type_id="appt_065", provider_id="prov_014", location_id="loc_004"))
        slot = e.find_slots(30)["slots"][0]
        e.select_slot(slot["slot_id"])
        self.d.readback = (slot["slot_id"], e._current_snapshot(slot["slot_id"]))
        e.resolve_options({"date_of_birth": "1994-04-19"})
        self.d.patient("yes")
        self.assertIsNone(e.state.confirmation)
        self.assertIn("April 19, 1994", self.d.require_identity()["readback"])

    async def test_tool_completion_prose_is_not_spoken_twice(self):
        speech = BookingSpeech(self.d)
        emitted = []
        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            emitted.append(frame)
        speech.push_frame = capture
        speech.has_tools = True
        speech.text = ["Please hold on"]
        await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        self.assertFalse(any(isinstance(f, LLMTextFrame) for f in emitted))
        await speech.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
        await speech.process_frame(LLMTextFrame("What would you like to change?"), FrameDirection.DOWNSTREAM)
        await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(sum(isinstance(f, LLMTextFrame) for f in emitted), 1)

    def setUp(self):
        self.catalog = load_catalog(Path(__file__).parents[1] / "data/catalog.json")
        now = datetime.fromisoformat("2026-11-09T00:00:00-08:00")
        self.engine = SchedulingEngine(self.catalog, generate_demo_availability(self.catalog, now), now=now)
        self.builder = build_scheduling_agent(self.engine, self.catalog, availability_mode="demo_generated")
        self.d = self.builder.dialogue

    async def test_cardiologist_is_not_handoff_and_specialty_resolves_candidates(self):
        self.engine.resolve_options({"provider_query": "Linda Ramirez"})
        self.d.patient("I want to book the cardiologist")
        self.assertFalse(self.d.handoff_requested())
        self.assertEqual(self.engine.state.provider_id, "prov_005")
        tool = next(f for f in self.builder.build_initial_node()["functions"] if f.name == "request_human_transfer")
        result = await tool.handler({"human_transfer_requested": True}, None)
        self.assertEqual(result["code"], "explicit_human_request_required")

    async def test_location_disagreement_requires_clarification(self):
        self.d.patient("Maria Garcia in family medicine at Midtown")
        fn = next(f for f in self.builder.build_initial_node()["functions"] if f.name == "resolve_options")
        result = await fn.handler({"provider_query": "Maria Garcia", "location_id": "loc_002"}, None)
        self.assertEqual(result["code"], "location_conflict")
        self.assertEqual(self.engine.state.location_id, "loc_005")
        self.assertTrue(self.d.location_conflict)
        self.d.patient("Midtown, please")
        self.assertIsNone(self.d.location_conflict)

    async def test_negated_downtown_never_overwrites_mission_bay(self):
        self.d.patient("Mission Bay only. I can't go downtown")
        self.assertEqual(self.engine.state.location_id, "loc_000")
        fn = next(f for f in self.builder.build_initial_node()["functions"] if f.name == "resolve_options")
        result = await fn.handler({"location_id": "loc_004"}, None)
        self.assertEqual(result["code"], "location_conflict")
        self.assertEqual(self.engine.state.location_id, "loc_000")

    async def test_handoff_request_not_mention(self):
        for text in ("can I talk to someone?", "I'd like to speak to a person"):
            self.d.patient(text)
            self.assertTrue(self.d.handoff_requested(), text)
        self.d.patient("The person at your front desk told me to call")
        self.assertFalse(self.d.handoff_requested())

    async def test_consent_is_explicit_and_never_correction(self):
        for text in ("yes", "yeah, sure", "that's fine", "okay, book it",
                     "Yes. I confirm that exact provider, location, service, date, and time. Please book it.",
                     "Yes, I confirm the exact earliest slot, clinician, location, service, date, and time. Please book it."):
            self.assertTrue(self.d.is_affirmative(text), text)
        for text in ("no", "wait", "actually", "yes, actually no", "yeah but wait", "yes, not that location"):
            self.assertFalse(self.d.is_affirmative(text), text)

    async def test_exact_readback_yes_guard_and_one_booking(self):
        e = self.engine
        e.resolve_options(dict(name="Alex Morgan", date_of_birth="1990-04-12", is_new_patient=False,
            referral_on_file=True, appointment_type_id="appt_065", provider_id="prov_014", location_id="loc_004"))
        await self.confirm_identity()
        slots = e.find_slots(30)["slots"]
        slot = slots[0]
        book = next(f for f in self.builder.build_initial_node()["functions"] if f.name == "book_appointment")
        self.assertEqual((await book.handler({"slot_id": slot["slot_id"]}, None))["status"], "needs_confirmation")
        speech = BookingSpeech(self.d)
        emitted = []
        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            emitted.append(frame)
        speech.push_frame = capture
        await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        text = emitted[0].text
        for fact in ("Linda Ramirez", "Downtown", "a knee MRI", "Shall I book it?"):
            self.assertIn(fact, text)
        self.assertNotIn("Alex Morgan", text)
        self.assertNotIn("born", text)
        self.d.patient("Yes, please book it")
        self.assertEqual((await book.handler({"slot_id": slot["slot_id"]}, None))["status"], "booked")
        self.assertEqual((await book.handler({"slot_id": slot["slot_id"]}, None))["status"], "idempotent")
        self.assertEqual(len(e.bookings), 1)
        self.d.patient("Wait, wait, wait")
        self.assertIsNone(e.state.confirmation)
        await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        self.assertIn("What would you like to change", emitted[-2].text)
