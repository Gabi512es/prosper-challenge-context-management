"""Regression: the 2026-11-12 voice call where an interruption during the slot
choice made the agent repeat "Your details are confirmed. I'll check the
available appointments." five times without any tool call (call 35e9b8b2,
logs/voice-tools.jsonl). The pending choice must survive an interruption,
questions during a choice get an answer plus the repeated contextual choice,
"I'll check" is never claimed without a tool call in the same turn, and the
loop breaker also catches repeated statements.

Also covers the same-day follow-up: a repeat request gets the choice once and
nothing else, a model self-offer is never doubled with the code-appended
choice, and - the same class of bug as matching "ENT" inside "patient" -
repeat-request keywords such as "sorry" and "pardon" must only fire when the
WHOLE utterance is a repeat request, never when they merely appear in one."""

import re
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

from pipecat.frames.frames import (InterruptionFrame, LLMFullResponseEndFrame,
    LLMFullResponseStartFrame, LLMTextFrame, TranscriptionFrame)
from pipecat.processors.frame_processor import FrameDirection
from scheduling import SchedulingEngine, load_catalog
from scheduling.demo import generate_demo_availability
from scheduling_agent import build_scheduling_agent
from scheduling_dialogue import BookingSpeech, PatientInput

CHECK_CLAIM = re.compile(r"i'll check|i will check|let me check|checking", re.I)
OLD_CANNED = "Your details are confirmed"


