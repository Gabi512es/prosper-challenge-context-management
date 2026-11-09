import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

from agent_builder import AgentBuilder
from pipecat.frames.frames import LLMFullResponseEndFrame, LLMTextFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection
from scheduling import SchedulingEngine, load_catalog
from scheduling_agent import build_scheduling_agent
from scheduling_dialogue import BookingSpeech, PatientInput


class LookupRecoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_lists_are_lazy_and_unknown_specialty_filters_preserve_candidates(self):
        for field, values in self.catalog.filter_values().items():
            if field in self.resolve.properties:
                self.assertNotIn("enum", self.resolve.properties[field])
        for specialty in ("primary care", "family doctor"):
            result = await self.resolve.handler({"provider_query": "Dr. Maria Garcia", "provider_specialty": specialty}, None)
            self.assertEqual(result["status"], "clarify")
            self.assertEqual({item["id"] for item in result["candidates"]}, {"prov_002", "prov_003"})
            issue = result["filter_issues"][0]
            self.assertEqual(issue["code"], "unknown_filter_value")
            self.assertEqual(issue["valid_values"], self.catalog.filter_values()["provider_specialty"])
            self.assertIsNone(result["resolved"]["provider_id"])
            self.assertIn("not applied", self.d.pending[1])

    async def test_valid_specialty_that_eliminates_names_falls_back_explicitly(self):
        result = await self.resolve.handler({"provider_query": "Linda Ramirez", "provider_specialty": "Dermatology"}, None)
        self.assertEqual({item["id"] for item in result["candidates"]}, {"prov_005", "prov_014"})
        self.assertEqual(result["filter_issues"][0]["code"], "filter_no_match")
        self.assertIsNone(result["resolved"]["provider_id"])

    async def test_unknown_ids_are_rejected_with_catalog_values(self):
        result = await self.resolve.handler({"provider_id": "invented", "provider_query": "Maria Garcia"}, None)
        self.assertEqual(result["filter_issues"][0]["filter"], "provider_id")
        self.assertEqual(result["filter_issues"][0]["valid_values"], sorted(self.catalog.providers_by_id))
        self.assertEqual(len(result["candidates"]), 2)

    def setUp(self):
        self.catalog = load_catalog(Path(__file__).parents[1] / "data/catalog.json")
        self.engine = SchedulingEngine(self.catalog, [], now=datetime.fromisoformat("2026-11-09T00:00:00-08:00"))
        self.builder = build_scheduling_agent(self.engine, self.catalog, availability_mode="unit_fixture")
        self.d = self.builder.dialogue
        self.resolve = next(f for f in self.builder.build_initial_node()["functions"] if f.name == "resolve_options")

    async def test_stutter_initial_titles_and_specialty_resolve_real_provider(self):
        processor = PatientInput(self.d)
        processor.push_frame = AsyncMock()
        await processor.process_frame(TranscriptionFrame("Dr. Maria M- Garcia, the family medicine nurse practitioner", "", ""), FrameDirection.DOWNSTREAM)
        for name in ("Dr. Maria M- Garcia", "Maria M. Garcia", "Mar- Maria Garcia", "Doctor Maria Garcia NP", "Maria Anne Garcia"):
            result = await self.resolve.handler({"provider_query": name, "appointment_type_query": "annual physical", "is_new_patient": True}, None)
            self.assertEqual(result["resolved"]["provider_id"], "prov_003", name)
            self.assertEqual({x["id"] for x in result["eligible_locations"]}, {"loc_002", "loc_005", "loc_007"})
            self.assertEqual({x["location"] for x in result["clinic_contacts"]}, {"North Beach Specialty Center", "Midtown Medical Group", "Richmond Care Center"})

    async def test_near_name_suggests_never_auto_selects(self):
        result = await self.resolve.handler({"provider_query": "Maria Garica", "provider_specialty": "Family Medicine", "appointment_type_query": "annual physical"}, None)
        self.assertEqual(result["status"], "clarify")
        self.assertIsNone(result["resolved"]["provider_id"])
        self.assertTrue(result["candidates"][0]["requires_confirmation"])
        self.assertEqual(result["clinic_contacts"], [])
        self.assertIn("Did you mean Dr. Maria Garcia?", self.d.pending[1])
        accepted = await self.resolve.handler({"provider_id": "prov_003"}, None)
        self.assertEqual(accepted["resolved"]["provider_id"], "prov_003")

    async def test_no_name_match_has_no_unrelated_phone(self):
        result = await self.resolve.handler({"provider_query": "Zephyr Imaginary", "appointment_type_query": "annual physical"}, None)
        self.assertEqual(result["clinic_contacts"], [])
        self.assertNotIn("555", self.d.pending[1])

    async def test_place_field_does_not_reparse_nearest_geographically(self):
        await self.resolve.handler({"provider_query": "Maria Garcia", "provider_specialty": "Family Medicine", "appointment_type_query": "annual physical", "is_new_patient": True}, None)
        processor = PatientInput(self.d)
        processor.push_frame = AsyncMock()
        for text in ("the closest to where I live", "the nearest clinic geographically", "near me"):
            await processor.process_frame(TranscriptionFrame(text, "", ""), FrameDirection.DOWNSTREAM)
            await self.resolve.handler({"location_preference": "place"}, None)
            self.assertNotIn("Do you mean", self.d.location_intent_question)
            self.assertIn("North Beach", self.d.location_intent_question)
            self.assertNotIn("Mission District", self.d.location_intent_question)
        invalid = await self.resolve.handler({"location_preference": "nearest"}, None)
        self.assertEqual(invalid["code"], "invalid_location_preference")

    async def test_unclear_retry_lists_sites_and_no_question_repeats(self):
        await self.resolve.handler({"provider_query": "Maria Garcia", "provider_specialty": "Family Medicine", "appointment_type_query": "annual physical"}, None)
        await self.resolve.handler({"location_preference": "unclear"}, None)
        first = self.d.location_intent_question
        await self.resolve.handler({"location_preference": "unclear"}, None)
        self.assertNotEqual(first, self.d.location_intent_question)
        self.assertIn("Eligible sites", self.d.location_intent_question)
        speech = BookingSpeech(self.d)
        speech.push_frame = AsyncMock()
        for _ in range(4):
            await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        emitted = [c.args[0].text for c in speech.push_frame.call_args_list if isinstance(c.args[0], LLMTextFrame)]
        self.assertTrue(all(a != b for a, b in zip(emitted, emitted[1:])))
        self.assertTrue(all("Mission District" not in text for text in emitted))
