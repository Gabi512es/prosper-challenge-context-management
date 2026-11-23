"""Offline real-engine + scripted acts, with verbatim portable M0 outputs."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
import json
import unittest
from unittest.mock import patch
from scheduling import SchedulingEngine, load_catalog
from v4.acts import ActError, validate_acts
from v4.reducer import SchedulingReducer

BACKEND=Path(__file__).parents[1]
NOW=datetime.fromisoformat('2026-11-19T00:00:00-08:00')
FACTS=dict(appointment_type_id='appt_002',provider_id='prov_003',location_id='loc_005',
           name='Alex Morgan',date_of_birth='1990-04-12',is_new_patient=True)
def act(kind,**values): return dict(kind=kind,quote=None,**values)
def delta(field,value,kind='set_field'): return act(kind,delta=dict(field=field,value=value))
def affirm(p): return act('affirm',target=dict(type='proposal',id=p.id))
def deny(p): return act('deny',target=dict(type='proposal',id=p.id))
def slot(ident,provider='prov_003',site='loc_005',day=20,hour=10):
    start=datetime(2026,11,day,hour,tzinfo=NOW.tzinfo)
    return dict(slot_id=ident,provider_id=provider,location_id=site,appointment_type_id='appt_002',
                start=start.isoformat(),end=(start+timedelta(minutes=30)).isoformat())

class ReducerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=load_catalog(BACKEND/'data/catalog.json')
        cls.m0=json.loads((BACKEND/'tests/fixtures/v4_m0_outputs.json').read_text())
    def make(self,facts=FACTS,specialty='Family Medicine',availability=None):
        availability=availability if availability is not None else [
            *[slot(f'early-{i}',day=19,hour=8+i) for i in range(6)],slot('friday'),
            slot('pediatric-friday',provider='prov_002',site='loc_000'),slot('richmond-friday',site='loc_007')]
        e=SchedulingEngine(self.catalog,availability,now=NOW)
        if facts:e.resolve_options(deepcopy(facts))
        return SchedulingReducer(e,requested_specialty=specialty)
    def send(self,r,*acts,event=None,words=None,version=None):
        # Booking consent needs an acceptance in the caller's words (v1.6+), so a
        # scripted yes is spoken as "Yes."; other scripted turns carry no words.
        # Step 3: a request for a person needs a person named in the caller's words.
        if words is None:words=('Yes.' if any(a['kind']=='affirm' for a in acts)
                                else 'Can I talk to a person?' if any(a['kind']=='human_request' for a in acts)
                                else 'scripted caller')
        return r.reduce(event or f'event-{len(r.processed)}',words,{'acts':list(acts)},state_version=version)
    def confirmed(self,r):
        p=r.propose_identity();r.deliver_proposal(p.id)
        self.assertEqual(self.send(r,affirm(p)).status,'accepted')
        self.assertEqual(r.identity_confirmed,r.identity())
    def proposal(self,r,slot_id=None):
        if r.identity_confirmed!=r.identity():self.confirmed(r)
        ids=[s['slot_id'] for s in r.find_slots(limit=20)['slots']]
        p=r.present('slot',ids,delivered=True);chosen=slot_id or ids[0]
        out=self.send(r,act('select_option',presentation_id=p.id,selector={'by':'ordinal','ordinal':ids.index(chosen)+1}))
        self.assertEqual(out.status,'accepted',out)
        p=r.proposals[out.effects[0]['proposal_id']];r.deliver_proposal(p.id);return p
    def test_correction_plus_yes_never_rebinds_consent(self):
        r=self.make();p=self.proposal(r)
        out=self.send(r,delta('location','Richmond','correct'),affirm(p))
        self.assertEqual(out.status,'accepted');self.assertEqual(r.engine.state.location_id,'loc_007')
        self.assertEqual(r.proposals[p.id].status,'revoked');self.assertEqual(r.consent_ledger[-1]['outcome'],'discarded')
        self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'not_booked')
        new=self.proposal(r);self.assertNotEqual(new.id,p.id)
        self.assertEqual(r.commit_booking(new.id,endpoint_closed=True)['status'],'not_booked')
        self.send(r,affirm(new));self.assertEqual(r.commit_booking(new.id,endpoint_closed=True)['status'],'booked')
    def test_provider_selection_and_specialty_correct_processed_together(self):
        r=self.make({**FACTS,'provider_id':'prov_002','location_id':'loc_000'},'Pediatrics')
        old=self.proposal(r);identity=r.identity_confirmed;p=r.present('provider',['prov_002','prov_003'],delivered=True)
        out=self.send(r,act('select_option',presentation_id=p.id,selector={'by':'ordinal','ordinal':2}),delta('provider_specialty','Family Medicine','correct'))
        self.assertEqual(out.status,'accepted',out);self.assertEqual(r.engine.state.provider_id,'prov_003')
        self.assertEqual(r.requested_specialty,'Family Medicine');self.assertIsNone(r.engine.state.location_id)
        self.assertFalse(r.engine.state.any_provider);self.assertFalse(r.engine.state.any_location)
        self.assertEqual(r.identity_confirmed,identity);self.assertFalse(r.engine.state.offered_slot_ids)
        self.assertEqual(r.proposals[old.id].status,'revoked')
        self.assertEqual(self.send(r,act('select_option',presentation_id=p.id,selector={'by':'ordinal','ordinal':1})).status,'rejected')
    def test_pause_information_after_yes_require_fresh_readback(self):
        controls=[act('pause'),act('information_question',entity='appointment',name=None,reference_id=None,attribute='time'),act('information_question',entity='location',name='Mission District',reference_id=None,attribute='phone')]
        for control in controls:
            with self.subTest(control=control):
                r=self.make();p=self.proposal(r);self.send(r,affirm(p));before=deepcopy(r.engine.state)
                out=self.send(r,control);self.assertEqual(out.status,'accepted');self.assertEqual(r.engine.state,before)
                self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'not_booked')
                new=r.prepare_booking(p.slot_id);r.deliver_proposal(new.id)
                self.assertEqual(r.commit_booking(new.id,endpoint_closed=True)['status'],'not_booked')
                self.send(r,affirm(new));self.assertEqual(r.commit_booking(new.id,endpoint_closed=True)['status'],'booked')
    def test_dob_correction_retains_all_entities_and_specialty(self):
        r=self.make();p=self.proposal(r);s=r.engine.state;expected=(s.provider_id,s.location_id,s.appointment_type_id,r.requested_specialty)
        with patch.object(r.engine,'resolve_options',wraps=r.engine.resolve_options) as resolve:
            out=self.send(r,delta('date_of_birth',{'year':1991,'month':None,'day':None},'correct'))
        self.assertEqual(out.status,'accepted');self.assertEqual(s.patient_facts.date_of_birth,'1991-04-12')
        self.assertEqual((s.provider_id,s.location_id,s.appointment_type_id,r.requested_specialty),expected)
        self.assertTrue(all('provider_query' not in c.args[0] for c in resolve.call_args_list))
        self.assertIsNone(r.identity_confirmed);self.assertEqual(r.proposals[p.id].status,'revoked')
    def test_unknown_provider_preserves_every_other_fact_and_false(self):
        r=self.make(None,None)
        out=self.send(r,delta('service','Annual Physical'),delta('provider','Dr. Nobody Exists'),delta('new_patient',False),delta('referral',False),delta('name','Alex Morgan'),delta('date_of_birth',{'year':1990,'month':4,'day':12}))
        self.assertEqual(out.status,'accepted');self.assertEqual(out.resolution['status'],'no_match');s=r.engine.state
        self.assertEqual(s.appointment_type_id,'appt_002');self.assertIs(s.patient_facts.is_new_patient,False)
        self.assertIs(s.patient_facts.referral_on_file,False);self.assertEqual(s.patient_facts.name,'Alex Morgan')
        self.assertEqual(s.patient_facts.date_of_birth,'1990-04-12')
        self.send(r,delta('provider','Maria Garcia','correct'),delta('provider_specialty','Family Medicine'))
        self.assertEqual(s.provider_id,'prov_003');self.assertEqual(s.appointment_type_id,'appt_002');self.assertFalse(s.patient_facts.is_new_patient)
    def test_ordered_membership_and_named_unpresented_option(self):
        r=self.make({k:v for k,v in FACTS.items() if k!='provider_id'},None)
        p=r.present('provider',['prov_003','prov_002'],delivered=True)
        self.assertEqual(self.send(r,act('select_option',presentation_id=p.id,selector={'by':'ordinal','ordinal':1})).status,'accepted')
        self.assertEqual(r.engine.state.provider_id,'prov_003');p=r.present('provider',['prov_003'],delivered=True)
        for selector in ({'by':'ordinal','ordinal':2},{'by':'name','words':'Wei Chen','option_id':'prov_004'}):
            self.assertEqual(self.send(r,act('select_option',presentation_id=p.id,selector=selector)).status,'rejected')
    def test_split_yes_please_duplicate_events_and_booking_idempotency(self):
        r=self.make();p=self.proposal(r);self.send(r,affirm(p),event='yes');v=r.state_version
        self.assertEqual(self.send(r,affirm(p),event='yes').state_version,v);self.assertEqual(r.state_version,v)
        self.send(r,affirm(p),event='please');self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'booked')
        self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'idempotent');self.assertEqual(len(r.engine.bookings),1)
        with self.assertRaises(ActError):self.send(r,deny(p),event='yes')
    def test_received_veto_blocks_pending_write_without_invalidating_running_turn(self):
        r=self.make();p=self.proposal(r);r.receive('yes');v=r.state_version;r.receive('veto')
        self.assertEqual(self.send(r,affirm(p),event='yes',version=v).status,'accepted')
        self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['code'],'unprocessed_input')
        self.send(r,deny(p),event='veto');self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'not_booked');self.assertFalse(r.engine.bookings)
    def test_identity_yes_is_not_booking_yes_and_pre_delivery_yes_fails(self):
        r=self.make();p=r.propose_identity();r.deliver_proposal(p.id);self.send(r,affirm(p))
        self.assertEqual(r.identity_confirmed,r.identity());self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'not_booked')
        found=r.find_slots();r.present('slot',[s['slot_id'] for s in found['slots']],delivered=True)
        p=r.prepare_booking(found['slots'][0]['slot_id']);r.receive('early');r.deliver_proposal(p.id)
        self.assertEqual(self.send(r,affirm(p),event='early').status,'rejected');self.assertFalse(r.engine.bookings)
    def test_unoffered_date_filters_before_truncation_and_survives_provider_change(self):
        r=self.make();self.confirmed(r);self.send(r,delta('appointment_date','2026-11-20'))
        self.assertEqual([s['slot_id'] for s in r.find_slots(limit=1)['slots']],['friday'])
        self.assertEqual(r.engine.state.patient_facts.date_of_birth,'1990-04-12')
        r.present('slot',['friday'],delivered=True);old=r.prepare_booking('friday');r.deliver_proposal(old.id)
        self.send(r,delta('provider','Maria Garcia','correct'),delta('provider_specialty','Pediatrics','correct'))
        self.assertEqual(r.appointment_date,date(2026,11,20));self.assertEqual(r.requested_specialty,'Pediatrics')
        self.send(r,delta('location','Mission Bay','correct'))
        self.assertEqual([s['slot_id'] for s in r.find_slots(limit=1)['slots']],['pediatric-friday'])
        self.assertEqual(r.commit_booking(old.id,endpoint_closed=True)['status'],'not_booked')
    def test_date_rechecked_before_booking(self):
        r=self.make();p=self.proposal(r,'friday');self.send(r,affirm(p));r.appointment_date=date(2026,11,23)
        self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'not_booked');self.assertFalse(r.engine.bookings)
    def test_control_acts_never_grant_consent(self):
        controls=[act('acknowledge'),act('pause'),act('cancel',scope='pending_request'),act('human_request',action='request'),act('unsupported',topic='clock_time'),act('urgent_escalation'),act('unclear',subject='meaning')]
        for control in controls:
            with self.subTest(kind=control['kind']):
                r=self.make();p=self.proposal(r);out=self.send(r,control)
                self.assertEqual(out.status,'accepted',out);self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'not_booked');self.assertFalse(r.engine.bookings)
        r=self.make();p=self.proposal(r)
        self.assertEqual(self.send(r,act('repeat_request',message_id=p.message_id,part='time')).status,'accepted')
        self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'not_booked')
    def test_acknowledge_preserves_question_without_clarification(self):
        r=self.make();p=self.proposal(r);r.set_question('booking_consent',delivered=True)
        state=deepcopy(r.engine.state);q=r.question;v=r.state_version;ledger=deepcopy(r.consent_ledger)
        self.send(r,act('acknowledge'));self.assertEqual(r.engine.state,state);self.assertEqual(r.question,q);self.assertEqual(r.state_version,v)
        self.assertEqual(r.proposals[p.id].status,'open');self.assertEqual(r.consent_ledger,ledger)
    def test_information_and_repeat_preserve_selection_but_not_accepted_consent(self):
        r=self.make();p=self.proposal(r);self.send(r,affirm(p));state=deepcopy(r.engine.state)
        for control in (act('information_question',entity='location',name='Mission District',reference_id=None,attribute='hours'),act('repeat_request',message_id=p.message_id,part='all')):
            self.assertEqual(self.send(r,control).status,'accepted');self.assertEqual(r.engine.state,state)
        self.assertEqual(r.engine.state.location_id,'loc_005');self.assertEqual(r.proposals[p.id].status,'revoked')
    def test_invalid_output_revokes_pending_write_without_fact_loss(self):
        for raw in ({'acts':[]},{'acts':[act('affirm',target={'type':'proposal','id':'invented'})]},{'acts':[act('acknowledge')],'state_version':1}):
            r=self.make();p=self.proposal(r);self.send(r,affirm(p));state=deepcopy(r.engine.state)
            self.assertEqual(r.reduce('bad','anything',raw).status,'rejected');self.assertEqual(r.engine.state,state)
            self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'not_booked')
    def test_core_slot_loss_and_recorded_booking_cancellation(self):
        r=self.make();p=self.proposal(r);self.send(r,affirm(p));r.engine.mark_slot_unavailable(p.slot_id)
        self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'not_booked');self.assertFalse(r.engine.bookings)
        r=self.make();p=self.proposal(r);self.send(r,affirm(p));r.commit_booking(p.id,endpoint_closed=True)
        # After a booking, with nothing pending, a pending-request cancel ("no, that's all";
        # every recorded case has this scope) closes the call; a cancel of the recorded
        # booking is answered as unsupported (Step 3). The booking is never touched.
        out=self.send(r,act('cancel',scope='pending_request'));self.assertEqual(out.effects[0]['kind'],'closing');self.assertEqual(len(r.engine.bookings),1)
        out=self.send(r,act('cancel',scope='recorded_booking'));self.assertEqual(out.effects[0],{'kind':'unsupported','topic':'recorded_booking_change'});self.assertEqual(len(r.engine.bookings),1)
    def test_partial_dob_and_slot_choice_cannot_be_confused(self):
        r=self.make({k:v for k,v in FACTS.items() if k!='date_of_birth'})
        self.send(r,delta('date_of_birth',{'year':None,'month':4,'day':12}));self.assertIsNone(r.engine.state.patient_facts.date_of_birth)
        self.send(r,delta('date_of_birth',{'year':1991,'month':None,'day':None}));self.assertEqual(r.engine.state.patient_facts.date_of_birth,'1991-04-12')
        r.set_question('slot_choice',delivered=True)
        self.assertEqual(self.send(r,delta('date_of_birth',{'year':2026,'month':11,'day':20})).status,'rejected')
        self.assertEqual(r.engine.state.patient_facts.date_of_birth,'1991-04-12')
    def test_schema_quote_and_strict_false_type_validation(self):
        raw={'acts':[{'kind':'affirm','quote':'Yes.','target':{'type':'proposal','id':'p'}}]}
        self.assertEqual(validate_acts(raw,'Yes. Yes.').quote_starts,((0,5),))
        for bad in ({'acts':[act('human_request',action='continue_scheduling')]},{'acts':[delta('new_patient',0)]},{'acts':[delta('appointment_date',1991)]},{'acts':[act('acknowledge',start=0)]}):
            with self.assertRaises(ActError):validate_acts(bad,'anything')
        with self.assertRaises(ActError):validate_acts(raw,'No.')
    def m0_session(self,case):
        ctx=case['context'];known=ctx['known'];updates={}
        for key,field in (('service','appointment_type_id'),('provider','provider_id'),('location','location_id')):
            if known.get(key):updates[field]=known[key]['id']
        identity=known.get('identity',{})
        for key in ('name','date_of_birth'):
            if identity.get(key):updates[key]=identity[key]
        if 'new_patient' in known:updates['is_new_patient']=known['new_patient']
        availability=([slot('probe-thursday',day=19),slot('probe-friday')] if any(p['entity']=='slot' for p in ctx['presentations']) else [slot('synthetic-probe-slot')])
        r=self.make(updates,known.get('provider_specialty'),availability)
        if identity.get('partial_date_of_birth'):self.send(r,delta('date_of_birth',{'year':None,**identity['partial_date_of_birth']}))
        if identity.get('confirmed'):self.confirmed(r)
        if ctx.get('proposal'):
            r.find_slots(limit=20);r.present('slot',['synthetic-probe-slot'],delivered=True)
            p=r.prepare_booking('synthetic-probe-slot',proposal_id=ctx['proposal']['id'],message_id=ctx['last_message']['id']);r.deliver_proposal(p.id)
        for p in ctx['presentations']:
            if p['entity']=='slot':r.find_slots(limit=20)
            r.present(p['entity'],[o['option_id'] for o in p['options']],presentation_id=p['id'],delivered=True,message_id=ctx['last_message']['id'])
        q=ctx['question'];r.set_question(q['kind'],question_id=q['id'],delivered=True)
        return r
    def test_fourteen_unchanged_saved_m0_outputs_as_fixtures(self):
        for case in self.m0['cases']:
            with self.subTest(label=case['label']):
                raw=json.loads(case['raw_output']);validate_acts(raw,case['caller_text']);r=self.m0_session(case)
                out=r.reduce(case['label'],case['caller_text'],raw,state_version=r.state_version)
                if case['label']=='04-ordinal':self.assertEqual(out.errors,('specialty_conflict',))
                else:self.assertEqual(out.status,'accepted',out)
                self.assertFalse(r.engine.bookings)

    def test_repeating_known_facts_does_not_retire_consent(self):
        r=self.make();p=self.proposal(r);self.send(r,affirm(p));before=deepcopy(r.engine.state)
        out=self.send(r,delta('service','Annual Physical'),delta('new_patient',True),delta('provider_specialty','Family Medicine'),delta('date_of_birth',{'year':1990,'month':4,'day':12}))
        self.assertEqual(out.status,'accepted',out);self.assertEqual(r.engine.state,before)
        self.assertEqual(r.proposals[p.id].status,'accepted')
        self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'booked')

    def test_multiple_hard_deltas_merge_and_omission_keeps_others(self):
        r=self.make();r.engine.state.hard_constraints={'appointment_date'}
        out=self.send(r,delta('hard_constraint',{'field':'provider','enabled':True}),delta('hard_constraint',{'field':'location','enabled':True}))
        self.assertEqual(out.status,'accepted',out)
        self.assertEqual(r.engine.state.hard_constraints,{'appointment_date','provider','location'})
        self.send(r,delta('referral',False))
        self.assertEqual(r.engine.state.hard_constraints,{'appointment_date','provider','location'})

    def test_specialty_alone_retires_incompatible_provider_without_widening(self):
        r=self.make({**FACTS,'provider_id':'prov_002','location_id':'loc_000'},'Pediatrics')
        out=self.send(r,delta('provider_specialty','Family Medicine','correct'))
        self.assertEqual(out.status,'accepted');self.assertIsNone(r.engine.state.provider_id)
        self.assertEqual(r.requested_specialty,'Family Medicine');self.assertFalse(r.engine.state.any_provider)

    def test_endpoint_is_closed_only_when_explicitly_supplied(self):
        r=self.make();p=self.proposal(r);self.send(r,affirm(p))
        self.assertEqual(r.commit_booking(p.id)['code'],'unprocessed_input')
        self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'booked')

    def test_out_of_order_application_cannot_skip_queued_correction(self):
        r=self.make();p=self.proposal(r);r.receive('first');r.receive('second');before=deepcopy(r.engine.state)
        with self.assertRaises(ActError):self.send(r,affirm(p),event='second')
        self.assertEqual(r.engine.state,before);self.assertEqual(list(r.pending_inputs),['first','second'])
        self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'not_booked')

    def test_retired_proposal_and_reused_ids_cannot_gain_delivery(self):
        r=self.make();p=self.proposal(r);self.send(r,act('pause'))
        with self.assertRaises(ActError):r.deliver_proposal(p.id)
        with self.assertRaises(ActError):r.prepare_booking(p.slot_id,proposal_id=p.id)
        r.set_question('boolean',field='referral',question_id='q')
        with self.assertRaises(ActError):r.set_question('boolean',field='new_patient',question_id='q')
        r.present('provider',['prov_003'],presentation_id='shared',delivered=True)
        with self.assertRaises(ActError):r.propose_identity(proposal_id='shared')

    def test_conflicting_affirm_and_deny_never_write_in_either_order(self):
        for reverse in (False,True):
            r=self.make();p=self.proposal(r);acts=[affirm(p),deny(p)]
            out=self.send(r,*(list(reversed(acts)) if reverse else acts))
            self.assertEqual(out.status,'accepted')
            self.assertEqual(r.commit_booking(p.id,endpoint_closed=True)['status'],'not_booked')
            self.assertFalse(r.engine.bookings)

    def test_hard_site_is_not_erased_by_provider_change(self):
        r=self.make({**FACTS,'provider_id':'prov_002','location_id':'loc_000'},'Pediatrics')
        r.engine.state.hard_constraints={'location'}
        self.send(r,delta('provider','Maria Garcia','correct'),delta('provider_specialty','Family Medicine','correct'))
        self.assertEqual(r.engine.state.location_id,'loc_000')
        self.assertIn('provider_not_at_location',{b['code'] for b in r.engine.resolve_options()['blocked_options']})
        self.assertFalse(r.engine.state.any_location)

    def test_stale_information_reference_and_ambiguous_named_selection(self):
        r=self.make();p=self.proposal(r)
        self.send(r,delta('location','Richmond','correct'))
        out=self.send(r,act('information_question',entity='appointment',name=None,reference_id=p.id,attribute='time'))
        self.assertEqual(out.status,'rejected')
        r=self.make(specialty=None);choices=r.present('provider',['prov_002','prov_003'],delivered=True)
        out=self.send(r,act('select_option',presentation_id=choices.id,selector={'by':'name','words':'Maria Garcia','option_id':'prov_003'}))
        self.assertEqual(out.errors,('ambiguous_named_option',))

    def test_engine_hours_policy_and_specialty_are_enforced_at_v4_boundary(self):
        outside=slot('late');outside['start']='2026-11-20T17:30:00-08:00';outside['end']='2026-11-20T18:00:00-08:00'
        r=self.make(availability=[outside,slot('valid')]);self.confirmed(r)
        self.assertEqual([s['slot_id'] for s in r.find_slots()['slots']],['valid'])
        self.send(r,delta('service','Follow-up Visit','correct'))
        result=r.find_slots();self.assertEqual(result['status'],'blocked')
        self.assertIn('new_patient_type_restricted',{i['code'] for i in result['issues']})

    def test_saved_m0_split_finals_keep_same_consent_until_write_or_veto(self):
        cases={c['label']:c for c in self.m0['cases']}
        for veto in (False,True):
            r=self.m0_session(cases['07a-split-yes'])
            for key in ('07a-split-yes','07b-split-please'):
                c=cases[key];self.assertEqual(r.reduce(key,c['caller_text'],json.loads(c['raw_output'])).status,'accepted')
            if veto:
                c=cases['02-deny'];r.reduce(c['label'],c['caller_text'],json.loads(c['raw_output']))
            self.assertEqual(r.commit_booking('proposal-book',endpoint_closed=True)['status'],'not_booked' if veto else 'booked')

    def test_duplicate_selection_has_no_repeated_speech_effect(self):
        r=self.make();self.confirmed(r);found=r.find_slots();p=r.present('slot',[s['slot_id'] for s in found['slots']],delivered=True)
        selection=act('select_option',presentation_id=p.id,selector={'by':'ordinal','ordinal':1})
        first=self.send(r,selection,event='choice');second=self.send(r,selection,event='choice')
        self.assertTrue(first.effects);self.assertTrue(second.duplicate);self.assertEqual(second.effects,())
        self.assertEqual(len([p for p in r.proposals.values() if p.kind=='booking']),1)

    def test_explicit_scope_and_question_false_are_deltas_not_defaults(self):
        r=self.make();out=self.send(r,delta('any_provider',True))
        self.assertEqual(out.status,'accepted',out);self.assertTrue(r.engine.state.any_provider)
        self.assertIsNone(r.engine.state.provider_id);self.assertEqual(r.requested_specialty,'Family Medicine')
        r=self.make({k:v for k,v in FACTS.items() if k!='is_new_patient'})
        q=r.set_question('boolean',field='new_patient');r.deliver_question(q.id)
        out=self.send(r,act('deny',target={'type':'question','id':q.id}))
        self.assertEqual(out.status,'accepted',out);self.assertIs(r.engine.state.patient_facts.is_new_patient,False)
        self.assertFalse(r.engine.bookings)

    def test_unrelated_service_change_preserves_explicit_scope(self):
        for flags in (('any_provider',), ('any_location',), ('any_provider','any_location')):
            with self.subTest(flags=flags):
                r=self.make();self.send(r,*(delta(flag,True) for flag in flags))
                out=self.send(r,delta('service','New Patient Consultation','correct'))
                self.assertEqual(out.status,'accepted',out)
                for flag in flags:
                    self.assertTrue(getattr(r.engine.state,flag))
                    self.assertTrue(out.resolution['search_scope'][flag])

    def test_provider_change_preserves_any_location(self):
        r=self.make();self.send(r,delta('any_location',True))
        provider=next(p for p in self.catalog.providers if p.id!='prov_003'
                      and p.specialty=='Family Medicine' and 'appt_002' in p.appointment_type_ids)
        p=r.present('provider',[provider.id],delivered=True)
        out=self.send(r,act('select_option',presentation_id=p.id,selector={'by':'ordinal','ordinal':1}))
        self.assertEqual(out.status,'accepted',out);self.assertEqual(r.engine.state.provider_id,provider.id)
        self.assertTrue(r.engine.state.any_location);self.assertIsNone(r.engine.state.location_id)
        self.assertTrue(out.resolution['search_scope']['any_location'])

    def test_named_choice_replaces_only_contradicted_scope(self):
        for entity,ident,cleared,retained in (
                ('provider','prov_003','any_provider','any_location'),
                ('location','loc_005','any_location','any_provider')):
            with self.subTest(entity=entity):
                r=self.make();self.send(r,delta('any_provider',True),delta('any_location',True))
                p=r.present(entity,[ident],delivered=True)
                out=self.send(r,act('select_option',presentation_id=p.id,selector={'by':'ordinal','ordinal':1}))
                self.assertEqual(out.status,'accepted',out)
                self.assertFalse(getattr(r.engine.state,cleared));self.assertTrue(getattr(r.engine.state,retained))
                self.send(r,delta(retained,False));self.assertFalse(getattr(r.engine.state,retained))

    def test_scope_restoration_keeps_lookup_errors_and_candidates(self):
        for name,specialty,status in (('Dr. Nobody Exists','Family Medicine','no_match'),
                                       ('Maria Garcia',None,'clarify')):
            with self.subTest(status=status):
                r=self.make();self.send(r,delta('any_location',True))
                out=self.send(r,delta('provider',name,'correct'),delta('provider_specialty',specialty,'correct'))
                self.assertEqual(out.status,'accepted',out);self.assertTrue(r.engine.state.any_location)
                self.assertEqual(out.resolution['status'],status)
                if status=='no_match':
                    self.assertEqual(out.resolution['errors'][0]['code'],'unknown_provider')
                else:
                    self.assertEqual({c['id'] for c in out.resolution['candidates']},{'prov_002','prov_003'})
                    self.assertEqual(r.engine.state.last_candidates,out.resolution['candidates'])

    def test_terminal_controls_dominate_pause_in_both_orders_and_stay_stopped(self):
        # v1.8: only urgent escalation and a request for a person are terminal; a
        # cancel retires the pending request, not the call (asserted below).
        for terminal,expected in ((act('human_request',action='request'),'human'),
                                  (act('urgent_escalation'),'urgent')):
            for reverse in (False,True):
                with self.subTest(control=expected,reverse=reverse):
                    r=self.make();controls=[terminal,act('pause')]
                    if reverse:controls.reverse()
                    out=self.send(r,*controls)
                    self.assertEqual(out.status,'accepted',out);self.assertEqual(r.control,expected)
                    self.assertNotIn('pause',{e['kind'] for e in out.effects})
                    # Later ordinary facts/acknowledgement/pause must not resume scheduling.
                    self.send(r,act('acknowledge'),delta('new_patient',False,'correct'),act('pause'))
                    self.assertEqual(r.control,expected)
                    if expected=='human':
                        # Step 8: after the honest "I cannot transfer", a new booking request, a plain
                        # okay or a yes resumes scheduling; another request for a person does not.
                        self.send(r,act('human_request',action='request'),delta('service','flu shot'))
                        self.assertEqual(r.control,'human')
                        self.send(r,delta('service','flu shot'));self.assertEqual(r.control,'active')
                        continue
                    self.confirmed(r)
                    ids=[s['slot_id'] for s in r.find_slots()['slots']]
                    r.present('slot',ids,delivered=True)
                    with self.assertRaises(ActError) as error:r.prepare_booking(ids[0])
                    self.assertEqual(error.exception.code,'scheduling_stopped')
                    self.assertEqual(r.control,expected);self.assertFalse(r.engine.bookings)

    def test_cancel_with_pause_retires_the_request_not_the_call(self):
        for reverse in (False,True):
            with self.subTest(reverse=reverse):
                r=self.make();controls=[act('cancel',scope='pending_request'),act('pause')]
                if reverse:controls.reverse()
                out=self.send(r,*controls)
                self.assertEqual(out.status,'accepted',out);self.assertEqual(r.control,'active')
                self.assertTrue(r.request_cancelled);self.assertNotIn('pause',{e['kind'] for e in out.effects})
                self.assertIsNone(r.engine.state.appointment_type_id);self.assertFalse(r.engine.bookings)

    def test_urgent_control_cannot_be_downgraded_by_human_request(self):
        for reverse in (False,True):
            r=self.make();controls=[act('human_request',action='request'),act('urgent_escalation')]
            if reverse:controls.reverse()
            self.assertEqual(self.send(r,*controls).status,'accepted');self.assertEqual(r.control,'urgent')
            self.send(r,act('human_request',action='request'),act('pause'))
            self.assertEqual(r.control,'urgent')

    def test_slot_selection_plus_information_preserves_choice_not_consent(self):
        for reverse in (False,True):
            with self.subTest(reverse=reverse):
                r=self.make();old=self.proposal(r);self.send(r,affirm(old))
                presentation=next(p for p in r.presentations.values() if p.entity=='slot')
                chosen=presentation.option_ids[1]
                info=act('information_question',entity='location',name='Mission District',reference_id=None,attribute='phone')
                acts=[act('select_option',presentation_id=presentation.id,selector={'by':'ordinal','ordinal':2}),info,affirm(old)]
                if reverse:acts.reverse()
                out=self.send(r,*acts,event='select-and-info')
                self.assertEqual(out.status,'accepted',out);self.assertEqual(r.engine.state.selected_slot_id,chosen)
                self.assertEqual([e for e in out.effects if e['kind']=='information_question'],[info])
                readbacks=[e for e in out.effects if e['kind']=='booking_readback']
                self.assertEqual(len(readbacks),1);new=r.proposals[readbacks[0]['proposal_id']]
                self.assertNotEqual(new.id,old.id);self.assertEqual(new.slot_id,chosen)
                self.assertEqual(new.status,'open');self.assertFalse(new.delivered)
                self.assertEqual(r.proposals[old.id].status,'revoked')
                self.assertEqual([e for e in r.consent_ledger if e.get('event_id')=='select-and-info'][-1]['outcome'],'discarded')
                # The information effect can be answered without mutating the selected booking.
                state=deepcopy(r.engine.state);answer=r.engine.get_details('location','loc_001')
                self.assertEqual(answer['status'],'ok');self.assertEqual(r.engine.state,state)
                self.assertFalse(r.engine.bookings)
                self.assertEqual(r.commit_booking(old.id,endpoint_closed=True)['status'],'not_booked')
                self.assertEqual(r.commit_booking(new.id,endpoint_closed=True)['status'],'not_booked')
                r.deliver_proposal(new.id)
                self.assertEqual(r.commit_booking(new.id,endpoint_closed=True)['status'],'not_booked')
                self.send(r,affirm(new))
                self.assertEqual(r.commit_booking(new.id,endpoint_closed=True)['status'],'booked')
                self.assertEqual(r.engine.bookings[0]['slot_id'],chosen)

    def test_unique_named_choice_and_proposal_ids_are_context_bound(self):
        r=self.make(specialty=None);p=r.present('provider',['prov_003'],delivered=True)
        out=self.send(r,act('select_option',presentation_id=p.id,selector={'by':'name','words':'Dr. Maria Garcia','option_id':'prov_003'}))
        self.assertEqual(out.status,'accepted',out)
        with self.assertRaises(ActError):r.present('provider',['prov_003'],presentation_id=p.id,delivered=True)
        with self.assertRaises(ActError):r.present('provider',['prov_003'],message_id=p.id,delivered=True)
