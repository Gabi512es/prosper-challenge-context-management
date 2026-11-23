"""v2-line parity scenarios, replayed offline through the v4 candidate.

Each scenario is a list of (caller words, scripted acts). Acts may be a
callable of the interpretation envelope, so they can name the presentation,
proposal or question the caller is answering, exactly as the interpreter
would. Sources: docs/results/* (DEV runs, a-l smoke cases),
docs/call-anatomy.md, docs/voice-findings.md and the v2.1 transcripts.
"""
import asyncio
from datetime import datetime

from tests.test_v4_reducer import act, delta
from tests.test_v4_session import FakeInterpreter
from v4.session import Session as RecoverySession
from v4.session import load_engine

NOW = datetime.fromisoformat('2026-11-20T17:00:28+00:00')


def acts(*items):
    return {'acts': list(items)}


def correct(field, value):
    return delta(field, value, 'correct')


def choose(n):
    return lambda e: acts(act('select_option', presentation_id=e['context']['presentations'][-1]['id'],
                              selector={'by': 'ordinal', 'ordinal': n}))


def yes(e):
    return acts(act('affirm', target={'type': 'proposal', 'id': e['context']['proposal']['id']}))


def answer(kind):
    return lambda e: acts(act(kind, target={'type': 'question', 'id': e['context']['question']['id']}))


def repeat(e):
    return acts(act('repeat_request', message_id=e['context']['last_message']['id'], part='all'))


def info(entity, name, attribute):
    return act('information_question', entity=entity, name=name, reference_id=None, attribute=attribute)


IDENTITY = acts(delta('name', 'Alex Morgan'), delta('date_of_birth', {'year': 1990, 'month': 4, 'day': 12}))
OPENING = acts(delta('service', 'annual physical'), delta('provider', 'Dr. Maria Garcia'),
               delta('provider_specialty', 'Family Medicine'), delta('new_patient', True))
TO_SLOTS = [('annual physical with Maria Garcia, Family Medicine. New patient.', OPENING),
            ('Midtown, please.', choose(2)), ('Alex Morgan, April 12, 1990.', IDENTITY), ('Yes.', yes)]
TO_READBACK = TO_SLOTS + [('The first one, please.', choose(1))]
BOOKED = TO_READBACK + [('Yes, please.', yes)]


async def run(steps, log_dir, sessions, *, engine=None, prepare=None):
    """Returns the greeting and each caller turn's reply text."""
    engine = engine or load_engine(now=NOW)[0]
    fake = FakeInterpreter([raw for _, raw in steps])
    s = RecoverySession(engine, fake, run_id=f'parity-{len(sessions)}', log_dir=log_dir)
    sessions.append(s)
    greeting = await s.start()
    s.delivery(greeting.attempt_id, 'completed')
    replies = [greeting.text]
    for index, (words, _) in enumerate(steps):
        if prepare:
            prepare(index, s)
        reply = await asyncio.wait_for(s.receive(f'caller-{index}', words), 2)
        if reply is None:
            replies.append(None)
            continue
        s.delivery(reply.attempt_id, 'completed')
        replies.append(reply.text)
    return s, replies
