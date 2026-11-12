"""Public DEV-derived/synthetic checks only; no external scenario access."""
from copy import deepcopy
import random
import unittest
from evals.loader import DEFAULT_CATALOG_PATH, load_dev_scenarios
from evals.external_contract import compile_scenario, PatientDriver
from evals.external_score import grade
from evals.preflight_reviewed import exercise_write_fault
from evals.write_faults import normalize_faults
from scheduling import load_catalog


class BoundaryTest(unittest.TestCase):
    def test_aliases_and_conflicts(self):
        a = normalize_faults([{'tool':'book_appointment','mode':'slot taken','slot_id':'synthetic','times':1}])[0]
        self.assertEqual(a, {'tool':'book_appointment','mode':'slot_taken','slot_id':'synthetic','attempts':1,'stage':'write'})
        with self.assertRaises(ValueError): normalize_faults([dict(a, times=2)])
        with self.assertRaises(ValueError): normalize_faults([dict(a, stage='offer')])

    def test_semantic_extensions_require_review_not_pass(self):
        catalog=load_catalog(DEFAULT_CATALOG_PATH)
        case=deepcopy(next(s for s in load_dev_scenarios()['scenarios'] if s['expected_outcome']=='no_booking'))
        case['expected']['additional_semantic_requirement']=True
        case['patient_facts']['additional_private_fact']='private'
        case['patient_facts']['location_preference']={'unsupported_semantics':'retain for review'}
        compiled=compile_scenario(case,catalog)
        self.assertIn('expected.additional_semantic_requirement',compiled['review_required'])
        self.assertIn('patient_facts.additional_private_fact',compiled['review_required'])
        self.assertIn('patient_facts.location_preference',compiled['review_required'])
        self.assertFalse(grade(compiled,{'bookings':[]},catalog)['passed'])

    def test_requested_location_alias_retains_source_and_behavior(self):
        catalog=load_catalog(DEFAULT_CATALOG_PATH)
        original=deepcopy(next(s for s in load_dev_scenarios()['scenarios'] if 'initial_location_id' in s['patient_facts']))
        aliased=deepcopy(original)
        aliased['patient_facts']['requested_location_id']=aliased['patient_facts'].pop('initial_location_id')
        compiled=compile_scenario(aliased,catalog)
        a=PatientDriver.from_compiled(compile_scenario(original,catalog))
        b=PatientDriver.from_compiled(compiled)
        self.assertEqual(a.reply('Which location would you like?',catalog),b.reply('Which location would you like?',catalog))
        self.assertEqual(compiled['scenario'],aliased)

    def test_unsupported_correction_is_unknown_not_false_location_failure(self):
        catalog=load_catalog(DEFAULT_CATALOG_PATH)
        case=deepcopy(next(s for s in load_dev_scenarios()['scenarios'] if s['expected_outcome']=='no_booking'))
        case['expected']['old_slot_invalidated_after_correction']=True
        result=grade(compile_scenario(case,catalog),{'bookings':[],'state':{'selected_slot_id':None}},catalog)
        check=next(a for a in result['assertions'] if a['name']=='correction_observed:selected_slot_id')
        self.assertIsNone(check['passed'])
        self.assertIn('missing_evidence:old_slot_invalidated',result['required_review'])
        self.assertFalse(result['passed'])

    def test_unexercised_fault_never_passes(self):
        catalog=load_catalog(DEFAULT_CATALOG_PATH)
        case=deepcopy(next(s for s in load_dev_scenarios()['scenarios'] if s['expected_outcome']=='book'))
        case['faults']=[{'tool':'book_appointment','mode':'error'}]
        result=grade(compile_scenario(case,catalog), {'bookings':[], 'fault_evidence':[]}, catalog)
        self.assertFalse(next(a['passed'] for a in result['assertions'] if a['name']=='fault:0:triggered'))
        self.assertFalse(result['passed'])

    def test_scripts_and_manual_requirements_ignore_labels_and_order(self):
        catalog=load_catalog(DEFAULT_CATALOG_PATH)
        cases=deepcopy(load_dev_scenarios()['scenarios'])
        for c in cases: c['patient_script']=[{'when':'human_help_offer','response':'I will contact staff myself.'}]
        def signature(c):
            compiled=compile_scenario(c,catalog); d=PatientDriver.from_compiled(compiled)
            g=grade(compiled,{'bookings':[]},catalog); g.pop('scenario_id')
            return d.reply('Would you like human assistance?',catalog),g
        expected={c['opening']:signature(c) for c in cases}
        random.Random(4).shuffle(cases)
        for i,c in enumerate(cases):
            c['id']='arbitrary-'+str(i)
            self.assertEqual(signature(c),expected[c['opening']])


class WriteFaultTest(unittest.IsolatedAsyncioTestCase):
    async def prove(self, mode):
        catalog=load_catalog(DEFAULT_CATALOG_PATH)
        case=deepcopy(next(s for s in load_dev_scenarios()['scenarios'] if s['expected_outcome']=='book'))
        fault={'tool':'book_appointment','mode':mode}
        if mode=='slot_taken':
            from scheduling import SchedulingEngine
            from datetime import datetime
            e=SchedulingEngine(catalog,case['availability_fixture'],now=datetime.fromisoformat('2026-11-07T00:00:00-08:00'))
            facts=case['patient_facts']
            e.resolve_options({k:v for k,v in facts.items() if k in {'name','date_of_birth','is_new_patient','referral_on_file','appointment_type_id','provider_id','location_id'}})
            fault.update(slot_id=e.find_slots(30)['slots'][0]['slot_id'],times=1)
        case['faults']=[fault]
        proof=await exercise_write_fault(catalog,case)
        self.assertTrue(proof['protocol_ready'])
        self.assertFalse(proof['phase_one_triggered']); self.assertFalse(proof['before_consent_triggered'])
        self.assertTrue(proof['consent_recorded']); self.assertTrue(proof['write_returned_structured_error'])
        self.assertFalse(proof['booking_created'])
        self.assertTrue(proof['fault_evidence'][0]['triggered']); self.assertTrue(proof['fault_evidence'][0]['write_after_consent'])
        return proof

    async def test_error_every_actual_write_not_preparation(self):
        proof=await self.prove('error')
        self.assertEqual(proof['fault_evidence'][0]['trigger_count'],2)

    async def test_slot_loss_at_write_then_unavailable(self):
        proof=await self.prove('slot_taken')
        self.assertTrue(proof['slot_loss_persists'])