class ChoiceInterruptionRecoveryTest(unittest.IsolatedAsyncioTestCase):
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

    async def agent_turn(self, model_text=""):
        """One tool-free model completion, as in turns 19-23 of the stuck call."""
        before = self.output.push_frame.call_count
        await self.output.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
        if model_text:
            await self.output.process_frame(LLMTextFrame(model_text), FrameDirection.DOWNSTREAM)
        await self.output.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        return "".join(call.args[0].text for call in self.output.push_frame.call_args_list[before:]
                       if isinstance(call.args[0], LLMTextFrame))

    async def reach_choice(self):
        """Annual physical, Maria Garcia NP, Midtown, identity confirmed."""
        await self.tools["resolve_options"].handler(
            {"appointment_type_id": "appt_002", "provider_id": "prov_003",
             "location_id": "loc_005", "is_new_patient": True,
             "patient_name": "Alex Morgan", "date_of_birth": "1990-04-12"}, None)
        self.assertIn("is that right?", await self.agent_turn())
        await self.patient("Yes, my name and date of birth are correct.")
        result = await self.tools["find_slots"].handler({"horizon_days": 30}, None)
        self.assertGreaterEqual(len(result["slots"]), 2)
        offer = await self.agent_turn()
        return result["slots"], offer

    async def test_slot_offer_carries_service_provider_and_site_context(self):
        _slots, offer = await self.reach_choice()
        self.assertTrue(offer.lower().startswith("for your annual physical"), offer)
        self.assertIn("Dr. Maria Garcia", offer)
        self.assertIn("Midtown Medical Group", offer)
        self.assertIn(" or ", offer)
        self.assertIn("Which works for you?", offer)
        self.assertNotIn("Which slot would you like?", offer)

    async def test_interruption_keeps_pending_choice_and_never_claims_checking(self):
        slots, offer = await self.reach_choice()
        offered_before = set(self.engine.state.offered_slot_ids)

        # Barge-in during "Which works for you?", cut-off transcript.
        await self.output.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
        await self.patient("Sorry. W-")
        self.assertEqual(self.d.next_step()["stage"], "slot_choice")
        reply = await self.agent_turn("Sorry, could you repeat that?")
        self.assertIn("Which works for you?", reply)
        self.assertIn("Dr. Maria Garcia", reply)

        # Questions during the choice: answered, then the choice repeated.
        await self.patient("What are you referring to?")
        reply = await self.agent_turn("These are available appointment times for your annual physical.")
        self.assertTrue(reply.startswith("These are available appointment times"), reply)
        self.assertIn("Which works for you?", reply)

        await self.patient("Are these appointments?")
        reply = await self.agent_turn("Yes, these are bookable appointment times.")
        self.assertIn("Which works for you?", reply)

        # Throughout: no rollback to identity, no fabricated progress claim,
        # and the offered slots stay live.
        transcript = " ".join(call.args[0].text for call in self.output.push_frame.call_args_list
                              if isinstance(call.args[0], LLMTextFrame))
        self.assertNotIn(OLD_CANNED, transcript)
        self.assertIsNone(CHECK_CLAIM.search(transcript), transcript)
        self.assertEqual(set(self.engine.state.offered_slot_ids), offered_before)
        self.assertEqual(self.d.identity_confirmed, ("Alex Morgan", "1990-04-12"))

        # The kept choice remains directly bookable.
        prepared = await self.tools["book_appointment"].handler({"slot_id": slots[0]["slot_id"]}, None)
        self.assertEqual(prepared["status"], "needs_confirmation")
        readback = await self.agent_turn()
        self.assertIn("Shall I book it?", readback)
        await self.patient("Yes. I confirm that exact provider, location, service, date, and time. Please book it.")
        booked = await self.tools["book_appointment"].handler({"slot_id": slots[0]["slot_id"]}, None)
        self.assertEqual(booked["status"], "booked")
        self.assertEqual(self.engine.bookings[0]["slot_id"], slots[0]["slot_id"])

    def slot_phrase(self, slot):
        """How the model phrased its own re-offer in the 2026-11-12 retest."""
        from datetime import datetime as dt
        start = dt.fromisoformat(slot["start"])
        return (f"I have {start.strftime('%A')}, {start.strftime('%B')} {start.day}th at "
                f"{start.strftime('%I:%M %p').lstrip('0')} available at {slot['location']}. "
                "Would you like to book this?")

    async def test_repeat_request_gets_the_choice_once_and_nothing_else(self):
        slots, offer = await self.reach_choice()
        # The retest defect: the model re-offered ONE slot on its own, and the
        # code appended the two-slot choice after it - two contradicting offers.
        await self.patient("Sorry, what did you say?")
        reply = await self.agent_turn(self.slot_phrase(slots[0]))
        self.assertEqual(reply, self.d.slot_options)
        self.assertNotIn("Would you like to book this?", reply)

        # A second repeat request still gets the choice, never a bail-out.
        await self.patient("Can you repeat that?")
        reply = await self.agent_turn(self.slot_phrase(slots[0]))
        self.assertEqual(reply, self.d.slot_options)
        self.assertNotIn("call", reply.casefold())

    async def test_model_slot_mention_is_never_doubled(self):
        slots, _offer = await self.reach_choice()
        # Side question answered with a slot mention: nothing is appended, so
        # there is exactly one slot presentation in the turn.
        await self.patient("Are these appointments?")
        model_text = "Yes. " + self.slot_phrase(slots[0])
        reply = await self.agent_turn(model_text)
        self.assertEqual(reply, model_text)
        self.assertNotIn("Which works for you?", reply)

        # Side question answered without slots: the choice is appended once.
        await self.patient("Do I need to bring anything?")
        reply = await self.agent_turn("No special preparation is needed.")
        self.assertTrue(reply.startswith("No special preparation is needed."), reply)
        self.assertEqual(reply.count("Which works for you?"), 1)

    async def test_sorry_the_first_one_selects_a_slot_not_a_repeat(self):
        # "sorry" alone is a repeat trigger, but a whole utterance that picks
        # an option must never be swallowed by that keyword - the same class
        # of bug as matching "ENT" inside "patient".
        slots, offer = await self.reach_choice()
        await self.patient("Sorry, the first one")
        self.assertFalse(self.d.repeat_requested)
        prepared = await self.tools["book_appointment"].handler({"slot_id": slots[0]["slot_id"]}, None)
        self.assertEqual(prepared["status"], "needs_confirmation")
        readback = await self.agent_turn()
        self.assertIn("Shall I book it?", readback)
        self.assertNotEqual(readback, offer)
        self.assertNotIn("Which works for you?", readback)

    async def test_sorry_i_meant_the_second_one_selects_a_slot_not_a_repeat(self):
        slots, offer = await self.reach_choice()
        await self.patient("Sorry, I meant the second one")
        self.assertFalse(self.d.repeat_requested)
        prepared = await self.tools["book_appointment"].handler({"slot_id": slots[1]["slot_id"]}, None)
        self.assertEqual(prepared["status"], "needs_confirmation")
        readback = await self.agent_turn()
        self.assertIn("Shall I book it?", readback)
        self.assertNotEqual(readback, offer)

    async def test_sorry_richmond_instead_is_treated_as_a_change_not_a_repeat(self):
        slots, offer = await self.reach_choice()
        offered_before = set(self.engine.state.offered_slot_ids)
        self.assertTrue(offered_before)
        await self.patient("Sorry, can we do Richmond instead?")
        self.assertFalse(self.d.repeat_requested)
        # A real location change invalidates the stale Midtown choice, rather
        # than silently re-stating it as if nothing had happened.
        self.assertEqual(self.engine.state.location_id, "loc_007")
        self.assertEqual(self.engine.state.offered_slot_ids, set())
        self.assertNotEqual(self.d.next_step()["stage"], "slot_choice")

    async def test_bare_repeat_phrases_are_not_misled_by_surrounding_content(self):
        # A repeat request must be the WHOLE utterance: leading "sorry" plus
        # one recognized phrase and only trailing punctuation, nothing else.
        cases_true = [
            "Sorry, what did you say?",
            "Can you repeat that?",
            "Sorry?",
            "Pardon?",
            "Come again?",
        ]
        cases_false = [
            "Sorry, the first one",
            "Sorry, can we do Richmond instead?",
            "Sorry, I meant the second one",
            "I beg your pardon, I will take the first one",
            "No, sorry, book the second slot",
        ]
        for text in cases_true:
            self.d.patient(text)
            self.assertTrue(self.d.repeat_requested, text)
        for text in cases_false:
            self.d.patient(text)
            self.assertFalse(self.d.repeat_requested, text)

    async def test_loop_breaker_catches_repeated_statements_and_blank_turns(self):
        _slots, offer = await self.reach_choice()
        # Two blank completions in a row (as after the interrupted turn 21):
        # the exact same choice text must not simply repeat forever.
        first = await self.agent_turn()
        self.assertNotEqual(first, offer)
        self.assertIn("Which works for you?", first)  # escalation keeps context
        second = await self.agent_turn()
        self.assertNotEqual(second, first)
        transcript = " ".join(call.args[0].text for call in self.output.push_frame.call_args_list
                              if isinstance(call.args[0], LLMTextFrame))
        self.assertNotIn(OLD_CANNED, transcript)
        self.assertIsNone(CHECK_CLAIM.search(transcript), transcript)

    async def test_repeated_statement_is_caught_outside_questions(self):
        statement = "No transfer or callback is recorded."
        self.assertEqual(self.d.avoid_repeated_question(statement), statement)
        retry = self.d.avoid_repeated_question(statement)
        self.assertNotEqual(retry, statement)


if __name__ == "__main__":
    unittest.main()
