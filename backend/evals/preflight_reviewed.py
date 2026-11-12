"""Private, aggregate-only preflight of authorized revised assets. Never a model call."""
import asyncio
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import AsyncMock

from .external_contract import require
from .write_faults import WriteFaultController


async def exercise_write_fault(catalog, source):
    """Tool-protocol proof using private fact fields, not expected outcomes or labels.

    This proves the injector reaches the guarded write, not that the conversational
    agent will reach it or recover. Live runs must independently log their trigger.
    """
    from scheduling import SchedulingEngine
    from scheduling_agent import build_scheduling_agent
    from scheduling_dialogue import BookingSpeech
    from pipecat.frames.frames import LLMFullResponseEndFrame
    from pipecat.processors.frame_processor import FrameDirection
    engine = SchedulingEngine(catalog, source['availability_fixture'], now=datetime.fromisoformat('2026-11-07T00:00:00-08:00'))
    faults = WriteFaultController(engine, source.get('faults', []))
    builder = build_scheduling_agent(engine, catalog, availability_mode='eval_fixture')
    builder.set_function_handler_wrapper(faults.wrap)
    functions = {f.name: f for f in builder.build_initial_node()['functions']}
    dialogue = builder.dialogue
    speech = BookingSpeech(dialogue); speech.push_frame = AsyncMock()
    facts = source['patient_facts']
    updates = {k: facts[k] for k in ('date_of_birth', 'is_new_patient', 'referral_on_file', 'appointment_type_id') if k in facts}
    if 'name' in facts: updates['patient_name'] = facts['name']
    for field in ('provider', 'location'):
        value = facts.get('intended_' + field + '_id', facts.get(field + '_id'))
        if value: updates[field + '_id'] = value
        else: updates['any_' + field] = True
    await functions['resolve_options'].handler(updates, None)
    dialogue.require_identity()
    await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
    dialogue.patient('yes')
    if dialogue.identity_confirmed != dialogue.identity():
        return {'protocol_ready': False, 'reason': 'identity_not_confirmed', 'fault_evidence': faults.evidence()}
    slots = engine.find_slots(30, limit=10000).get('slots', [])
    if not slots:
        return {'protocol_ready': False, 'reason': 'no_eligible_slot_from_private_facts', 'fault_evidence': faults.evidence()}
    chosen = min(slots, key=lambda s: datetime.fromisoformat(s['start']))
    prepared = await functions['book_appointment'].handler({'slot_id': chosen['slot_id']}, None)
    phase_one_triggered = bool(faults.events)
    # No consent/readback yet: a repeated call must not activate a write fault.
    await functions['book_appointment'].handler({'slot_id': chosen['slot_id']}, None)
    before_consent_triggered = bool(faults.events)
    await speech.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
    dialogue.patient('yes')
    consent_recorded = engine.state.confirmation is not None
    result = await functions['book_appointment'].handler({'slot_id': chosen['slot_id']}, None)
    first_result = deepcopy(result)
    if any(f['mode'] == 'error' for f in faults.faults):
        result = await functions['book_appointment'].handler({'slot_id': chosen['slot_id']}, None)
    return {'protocol_ready': prepared.get('status') == 'needs_confirmation',
            'phase_one_triggered': phase_one_triggered, 'before_consent_triggered': before_consent_triggered,
            'consent_recorded': consent_recorded, 'write_returned_structured_error': first_result.get('status') == 'error',
            'booking_created': bool(engine.bookings), 'fault_evidence': faults.evidence(),
            'slot_loss_persists': (all(f['slot_id'] in engine._unavailable_slot_ids for f in faults.faults if f['mode'] == 'slot_taken')
                                  if any(f['mode'] == 'slot_taken' for f in faults.faults) else None),
            'fault_recovery_by_agent_verified': False}


