"""Offline preservation tests; expanded catalogs never supply extra availability."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from evals.catalog_expander import COLLECTIONS, SEED, canonical_bytes, expand_catalog, validate_expansion
from evals.catalog_scaling import (BACKEND, INDEX_FIELDS, INDEX_MARKER, cache_billing,
                                  experiment_agent, index_message, project, reserved_names)
from evals.loader import DEFAULT_CATALOG_PATH, DEFAULT_SCENARIOS_PATH, load_dev_scenarios
from scheduling import SchedulingEngine, load_catalog
from scheduling.engine import BookingError

NOW = datetime.fromisoformat("2026-11-07T00:00:00-08:00")


class CatalogExpanderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dev_scenarios()
        cls.raw = json.loads(DEFAULT_CATALOG_PATH.read_text())
        cls.catalog = load_catalog(DEFAULT_CATALOG_PATH)
        cls.reserved = reserved_names(cls.dataset)
        cls.expanded = expand_catalog(cls.raw, 50, reserved_names=cls.reserved)
        cls.directory = tempfile.TemporaryDirectory()
        path = Path(cls.directory.name) / "expanded.json"
        path.write_bytes(canonical_bytes(cls.expanded))
        cls.large_catalog = load_catalog(path)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_deterministic_seed_and_nested_factors_without_source_mutation(self):
        before = canonical_bytes(self.raw)
        small = expand_catalog(self.raw, 5, reserved_names=self.reserved)
        repeated = expand_catalog(self.raw, 5, reserved_names=self.reserved)
        self.assertEqual(canonical_bytes(small), canonical_bytes(repeated))
        self.assertNotEqual(small, expand_catalog(self.raw, 5, seed=SEED + 1, reserved_names=self.reserved))
        for key in COLLECTIONS:
            self.assertEqual(small[key], self.expanded[key][:len(small[key])])
        self.assertEqual(before, canonical_bytes(self.raw))
        self.assertEqual(expand_catalog(self.raw, 1), self.raw)

    def test_original_records_policies_counts_and_disconnected_relations(self):
        validate_expansion(self.raw, self.expanded, 50, reserved_names=self.reserved)
        self.assertEqual(self.raw["policies"], self.expanded["policies"])
        for key in COLLECTIONS:
            self.assertEqual(self.expanded[key][:len(self.raw[key])], self.raw[key])
            self.assertEqual(len(self.expanded[key]), 50 * len(self.raw[key]))
        for item in self.catalog.appointment_types:
            self.assertEqual(self.catalog.providers_for_type(item.id), self.large_catalog.providers_for_type(item.id))
        self.assertEqual(sum(not self.large_catalog.providers_for_type(t.id) for t in self.catalog.appointment_types), 8)

    def test_all_original_details_and_provider_search_results_are_preserved(self):
        for entity, key in (("location", "locations"), ("provider", "providers"), ("appointment_type", "appointment_types")):
            for row in self.raw[key]:
                self.assertEqual(self.catalog.details(entity, row["id"]), self.large_catalog.details(entity, row["id"]))
                self.assertEqual(self.catalog.search(entity, row["name"]), self.large_catalog.search(entity, row["name"]))
        for query, specialty in (("Dr. Maria M- Garcia", "Family Medicine"), ("Linda Ramirez", "Radiology")):
            self.assertEqual(self.catalog.search("provider", query, specialty=specialty),
                             self.large_catalog.search("provider", query, specialty=specialty))
        for name in self.reserved:
            self.assertEqual(self.catalog.search("provider", name), self.large_catalog.search("provider", name))

    def test_every_dev_fact_card_has_identical_core_resolution_slots_and_booking(self):
        for scenario in self.dataset["scenarios"]:
            facts = scenario["patient_facts"]
            updates = {k: facts[k] for k in ("name", "date_of_birth", "is_new_patient", "referral_on_file", "appointment_type_id") if k in facts}
            provider = facts.get("provider_id", facts.get("intended_provider_id"))
            location = facts.get("final_location_id", facts.get("location_id", facts.get("intended_location_id")))
            if provider:
                updates["provider_id"] = provider
            if location:
                updates["location_id"] = location
            if facts.get("preference") == "soonest":
                updates.update(any_provider=True, any_location=True)
            if facts.get("provider_name"):
                updates.update(provider_query=facts["provider_name"], any_provider=False)
            engines = [SchedulingEngine(c, scenario["availability_fixture"], now=NOW)
                       for c in (self.catalog, self.large_catalog)]
            results = [e.resolve_options(updates) for e in engines]
            self.assertEqual(results[0], results[1], scenario["id"])
            slots = [e.find_slots(7) for e in engines]
            self.assertEqual(slots[0], slots[1], scenario["id"])
            if scenario["expected_outcome"] == "book":
                self.assertTrue(slots[0]["slots"], scenario["id"])
                slot_id = slots[0]["slots"][0]["slot_id"]
                bookings = []
                for engine in engines:
                    engine.select_slot(slot_id)
                    engine.confirm_selected_slot()
                    bookings.append(engine.book_appointment(slot_id))
                self.assertEqual(bookings[0], bookings[1], scenario["id"])
                if "booking" in scenario["expected"]:
                    self.assertEqual({k: bookings[1]["booking"][k] for k in scenario["expected"]["booking"]},
                                     scenario["expected"]["booking"], scenario["id"])

    def test_bridge_to_original_service_is_rejected(self):
        document = expand_catalog(self.raw, 2)
        document["providers"][len(self.raw["providers"])]["appointment_type_ids"].append(self.raw["appointment_types"][0]["id"])
        with self.assertRaisesRegex(ValueError, "bridges"):
            validate_expansion(self.raw, document, 2)

    def test_primary_agent_copies_change_only_index_data_and_validate(self):
        from agent_store import AgentStore
        path = BACKEND / "agents/catalog_scheduler.json"
        original_bytes = path.read_bytes()
        original = json.loads(original_bytes)
        for factor in (1, 5, 10, 50):
            document = self.raw if factor == 1 else expand_catalog(self.raw, factor, reserved_names=self.reserved)
            derived = experiment_agent(original, document)
            AgentStore.validate(derived)
            message = index_message(derived)
            data = json.loads(message["content"].partition(INDEX_MARKER)[2])
            self.assertEqual(data, [{key: row[key] for key in INDEX_FIELDS} for row in document["appointment_types"]])
            self.assertTrue(all(tuple(row) == INDEX_FIELDS for row in data))
            self.assertEqual(message["content"].partition(INDEX_MARKER)[:2],
                             index_message(original)["content"].partition(INDEX_MARKER)[:2])
            message["content"] = index_message(original)["content"]
            self.assertEqual(derived, original)  # All roles, tasks, tools, edges, model, etc.
        self.assertEqual(original_bytes, path.read_bytes())

    def test_blocked_new_patient_service_gains_no_new_provider_or_service_answer(self):
        scenario = next(s for s in self.dataset["scenarios"] if s["id"] == "DEV-004")
        facts = scenario["patient_facts"]
        updates = {k: v for k, v in facts.items() if k != "synthetic"}
        responses = []
        for catalog in (self.catalog, self.large_catalog):
            engine = SchedulingEngine(catalog, scenario["availability_fixture"], now=NOW)
            resolution = engine.resolve_options(updates)
            self.assertEqual(resolution["status"], "blocked")
            slots = engine.find_slots(14)
            self.assertFalse(slots["slots"])
            self.assertFalse(slots["alternatives"])
            self.assertFalse(engine.bookings)
            responses.append((resolution, slots))
            self.assertEqual(catalog.providers_for_type(facts["appointment_type_id"]),
                             self.catalog.providers_for_type(facts["appointment_type_id"]))
        self.assertEqual(*responses)

    def test_location_correction_still_invalidates_old_offer_and_confirmation(self):
        scenario = next(s for s in self.dataset["scenarios"] if s["id"] == "DEV-008")
        facts = scenario["patient_facts"]
        updates = {k: facts[k] for k in ("name", "date_of_birth", "is_new_patient", "referral_on_file", "provider_id", "appointment_type_id")}
        responses = []
        for catalog in (self.catalog, self.large_catalog):
            engine = SchedulingEngine(catalog, scenario["availability_fixture"], now=NOW)
            engine.resolve_options({**updates, "location_id": facts["initial_location_id"]})
            offered = engine.find_slots(14)
            slot_id = offered["slots"][0]["slot_id"]
            engine.select_slot(slot_id)
            # Also stress invalidation with a snapshot: gold case corrects before consenting.
            engine.confirm_selected_slot()
            resolution = engine.resolve_options({"location_id": facts["final_location_id"],
                                                 "hard_constraints": {"location_id": True}})
            self.assertIsNone(engine.state.confirmation)
            self.assertIsNone(engine.state.selected_slot_id)
            self.assertNotIn(slot_id, engine.state.offered_slot_ids)
            slots = engine.find_slots(14)
            self.assertFalse(slots["slots"])
            with self.assertRaises(BookingError):
                engine.book_appointment(slot_id)
            self.assertFalse(engine.bookings)
            responses.append((resolution, slots))
        self.assertEqual(*responses)

    def test_cache_accounting_does_not_invent_write_tokens_or_missing_usage(self):
        measured = cache_billing(dict(cached_tokens=1000, uncached_prompt_tokens=2000))
        self.assertEqual(measured["actual_cached_tokens"], 1000)
        self.assertEqual(measured["actual_cached_input_cost_usd"], .00125)
        self.assertEqual(measured["actual_uncached_input_cost_usd"], .005)
        self.assertEqual(measured["cache_write_surcharge_usd"], 0)
        self.assertIsNone(measured["cache_write_tokens"])
        self.assertIsNone(measured["cache_write_input_cost_usd"])
        unknown = cache_billing(dict(cached_tokens=None, uncached_prompt_tokens=None))
        self.assertIsNone(unknown["actual_cached_tokens"])
        self.assertIsNone(unknown["actual_cached_input_cost_usd"])
        self.assertIsNone(unknown["actual_uncached_input_cost_usd"])

    def test_expansion_never_rewrites_pinned_source_files(self):
        before = (DEFAULT_CATALOG_PATH.read_bytes(), DEFAULT_SCENARIOS_PATH.read_bytes())
        expand_catalog(self.raw, 2, reserved_names=self.reserved)
        self.assertEqual(before, (DEFAULT_CATALOG_PATH.read_bytes(), DEFAULT_SCENARIOS_PATH.read_bytes()))
        load_dev_scenarios()  # Original pin still passes.

    def test_invalid_factors_fail(self):
        for value in (0, -1, 51, 1.5, True):
            with self.assertRaises(ValueError):
                expand_catalog(self.raw, value)

    def test_over_context_cost_is_hypothetical_only(self):
        profile = dict(repetitions=3, model_calls=30, prompt_tokens=100000, cached_tokens=90000,
                       completion_tokens=1000, cached_fraction=.9, max_prompt_tokens=10000, max_startup_cached_tokens=7000)
        result = project(profile, 200000, 1)
        self.assertFalse(result["fits_observed_history_shape"])
        self.assertIsNone(result["projected_usd_with_observed_cache_share"])
        self.assertGreater(result["hypothetical_unlimited_context_usd_observed_cache"], 0)
