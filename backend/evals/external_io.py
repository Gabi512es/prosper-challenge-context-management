"""Evaluation infrastructure only: explicit JSON, durable evidence and request receipts."""
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from time import perf_counter

from .external_budget import FinalSpendGuard

INFRA_VERSION = 'external-infra-v1.2'


class EvidenceWriteError(RuntimeError):
    """A durable evidence write failed; no further paid requests are allowed."""


def json_value(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Report datetime must include an explicit timezone')
        return value.isoformat()  # Keep the original offset, do not assume/convert it.
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f'Unsupported report type: {type(value).__module__}.{type(value).__qualname__}')


def json_text(value, **kwargs):
    return json.dumps(value, default=json_value, ensure_ascii=False, allow_nan=False, **kwargs)


def atomic_json(path, value):
    """Serialize before touching the old report; fsync and atomically replace it."""
    body = (json_text(value, indent=2) + '\n').encode()
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


class EvidenceJournal:
    """Append+fsync every event; this file never depends on aggregate export."""
    def __init__(self, path, run_id):
        self.path = Path(path); self.run_id = run_id; self.context = {}; self.sequence = 0; self.failed = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)  # Never mix a restart with an earlier journal.

    def emit(self, event, **values):
        if self.failed: raise EvidenceWriteError("Evidence journal is unhealthy; refusing to continue")
        try:
            row = {'sequence': self.sequence+1, 'timestamp': datetime.now(timezone.utc).isoformat(),
                   'infrastructure_version': INFRA_VERSION, 'run_id': self.run_id,
                   **self.context, 'event': event, **values}
            body = (json_text(row, separators=(',', ':'))+'\n').encode()
            fd = os.open(self.path, os.O_APPEND | os.O_WRONLY)
            try:
                view = memoryview(body)
                while view:
                    size = os.write(fd, view)
                    if size <= 0: raise OSError('Short evidence write')
                    view = view[size:]
                os.fsync(fd)
            finally: os.close(fd)
            self.sequence += 1
        except (TypeError, ValueError, OSError) as error:
            self.failed = True
            raise EvidenceWriteError(f'Evidence event {event} could not be persisted ({type(error).__name__})') from error

    def wrap_tool(self, name, handler):
        # Same direct wrapper pattern as voice_support.tool_trace_wrapper;
        # use strict JSON and save the start BEFORE invoking the unchanged handler.
        async def traced(args, manager):
            tool_event_id = f'{self.context["attempt_id"]}:tool:{self.sequence+1}'
            self.emit('tool_started', tool_event_id=tool_event_id, tool=name, arguments=args)
            start = perf_counter()
            try:
                result = await handler(args, manager)
            except BaseException as error:
                self.emit('tool_exception', tool_event_id=tool_event_id, tool=name,
                          error_type=type(error).__name__, latency_ms=(perf_counter()-start)*1000)
                raise
            payload = result[0] if isinstance(result, tuple) else result
            self.emit('tool_finished', tool_event_id=tool_event_id, tool=name, arguments=args,
                      result=payload, latency_ms=(perf_counter()-start)*1000)
            return result  # No argument/result mutation or added agent message.
        return traced


class DurableBudgets:
    """Reuse the frozen budget arithmetic, add a write-ahead request ledger.

    One SDK hook routes to independent caps. No retries, no cost prediction.
    """
    def __init__(self, limits, config, evidence):
        self.guards = {k: FinalSpendGuard(v, config) for k,v in limits.items()}
        self.evidence = evidence; self.active = next(iter(self.guards))

    def use(self, kind):
        if kind not in self.guards: raise ValueError('No budget for dataset')
        self.active = kind

    @property
    def guard(self): return self.guards[self.active]
    @property
    def stopped(self): return any(g.stopped for g in self.guards.values())
    @stopped.setter
    def stopped(self, value): self.guard.stopped = value
    @property
    def stop_reason(self): return self.guard.stop_reason
    @stop_reason.setter
    def stop_reason(self, value): self.guard.stop_reason = value
    @property
    def accounted(self): return self.guard.accounted
    @property
    def ceiling(self): return self.guard.ceiling
    @property
    def limit(self): return self.guard.limit
    @property
    def requests(self): return sum(g.requests for g in self.guards.values())

    def summary(self):
        return {'by_batch': {k:g.summary() for k,g in self.guards.items()},
                'requests': self.requests, 'stopped': self.stopped}

    def __enter__(self):
        from openai.resources.chat.completions import AsyncCompletions
        self.original = AsyncCompletions.create; owner = self
        async def guarded(client, *args, **kwargs):
            if kwargs.get('model') != 'gpt-4o' or not kwargs.get('stream'):
                raise ValueError('Spend guard supports streaming gpt-4o only')
            kwargs.pop('max_tokens', None); kwargs['max_completion_tokens'] = 512
            guard = owner.guard; dataset = owner.active
            if owner.stopped: raise RuntimeError('Batch already stopped')
            request_id = f'{owner.evidence.run_id}:{dataset}:{guard.requests+1}'
            request_context = dict(owner.evidence.context)
            def record(event, **values):
                owner.evidence.emit(event, **request_context, **values)
            try:
                reserve = guard.reserve()
            except RuntimeError:
                record('request_not_admitted', request_id=request_id, budget=owner.summary())
                raise
            # Durable reservation and actual messages BEFORE the HTTP request.
            try:
                record('request_reserved', request_id=request_id, budget_dataset=dataset,
                    reserve_usd=str(reserve), model=kwargs['model'], max_completion_tokens=512,
                    messages=kwargs.get('messages', []), budget=owner.summary())
            except EvidenceWriteError:
                guard.stopped = True; guard.stop_reason = 'Write-ahead evidence failed; HTTP not sent'
                raise
            try:
                stream = await owner.original(client, *args, **kwargs)
            except BaseException as error:
                guard.account_unknown(reserve)
                record('request_exception', request_id=request_id, error_type=type(error).__name__,
                    provider_status=getattr(error,'status_code',None), usage=None, budget=owner.summary())
                raise

            async def watched():
                settled = False; complete_usage = False; failed = None
                try:
                    headers = getattr(getattr(stream, 'response', None), 'headers', {})
                    record('request_opened', request_id=request_id, provider_request_id=headers.get('x-request-id'))
                    async for chunk in stream:
                        # Explicit SDK model serialization: raw model text/tool deltas,
                        # distinct from the actual code-generated assistant message.
                        record('model_chunk', request_id=request_id, chunk=chunk.model_dump(mode='json'))
                        if chunk.usage and not settled:
                            previous_known = len(guard.observed)
                            guard.settle(reserve, chunk.usage); settled = True
                            complete_usage = len(guard.observed) == previous_known + 1
                            record('request_usage', request_id=request_id,
                                usage=chunk.usage.model_dump(mode='json'),
                                usage_status='reported' if complete_usage else 'unknown', budget=owner.summary())
                        yield chunk
                except BaseException as error:
                    failed = type(error).__name__
                    if isinstance(error, EvidenceWriteError):
                        guard.stopped = True; guard.stop_reason = 'Evidence failure; no further HTTP requests'
                    raise
                finally:
                    if not settled: guard.account_unknown(reserve)
                    try:
                        await stream.close()
                    finally:
                        record('request_closed', request_id=request_id, usage_received=settled,
                            error_type=failed, usage_status='reported' if complete_usage else 'unknown', budget=owner.summary())
            return watched()
        AsyncCompletions.create = guarded
        return self

    def __exit__(self, *args):
        from openai.resources.chat.completions import AsyncCompletions
        AsyncCompletions.create = self.original
