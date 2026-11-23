"""Sequential v4 interpretation, one composer, and attempt-bound delivery.

No Pipecat/Flows planner, transcript parser, second model or tool inference.
Voice and text vary only in how a Reply is delivered and acknowledged.
"""
import asyncio
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from code_identity import CODE_REVISION, GIT_COMMIT
from evals.external_io import EvidenceJournal
from metrics_logging import TurnMetricsObserver
from .acts import ActError
from .catalog import CatalogMatcher
from .composer import Composer
from .interpreter import MODEL, SCHEMA_SHA, INSTRUCTIONS_SHA
from .reducer import SchedulingReducer, CLINIC_ZONE, ENTITY

VERSION = 'v4-m2-worker-v1'
SAY_AGAIN = "Sorry, I didn't catch that, could you say it again?"
RETRY_BACKOFF_S = 0.5  # One retry of a transient model error, after this pause.
MAX_FAILED_TURNS = 2  # Consecutive turns the model could not interpret before the call ends.
# Errors no retry can fix: the call ends at once with the handoff message.
FATAL_MODEL_CODES = {'credit_balance_exhausted', 'insufficient_quota', 'billing_hard_limit_reached',
                     'invalid_api_key', 'account_deactivated'}


class ModelUnavailable(Exception):
    """A turn the model could not interpret, after its retry (or at once when fatal)."""
    def __init__(self, fatal):
        super().__init__('fatal' if fatal else 'transient')
        self.fatal = fatal


def is_fatal_model_error(error):
    """Authentication, permission and credit errors: retrying cannot help."""
    if getattr(error, 'code', None) in FATAL_MODEL_CODES:
        return True
    from openai import AuthenticationError, PermissionDeniedError
    return isinstance(error, (AuthenticationError, PermissionDeniedError))
AGENT_VERSION = 'v4-recovery-candidate-v1.10'
BACKEND = Path(__file__).resolve().parents[1]


class AuditedEngine:
    """Trace actual core calls; all policy/search/booking implementation is reused."""
    METHODS = {'resolve_options', 'get_details', 'find_slots', 'select_slot',
               'confirm_selected_slot', 'book_appointment'}

    def __init__(self, engine, record):
        object.__setattr__(self, '_engine', engine)
        object.__setattr__(self, '_record', record)

    def __setattr__(self, name, value):
        setattr(self._engine, name, value)

    def __getattr__(self, name):
        value = getattr(self._engine, name)
        if name not in self.METHODS:
            return value
        def call(*args, **kwargs):
            from inspect import signature
            arguments = dict(signature(value).bind(*args, **kwargs).arguments)
            self._record('tool_started', tool=name, arguments=arguments)
            start = perf_counter()
            try:
                result = value(*args, **kwargs)
            except Exception as error:
                self._record('tool_failed', tool=name, arguments=arguments, error_type=type(error).__name__,
                             code=getattr(error, 'code', None), latency_ms=(perf_counter()-start)*1000)
                raise
            self._record('tool_finished', tool=name, arguments=arguments, result=result,
                         latency_ms=(perf_counter()-start)*1000)
            return result
        return call


@dataclass(frozen=True)
class Reply:
    attempt_id: str
    message_id: str
    text: str
    proposal_ids: tuple[str, ...] = ()
    presentation_ids: tuple[str, ...] = ()
    question_id: str | None = None


def agent_metadata(interpreter):
    """The agent version and the hashes of the instructions and schema actually sent."""
    instructions = getattr(interpreter, 'instructions', None)
    schema = getattr(interpreter, 'schema', None)
    return dict(candidate_version=AGENT_VERSION,
                effective_instructions_sha256=sha256(instructions.encode()).hexdigest() if instructions else None,
                effective_schema_sha256=sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest() if schema else None)


