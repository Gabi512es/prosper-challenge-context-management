"""Model errors never leave a call mute: a transient error is retried once; a
turn still lost is asked again with state unchanged; two lost turns in a row, or
an authentication or credit error, end the call with the handoff message and a
hang-up. Offline: a fake OpenAI client raising the SDK's own error types."""
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import httpx
import openai

from tests.v4_parity import NOW
from v4.composer import NO_TRANSFER
from v4.interpreter import MODEL, OpenAIInterpreter
from v4.session import SAY_AGAIN, load_engine
from v4_text import V4TextSession
import v4_bot

REQUEST = httpx.Request('POST', 'https://api.openai.com/v1/chat/completions')


def status_error(kind, status, code=None):
    body = {'message': 'test', 'code': code} if code else None
    return kind('test', response=httpx.Response(status, request=REQUEST), body=body)


TRANSIENT = lambda: status_error(openai.InternalServerError, 500)
CREDIT = lambda: status_error(openai.RateLimitError, 429, 'credit_balance_exhausted')
AUTH = lambda: status_error(openai.AuthenticationError, 401, 'invalid_api_key')
FLU_SHOT = {'acts': [{'kind': 'set_field', 'delta': {'field': 'service', 'value': 'flu shot'}, 'quote': 'flu shot'}]}


def completion(acts):
    content = json.dumps(acts)
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=10,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=0))
    choice = SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=content, refusal=None))
    return SimpleNamespace(model=MODEL, usage=usage, choices=[choice],
                           model_dump=lambda mode=None: {'model': MODEL, 'content': content})


class FakeClient:
    """chat.completions.create returns or raises the scripted outcomes in order."""
    def __init__(self, script):
        self.script, self.calls = list(script), 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **params):
        self.calls += 1
        outcome = self.script.pop(0)()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def close(self):
        pass


class ModelErrorTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.texts = []

    async def asyncTearDown(self):
        for text in self.texts:
            await text.close()
        self.temp.cleanup()

    async def call(self, script):
        client = FakeClient(script)
        text = V4TextSession(engine=load_engine(now=NOW)[0], interpreter=OpenAIInterpreter(client),
                             run_id=f'errors-{len(self.texts)}', log_dir=self.temp.name)
        text.session.retry_backoff_s = 0
        text.session.on_end = AsyncMock()
        self.texts.append(text)
        await text.start()
        return text, client

    def events(self, text, name):
        rows = (Path(self.temp.name) / f'{text.session.run_id}.events.jsonl').read_text().splitlines()
        return [row for row in map(json.loads, rows) if row['event'] == name]

    async def test_one_transient_error_then_success(self):
        text, client = await self.call([TRANSIENT, lambda: completion(FLU_SHOT)])
        reply = await text.send('I need a flu shot.')
        self.assertNotEqual(reply.text, SAY_AGAIN)
        self.assertEqual(client.calls, 2)
        self.assertEqual(text.session.r.engine._appointment_type().name, 'Flu Shot')
        self.assertEqual(len(self.events(text, 'model_retry')), 1)
        self.assertFalse(text.session.ended)

    async def test_a_lost_turn_is_asked_again_with_state_unchanged(self):
        text, client = await self.call([TRANSIENT, TRANSIENT, lambda: completion(FLU_SHOT)])
        before, version = asdict(text.session.r.engine.state), text.session.r.state_version
        reply = await text.send('I need a flu shot.')
        self.assertEqual(reply.text, SAY_AGAIN)
        self.assertEqual(asdict(text.session.r.engine.state), before)
        self.assertEqual(text.session.r.state_version, version)
        self.assertFalse(text.session.r.pending_inputs)
        # The session stays alive: the next turn is interpreted normally.
        reply = await text.send('A flu shot, please.')
        self.assertEqual(text.session.r.engine._appointment_type().name, 'Flu Shot')
        self.assertFalse(text.session.ended)
        self.assertEqual(text.session.failed_turns, 0)

    async def test_two_lost_turns_in_a_row_end_the_call(self):
        text, client = await self.call([TRANSIENT] * 4)
        self.assertEqual((await text.send('I need a flu shot.')).text, SAY_AGAIN)
        goodbye = await text.send('Hello? A flu shot.')
        self.assertIn(NO_TRANSFER, goodbye.text)
        self.assertTrue(text.session.ended)
        text.session.on_end.assert_awaited_once()
        self.assertIsNone(await text.send('Are you there?'))  # No reply after the end.
        self.assertEqual(client.calls, 4)
        self.assertEqual(self.events(text, 'call_ended')[0]['reason'], 'model_failed_turns')

    async def test_credit_and_authentication_errors_end_at_once_without_retry(self):
        for error, code in ((CREDIT, 'credit_balance_exhausted'), (AUTH, 'invalid_api_key')):
            with self.subTest(code=code):
                text, client = await self.call([error])
                goodbye = await text.send('I need a flu shot.')
                self.assertIn(NO_TRANSFER, goodbye.text)
                self.assertEqual(client.calls, 1)
                self.assertTrue(text.session.ended)
                text.session.on_end.assert_awaited_once()
                failure = self.events(text, 'interpretation_failed')[0]
                self.assertEqual(failure['code'], code)
                self.assertEqual(self.events(text, 'call_ended')[0]['reason'], 'model_fatal_error')
                self.assertFalse(self.events(text, 'model_retry'))

    async def test_voice_hang_up_queues_an_end_frame_after_the_reply(self):
        worker = SimpleNamespace(queue_frames=AsyncMock())
        await v4_bot.hang_up(worker)()
        frames = worker.queue_frames.await_args.args[0]
        self.assertEqual([type(frame).__name__ for frame in frames], ['EndFrame'])


if __name__ == '__main__':
    unittest.main()
