"""No-model tests for common patient recovery and completion, not agent repairs."""
import unittest
from datetime import datetime
from types import SimpleNamespace

from evals.loader import load_dev_scenarios, DEFAULT_CATALOG_PATH
from evals.text_integration import _PatientDriver, _conversation_complete
from evals.spend_guard import SpendGuard
from scheduling import SchedulingEngine, load_catalog


class EvalRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.cases = {s["id"]: s for s in load_dev_scenarios()["scenarios"]}
        self.catalog = load_catalog(DEFAULT_CATALOG_PATH)
        self.engine = SchedulingEngine(self.catalog, [], now=datetime.fromisoformat("2026-11-07T00:00:00-08:00"))

    @staticmethod
    def turn(text):
        return SimpleNamespace(assistant_text=text, ended=False)

    def test_status_repeats_once_then_stops_without_writing_agent_state(self):
        driver = _PatientDriver(self.cases["DEV-002"])
        result = self.turn("Please confirm is new patient.")
        self.assertEqual(driver.reply(result, self.engine), "I am a new patient.")
        self.assertEqual(driver.reply(result, self.engine), "I am a new patient.")
        self.assertIsNone(driver.reply(result, self.engine))
        self.assertIsNone(self.engine.state.patient_facts.is_new_patient)
        self.assertEqual([e["type"] for e in driver.events], ["fact_question", "unnecessary_question"])

    def test_service_can_be_restated_once_with_no_engine_update(self):
        driver = _PatientDriver(self.cases["DEV-006"])
        result = self.turn("What appointment service do you need?")
        self.assertEqual(driver.reply(result, self.engine), "I'm asking for Dermatology Consultation.")
        self.assertIsNone(driver.reply(result, self.engine))
        self.assertIsNone(self.engine.state.appointment_type_id)

    def test_blocked_state_does_not_end_before_spoken_explanation(self):
        case = self.cases["DEV-005"]
        facts = case["patient_facts"]
        self.engine.resolve_options({k: facts[k] for k in ("provider_id", "location_id", "is_new_patient", "referral_on_file")})
        driver = _PatientDriver(case)
        self.assertFalse(_conversation_complete(case, self.turn("What appointment service do you need?"), self.engine, driver))
        driver.reply(self.turn("What appointment service do you need?"), self.engine)
        self.assertTrue(_conversation_complete(case, self.turn("This provider does not accept new patients."), self.engine, driver))

    def test_spelling_request_precedes_unknown_name_completion(self):
        case = self.cases["DEV-011"]
        driver = _PatientDriver(case)
        result = self.turn("I couldn't find a provider with that name. Could you spell the first name and surname?")
        self.assertFalse(_conversation_complete(case, result, self.engine, driver))
        self.assertEqual(driver.reply(result, self.engine), "It is spelled Zephyr Imaginary. I only want that doctor.")
        self.assertTrue(_conversation_complete(case, result, self.engine, driver))

    def test_identity_confirmation_remains_supported(self):
        driver = _PatientDriver(self.cases["DEV-002"], identity_given=True)
        self.assertEqual(driver.reply(self.turn("Alex Morgan, born April 12, 1990, is that right?"), self.engine),
                         "Yes, my name and date of birth are correct.")

    def test_identity_fact_repeat_is_bounded_and_never_fills_engine(self):
        driver = _PatientDriver(self.cases["DEV-002"], identity_given=True)
        result = self.turn("What is your full name and date of birth?")
        self.assertEqual(driver.reply(result, self.engine), "My name is Alex Morgan and my date of birth is 1990-04-12.")
        self.assertIsNone(driver.reply(result, self.engine))
        self.assertIsNone(self.engine.state.patient_facts.name)

    def test_ambiguous_service_request_is_not_reworded_to_bypass_handoff_guard(self):
        driver = _PatientDriver(self.cases["DEV-007"])
        self.assertEqual(driver.reply(self.turn("Which service?"), self.engine),
                         "I cannot choose between Skin Cancer Screening and Full Body Skin Exam. Please have a staff member confirm the intended service.")

    def test_budget_stop_is_explicit_and_no_request_is_admitted(self):
        guard = SpendGuard("0.001")
        with self.assertRaisesRegex(RuntimeError, "request not sent"):
            guard.reserve()
        self.assertTrue(guard.stopped)
        self.assertEqual(guard.requests, 0)

    def test_unknown_charge_is_bounded_for_admission_but_never_reported_as_actual(self):
        from decimal import Decimal
        guard = SpendGuard("2.00", bound_unknown=True)
        reservation = guard.reserve()
        guard.account_unknown(reservation)
        self.assertEqual(guard.accounted, Decimal("0.32512"))
        self.assertTrue(guard.unknown_usage)
        self.assertIsNone(guard.summary()["unreported_cost_usd"])
        self.assertEqual(guard.observed, [])
        guard.reserve()  # More authorized work fits even at the absolute bound.
