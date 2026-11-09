import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

from pipecat.frames.frames import TranscriptionFrame, LLMFullResponseEndFrame, LLMTextFrame
from pipecat.processors.frame_processor import FrameDirection
from scheduling import SchedulingEngine, load_catalog
from scheduling.demo import generate_demo_availability
from scheduling_agent import build_scheduling_agent
from scheduling_dialogue import PatientInput, BookingSpeech


class SlotFillingSequenceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        catalog = load_catalog(Path(__file__).parents[1] / "data/catalog.json")
        now = datetime.fromisoformat("2026-11-09T00:00:00-08:00")
        self.engine = SchedulingEngine(catalog, generate_demo_availability(catalog, now), now=now)
        builder = build_scheduling_agent(self.engine, catalog, availability_mode="unit_fixture")
        self.d = builder.dialogue
        self.tools = {f.name: f for f in builder.build_initial_node()["functions"]}
        self.input = PatientInput(self.d)
        self.input.push_frame = AsyncMock()
        self.output = BookingSpeech(self.d)
        self.output.push_frame = AsyncMock()

    async def patient(self, text):
        await self.input.process_frame(TranscriptionFrame(text, "patient", ""), FrameDirection.DOWNSTREAM)

    async def say(self):
        before = self.output.push_frame.call_count
        await self.output.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        return "".join(call.args[0].text for call in self.output.push_frame.call_args_list[before:]
                       if isinstance(call.args[0], LLMTextFrame))

    async def test_site_then_two_identity_segments_confirmation_and_offer(self):
        await self.tools["resolve_options"].handler({"appointment_type_id": "appt_002", "provider_id": "prov_003", "is_new_patient": True}, None)
        self.assertEqual(self.d.next_step()["stage"], "location")
        await self.tools["resolve_options"].handler({"location_preference": "place"}, None)
        self.assertIn("Midtown", await self.say())
        await self.patient("Midtown")
        await self.tools["resolve_options"].handler({"location_id": "loc_005"}, None)
        self.assertIn("full name and date of birth", await self.say())
        self.assertEqual(self.d.next_step()["stage"], "identity")

        await self.patient("Alex Morgan, April 12th.")
        await self.tools["resolve_options"].handler({"patient_name": "Alex Morgan", "location_preference": "place"}, None)
        self.assertEqual(self.engine.state.location_id, "loc_005")
        self.assertEqual(self.engine.state.patient_facts.name, "Alex Morgan")
        self.assertEqual(await self.say(), "What year were you born?")
        # A check-in cannot erase partial identity or restart site selection.
        await self.patient("Hello?")
        self.assertEqual(self.d.next_step()["stage"], "identity")
        self.assertEqual(self.engine.state.location_id, "loc_005")
        await self.patient("1991.")
        await self.tools["resolve_options"].handler({}, None)
        self.assertEqual(self.engine.state.patient_facts.date_of_birth, "1991-04-12")
        self.assertEqual(await self.say(), "Alex Morgan, born April 12, 1991, is that right?")
        await self.patient("yes")
        self.assertEqual(self.d.next_step()["stage"], "offer")
        self.assertEqual(self.d.identity_confirmed, ("Alex Morgan", "1991-04-12"))

        result = await self.tools["find_slots"].handler({"horizon_days": 30}, None)
        self.assertTrue(result["slots"])
        self.assertTrue(all(s["location_id"] == "loc_005" for s in result["slots"]))
        await self.say()
        slot = result["slots"][0]
        await self.tools["book_appointment"].handler({"slot_id": slot["slot_id"]}, None)
        offer = await self.say()
        self.assertIn("Shall I book it?", offer)
        self.assertIn("Midtown Medical Group", offer)
        self.assertNotIn("born", offer)
        await self.patient("yes")
        self.assertEqual((await self.tools["book_appointment"].handler({"slot_id": slot["slot_id"]}, None))["status"], "booked")
        self.assertEqual(self.engine.bookings[0]["location_id"], "loc_005")

    async def test_alternating_questions_are_caught_within_recent_history(self):
        self.engine.resolve_options({"appointment_type_id": "appt_002", "provider_id": "prov_003", "location_id": "loc_005", "is_new_patient": True})
        a = "What is your full name and date of birth?"
        b = "Please give your name and birthday?"
        self.assertEqual(self.d.avoid_repeated_question(a), a)
        self.assertEqual(self.d.avoid_repeated_question(b), b)
        retry = self.d.avoid_repeated_question(a)
        self.assertNotIn(retry, {a, b})
        self.assertNotIn("Eligible sites", retry)
        self.assertEqual(self.engine.state.location_id, "loc_005")

    async def test_rephrased_identity_question_still_accepts_yes(self):
        self.engine.resolve_options({"appointment_type_id": "appt_002", "provider_id": "prov_003", "location_id": "loc_005", "is_new_patient": True,
                                     "name": "Alex Morgan", "date_of_birth": "1991-04-12"})
        original = await self.say()
        self.assertIn("is that right?", original)
        await self.patient("Could you repeat that?")
        rephrased = await self.say()
        self.assertNotEqual(original, rephrased)
        self.assertIn("Alex Morgan, born April 12, 1991", rephrased)
        await self.patient("yes")
        self.assertEqual(self.d.identity_confirmed, self.d.identity())
        self.assertEqual(self.d.next_step()["stage"], "offer")