class Session:
    """One long-lived sequential worker. Arrival is synchronous; inference isn't."""
    respond_immediately = False
    tool_followup_inference = False

    def __init__(self, engine, interpreter, *, run_id=None, log_dir=None, metadata=None, emit=None, agent=None):
        """agent: the v4 agent file's settings (wording, revision); None keeps the code defaults."""
        if not isinstance(engine.catalog, CatalogMatcher):
            engine.catalog = CatalogMatcher(engine.catalog)
        metadata = dict(metadata or {}, **agent_metadata(interpreter), **(agent.metadata() if agent else {}))
        self.run_id = run_id or 'v4-'+str(uuid4())
        if not self.run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in self.run_id):
            raise ValueError('Invalid run_id')
        log_dir = Path(log_dir or BACKEND/'logs/evals')
        self.metadata = dict(metadata or {}, git_commit=GIT_COMMIT, code_revision=CODE_REVISION,
                             code_version=VERSION, model=MODEL, schema_sha256=SCHEMA_SHA,
                             instructions_sha256=INSTRUCTIONS_SHA)
        self.journal = EvidenceJournal(log_dir/(self.run_id+'.events.jsonl'),self.run_id)
        self.journal.context = dict(self.metadata, call_id=self.run_id)
        self.metrics = TurnMetricsObserver(call_id=self.run_id,run_id=self.run_id,node_name=lambda:'scheduling',
            default_model=MODEL,output_path=log_dir/(self.run_id+'.jsonl'),session_metadata=self.metadata)
        self.current_event = None
        self.r = SchedulingReducer(AuditedEngine(engine,self.record))
        self.composer = Composer(self.r, **({} if agent is None else dict(
            greeting=agent.greeting, handoff_lead=agent.handoff_lead, emergency_lead=agent.emergency_lead)))
        self.interpreter = interpreter
        self.emit = emit
        self.queue = deque();self.events = {};self.wake = asyncio.Event()
        self.worker = None;self.closed = False;self.failed = False
        self.endpoint_closed = True;self.speaking = False
        self.input_epoch = 0
        self.attempts = {};self.replies = [];self.prior_acts = []
        self.pending_results = [];self.pending_events = []
        self.model_calls = 0
        self.last_message = None
        self.limit_reached = False
        self.failed_turns = 0  # Consecutive turns lost to model errors.
        self.end_reason = None  # Set when the call must end (model unavailable).
        self.ended = False
        self.transcript = []  # (role, text, caller event ID) in call order: recent_turns for v1.11.
        # Finals received while the caller's turn is open are joined and interpreted once when
        # it ends. Off only to replay recordings whose acts were recorded per final.
        self.merge_held_finals = True
        self.on_end = None  # Voice: hangs up after the final message is spoken.
        self.retry_backoff_s = RETRY_BACKOFF_S
        self.record('session_started', respond_immediately=False, tool_followup_inference=False, planner='disabled')

    def record(self, event, **values):
        self.journal.emit(event, caller_event_id=self.current_event, **values)

    def receive(self, event_id, text):
        if event_id in self.events:
            old,future = self.events[event_id]
            if old != text:
                self.r._revoke_booking('duplicate_event_conflict')
                self.failed=True
                self.wake.set()
                raise ValueError('Caller event ID reused with different text')
            return future
        if (self.limit_reached or self.ended) and not self.closed:
            # The limit or the end was already announced once: later finals get no reply.
            self.journal.emit('caller_after_request_limit',caller_event_id=event_id,text=text)
            future = asyncio.get_running_loop().create_future()
            future.set_result(None)
            self.events[event_id] = text,future
            return future
        if self.closed or self.failed:
            raise RuntimeError('Session stopped')
        if not isinstance(text,str) or not text.strip():
            raise ValueError('Caller final must not be empty')
        future = asyncio.get_running_loop().create_future()
        self.r.receive(event_id)
        self.input_epoch += 1
        self.events[event_id] = text,future
        self.transcript.append(('caller',text,event_id))
        self.queue.append((event_id,text));self.wake.set()
        self.journal.emit('caller_received',caller_event_id=event_id,text=text)
        if self.worker is None:
            self.worker = asyncio.create_task(self._run(),name='v4-sequential-'+self.run_id)
        return future

    def endpoint(self, closed):
        self.endpoint_closed = bool(closed)
        self.record('speech_endpoint',closed=self.endpoint_closed)
        self.wake.set()

    def interrupt(self):
        for attempt_id,status in list(self.attempts.items()):
            if status == 'pending':
                self.delivery(attempt_id,'interrupted')

    def delivery(self, attempt_id, status):
        if self.attempts.get(attempt_id) != 'pending':
            self.record('delivery_ignored',attempt_id=attempt_id,status=status)
            return False
        reply = next(reply for reply in self.replies if reply.attempt_id==attempt_id)
        if status not in {'completed','interrupted'}:
            raise ValueError('Delivery must be completed or interrupted')
        self.attempts[attempt_id] = status
        self.record('delivery',attempt_id=attempt_id,message_id=reply.message_id,status=status,
                    proposal_ids=reply.proposal_ids)
        if status=='interrupted':
            for pid in reply.proposal_ids:
                self.r.interrupt_proposal(pid)
        else:
            for pid in reply.proposal_ids:
                try:self.r.deliver_proposal(pid)
                except ActError:pass  # Late completion of retired state is not delivery.
            for pid in reply.presentation_ids:
                try:self.r.deliver_presentation(pid)
                except ActError:pass
            if reply.question_id and self.r.question and self.r.question.id==reply.question_id:
                self.r.deliver_question(reply.question_id)
            if self.last_message and self.last_message['id']==reply.message_id:
                self.last_message['delivered'] = True
        self.speaking = any(status=='pending' for status in self.attempts.values())
        self.wake.set()
        if self.replies[-1].attempt_id == attempt_id:
            # A question cut off by the caller is asked again once, in full.
            self.composer.interrupted_text = reply.text if status == 'interrupted' and reply.text.endswith('?') else None
        return True

    def context(self, event_id):
        r = self.r;s = r.engine.state;arrival = r.pending_inputs[event_id]
        known = {entity:r.engine.catalog.summary(kind,getattr(s,field)) if getattr(s,field) else None
                 for entity,(kind,field) in ENTITY.items()}
        known.update(provider_specialty=r.requested_specialty,appointment_date=r.appointment_date.isoformat() if r.appointment_date else None,
            identity=dict(name=r.identity()[0],date_of_birth=r.identity()[1],partial_date_of_birth=r.partial_dob,
                          confirmed=r.identity_confirmed==r.identity() and all(r.identity())),
            new_patient=s.patient_facts.is_new_patient,referral=s.patient_facts.referral_on_file,
            any_provider=s.any_provider,any_location=s.any_location)
        presentations = []
        for p in r.presentations.values():
            if p.generation != r.generation:continue
            options = []
            for i,ident in enumerate(p.option_ids):
                item = r.engine._present_slot(r.engine._slots[ident]) if p.entity=='slot' else r.engine.catalog.summary(ENTITY[p.entity][0],ident)
                options.append(dict(item,option_id=ident,ordinal=i+1))
            presentations.append(dict(id=p.id,entity=p.entity,delivered=p.id in arrival.presentations,options=options))
        proposal = next((p for p in reversed(list(r.proposals.values()))
                         if p.status in {'open','accepted'} and r._current_proposal(p)),None)
        question = r.question
        context = dict(clock=dict(clinic_today=r.engine.now.astimezone(CLINIC_ZONE).date().isoformat(),clinic_timezone=str(CLINIC_ZONE)),
            known=known,control=r.control,
            question=dict(id=question.id,kind=question.kind,expected=[question.field or question.kind],
                          delivered=question.id in arrival.questions) if question else None,
            presentations=presentations,last_message=deepcopy(self.last_message),
            proposal=dict(id=proposal.id,kind=proposal.kind,slot_id=proposal.slot_id,
                          delivered_before_reply=proposal.id in arrival.proposals) if proposal else None,
            prior_acts=self.prior_acts)
        if getattr(self.interpreter,'recent_turns',False):
            # v1.11: the last two exchanges before this caller text, short, for reference.
            upto=next((i for i,(_,_,key) in enumerate(self.transcript) if key==event_id),len(self.transcript))
            context['recent_turns']=[dict(role=role,text=text[:200]) for role,text,_ in self.transcript[:upto][-4:]]
        self._add_partial_identity(context['known']['identity'])
        context['unresolved_requests'] = {field: r.fields[field] for field, (_, state_field) in ENTITY.items()
                                          if not getattr(s, state_field) and isinstance(r.fields.get(field), str)}
        return context

    def _add_partial_identity(self, identity):
        """The name and date-of-birth parts still missing, for one-word or split answers."""
        partial = self.r.partial_name()
        identity['partial_name'] = partial
        identity['missing_name_parts'] = ['last name'] if partial else []
        identity['missing_date_of_birth_parts'] = [part for part in ('year', 'month', 'day')
                                                   if self.r.partial_dob and part not in self.r.partial_dob]

    async def _reply(self, parts):
        text,proposals,presentations,question = parts
        if not text.strip():
            return None
        if self.speaking:self.interrupt()
        message_id = self.r.proposals[proposals[0]].message_id if proposals else self.r._id('message')
        reply = Reply(str(uuid4()),message_id,text,proposals,presentations,question)
        self.replies.append(reply);self.attempts[reply.attempt_id]='pending';self.speaking=True
        self.last_message = dict(id=message_id,text=text,delivered=False)
        self.transcript.append(('agent',text,None))
        self.composer.message_text[message_id] = text
        self.record('reply',reply=asdict(reply))
        if self.emit:await self.emit(reply)
        self._remember_reply(reply)
        return reply

    def _remember_reply(self, reply):
        """What a later repeat request for this reply's message replays."""
        texts, messages = self.composer.message_text, self.r.messages
        if reply.message_id not in messages:
            # The interpreter sees last_message.id; a repeat request names it.
            messages[reply.message_id] = (('presentation', reply.presentation_ids[0])
                                          if reply.presentation_ids else ('message', reply.message_id))
            if reply.presentation_ids and texts.get(reply.presentation_ids[0]):
                # Repeating this message replays its choice, not its side answers.
                texts[reply.message_id] = texts[reply.presentation_ids[0]]
        composed, canonical = self.composer.last_canonical or (None, None)
        if composed == reply.text and canonical != reply.text and texts.get(reply.message_id) == reply.text:
            texts[reply.message_id] = canonical  # Without its "To repeat:" lead.
        if 'Take your time' in reply.text and len(self.replies) > 1:
            # "Can you repeat that?" after a pause replays the question it holds.
            held = self.replies[-2]
            if texts.get(held.message_id) and held.message_id in messages:
                texts[reply.message_id] = texts[held.message_id]
                messages[reply.message_id] = messages[held.message_id]
        if reply.proposal_ids and reply.proposal_ids[0] in self.composer.readbacks:
            # "Shall I book it?" re-asks a read-back; repeating it replays the full read-back.
            texts[reply.message_id] = self.composer.readbacks[reply.proposal_ids[0]]

    async def start(self):
        return await self._reply(self.composer._question(self.composer.greeting,'service','service'))

    async def _run(self):
        try:
            while not self.closed:
                await self.wake.wait();self.wake.clear()
                if self.failed:raise RuntimeError('Session input integrity failure')
                while self.queue:
                    if self.merge_held_finals and not self.endpoint_closed:
                        break  # The caller is still speaking: hold the finals until the turn ends.
                    event_id,text = self.queue.popleft();self.current_event=event_id
                    if self.merge_held_finals and self.queue:
                        # One turn of several finals ("um, Monday" / "the thirtieth" / "at nine
                        # forty") is one utterance: interpreted once, answered once.
                        merged=[]
                        while self.queue:
                            later,later_text=self.queue.popleft()
                            self.r.pending_inputs.pop(later,None)
                            merged.append(later);text=text+' '+later_text
                        self.pending_events.extend(merged)
                        self.record('finals_merged',event_ids=[event_id,*merged],text=text)
                    envelope=dict(turn_id=event_id,state_version=self.r.state_version,caller_text=text,context=self.context(event_id))
                    self.record('interpretation_input',envelope=envelope)
                    try:
                        interpretation = await self._interpret(envelope)
                    except ModelUnavailable as error:
                        if self._lose_turn(event_id, error):
                            break
                        continue
                    self.failed_turns = 0
                    if self.failed:raise RuntimeError('Session input integrity failure')
                    self.record('raw_acts',raw=interpretation.raw)
                    before=asdict(self.r.engine.state)
                    result=self.r.reduce(event_id,text,interpretation.raw,state_version=envelope['state_version'])
                    self.prior_acts=interpretation.raw['acts']
                    self.record('reduced',before=before,after=asdict(self.r.engine.state),result=asdict(result),
                                control=self.r.control,proposals=[asdict(p) for p in self.r.proposals.values()])
                    self.pending_results.append(result);self.pending_events.append(event_id)
                # Let already-received event callbacks run before testing the write gate.
                await asyncio.sleep(0)
                if self.queue and (self.endpoint_closed or not self.merge_held_finals):
                    self.wake.set();continue
                if not self.endpoint_closed or not self.pending_events:
                    continue
                if self.end_reason or not self.pending_results:
                    await self._reply_without_interpretation()
                    continue
                booking=None
                accepted=next((p for p in reversed(list(self.r.proposals.values())) if p.kind=='booking' and p.status=='accepted'),None)
                # No await between this dispatch check and the engine's synchronous write.
                if accepted and not self.speaking and not self.queue and not self.r.pending_inputs and self.endpoint_closed:
                    self.record('write_dispatch',proposal_id=accepted.id,queue_empty=True,endpoint_closed=True)
                    booking=self.r.commit_booking(accepted.id,endpoint_closed=True)
                    self.record('booking_result',proposal_id=accepted.id,result=booking)
                self.composer.last_info_answered=False
                reply=await self._reply(self.composer.compose(self.pending_results,booking=booking))
                for event_id in self.pending_events:
                    future=self.events[event_id][1]
                    if not future.done():future.set_result(reply)
                self.pending_results=[];self.pending_events=[]
                if self.composer.end_call and not self.ended:
                    # The loop breaker's final message, or the short emergency line: end the call.
                    self.ended=True
                    reason=self.composer.end_reason or 'loop_breaker'
                    if reason=='loop_breaker':
                        self.record('loop_breaker',stalled_turns=self.composer.stalled,
                                    question=self.r.question.kind if self.r.question else None)
                    self.record('call_ended',reason=reason)
                    if self.on_end:await self.on_end()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failed=True;self.r._revoke_booking('session_failure')
            reply=None
            # request_not_sent: the interpreter refused a request over its limit.
            self.limit_reached=getattr(error,'code',None)=='request_not_sent'
            try:
                if self.limit_reached:
                    self.record('request_limit_reached',request_limit=getattr(self.interpreter,'request_limit',None))
                    reply=await self._reply((self.composer.limit_text(),(),(),None))
                else:
                    self.record('session_failed',error_type=type(error).__name__)
                    await self._reply(('I am having a technical problem and cannot complete this request.'+self.composer.contact(),(),(),None))
            finally:
                for _,future in self.events.values():
                    if future.done():continue
                    if self.limit_reached:future.set_result(reply)
                    else:future.set_exception(RuntimeError('v4 session infrastructure failure'))

    async def _interpret(self, envelope):
        """One interpretation. A transient model error is retried once after a short
        pause; an authentication or credit error is not retried. Raises
        ModelUnavailable when the turn cannot be interpreted."""
        for attempt in (1, 2):
            start = perf_counter(); self.model_calls += 1
            try:
                interpretation = await self.interpreter.interpret(envelope, self.record)
            except Exception as error:
                code = getattr(error, 'code', None)
                self.record('interpretation_failed', error_type=type(error).__name__, code=code, attempt=attempt)
                if code == 'request_not_sent':
                    self.model_calls -= 1
                    raise  # The interpreter's request limit: announced by the limit path.
                self._metrics(getattr(error, 'receipt', None), (perf_counter() - start) * 1000)
                fatal = is_fatal_model_error(error)
                if fatal or attempt == 2:
                    raise ModelUnavailable(fatal) from error
                self.record('model_retry', backoff_s=self.retry_backoff_s)
                await asyncio.sleep(self.retry_backoff_s)
                continue
            self._metrics(interpretation, interpretation.latency_ms or (perf_counter() - start) * 1000)
            return interpretation

    def _lose_turn(self, event_id, error):
        """The turn changes nothing: it leaves the reducer's queue unapplied and is
        answered without interpretation. True when the call must end."""
        self.r.pending_inputs.pop(event_id, None)
        self.pending_events.append(event_id)
        self.failed_turns += 1
        reason = ('model_fatal_error' if error.fatal
                  else 'model_failed_turns' if self.failed_turns >= MAX_FAILED_TURNS else None)
        self.record('turn_not_interpreted', fatal=error.fatal, failed_turns=self.failed_turns, ends_call=bool(reason))
        if reason:
            self.end_reason = reason
            while self.queue:  # Later finals in the same batch get the same goodbye.
                later, _ = self.queue.popleft()
                self.r.pending_inputs.pop(later, None)
                self.pending_events.append(later)
        return bool(reason)

    async def _reply_without_interpretation(self):
        """Answers turns the model could not interpret: ask again, or end the call."""
        if self.end_reason:
            reply = await self._reply((self.composer.handoff_text(), (), (), None))
        else:
            reply = await self._reply((SAY_AGAIN, (), (), self.r.question.id if self.r.question else None))
        for event_id in self.pending_events:
            future = self.events[event_id][1]
            if not future.done():
                future.set_result(reply)
        self.pending_results = []; self.pending_events = []
        if self.end_reason and not self.ended:
            self.ended = True
            self.record('call_ended', reason=self.end_reason)
            if self.on_end:
                await self.on_end()

    def _metrics(self, result, latency):
        self.metrics._append_jsonl(dict(timestamp=datetime.now().astimezone().isoformat(),
            run_id=self.run_id,call_id=self.run_id,**self.metadata,turn=self.model_calls,
            patient_turn=self.model_calls,caller_event_id=self.current_event,trigger='patient',node='scheduling',
            prompt_tokens=result.prompt_tokens if result else None,cached_tokens=result.cached_tokens if result else None,
            completion_tokens=result.completion_tokens if result else None,latency_ms=latency,ttfb_ms=None,
            usage_status='reported' if result and result.prompt_tokens is not None else 'unavailable'))

    async def close(self):
        self.closed=True
        if self.worker:
            self.worker.cancel()
            try:await self.worker
            except asyncio.CancelledError:pass
        for _,future in self.events.values():
            if not future.done():future.cancel()
        close=getattr(self.interpreter,'close',None)
        if close:await close()


def load_engine(*, now=None):
    """Demo availability only. Frozen builders/agents are not instantiated."""
    from datetime import timezone
    from scheduling import SchedulingEngine,load_catalog
    from scheduling.demo import generate_demo_availability
    catalog=load_catalog(BACKEND/'data/catalog.json');now=now or datetime.now(timezone.utc)
    engine=SchedulingEngine(catalog,generate_demo_availability(catalog,now),now=now)
    raw=(BACKEND/'reference/catalog_scheduler.json').read_bytes()
    return engine,dict(agent_id='v4-reduced',agent_revision=sha256((SCHEMA_SHA+INSTRUCTIONS_SHA).encode()).hexdigest(),
        voice_config_revision=sha256(raw).hexdigest(),
        availability_mode='demo_generated',catalog_sha256=sha256((BACKEND/'data/catalog.json').read_bytes()).hexdigest())
