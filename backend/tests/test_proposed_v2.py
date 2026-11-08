import unittest
from datetime import datetime, timedelta
from pathlib import Path

from scheduling import load_catalog, SchedulingEngine
from scheduling.demo import generate_demo_availability
from scheduling.opening_hours import within_opening_hours
from evals.scorer import general_conversation_checks


class ProposedV2Test(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(Path(__file__).parents[1] / "data/catalog.json")
        self.now = datetime.fromisoformat("2026-11-08T12:00:00-08:00")

    def test_demo_covers_every_valid_combination_and_is_repeatable(self):
        slots = generate_demo_availability(self.catalog, self.now)
        self.assertEqual(slots, generate_demo_availability(self.catalog, self.now))
        expected = {(p.id, l, t) for p in self.catalog.providers for l in p.location_ids
                    for t in p.appointment_type_ids
                    if not self.catalog.appointment_types_by_id[t].required_capability
                    or self.catalog.appointment_types_by_id[t].required_capability in self.catalog.locations_by_id[l].capabilities}
        self.assertEqual(expected, {(s["provider_id"], s["location_id"], s["appointment_type_id"]) for s in slots})
        for slot in slots:
            start, end = datetime.fromisoformat(slot["start"]), datetime.fromisoformat(slot["end"])
            self.assertTrue(self.now < start < end <= self.now + timedelta(days=14))
            self.assertTrue(within_opening_hours(self.catalog.locations_by_id[slot["location_id"]].hours, start, end))

    def test_relaxation_previews_do_not_mutate_or_authorize_booking(self):
        slots = generate_demo_availability(self.catalog, self.now)
        engine = SchedulingEngine(self.catalog, slots, now=self.now)
        slot = slots[0]
        engine.resolve_options(dict(name="Test Patient", date_of_birth="1990-01-01", is_new_patient=False,
            referral_on_file=True, provider_id=slot["provider_id"], location_id=slot["location_id"],
            appointment_type_id=slot["appointment_type_id"], hard_constraints={"location": True}))
        alternatives = engine._slot_alternatives(1, 3)
        self.assertTrue(alternatives)
        self.assertTrue(all(a["requires_patient_consent"] for a in alternatives))
        self.assertEqual(engine.state.location_id, slot["location_id"])
        self.assertFalse(engine.state.offered_slot_ids)

    def test_scorer_rejects_missing_location_callback_and_dead_end(self):
        checks = general_conversation_checks([
            {"role": "assistant", "text": "An appointment is available at 1 PM. Would you like it?"},
            {"role": "assistant", "text": "Clinic staff will follow up with you shortly."},
            {"role": "assistant", "text": "There are no slots."}], self.catalog)
        self.assertFalse(any(checks.values()))