def inspect_offline(catalog, sets, hashes):
    from scheduling import SchedulingEngine
    from .external_eval import ASSET_MANIFEST, PIN, ROOT
    from .write_faults import normalize_faults
    from openai.resources.chat.completions import AsyncCompletions
    from unittest.mock import patch
    manifest = json.loads(ASSET_MANIFEST.read_text())
    private_manifest = Path(manifest['assets']['heldout']['revised_path']).parent / 'exact-change-manifest.json'
    require(sha256(private_manifest.read_bytes()).hexdigest() == manifest['exact_change_manifest_sha256'], 'change_manifest_mismatch', 'manifest')
    removed_path = Path(manifest['removed_record_evidence'])
    require(sha256(removed_path.read_bytes()).hexdigest() == manifest['removed_record_evidence_sha256'], 'removed_evidence_mismatch', 'manifest')
    removed = json.loads(removed_path.read_text())['records']
    rejects = 0
    for item in removed:
        slot = item['record']
        appt = catalog.appointment_types_by_id[slot['appointment_type_id']]
        location = catalog.locations_by_id[slot['location_id']]
        require(appt.required_capability not in location.capabilities, 'removed_record_condition_changed', 'offline_initializer')
        try: SchedulingEngine(catalog, [slot])
        except ValueError: rejects += 1
    require(rejects == 4, 'initializer_evidence_mismatch', 'offline_initializer')
    result = {'scope_preserved_fully': False, 'scope_change': manifest['scope_change'],
              'originals_unchanged': True, 'removed_records': 4, 'offline_initializer_rejections': rejects,
              'exact_change_manifest_sha256': manifest['exact_change_manifest_sha256'],
              'assets': hashes, 'sets': {}, 'fault_protocol_checks': [],
              'manual_review': {'required_conversation_reviews': 40, 'heldout': 32, 'robustness': 8,
                                'incomplete_review_can_pass': False, 'rubric_path': 'backend/evals/review_rubric_v1_1.json',
                                'estimated_minutes_per_transcript': [3, 5], 'estimated_total_hours': [2, 3.33]},
              'paid_execution_performed': False}
    with patch.object(AsyncCompletions, 'create', side_effect=AssertionError('API forbidden in offline preflight')) as network:
        for kind, compiled in sets.items():
            revised = json.loads(Path(hashes[kind]['revised_path']).read_bytes())
            original = json.loads(Path(hashes[kind]['original_path']).read_bytes())
            normalized = json.loads(Path(hashes[kind]['normalized_path']).read_bytes())
            for old, new, mapped in zip(original['scenarios'], revised['scenarios'], normalized['scenarios']):
                require(old['id'] == new['id'] and old['expected_outcome'] == new['expected_outcome'], 'outcome_changed', 'revision')
                require(all(new['expected'].get(k) == v for k, v in old['expected'].items()), 'original_expectation_changed', 'revision')
                require(new['availability_fixture'] == mapped['availability_fixture'], 'boundary_fixture_changed', 'revision')
                compare = deepcopy(mapped)
                if 'faults' in compare: compare['faults'] = new['faults']
                require(compare == new, 'non_fault_boundary_change', 'revision')
                if 'faults' in mapped: require(mapped['faults'] == normalize_faults(new['faults']), 'fault_mapping_changed', 'revision')
            result['sets'][kind] = {'schema_compatible': True, 'scenarios': len(compiled),
                'fixture_records': sum(len(c['scenario']['availability_fixture']) for c in compiled),
                'engine_fixture_arrays_accepted': len(compiled), 'original_outcomes_and_booking_identities_preserved': True,
                'requiring_manual_review': sum(bool(c['review_required']) for c in compiled),
                'manual_review_field_paths': sorted({k for c in compiled for k in c['review_required']}),
                'automatic_assertion_names': sorted({a['name'] for c in compiled for a in __import__('evals.external_score', fromlist=['grade']).grade(c, {}, catalog)['assertions']})}
            for item in compiled:
                if item['scenario'].get('faults'):
                    proof = asyncio.run(exercise_write_fault(catalog, item['scenario']))
                    result['fault_protocol_checks'].append({'scenario_label': item['scenario']['id'], **proof})
            if kind == 'robustness':
                # Structural assertion, not scenario-ID dispatch: every original Saturday record must survive exactly.
                saturday = [s for c in original['scenarios'] for s in c['availability_fixture'] if datetime.fromisoformat(s['start']).weekday() == 5]
                kept = [s for c in revised['scenarios'] for s in c['availability_fixture']]
                require(all(s in kept for s in saturday), 'saturday_fixture_changed', 'revision')
                result['saturday_fixture_records_preserved'] = len(saturday)
        network.assert_not_called()
    result['fault_protocol_compatible'] = all(p.get('protocol_ready') and not p.get('phase_one_triggered') and not p.get('before_consent_triggered')
         and p.get('consent_recorded') and p.get('write_returned_structured_error') and not p.get('booking_created')
         and all(e['triggered'] and e['write_after_consent'] for e in p['fault_evidence']) for p in result['fault_protocol_checks'])
    require(result['fault_protocol_compatible'], 'write_fault_protocol_not_exercised', 'fault_protocol')
    result['rubric_sha256'] = sha256((ROOT / 'backend/evals/review_rubric_v1_1.json').read_bytes()).hexdigest()
    return result
