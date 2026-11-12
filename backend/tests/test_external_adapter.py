"""Public DEV/synthetic offline validation only. Never reads external scenario files."""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
import random
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from evals.external_contract import ContractError, PatientDriver, compile_scenario
from evals.external_score import grade, saved_observation
from evals.external_budget import FinalSpendGuard
from evals.loader import load_dev_scenarios, DEFAULT_CATALOG_PATH, DEFAULT_SCENARIOS_PATH
from scheduling import load_catalog


class ExternalAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(DEFAULT_CATALOG_PATH)
        cls.data = load_dev_scenarios()
        cls.cfg = json.loads(DEFAULT_SCENARIOS_PATH.with_name('external_config.json').read_text())

    def synthetic(self, outcome='book'):
        source = next(s for s in self.data['scenarios'] if s['expected_outcome']=='book')
        return {'id':'arbitrary label', 'opening':source['opening'], 'patient_facts':deepcopy(source['patient_facts']),
                'expected_outcome':outcome, 'expected':deepcopy(source['expected']) if outcome=='book' else {'bookings':0},
                'availability_fixture':deepcopy(source['availability_fixture'])}

    def observation(self, **updates):
        obs = {'transcript':[], 'bookings':[], 'state':{'appointment_type_id':None,'provider_id':None,
               'location_id':None,'selected_slot_id':None,'confirmation':None},'policy_codes':[],
               'tool_events':[], 'driver_events':[], 'runner_error':False}
        obs.update(updates)
        return obs

    def offer(self, slot):
        from datetime import datetime
        c=self.catalog; d=datetime.fromisoformat(slot['start'])
        return f"I'll book {c.appointment_types_by_id[slot['appointment_type_id']].name} with {c.providers_by_id[slot['provider_id']].name} at {c.locations_by_id[slot['location_id']].name}, {d.strftime('%A %B %d at %I:%M %p')}. Shall I book it?"

    def test_valid_booking(self):
        case=self.synthetic(); slot=case['availability_fixture'][0]
        obs=self.observation(bookings=[slot],state={'confirmation':True, **{k:slot[k] for k in ('provider_id','location_id','appointment_type_id')}},
                             transcript=[{'role':'assistant','text':self.offer(slot)}])
        result=grade(compile_scenario(case,self.catalog),obs,self.catalog)
        self.assertEqual(result['status'],'passed')

    def test_policy_block_uses_explicit_code_not_category(self):
        case=self.synthetic('no_booking'); case['expected']['assertions']=[{'kind':'policy_block','code':'referral_required'}]
        case['category']='not a policy'; case['id']='anything'
        compiled=compile_scenario(case,self.catalog)
        self.assertTrue(grade(compiled,self.observation(policy_codes=['referral_required']),self.catalog)['passed'])
        self.assertFalse(grade(compiled,self.observation(policy_codes=[]),self.catalog)['passed'])

    def test_factual_answer_dynamic_facts(self):
        location=self.catalog.locations[0]
        case=self.synthetic('answer_only'); case['expected']['required_facts']={'location_id':location.id,'phone':location.phone,'hours':location.hours}
        text=f'{location.name}: {location.phone}; {location.hours}.'
        self.assertTrue(grade(compile_scenario(case,self.catalog),self.observation(transcript=[{'role':'assistant','text':text}]),self.catalog)['passed'])
        bad=grade(compile_scenario(case,self.catalog),self.observation(transcript=[{'role':'assistant','text':'It is open.'}]),self.catalog)
        self.assertFalse(bad['passed'])

    def test_ambiguity_explicit_assertions(self):
        original=next(s for s in self.data['scenarios'] if s['expected'].get('ambiguity_preserved'))
        case=self.synthetic('clarify_or_handoff'); ids=original['patient_facts']['ambiguous_type_ids']
        case['expected'].update(ambiguity_preserved=True,assertions=[{'kind':'catalog_distinction','ids':ids},{'kind':'staff_request'}])
        names=' and '.join(self.catalog.appointment_types_by_id[i].name for i in ids)
        text=f'The catalog does not document a clinical distinction between {names}. Staff can confirm the intended service.'
        self.assertTrue(grade(compile_scenario(case,self.catalog),self.observation(transcript=[{'role':'assistant','text':text}]),self.catalog)['passed'])

    def test_correction_needs_actual_event_and_invalidated_state(self):
        original=next(s for s in self.data['scenarios'] if 'final_location_id' in s['patient_facts'])
        case=self.synthetic('no_booking'); case['patient_facts']=deepcopy(original['patient_facts'])
        case['expected'].update(old_slot_invalidated_after_correction=True,confirmation_invalidated_after_correction=True)
        obs=self.observation(state={'selected_slot_id':None,'confirmation':None,'location_id':case['patient_facts']['final_location_id']},driver_events=[{'type':'location_correction'}])
        compiled=compile_scenario(case,self.catalog)
        self.assertTrue(grade(compiled,obs,self.catalog)['passed'])
        obs['driver_events']=[]
        self.assertFalse(grade(compiled,obs,self.catalog)['passed'])

    def test_infrastructure_is_not_agent_failure_or_pass(self):
        result=grade(compile_scenario(self.synthetic(),self.catalog),self.observation(runner_error=True,infrastructure_failure=True),self.catalog)
        self.assertEqual(result['status'],'infrastructure_failure')
        self.assertEqual(result['agent_assessment'],'not_assessable')
        self.assertFalse(result['passed'])

    def test_internal_selection_is_not_false_statement_or_wrong_booking(self):
        case=self.synthetic(); wanted=case['expected']['booking']['provider_id']
        other=next(p.id for p in self.catalog.providers if p.id!=wanted)
        result=grade(compile_scenario(case,self.catalog),self.observation(state={'provider_id':other}),self.catalog)
        self.assertIn('incorrect_internal_selection',result['consequences_automatic'])
        self.assertNotIn('wrong_booking',result['consequences_automatic'])
        self.assertNotIn('false_statement_to_patient',result['consequences_automatic'])
        self.assertNotIn('false_refusal',result['consequences_automatic'])

    def test_wrong_booking_is_distinct_from_absent_booking(self):
        case=self.synthetic(); slot=deepcopy(case['availability_fixture'][0]); slot['provider_id']='wrong observed ID'
        compiled=compile_scenario(case,self.catalog)
        self.assertIn('wrong_booking',grade(compiled,self.observation(bookings=[slot]),self.catalog)['consequences_automatic'])
        self.assertNotIn('wrong_booking',grade(compiled,self.observation(),self.catalog)['consequences_automatic'])

    def test_required_review_never_passes(self):
        case=self.synthetic('no_booking'); case['expected']['explanation']='Private grading canary'
        result=grade(compile_scenario(case,self.catalog),self.observation(),self.catalog)
        self.assertEqual(result['status'],'review_required'); self.assertFalse(result['passed'])

    def test_missing_saved_evidence_is_unknown_not_filled_from_expectations(self):
        case=self.synthetic(); compiled=compile_scenario(case,self.catalog)
        run={'transcript':[],'context_messages':[],'outcome_signature':{'bookings':case['availability_fixture']},'error':None}
        observed=saved_observation(run)
        self.assertNotIn('confirmation',observed['state'])
        result=grade(compiled,observed,self.catalog)
        self.assertFalse(result['passed']); self.assertIn('missing_evidence:confirmation_recorded',result['required_review'])

    def test_missing_unknown_and_malformed_fail_visibly(self):
        variants=[]
        case=self.synthetic(); del case['expected']; variants.append(case)
        case=self.synthetic(); case['expected']['assertions']=[{'kind':'magic'}]; variants.append(case)
        case=self.synthetic(); case['patient_facts']['date_of_birth']='not a date'; variants.append(case)
        case=self.synthetic(); case['availability_fixture'][0]['start']='bad'; variants.append(case)
        case=self.synthetic(); case['expected']['assertions']=None; variants.append(case)
        case=self.synthetic(); case['patient_script']=[{'when':'secret event','response':'yes'}]; variants.append(case)
        for case in variants:
            with self.subTest(case=list(case)):
                with self.assertRaises(ContractError): compile_scenario(case,self.catalog)

    def test_private_expectations_never_reach_patient_replies(self):
        case=self.synthetic(); case['expected']['explanation']='GOLD_EXPECTATION_CANARY'
        driver=PatientDriver.from_compiled(compile_scenario(case,self.catalog))
        self.assertNotIn('expected',vars(driver)); self.assertNotIn('id',vars(driver))
        self.assertIsNone(driver.reply('How can I help?',self.catalog))
        answer=driver.reply('What is your name and date of birth?',self.catalog)
        self.assertIn(case['patient_facts']['name'],answer)
        self.assertNotIn('GOLD_EXPECTATION_CANARY',answer)

    def test_dataset_count_duplicate_labels_and_unknown_fields(self):
        from evals.external_eval import compile_dataset
        data=deepcopy(self.data); data['scenarios'][1]['id']=data['scenarios'][0]['id']
        with self.assertRaises(ContractError): compile_dataset(data,self.catalog)

    def test_dataset_prose_contract_is_not_silently_graded(self):
        from evals.external_eval import compile_dataset
        for compiled in compile_dataset(self.data,self.catalog):
            self.assertIn('dataset.contract.grading',compiled['review_required'])
            self.assertIn('dataset.contract.confirmation',compiled['review_required'])
        with self.assertRaises(ContractError): compile_dataset(self.data,self.catalog,99)
        data=deepcopy(self.data); data['unrecognized_execution_rule']='must not be ignored'
        with self.assertRaises(ContractError): compile_dataset(data,self.catalog)

    def test_argument_types_and_unused_arguments_fail(self):
        for rule in ({'kind':[]}, {'kind':'transcript_contains','text':9},
                     {'kind':'policy_block','code':'referral_required','text':'unused'},
                     {'kind':'catalog_distinction','ids':[{}]}):
            case=self.synthetic('no_booking'); case['expected']['assertions']=[rule]
            with self.assertRaises(ContractError): compile_scenario(case,self.catalog)

    def test_explicit_patient_script_is_bounded(self):
        case=self.synthetic(); case['patient_script']=[{'when':'assistant_contains','match':'request a human','response':'Please let me speak to a person.'}]
        driver=PatientDriver.from_compiled(compile_scenario(case,self.catalog))
        self.assertEqual(driver.reply('Do you request a human?',self.catalog),'Please let me speak to a person.')
        self.assertIsNone(driver.reply('Do you request a human?',self.catalog))

    def test_soonest_does_not_consent_to_later_slot(self):
        original=next(s for s in self.data['scenarios'] if s['patient_facts'].get('preference')=='soonest')
        compiled=compile_scenario(original,self.catalog); driver=PatientDriver.from_compiled(compiled)
        slots=sorted(original['availability_fixture'],key=lambda x:x['start'])
        self.assertEqual(driver.reply(self.offer(slots[-1]),self.catalog,[slots[-1]]),'Is there an earlier eligible appointment?')
        self.assertTrue(driver.reply(self.offer(slots[0]),self.catalog,[slots[0]]).startswith('Yes'))

    def test_soonest_recovery_uses_observed_remaining_availability(self):
        original=next(s for s in self.data['scenarios'] if s['patient_facts'].get('preference')=='soonest')
        driver=PatientDriver.from_compiled(compile_scenario(original,self.catalog))
        slots=sorted(original['availability_fixture'],key=lambda x:x['start'])
        self.assertTrue(driver.reply(self.offer(slots[0]),self.catalog,[slots[0]]).startswith('Yes'))
        driver.availability=[s for s in driver.availability if s['slot_id']!=slots[0]['slot_id']]
        self.assertTrue(driver.reply(self.offer(slots[1]),self.catalog,[slots[1]]).startswith('Yes'))

    def test_brief_selection_is_not_booking_consent(self):
        from datetime import datetime
        case=self.synthetic(); slot=case['availability_fixture'][0]
        d=datetime.fromisoformat(slot['start']); site=self.catalog.locations_by_id[slot['location_id']].name
        brief=f"{d.strftime('%A %B %d at %I:%M %p')} at {site}. Which slot would you like?"
        driver=PatientDriver.from_compiled(compile_scenario(case,self.catalog))
        reply=driver.reply(brief,self.catalog,[slot])
        self.assertIn('Please read back the full appointment before booking.',reply)
        self.assertFalse(reply.startswith('Yes'))

    def test_correction_waits_for_matching_offer_and_precedes_consent(self):
        source=next(s for s in self.data['scenarios'] if 'final_location_id' in s['patient_facts'])
        driver=PatientDriver.from_compiled(compile_scenario(source,self.catalog)); slot=source['availability_fixture'][0]
        driver.reply('Shall I book it?',self.catalog,[slot])
        self.assertFalse(driver.corrected)
        correction=driver.reply(self.offer(slot),self.catalog,[slot])
        self.assertTrue(correction.startswith('Actually,')); self.assertTrue(driver.corrected)

    def test_readback_consent_rejects_wrong_service_location_and_missing_fields(self):
        case=self.synthetic(); slot=case['availability_fixture'][0]
        for text in ('Shall I book it?',self.offer(slot).replace(self.catalog.locations_by_id[slot['location_id']].name,'another site')):
            driver=PatientDriver.from_compiled(compile_scenario(case,self.catalog))
            self.assertFalse((driver.reply(text,self.catalog,[slot]) or '').startswith('Yes'))
        driver=PatientDriver.from_compiled(compile_scenario(case,self.catalog))
        self.assertTrue(driver.reply(self.offer(slot),self.catalog,[slot]).startswith('Yes'))

    def test_recovery_repeats_are_bounded_and_unchanged_by_labels(self):
        case=self.synthetic(); case['opening']='I need an appointment.'
        driver=PatientDriver.from_compiled(compile_scenario(case,self.catalog))
        replies=[driver.reply('Please confirm new or existing patient.',self.catalog) for _ in range(3)]
        self.assertTrue(replies[0]); self.assertTrue(replies[1]); self.assertIsNone(replies[2])
        self.assertEqual(sum(e['type']=='unnecessary_question' for e in driver.events),1)

    def test_ids_and_shuffle_do_not_affect_driver_or_scoring(self):
        cases=deepcopy(self.data['scenarios'])
        def signature(case):
            compiled=compile_scenario(case,self.catalog); driver=PatientDriver.from_compiled(compiled)
            replies=[driver.reply(t,self.catalog) for t in ('Which provider did you mean?', 'Which location would you like?',
                'What appointment service do you need?', 'What is your full name and date of birth?',
                'Please confirm new or existing patient.', 'Do you have a referral on file?')]
            scored=grade(compiled,self.observation(),self.catalog); scored.pop('scenario_id')
            return replies,scored
        before={json.dumps(c['patient_facts'],sort_keys=True)+c['opening']:signature(c) for c in cases}
        random.Random(20261110).shuffle(cases)
        for i,case in enumerate(cases):
            case['id']='renamed-'+str(i)
            self.assertEqual(signature(case),before[json.dumps(case['patient_facts'],sort_keys=True)+case['opening']])

    def test_prose_and_forbidden_criteria_are_not_omitted(self):
        for source in self.data['scenarios']:
            compiled=compile_scenario(source,self.catalog)
            self.assertIn('reply_rules_execution',compiled['review_required'])
            for i in range(len(source['forbidden'])):
                self.assertIn(f'forbidden[{i}]',compiled['review_required'])

    def test_absolute_missing_usage_reserve_and_no_admission_over_cap(self):
        guard=FinalSpendGuard('0.65',self.cfg)
        self.assertEqual(guard.ceiling,Decimal('0.32512'))
        reserve=guard.reserve(); guard.account_unknown(reserve)
        self.assertEqual(guard.accounted,Decimal('0.32512'))
        with self.assertRaises(RuntimeError): guard.reserve()
        self.assertEqual(guard.requests,1)

    def test_known_usage_releases_reservation_unknown_usage_does_not(self):
        guard=FinalSpendGuard('1',self.cfg)
        reserve=guard.reserve()
        usage=SimpleNamespace(prompt_tokens=100,cached_tokens=None,completion_tokens=10,
                              prompt_tokens_details=SimpleNamespace(cached_tokens=0))
        guard.settle(reserve,usage)
        self.assertEqual(guard.accounted,Decimal('0.00035'))
        reserve=guard.reserve(); usage.prompt_tokens_details.cached_tokens=None
        guard.settle(reserve,usage)
        self.assertEqual(guard.accounted,Decimal('0.32547'))

    def test_provider_limit_violation_stops_and_discloses_bound_assumption(self):
        guard=FinalSpendGuard('1',self.cfg); reserve=guard.reserve()
        usage=SimpleNamespace(prompt_tokens=128001,completion_tokens=1,prompt_tokens_details=SimpleNamespace(cached_tokens=0))
        guard.settle(reserve,usage)
        self.assertTrue(guard.stopped); self.assertFalse(guard.summary()['exposure_bound_valid'])
        self.assertEqual(guard.accounted,Decimal('0.32512'))

    def test_public_sources_and_frozen_evaluator_are_unchanged(self):
        from evals.version import evaluator_sha256
        self.assertEqual(evaluator_sha256(),'97117348b6d00263d60c0561381841e3fc50e843873a53b60e827a8c7415a996')
        self.assertEqual(sha256(DEFAULT_SCENARIOS_PATH.read_bytes()).hexdigest(),'825a832f5131455fb1e8b96a3385b81c8900850b1be72dc580a2fb211db4f130')


