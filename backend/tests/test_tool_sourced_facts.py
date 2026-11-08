"""Tool results carry the facts the agent is allowed to state."""

import json
import unittest
from datetime import datetime
from pathlib import Path

from scheduling import SchedulingEngine, load_catalog
from scheduling_agent import DEFAULT_SCHEDULING_AGENT_PATH


BACKEND_DIR = Path(__file__).parents[1]
NOW = datetime.fromisoformat("2026-11-07T00:00:00-08:00")


class ToolSourcedFactsTest(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(BACKEND_DIR / "data" / "catalog.json")
        self.engine = SchedulingEngine(self.catalog, [], now=NOW)

    def test_provider_candidates_name_every_site_they_practice_at(self):
        result = self.engine.resolve_options({"provider_query": "Maria Garcia"})
        self.assertEqual(result["status"], "clarify")
        for candidate in result["candidates"]:
            provider = self.catalog.providers_by_id[candidate["id"]]
            self.assertNotIn("location_ids", candidate)
            self.assertEqual(
                candidate["locations"],
                [
                    {"id": location_id, "name": self.catalog.locations_by_id[location_id].name}
                    for location_id in provider.location_ids
                ],
            )
        names = {
            candidate["id"]: {location["name"] for location in candidate["locations"]}
            for candidate in result["candidates"]
        }
        # The DEV-002 failure denied this exact pairing to the patient.
        self.assertIn("Midtown Medical Group", names["prov_003"])

    def test_capability_alternatives_do_not_wait_for_unknown_patient_facts(self):
        # Same request shape as the failed DEV-003 run: referral status not yet
        # persisted. Capability-valid sites are returned, the gap is flagged.
        result = self.engine.resolve_options(
            {
                "provider_id": "prov_014",
                "location_id": "loc_000",
                "appointment_type_id": "appt_065",
            }
        )
        block = next(
            item
            for item in result["blocked_options"]
            if item["code"] == "location_missing_capability"
        )
        self.assertIn("loc_004", {item["id"] for item in block["alternatives"]})
        for alternative in block["alternatives"]:
            location = self.catalog.locations_by_id[alternative["id"]]
            self.assertIn("imaging", location.capabilities)
        self.assertIn("referral_on_file", block["alternatives_pending_patient_facts"])
        self.assertIn("referral_on_file", result["missing_facts"])

    def test_known_referral_block_still_hides_alternatives(self):
        result = self.engine.resolve_options(
            {
                "provider_id": "prov_014",
                "location_id": "loc_000",
                "appointment_type_id": "appt_065",
                "is_new_patient": False,
                "referral_on_file": False,
            }
        )
        block = next(
            item
            for item in result["blocked_options"]
            if item["code"] == "location_missing_capability"
        )
        self.assertNotIn("alternatives", block)

    def test_known_facts_give_alternatives_without_pending_flag(self):
        result = self.engine.resolve_options(
            {
                "provider_id": "prov_014",
                "location_id": "loc_000",
                "appointment_type_id": "appt_065",
                "is_new_patient": False,
                "referral_on_file": True,
            }
        )
        block = next(
            item
            for item in result["blocked_options"]
            if item["code"] == "location_missing_capability"
        )
        self.assertTrue(block["alternatives"])
        self.assertNotIn("alternatives_pending_patient_facts", block)

    def test_saved_agent_requires_tool_sourced_catalog_facts(self):
        persona = json.loads(DEFAULT_SCHEDULING_AGENT_PATH.read_text())["persona"]
        self.assertIn("only when it appears in a tool result", persona)
        self.assertIn("never infer a name from an ID", persona)


if __name__ == "__main__":
    unittest.main()
