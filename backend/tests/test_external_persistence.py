"""Offline infrastructure checks: actual searched/booked state, no paid calls."""
import asyncio
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from evals.external_io import EvidenceJournal, EvidenceWriteError, DurableBudgets, atomic_json, json_text
from evals.external_eval import checkpoint, run_batch, live_observation, compile_scenario, PatientDriver
from evals.external_score import grade
from evals.loader import load_dev_scenarios, DEFAULT_CATALOG_PATH
from scheduling import SchedulingEngine, load_catalog


async def real_completed_result():
    """Actual production handlers/identity/readback/consent, public DEV only."""
    from scheduling_agent import build_scheduling_agent
    from scheduling_dialogue import BookingSpeech
    from pipecat.frames.frames import LLMFullResponseEndFrame
    from pipecat.processors.frame_processor import FrameDirection
    catalog = load_catalog(DEFAULT_CATALOG_PATH)
    source = deepcopy(next(s for s in load_dev_scenarios()['scenarios'] if s['expected_outcome']=='book'))
    engine = SchedulingEngine(catalog, source['availability_fixture'], now=datetime.fromisoformat('2026-11-07T00:00:00-08:00'))
    builder = build_scheduling_agent(engine, catalog, availability_mode='eval_fixture')
    functions = {f.name:f for f in builder.build_initial_node()['functions']}
    facts = source['patient_facts']
    updates = {k:v for k,v in facts.items() if k in {'name','date_of_birth','is_new_patient','referral_on_file','provider_id','location_id','appointment_type_id'}}
    updates['patient_name'] = updates.pop('name')
    await functions['resolve_options'].handler(updates,None)
    speech=BookingSpeech(builder.dialogue);speech.push_frame=AsyncMock()
    builder.dialogue.require_identity()
    await speech.process_frame(LLMFullResponseEndFrame(),FrameDirection.DOWNSTREAM)
    builder.dialogue.patient('yes')
    slots=engine.find_slots(30)['slots'];assert slots
    slot=slots[0]
    await functions['book_appointment'].handler({'slot_id':slot['slot_id']},None)
    await speech.process_frame(LLMFullResponseEndFrame(),FrameDirection.DOWNSTREAM)
    builder.dialogue.patient('yes')
    booked=await functions['book_appointment'].handler({'slot_id':slot['slot_id']},None)
    assert booked['status']=='booked' and isinstance(engine.state.last_horizon_end,datetime)
    driver=PatientDriver.from_compiled(compile_scenario(source,catalog))
    obs=live_observation(engine,[],[],driver)
    # Production types, plus nested aware dates to cover recursive serialization.
    obs['nested']={'clock':engine.now,'dates':[date(2026,11,7), {'horizon':engine.state.last_horizon_end}], 'values':{'b','a'}}
    result={**grade(compile_scenario(source,catalog),obs,catalog),'call_id':'offline-call','run_id':'offline-run',
            'agent':builder.session_metadata,'observation':obs,'transcript':[{'role':'patient','text':'yes'},{'role':'assistant','text':"You're all set."}],
            'patient_turn_metrics':[{'patient_turn':1,'completed':True,'elapsed_ms':10.0}]}
    return catalog,source,result