class ExecutionPrivacyTest(unittest.IsolatedAsyncioTestCase):
    async def test_executor_only_sends_opening_then_requested_facts(self):
        from evals.external_eval import run_one
        catalog=load_catalog(DEFAULT_CATALOG_PATH)
        source=deepcopy(next(s for s in load_dev_scenarios()['scenarios'] if s['expected_outcome']=='book'))
        source['patient_facts']['name']='PRIVATE_PATIENT_CANARY'
        source['expected']['explanation']='GOLD_EXPECTATION_CANARY'
        sent=[]; captured=[]
        class FakeSession:
            call_id='offline-only'
            context_messages=[]
            def __init__(self,**kwargs):
                captured.append(kwargs['builder'])
                self.run_id=kwargs['run_id']
                self._runtime=SimpleNamespace(llm=SimpleNamespace(_retry_on_timeout=True,_client=SimpleNamespace(max_retries=2)))
            async def start(self):
                return SimpleNamespace(assistant_text='How can I help?')
            async def send(self,text):
                sent.append(text)
                return SimpleNamespace(assistant_text='What is your full name and date of birth?' if len(sent)==1 else 'Thank you.',
                                       tool_calls=(),node='scheduling',ended=len(sent)>1)
            async def close(self): pass
        cfg=json.loads(DEFAULT_SCENARIOS_PATH.with_name('external_config.json').read_text())
        with patch('text_runner.TextAgentSession',FakeSession):
            await run_one(compile_scenario(source,catalog),catalog,'proposed','offline-only',cfg)
        self.assertEqual(sent[0],source['opening'])
        self.assertNotIn('PRIVATE_PATIENT_CANARY',sent[0])
        self.assertIn('PRIVATE_PATIENT_CANARY',sent[1])
        self.assertTrue(all('GOLD_EXPECTATION_CANARY' not in s for s in sent))
        from dataclasses import asdict
        agent=json.dumps(asdict(captured[0].config))
        self.assertNotIn('PRIVATE_PATIENT_CANARY',agent)
        self.assertNotIn('GOLD_EXPECTATION_CANARY',agent)

    async def test_no_booking_basics_do_not_truncate_explicit_patient_script(self):
        from evals.external_eval import run_one
        catalog=load_catalog(DEFAULT_CATALOG_PATH)
        source=deepcopy(next(s for s in load_dev_scenarios()['scenarios'] if s['expected_outcome']=='no_booking'))
        source['expected']={'bookings':0}
        source['patient_script']=[{'when':'service_question','response':'No substitute services, thank you.'}]
        sent=[]
        class FakeSession:
            call_id='offline-script'; context_messages=[]
            def __init__(self,**kwargs):
                self._runtime=SimpleNamespace(llm=SimpleNamespace(_retry_on_timeout=True,_client=SimpleNamespace(max_retries=2)))
            async def start(self): return SimpleNamespace(assistant_text='How can I help?')
            async def send(self,text):
                sent.append(text)
                return SimpleNamespace(assistant_text='Which service would you like?' if len(sent)==1 else 'Please contact staff directly.',tool_calls=(),node='scheduling',ended=len(sent)>1)
            async def close(self): pass
        cfg=json.loads(DEFAULT_SCENARIOS_PATH.with_name('external_config.json').read_text())
        with patch('text_runner.TextAgentSession',FakeSession):
            await run_one(compile_scenario(source,catalog),catalog,'proposed','offline-script',cfg)
        self.assertEqual(sent,[source['opening'],'No substitute services, thank you.'])
