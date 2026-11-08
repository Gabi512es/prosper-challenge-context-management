import unittest
from datetime import datetime
from pathlib import Path

from evals import load_dev_scenarios
from scheduling import BookingError, SchedulingEngine, SchedulingError, load_catalog
from scheduling.catalog import _specialty_matches, practitioner_nouns


BACKEND_DIR = Path(__file__).parents[1]
CATALOG_PATH = BACKEND_DIR / "data" / "catalog.json"
SCENARIOS_PATH = BACKEND_DIR / "evals" / "dev_scenarios.json"
NOW = datetime.fromisoformat("2026-11-07T00:00:00-08:00")


class SchedulingCoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(CATALOG_PATH)
        data = load_dev_scenarios(SCENARIOS_PATH, CATALOG_PATH)
        cls.scenarios = {item["id"]: item for item in data["scenarios"]}

    def engine_for(self, scenario_id: str) -> SchedulingEngine:
        return SchedulingEngine(
            self.catalog,
            self.scenarios[scenario_id]["availability_fixture"],
            now=NOW,
        )

    def test_dev_012_valid_referral_gated_booking(self):
        scenario = self.scenarios["DEV-012"]
        engine = self.engine_for("DEV-012")
        result = engine.resolve_options(self._updates_from(scenario))

        self.assertEqual(result["status"], "ready")
        slots = engine.find_slots(7)
        self.assertEqual([slot["slot_id"] for slot in slots["slots"]], ["dev012-s1"])

        engine.select_slot("dev012-s1")
        engine.confirm_selected_slot()
        booked = engine.book_appointment("dev012-s1")
        repeated = engine.book_appointment("dev012-s1")

        self.assertEqual(booked["status"], "booked")
        self.assertEqual(repeated["status"], "idempotent")
        self.assertEqual(len(engine.bookings), 1)
        self.assertEqual(
            {
                key: booked["booking"][key]
                for key in ("provider_id", "location_id", "appointment_type_id")
            },
            scenario["expected"]["booking"],
        )

    def test_dev_004_type_rule_blocks_new_patient(self):
        scenario = self.scenarios["DEV-004"]
        engine = self.engine_for("DEV-004")
        result = engine.resolve_options(self._updates_from(scenario))

        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "new_patient_type_restricted",
            {item["code"] for item in result["blocked_options"]},
        )
        self.assertNotIn(
            "new_patient_provider_restricted",
            {item["code"] for item in result["blocked_options"]},
        )
        self.assertEqual(engine.find_slots(7)["slots"], [])
        self.assertEqual(engine.bookings, [])

    def test_dev_008_correction_invalidates_old_slot(self):
        scenario = self.scenarios["DEV-008"]
        engine = self.engine_for("DEV-008")
        updates = self._updates_from(scenario)
        updates["location_id"] = scenario["patient_facts"]["initial_location_id"]
        updates.pop("initial_location_id", None)
        updates.pop("final_location_id", None)

        self.assertEqual(engine.resolve_options(updates)["status"], "ready")
        self.assertEqual(engine.find_slots(7)["slots"][0]["slot_id"], "dev008-s1")
        engine.select_slot("dev008-s1")
        self.assertEqual(engine.state.selected_slot_id, "dev008-s1")

        corrected = engine.resolve_options(
            {"location_id": scenario["patient_facts"]["final_location_id"]}
        )

        self.assertIsNone(engine.state.selected_slot_id)
        self.assertIsNone(engine.state.confirmation)
        self.assertIn(
            "location_missing_capability",
            {item["code"] for item in corrected["blocked_options"]},
        )
        capability_block = next(
            item
            for item in corrected["blocked_options"]
            if item["code"] == "location_missing_capability"
        )
        self.assertTrue(capability_block["alternatives"])
        for alternative in capability_block["alternatives"]:
            provider = self.catalog.providers_by_id[engine.state.provider_id]
            appointment_type = self.catalog.appointment_types_by_id[
                engine.state.appointment_type_id
            ]
            location = self.catalog.locations_by_id[alternative["id"]]
            self.assertIn(location.id, provider.location_ids)
            self.assertIn(appointment_type.required_capability, location.capabilities)
        with self.assertRaises(BookingError) as raised:
            engine.book_appointment("dev008-s1")
        self.assertEqual(raised.exception.code, "slot_not_selected")
        self.assertEqual(engine.bookings, [])

    def test_catalogs_eight_providerless_types_remain_unbookable(self):
        expected = {
            "appt_045",
            "appt_046",
            "appt_047",
            "appt_048",
            "appt_049",
            "appt_070",
            "appt_071",
            "appt_077",
        }
        observed = {
            item.id
            for item in self.catalog.appointment_types
            if not self.catalog.providers_for_type(item.id)
        }
        self.assertEqual(observed, expected)

        for appointment_type_id in expected:
            result = SchedulingEngine(self.catalog, [], now=NOW).resolve_options(
                {
                    "appointment_type_id": appointment_type_id,
                    "is_new_patient": False,
                }
            )
            self.assertIn(
                "unbookable_type_no_provider",
                {item["code"] for item in result["blocked_options"]},
            )

    def test_duplicate_provider_name_stays_ambiguous(self):
        engine = SchedulingEngine(self.catalog, [], now=NOW)
        result = engine.resolve_options({"provider_query": "Dr. Maria Garcia"})

        self.assertEqual(result["status"], "clarify")
        self.assertEqual(
            {item["id"] for item in result["candidates"]},
            {"prov_002", "prov_003"},
        )
        self.assertIsNone(engine.state.provider_id)

    def test_specialty_disambiguates_provider_and_type_word_order(self):
        engine = SchedulingEngine(self.catalog, [], now=NOW)
        result = engine.resolve_options(
            {
                "appointment_type_query": "knee MRI",
                "provider_query": "Linda Ramirez",
                "provider_specialty": "Radiology",
                "location_query": "Downtown",
                "name": "Alex Morgan",
                "date_of_birth": "1990-04-12",
                "is_new_patient": False,
                "referral_on_file": True,
            }
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(
            result["resolved"],
            {
                "appointment_type_id": "appt_065",
                "provider_id": "prov_014",
                "location_id": "loc_004",
            },
        )

    def test_practitioner_nouns_match_catalog_specialties(self):
        for practitioner, specialty in (
            ("pediatrician", "Pediatrics"),
            ("cardiologist", "Cardiology"),
            ("dermatologist", "Dermatology"),
            ("psychiatrist", "Psychiatry"),
        ):
            with self.subTest(practitioner=practitioner):
                provider = next(
                    item for item in self.catalog.providers if item.specialty == specialty
                )
                matches = self.catalog.search(
                    "provider",
                    provider.name,
                    specialty=practitioner,
                )
                self.assertIn(provider.id, {item["id"] for item in matches})

    def test_every_catalog_specialty_has_searchable_practitioner_nouns(self):
        specialties = {provider.specialty for provider in self.catalog.providers}
        specialties.update(item.specialty for item in self.catalog.appointment_types)

        for specialty in sorted(specialties):
            with self.subTest(specialty=specialty):
                nouns = practitioner_nouns(specialty)
                self.assertTrue(nouns, f"No practitioner noun mapping for {specialty!r}")
                self.assertTrue(
                    all(_specialty_matches(noun, specialty) for noun in nouns),
                    f"Unsearchable practitioner noun mapping for {specialty!r}: {nouns}",
                )

    def test_catalog_entities_are_resolved_before_identity_is_requested(self):
        engine = SchedulingEngine(self.catalog, [], now=NOW)

        result = engine.resolve_options({"provider_query": "No Such Provider"})

        self.assertEqual(result["status"], "no_match")
        self.assertEqual(
            result["next_action"],
            "explain_no_match_before_collecting_patient_details",
        )
        self.assertNotIn("name", result["missing_facts"])
        self.assertNotIn("date_of_birth", result["missing_facts"])
        self.assertEqual(
            set(result["deferred_patient_facts"]),
            {"name", "date_of_birth"},
        )

    def test_resolution_order_does_not_hide_an_incompatible_location(self):
        scenario = self.scenarios["DEV-003"]
        engine = self.engine_for("DEV-003")
        engine.resolve_options(
            {
                "provider_id": scenario["patient_facts"]["provider_id"],
                "location_id": scenario["patient_facts"]["location_id"],
                "is_new_patient": scenario["patient_facts"]["is_new_patient"],
                "referral_on_file": scenario["patient_facts"]["referral_on_file"],
            }
        )

        result = engine.resolve_options(
            {"appointment_type_id": scenario["patient_facts"]["appointment_type_id"]}
        )

        self.assertEqual(
            result["resolved"]["location_id"],
            scenario["patient_facts"]["location_id"],
        )
        self.assertIn(
            "location_missing_capability",
            {item["code"] for item in result["blocked_options"]},
        )

    def test_find_slots_requires_identity_to_be_persisted(self):
        scenario = self.scenarios["DEV-012"]
        engine = self.engine_for("DEV-012")
        updates = self._updates_from(scenario)
        updates.pop("name")
        updates.pop("date_of_birth")
        engine.resolve_options(updates)

        result = engine.find_slots(7)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["slots"], [])
        self.assertTrue(
            {"name", "date_of_birth"}
            <= {item.get("field") for item in result["issues"]}
        )

    def test_slot_must_come_from_latest_closed_world_search(self):
        scenario = self.scenarios["DEV-012"]
        engine = self.engine_for("DEV-012")
        engine.resolve_options(self._updates_from(scenario))

        with self.assertRaises(SchedulingError) as raised:
            engine.select_slot("dev012-s1")
        self.assertEqual(raised.exception.code, "slot_not_offered")

    def test_slot_outside_location_opening_hours_is_never_offerable_or_bookable(self):
        scenario = self.scenarios["DEV-012"]
        after_hours = dict(scenario["availability_fixture"][0])
        after_hours.update(
            {
                "slot_id": "after-hours",
                "start": "2026-11-10T18:00:00-08:00",
                "end": "2026-11-10T18:30:00-08:00",
            }
        )
        engine = SchedulingEngine(self.catalog, [after_hours], now=NOW)
        engine.resolve_options(self._updates_from(scenario))

        result = engine.find_slots(7)

        self.assertEqual(result["status"], "no_availability")
        self.assertEqual(result["slots"], [])
        self.assertEqual(result["excluded"]["outside_opening_hours"], 1)
        with self.assertRaises(SchedulingError) as selected:
            engine.select_slot("after-hours")
        self.assertEqual(selected.exception.code, "outside_opening_hours")
        with self.assertRaises(BookingError) as booked:
            engine.book_appointment("after-hours")
        self.assertEqual(booked.exception.code, "outside_opening_hours")

    def test_slot_may_end_at_closing_but_not_five_minutes_later(self):
        scenario = self.scenarios["DEV-012"]
        fixture = scenario["availability_fixture"][0]
        at_close = {
            **fixture,
            "slot_id": "ends-at-close",
            "start": "2026-11-10T16:15:00-08:00",
            "end": "2026-11-10T17:00:00-08:00",
        }
        after_close = {
            **fixture,
            "slot_id": "ends-after-close",
            "start": "2026-11-10T16:20:00-08:00",
            "end": "2026-11-10T17:05:00-08:00",
        }
        engine = SchedulingEngine(self.catalog, [at_close, after_close], now=NOW)
        engine.resolve_options(self._updates_from(scenario))

        result = engine.find_slots(7)

        self.assertEqual(
            [slot["slot_id"] for slot in result["slots"]],
            ["ends-at-close"],
        )
        self.assertEqual(result["excluded"]["outside_opening_hours"], 1)

    def test_taken_slot_disappears_from_later_searches_and_stays_unbookable(self):
        scenario = self.scenarios["DEV-012"]
        engine = self.engine_for("DEV-012")
        engine.resolve_options(self._updates_from(scenario))
        self.assertEqual(engine.find_slots(7)["slots"][0]["slot_id"], "dev012-s1")

        engine.mark_slot_unavailable("dev012-s1")
        refreshed = engine.find_slots(7)

        self.assertEqual(refreshed["slots"], [])
        self.assertEqual(refreshed["excluded"]["unavailable"], 1)
        with self.assertRaises(BookingError) as booked:
            engine.book_appointment("dev012-s1")
        self.assertEqual(booked.exception.code, "slot_taken")

    def test_global_slot_search_uses_complete_fixture_and_ranks_before_truncating(self):
        scenario = self.scenarios["DEV-009"]
        engine = self.engine_for("DEV-009")
        engine.resolve_options(
            {
                "name": scenario["patient_facts"]["name"],
                "date_of_birth": scenario["patient_facts"]["date_of_birth"],
                "is_new_patient": True,
                "referral_on_file": False,
                "appointment_type_id": "appt_011",
                "any_provider": True,
                "any_location": True,
                "preferences": {"soonest": True},
            }
        )

        slots = engine.find_slots(7, limit=1)
        self.assertEqual(slots["slots"][0]["slot_id"], "dev009-early")
        self.assertEqual(slots["more_available"], 2)

        engine.select_slot("dev009-early")
        self.assertEqual(engine.state.provider_id, "prov_016")
        self.assertEqual(engine.state.location_id, "loc_005")

    def test_missing_provider_and_location_require_explicit_any_scope(self):
        scenario = self.scenarios["DEV-009"]
        engine = self.engine_for("DEV-009")
        engine.resolve_options(
            {
                "name": scenario["patient_facts"]["name"],
                "date_of_birth": scenario["patient_facts"]["date_of_birth"],
                "is_new_patient": True,
                "appointment_type_id": scenario["patient_facts"]["appointment_type_id"],
            }
        )

        blocked = engine.find_slots(7)

        self.assertEqual(blocked["status"], "blocked")
        self.assertTrue(
            {"provider_id", "location_id"}
            <= {item.get("field") for item in blocked["issues"]}
        )

    def test_get_details_is_authoritative_and_unknown_ids_fail(self):
        engine = SchedulingEngine(self.catalog, [], now=NOW)
        details = engine.get_details("location", "loc_001")
        self.assertEqual(details["details"]["phone"], "(415) 555-4657")

        with self.assertRaises(SchedulingError) as raised:
            engine.get_details("provider", "prov_missing")
        self.assertEqual(raised.exception.code, "unknown_entity")

    @staticmethod
    def _updates_from(scenario: dict) -> dict:
        allowed = {
            "name",
            "date_of_birth",
            "is_new_patient",
            "referral_on_file",
            "provider_id",
            "location_id",
            "appointment_type_id",
        }
        return {
            key: value
            for key, value in scenario["patient_facts"].items()
            if key in allowed
        }
