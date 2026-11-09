import unittest
from datetime import datetime
from pathlib import Path
from pipecat.frames.frames import LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame
from pipecat.processors.frame_processor import FrameDirection
from scheduling import SchedulingEngine, load_catalog
from scheduling.demo import generate_demo_availability
from scheduling_agent import build_scheduling_agent
from scheduling_dialogue import BookingSpeech


class DialogueTest(unittest.IsolatedAsyncioTestCase):
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
        for text in ("yes", "yeah, sure", "that's fine", "okay, book it"):
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
