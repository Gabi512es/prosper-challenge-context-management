import unittest
from datetime import datetime
from pathlib import Path
from pipecat.frames.frames import LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection
from scheduling import SchedulingEngine, load_catalog
from scheduling.demo import generate_demo_availability
from scheduling_agent import build_scheduling_agent
from scheduling_dialogue import BookingSpeech, PatientInput


class DialogueTest(unittest.IsolatedAsyncioTestCase):
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
        self.assertIn("April 19, 1994", self.d.render(slot))

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
        slots = e.find_slots(30)["slots"]
        slot = slots[0]
        book = next(f for f in self.builder.build_initial_node()["functions"] if f.name == "book_appointment")
        self.assertNotEqual((await book.handler({"slot_id": slot["slot_id"]}, None))["status"], "booked")
        self.d.pending = ("offer", slot)
        speech = BookingSpeech(self.d)
        emitted = []
        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            emitted.append(frame)
        speech.push_frame = capture
        await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        text = emitted[0].text
        for fact in ("Alex Morgan", "April 12, 1990", "Linda Ramirez", "Downtown", "MRI - Knee", "Shall I book it?"):
            self.assertIn(fact, text)
        self.d.patient("Yes, please book it")
        self.assertEqual((await book.handler({"slot_id": slot["slot_id"]}, None))["status"], "booked")
        self.assertEqual((await book.handler({"slot_id": slot["slot_id"]}, None))["status"], "idempotent")
        self.assertEqual(len(e.bookings), 1)
        self.d.patient("Wait, wait, wait")
        self.assertIsNone(e.state.confirmation)
        await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        self.assertIn("What would you like to change", emitted[-2].text)