class JSONTest(unittest.TestCase):
    def test_dates_offsets_sets_and_unknown_types(self):
        instant=datetime(2026,11,7,8,15,tzinfo=timezone(timedelta(hours=-8)))
        obj={'nested':[{'when':instant,'date':date(2026,11,7)}],'set':{'b','a'},'null':None}
        parsed=json.loads(json_text(obj))
        self.assertEqual(parsed['nested'][0]['when'],'2026-11-07T08:15:00-08:00')
        self.assertEqual(datetime.fromisoformat(parsed['nested'][0]['when']),instant)
        self.assertEqual(parsed['nested'][0]['date'],'2026-11-07')
        self.assertEqual(parsed['set'],['a','b']);self.assertIsNone(parsed['null'])
        with self.assertRaises(TypeError):json_text({'unsupported':object()})
        with self.assertRaises(ValueError):json_text({'naive':datetime(2026,11,7)})

    def test_failed_serialization_and_replace_keep_previous_checkpoint(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'report.json';atomic_json(path,{'previous':True});old=path.read_bytes()
            with self.assertRaises(TypeError):atomic_json(path,{'bad':object()})
            self.assertEqual(path.read_bytes(),old)
            with patch('evals.external_io.os.replace',side_effect=OSError('deliberate disk failure')):
                with self.assertRaises(OSError):atomic_json(path,{'new':True})
            self.assertEqual(path.read_bytes(),old)
            self.assertFalse(list(Path(temp).glob('*.tmp')))


class PersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_result_checkpoints_final_export_and_independent_evidence(self):
        cat,source,result=await real_completed_result()
        self.assertIsInstance(result['observation']['state']['last_horizon_end'],datetime)
        with self.assertRaisesRegex(TypeError,'datetime'):
            json.dumps(result,default=list)  # Exact historical failure, offline.
        cfg=json.loads(Path('evals/external_config.json').read_text())
        with TemporaryDirectory() as temp:
            path=Path(temp)/'results.json';metrics=Path(temp)/'metrics.jsonl'
            journal=EvidenceJournal(Path(temp)/'events.jsonl','offline')
            journal.context={'attempt_id':'offline-attempt','dataset':'heldout','arm':'proposed'}
            async def handler(args,manager):return {'status':'booked','nested':{'time':cat and datetime.fromisoformat('2026-11-07T08:00:00-08:00')}}
            wrapped=journal.wrap_tool('book_appointment',handler)
            returned=await wrapped({'slot_id':'offline'},None)
            journal.emit('patient_message',text='yes');journal.emit('assistant_message',text="You're all set.")
            journal.emit('conversation_result',result=result)
            budgets=DurableBudgets({'heldout':'5'},cfg,journal)
            result['admitted_requests']=0
            report={'runs':[result],'complete':False}
            checkpoint(path,report,metrics,budgets)
            saved=json.loads(path.read_text())
            horizon=saved['runs'][0]['observation']['state']['last_horizon_end']
            self.assertIsNotNone(datetime.fromisoformat(horizon).utcoffset())
            self.assertEqual(horizon,result['observation']['state']['last_horizon_end'].isoformat())
            self.assertEqual(saved['runs'][0]['observation']['nested']['clock'],'2026-11-07T00:00:00-08:00')
            self.assertEqual(saved['runs'][0]['observation']['nested']['dates'][0],'2026-11-07')
            report['complete']=True;checkpoint(path,report,metrics,budgets)
            self.assertTrue(json.loads(path.read_text())['complete'])
            before=journal.path.read_bytes()
            with self.assertRaises(TypeError):atomic_json(path,{'deliberate_final_failure':object()})
            self.assertEqual(journal.path.read_bytes(),before)
            events=[json.loads(x) for x in journal.path.read_text().splitlines()]
            self.assertEqual([e['event'] for e in events],['tool_started','tool_finished','patient_message','assistant_message','conversation_result'])
            self.assertEqual(events[1]['result']['nested']['time'],'2026-11-07T08:00:00-08:00')
            self.assertTrue(json.loads(path.read_text())['complete'])

    async def exercise_batch(self, temp, final_failure=False):
        catalog,source,result=await real_completed_result()
        compiled=compile_scenario(source,catalog)
        cfg=json.loads(Path('evals/external_config.json').read_text())
        args=SimpleNamespace(batch='heldout',max_cost_usd='5',approval_ref='offline-not-authorization',dataset_hashes={})
        from openai.resources.chat.completions import AsyncCompletions
        from openai.types.chat import ChatCompletionChunk
        chunk=ChatCompletionChunk.model_validate({'id':'offline-stream','object':'chat.completion.chunk','created':1,'model':'gpt-4o','choices':[],
            'usage':{'prompt_tokens':100,'completion_tokens':10,'total_tokens':110,'prompt_tokens_details':{'cached_tokens':80}}})
        class Stream:
            def __aiter__(self):return self.items()
            async def items(self):yield chunk
            async def close(self):pass
        async def fake_api(client,**kwargs):return Stream()
        async def fake_run(*args, evidence, metrics_log, **kwargs):
            from metrics_logging import TurnMetricsObserver
            from pipecat.metrics.metrics import LLMTokenUsage, LLMUsageMetricsData, ProcessingMetricsData
            from pipecat.frames.frames import MetricsFrame
            from pipecat.observers.base_observer import FramePushed
            call_id='offline-'+evidence.context['attempt_id']
            evidence.context['call_id']=call_id
            evidence.emit('patient_message',text='yes')
            stream=await AsyncCompletions.create(object(),model='gpt-4o',stream=True,messages=[{'role':'user','content':'yes'}])
            async for _ in stream:pass
            # Reuse the actual metrics observer, independent of the final report.
            observer=TurnMetricsObserver(call_id=call_id,run_id=evidence.run_id,node_name=lambda:'scheduling',default_model='gpt-4o',output_path=metrics_log)
            for metric in (LLMUsageMetricsData(processor='OpenAILLMService#offline',model='gpt-4o',value=LLMTokenUsage(prompt_tokens=100,cache_read_input_tokens=80,completion_tokens=10,total_tokens=110)),
                           ProcessingMetricsData(processor='OpenAILLMService#offline',model='gpt-4o',value=.1)):
                await observer.on_push_frame(FramePushed(source=None,destination=None,frame=MetricsFrame(data=[metric]),direction=None,timestamp=0))
            async def booked_handler(args,manager):return {'status':'booked','booking':result['observation']['bookings'][0]}
            await evidence.wrap_tool('book_appointment',booked_handler)({'slot_id':result['observation']['bookings'][0]['slot_id']},None)
            evidence.emit('assistant_message',text="You're all set.")
            completed=deepcopy(result);completed['call_id']=call_id
            return completed
        from evals import external_eval as module
        original=module.atomic_json
        def write(path,value):
            if final_failure and str(path).endswith('.results.json') and value.get('complete'):
                raise OSError('deliberate final report failure')
            return original(path,value)
        with patch.object(AsyncCompletions,'create',new=fake_api),patch.object(module,'BACKEND',Path(temp)),patch.object(module,'PIN',Path('evals/external_pin_v1_1.json')),patch.object(module,'run_one',side_effect=fake_run),patch.object(module,'atomic_json',side_effect=write):
            return await run_batch(catalog,{'heldout':[compiled]},cfg,args)

    async def test_actual_batch_final_export_with_real_state_types(self):
        with TemporaryDirectory() as temp:
            output=await self.exercise_batch(temp)
            report=json.loads(Path(output['report']).read_text())
            self.assertTrue(report['complete']);self.assertEqual(len(report['runs']),2)
            self.assertEqual(len(list(Path(temp).rglob('*.conversation.json'))),2)

    async def test_actual_batch_export_failure_preserves_all_conversation_evidence(self):
        with TemporaryDirectory() as temp:
            with self.assertRaisesRegex(OSError,'deliberate final'):
                await self.exercise_batch(temp,True)
            reportpath=next(Path(temp).rglob('*.results.json'))
            report=json.loads(reportpath.read_text())
            self.assertFalse(report['complete']);self.assertEqual(len(report['runs']),2)
            independent=list(Path(temp).rglob('*.conversation.json'))
            self.assertEqual(len(independent),2)
            self.assertTrue(all(json.loads(p.read_text())['observation']['bookings'] for p in independent))
            events=[json.loads(x) for x in next(Path(temp).rglob('*.events.jsonl')).read_text().splitlines()]
            self.assertEqual(sum(e['event']=='conversation_result' for e in events),2)
            self.assertEqual(events[-1]['event'],'batch_aborted')
            self.assertIn('budget',events[-1])
            self.assertEqual(events[-1]['budget']['by_batch']['heldout']['requests'],2)
            for event in ('patient_message','assistant_message','tool_started','tool_finished','request_reserved','request_usage','request_closed'):
                self.assertEqual(sum(e['event']==event for e in events),2)
            self.assertEqual(len(next(Path(temp).rglob('*.jsonl')).read_text().splitlines())>0,True)
            self.assertEqual(len(next(p for p in Path(temp).rglob('*.jsonl') if not p.name.endswith('.events.jsonl')).read_text().splitlines()),2)


class RequestLedgerTest(unittest.IsolatedAsyncioTestCase):
    async def test_stream_usage_status_caps_and_unknowns_survive_report_error(self):
        from openai.resources.chat.completions import AsyncCompletions
        from openai.types.chat import ChatCompletionChunk
        cfg=json.loads(Path('evals/external_config.json').read_text())
        chunk=ChatCompletionChunk.model_validate({'id':'offline-stream','object':'chat.completion.chunk','created':1,'model':'gpt-4o','choices':[],
            'usage':{'prompt_tokens':100,'completion_tokens':10,'total_tokens':110,'prompt_tokens_details':{'cached_tokens':80}}})
        class Stream:
            response=SimpleNamespace(headers={'x-request-id':'offline-provider-request'})
            def __init__(self, chunks):self.chunks=chunks
            def __aiter__(self):return self.items()
            async def items(self):
                for c in self.chunks:yield c
            async def close(self):pass
        calls=[]
        async def fake(client,**kwargs):calls.append(kwargs);return Stream([chunk] if len(calls)==1 else [])
        with TemporaryDirectory() as temp:
            evidence=EvidenceJournal(Path(temp)/'events.jsonl','offline-request');evidence.context={'attempt_id':'attempt','dataset':'heldout','call_id':'offline'}
            with patch.object(AsyncCompletions,'create',new=fake):
                with DurableBudgets({'heldout':'1','robustness':'.1'},cfg,evidence) as budget:
                    stream=await AsyncCompletions.create(object(),model='gpt-4o',stream=True,messages=[{'role':'user','content':'yes'}])
                    async for _ in stream:pass
                    self.assertEqual(budget.guard.accounted,Decimal('.00025'))
                    stream=await AsyncCompletions.create(object(),model='gpt-4o',stream=True,messages=[])
                    async for _ in stream:pass
                    self.assertEqual(budget.guard.accounted,Decimal('.32537'))
                    budget.use('robustness')
                    with self.assertRaises(RuntimeError):await AsyncCompletions.create(object(),model='gpt-4o',stream=True,messages=[])
                    self.assertEqual(len(calls),2)  # No HTTP call if its reserve cannot fit.
                    with self.assertRaises(TypeError):atomic_json(Path(temp)/'bad-report.json',{'bad':object()})
            rows=[json.loads(x) for x in evidence.path.read_text().splitlines()]
            reserved=[r for r in rows if r['event']=='request_reserved'];self.assertEqual(len(reserved),2)
            self.assertEqual(reserved[0]['messages'],[{'role':'user','content':'yes'}])
            self.assertEqual(reserved[0]['reserve_usd'],'.32512' if reserved[0]['reserve_usd'].startswith('.') else '0.32512')
            usage=next(r for r in rows if r['event']=='request_usage')
            self.assertEqual(usage['usage']['prompt_tokens_details']['cached_tokens'],80)
            closed=[r for r in rows if r['event']=='request_closed']
            self.assertTrue(closed[0]['usage_received']);self.assertFalse(closed[1]['usage_received'])
            self.assertEqual(closed[1]['usage_status'],'unknown')
            self.assertEqual(closed[1]['budget']['by_batch']['heldout']['unreported_requests'],1)
            self.assertTrue(any(r['event']=='request_not_admitted' for r in rows))

    async def test_request_exception_is_journaled_once_without_retry(self):
        from openai.resources.chat.completions import AsyncCompletions
        cfg=json.loads(Path('evals/external_config.json').read_text())
        api=AsyncMock(side_effect=ConnectionError('offline connection failure'))
        with TemporaryDirectory() as temp:
            journal=EvidenceJournal(Path(temp)/'events.jsonl','offline-exception')
            with patch.object(AsyncCompletions,'create',api):
                with DurableBudgets({'heldout':'1'},cfg,journal) as budget:
                    with self.assertRaises(ConnectionError):await AsyncCompletions.create(object(),model='gpt-4o',stream=True,messages=[])
                    self.assertEqual(budget.guard.accounted,Decimal('.32512'))
            self.assertEqual(api.await_count,1)
            rows=[json.loads(x) for x in journal.path.read_text().splitlines()]
            self.assertEqual([r['event'] for r in rows],['request_reserved','request_exception'])
            self.assertIsNone(rows[-1]['usage'])

    async def test_cancelled_stream_keeps_partial_delta_and_full_reserve(self):
        from openai.resources.chat.completions import AsyncCompletions
        from openai.types.chat import ChatCompletionChunk
        cfg=json.loads(Path('evals/external_config.json').read_text())
        chunk=ChatCompletionChunk.model_validate({'id':'partial','object':'chat.completion.chunk','created':1,'model':'gpt-4o',
            'choices':[{'index':0,'delta':{'content':'Partial model text'},'finish_reason':None}]})
        class Stream:
            def __aiter__(self):return self.items()
            async def items(self):
                yield chunk
                raise asyncio.CancelledError()
            async def close(self):pass
        api=AsyncMock(return_value=Stream())
        with TemporaryDirectory() as temp:
            journal=EvidenceJournal(Path(temp)/'events.jsonl','cancel')
            with patch.object(AsyncCompletions,'create',api):
                with DurableBudgets({'heldout':'1'},cfg,journal) as budget:
                    stream=await AsyncCompletions.create(object(),model='gpt-4o',stream=True,messages=[])
                    with self.assertRaises(asyncio.CancelledError):
                        async for _ in stream:pass
                    self.assertEqual(budget.guard.accounted,Decimal('.32512'))
            rows=[json.loads(x) for x in journal.path.read_text().splitlines()]
            self.assertEqual(next(x for x in rows if x['event']=='model_chunk')['chunk']['choices'][0]['delta']['content'],'Partial model text')
            self.assertEqual(rows[-1]['usage_status'],'unknown')
            self.assertEqual(rows[-1]['error_type'],'CancelledError')
            self.assertEqual(api.await_count,1)

    async def test_evidence_failure_before_http_is_fail_closed(self):
        from openai.resources.chat.completions import AsyncCompletions
        cfg=json.loads(Path('evals/external_config.json').read_text());api=AsyncMock()
        with TemporaryDirectory() as temp:
            journal=EvidenceJournal(Path(temp)/'events.jsonl','no-send')
            with patch.object(AsyncCompletions,'create',api),patch.object(journal,'emit',side_effect=EvidenceWriteError('deliberate offline failure')):
                with DurableBudgets({'heldout':'1'},cfg,journal) as budget:
                    with self.assertRaises(EvidenceWriteError):
                        await AsyncCompletions.create(object(),model='gpt-4o',stream=True,messages=[])
                    self.assertTrue(budget.stopped)
            api.assert_not_awaited()


class RestartPlanTest(unittest.TestCase):
    def test_exactly_two_infrastructure_replacements_then_all_unrun_labels(self):
        from evals.external_eval import restart_plan
        planpath=Path('evals/external_restart_v1_2.json').resolve();plan=json.loads(planpath.read_text())
        # Public DEV bodies; existing manifest labels address jobs, never policy.
        dev=load_dev_scenarios()['scenarios'][0];sets={'heldout':[],'robustness':[]};seen=set()
        for row in plan['conversations']:
            key=row['batch'],row['scenario_id']
            if key in seen:continue
            seen.add(key);source=deepcopy(dev);source['id']=row['scenario_id']
            sets[row['batch']].append({'scenario':source})
        jobs=restart_plan(sets,planpath)
        self.assertEqual(len(jobs),40)
        self.assertTrue(all(job[4] for job in jobs[:2]));self.assertTrue(all(not job[4] for job in jobs[2:]))
        self.assertEqual(sum(job[0]=='heldout' for job in jobs),32);self.assertEqual(sum(job[0]=='robustness' for job in jobs),8)
        self.assertTrue(all(job[4]['agent_outcome']=='unknown' for job in jobs[:2]))


class IncompleteUsageTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_cached_usage_is_unknown_not_zero(self):
        from openai.resources.chat.completions import AsyncCompletions
        from openai.types.chat import ChatCompletionChunk
        cfg=json.loads(Path('evals/external_config.json').read_text())
        chunk=ChatCompletionChunk.model_validate({'id':'missing-cache','object':'chat.completion.chunk','created':1,'model':'gpt-4o','choices':[],
            'usage':{'prompt_tokens':100,'completion_tokens':10,'total_tokens':110,'prompt_tokens_details':{'cached_tokens':None}}})
        class Stream:
            def __aiter__(self):return self.items()
            async def items(self):yield chunk
            async def close(self):pass
        with TemporaryDirectory() as temp:
            journal=EvidenceJournal(Path(temp)/'events.jsonl','missing-cache')
            journal.context={'call_id':'missing-cache'}
            with patch.object(AsyncCompletions,'create',AsyncMock(return_value=Stream())):
                with DurableBudgets({'heldout':'1'},cfg,journal) as budget:
                    stream=await AsyncCompletions.create(object(),model='gpt-4o',stream=True,messages=[])
                    async for _ in stream:pass
                    self.assertEqual(budget.guard.accounted,Decimal('.32512'))
            rows=[json.loads(x) for x in journal.path.read_text().splitlines()]
            usage=next(x for x in rows if x['event']=='request_usage')
            self.assertIsNone(usage['usage']['prompt_tokens_details']['cached_tokens'])
            self.assertEqual(rows[-1]['usage_status'],'unknown')
            self.assertEqual(rows[-1]['budget']['by_batch']['heldout']['unreported_requests'],1)

            # A populated legacy row cannot certify complete SDK usage.
            metrics=Path(temp)/'metrics.jsonl'
            metrics.write_text(json.dumps({'call_id':'missing-cache','prompt_tokens':100,'cached_tokens':0,'completion_tokens':10})+'\n')
            report={'runs':[{'call_id':'missing-cache','admitted_requests':1}],'evidence_path':str(journal.path)}
            checkpoint(Path(temp)/'report.json',report,metrics,budget)
            self.assertIsNone(report['runs'][0]['usage'])
            self.assertIsNone(report['runs'][0]['known_usage_subtotal'])
            self.assertFalse(report['runs'][0]['request_coverage']['certified'])
