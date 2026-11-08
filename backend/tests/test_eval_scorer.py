import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from evals import load_dev_scenarios
from evals.scorer import SCORER_VERSION, evaluate_run
from scheduling import SchedulingEngine, load_catalog


BACKEND_DIR = Path(__file__).parents[1]
CATALOG_PATH = BACKEND_DIR / "data" / "catalog.json"
SCENARIOS_PATH = BACKEND_DIR / "evals" / "dev_scenarios.json"
NOW = datetime.fromisoformat("2026-11-07T00:00:00-08:00")


class EvalScorerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(CATALOG_PATH)
        data = load_dev_scenarios(SCENARIOS_PATH, CATALOG_PATH)
        cls.scenarios = {item["id"]: item for item in data["scenarios"]}

    def test_canonical_scorer_version_is_explicit(self):
        self.assertEqual(SCORER_VERSION, "dev-v4-voice-gaps")

    def test_dev_007_requires_catalog_distinction_explanation(self):
        good = self._score(
            "DEV-007",
            "The catalog does not document a clinical distinction between Skin Cancer "
            "Screening and Full Body Skin Exam, so staff must confirm the service.",
        )
        weak = self._score(
            "DEV-007",
            "Staff will confirm whether you need Skin Cancer Screening or Full Body Skin Exam.",
        )

        self.assertTrue(self._assertion(good, "undocumented_distinction_explained"))
        self.assertFalse(self._assertion(weak, "undocumented_distinction_explained"))

    def test_dev_008_requires_corrected_location_capability_explanation(self):
        scenario = self.scenarios["DEV-008"]
        engine = self._engine("DEV-008")
        engine.resolve_options(
            {
                "name": scenario["patient_facts"]["name"],
                "date_of_birth": scenario["patient_facts"]["date_of_birth"],
                "is_new_patient": scenario["patient_facts"]["is_new_patient"],
                "referral_on_file": scenario["patient_facts"]["referral_on_file"],
                "appointment_type_id": scenario["patient_facts"]["appointment_type_id"],
                "provider_id": scenario["patient_facts"]["provider_id"],
                "location_id": scenario["patient_facts"]["final_location_id"],
            }
        )
        good = self._evaluate(
            scenario,
            engine,
            "Mission Bay lacks the required imaging capability.",
        )
        weak = self._evaluate(scenario, engine, "That location cannot be used.")

        self.assertTrue(self._assertion(good, "corrected_location_explained"))
        self.assertFalse(self._assertion(weak, "corrected_location_explained"))

    def test_dev_010_requires_complete_location_details_explanation(self):
        good = self._score(
            "DEV-010",
            "Mission District Family Clinic is open Monday to Friday from 8 AM to 5 PM. "
            "Its phone number is (415) 555-4657.",
        )
        weak = self._score("DEV-010", "The phone number is (415) 555-4657.")

        self.assertTrue(self._assertion(good, "location_details_explained"))
        self.assertFalse(self._assertion(weak, "location_details_explained"))

    def test_dev_011_requires_unknown_requested_provider_explanation(self):
        good = self._score(
            "DEV-011",
            "I couldn't find Dr. Zephyr Imaginary in our catalog.",
        )
        weak = self._score("DEV-011", "I couldn't find that provider.")

        self.assertTrue(self._assertion(good, "unknown_provider_explained"))
        self.assertFalse(self._assertion(weak, "unknown_provider_explained"))

    def _score(self, scenario_id: str, assistant_text: str) -> dict:
        scenario = self.scenarios[scenario_id]
        engine = self._engine(scenario_id)
        if scenario_id == "DEV-010":
            engine.resolve_options(
                {"location_id": scenario["expected"]["required_facts"]["location_id"]}
            )
        elif scenario_id == "DEV-011":
            engine.resolve_options({"provider_query": "Zephyr Imaginary"})
        return self._evaluate(scenario, engine, assistant_text)

    def _engine(self, scenario_id: str) -> SchedulingEngine:
        scenario = self.scenarios[scenario_id]
        return SchedulingEngine(
            self.catalog,
            scenario["availability_fixture"],
            now=NOW,
        )

    @staticmethod
    def _evaluate(scenario: dict, engine: SchedulingEngine, text: str) -> dict:
        run = SimpleNamespace(
            error=None,
            engine=engine,
            transcript=[{"role": "assistant", "text": text, "tools": []}],
            call_id="offline-test",
            context_messages=[],
        )
        return evaluate_run(scenario, run)

    @staticmethod
    def _assertion(result: dict, name: str) -> bool:
        return next(item["passed"] for item in result["assertions"] if item["name"] == name)
