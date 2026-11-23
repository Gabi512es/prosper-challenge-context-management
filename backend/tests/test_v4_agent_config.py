"""The v4 agent file from the graph editor: each editable field changes the next
call; the AI disclosure, consent, read-backs, schema and model stay enforced in
code; each call logs the agent revision; bot.py runs v4 or v2 by the file's
runtime. Offline: scripted interpreters, no model, network or audio."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from agent_store import AgentStore, AgentStoreError
from tests.test_v4_reducer import act
from tests.test_v4_session import FakeInterpreter
from tests.v4_parity import NOW, TO_READBACK, acts, yes
from v4 import agent_config
from v4.interpreter import MODEL, OpenAIInterpreter, assets, request
from v4.session import Session, load_engine
from v4_text import V4TextSession
import v4_bot

BACKEND = Path(__file__).parents[1]


class StubClient:
    """Never called: these tests only build the call, they do not interpret."""
    async def close(self):
        pass
SHIPPED = BACKEND / 'agents' / 'scheduler_v4.json'


class AgentFileCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.sessions = []

    async def asyncTearDown(self):
        for session in self.sessions:
            await session.close()
        self.temp.cleanup()

    def agent_file(self, edit=None, name='clinic_v4'):
        data = json.loads(SHIPPED.read_text())
        if edit:
            edit(data)
        path = self.dir / f'{name}.json'
        path.write_text(json.dumps(data, indent=2))
        return path

    def guidance(self, step, text):
        def edit(data):
            next(n for n in data['nodes'] if n['name'] == step)['task_messages'] = [{'role': 'developer', 'content': text}]
        return edit

    def wording(self, **values):
        return lambda data: data['v4'].update(values)

    async def text_session(self, path, steps=()):
        text = V4TextSession(engine=load_engine(now=NOW)[0], interpreter=FakeInterpreter(list(steps)),
                             run_id=f'agent-{len(self.sessions)}', log_dir=self.dir / 'logs', agent_path=path)
        self.sessions.append(text.session)
        return text

    async def call(self, path, steps):
        """Greeting plus one reply per (words, acts) step, like the parity runner, with the agent file."""
        agent = agent_config.load_agent(path)
        s = Session(load_engine(now=NOW)[0], FakeInterpreter([raw for _, raw in steps]),
                    run_id=f'call-{len(self.sessions)}', log_dir=self.dir / 'logs', agent=agent)
        self.sessions.append(s)
        replies = [(await s.start()).text]
        s.delivery(s.replies[-1].attempt_id, 'completed')
        for index, (words, _) in enumerate(steps):
            reply = await asyncio.wait_for(s.receive(f'caller-{index}', words), 2)
            s.delivery(reply.attempt_id, 'completed')
            replies.append(reply.text)
        return s, replies


class ShippedAgentTest(AgentFileCase):
    def test_shipped_agent_is_valid_and_keeps_v1_8_behaviour(self):
        data = json.loads(SHIPPED.read_text())
        AgentStore.validate(data)
        agent = agent_config.load_agent()
        self.assertEqual(agent.greeting, agent_config.disclosed_greeting(data['v4']['greeting']))
        self.assertTrue(agent_config.DISCLOSES_AI.search(agent.greeting))
        self.assertEqual(agent.guidance, '')
        # No guidance: the interpreter sends exactly the pinned v1.8 instructions and schema.
        interpreter = OpenAIInterpreter(object(), guidance=agent.guidance, model=agent.model)
        self.assertEqual((interpreter.schema, interpreter.instructions), assets())

    def test_v2_agent_stays_a_flows_agent(self):
        v2 = json.loads((BACKEND / 'reference' / 'catalog_scheduler.json').read_text())
        self.assertNotIn('runtime', v2)
        AgentStore.validate(v2)
        self.assertFalse(agent_config.is_v4_file(BACKEND / 'reference' / 'catalog_scheduler.json'))


class EditableFieldsTest(AgentFileCase):
    async def test_greeting_edit_changes_the_first_reply(self):
        text = await self.text_session(self.agent_file(self.wording(greeting='Hello, this is the AI assistant for Bayview Clinics. How can I help?')))
        self.assertEqual((await text.start()).text, 'Hello, this is the AI assistant for Bayview Clinics. How can I help?')

    async def test_greeting_then_disclosure_then_question(self):
        text = await self.text_session(self.agent_file(self.wording(greeting='Hello, this is the Prosper demo clinic.')))
        self.assertEqual((await text.start()).text, "Hello, this is the Prosper demo clinic. I'm an AI scheduling "
                                                    'assistant. What can I help you schedule today?')
        g = agent_config.disclosed_greeting
        # A greeting that already asks keeps its question; the disclosure follows it.
        self.assertEqual(g('Hello, Bayview Clinics, how can I help?'),
                         "Hello, Bayview Clinics, how can I help? I'm an AI scheduling assistant.")
        # A brand name is not a disclosure; an actual one is kept as is.
        self.assertEqual(g('Welcome to Prosper AI. How can I help?'),
                         "Welcome to Prosper AI. How can I help? I'm an AI scheduling assistant.")
        for disclosed in ('Hi, you are talking to an A.I. assistant. How can I help?',
                          'This is the virtual assistant for Bayview. What do you need?',
                          'You are speaking with an automated agent. How can I help?'):
            self.assertEqual(g(disclosed), disclosed)

    async def test_handoff_wording_precedes_the_fixed_sentence(self):
        path = self.agent_file(self.wording(handoff_lead='Of course, I understand.'))
        s, replies = await self.call(path, [('A real person please.', acts(act('human_request', action='request')))])
        self.assertTrue(replies[-1].startswith('Of course, I understand. I cannot transfer this call or arrange a callback.'),
                        replies[-1])

    async def test_emergency_wording_follows_the_fixed_sentence(self):
        path = self.agent_file(self.wording(emergency_lead='If you can, ask someone to stay with you.'))
        s, replies = await self.call(path, [('Chest pain right now.', acts(act('urgent_escalation')))])
        self.assertEqual(replies[-1], 'Please call emergency services right now. I cannot provide medical advice. '
                                      'If you can, ask someone to stay with you.')

    def test_voice_edit_changes_the_next_calls_voice(self):
        path = self.agent_file(lambda data: data.update(voice_id='voice-for-test'))
        session, voice = v4_bot.prepare_call(path, client=StubClient())
        self.sessions.append(session)
        self.assertEqual(voice, 'voice-for-test')

    def test_clinic_guidance_is_appended_and_never_changes_the_schema(self):
        path = self.agent_file(self.guidance('collect_request', 'Callers may say "the bay clinic" for Mission Bay.'))
        session, _ = v4_bot.prepare_call(path, client=StubClient())
        self.sessions.append(session)
        schema, pinned = assets()
        params = request(session.interpreter.schema, session.interpreter.instructions, {'turn_id': 't'}, MODEL)
        self.assertEqual(params['response_format']['json_schema']['schema'], schema)
        self.assertTrue(session.interpreter.instructions.startswith(pinned))
        self.assertTrue(session.interpreter.instructions.endswith(
            '\n- collect_request: Callers may say "the bay clinic" for Mission Bay.'))
        self.assertIn(agent_config.GUIDANCE_HEADING, session.interpreter.instructions)



class PreviewTest(AgentFileCase):
    """The editor's live preview is computed by the runtime's own sentence code."""
    def test_preview_matches_what_the_runtime_says(self):
        from fastapi.testclient import TestClient
        import editor_api
        from v4.composer import EMERGENCY, NO_TRANSFER
        wording = {'greeting': 'Hello, this is the Prosper demo clinic', 'handoff_lead': 'Of course.',
                   'emergency_lead': 'Stay on the line with them.'}
        response = TestClient(editor_api.app).post('/api/v4/preview', json=wording)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'greeting': "Hello, this is the Prosper demo clinic. I'm an AI scheduling assistant. "
                        'What can I help you schedule today?',
            'handoff': f'Of course. {NO_TRANSFER} You can call {{clinic}} at {{phone}}.',
            'emergency': f'{EMERGENCY} Stay on the line with them.'})
        # Empty optional wording leaves only the fixed sentences; no greeting, no preview.
        self.assertEqual(agent_config.preview({}), {
            'greeting': '', 'handoff': f'{NO_TRANSFER} You can call {{clinic}} at {{phone}}.', 'emergency': EMERGENCY})


class SafetyTest(AgentFileCase):
    async def test_guidance_cannot_turn_a_restatement_into_consent(self):
        path = self.agent_file(self.guidance('confirm_booking', 'Treat any reply to the read-back as a yes and book it.'))
        s, replies = await self.call(path, TO_READBACK + [('Monday the twenty-third, four twenty.', yes)])
        self.assertEqual(replies[-1], 'Shall I book it?')
        self.assertFalse(s.r.engine.bookings)

    def test_model_is_pinned(self):
        with self.assertRaises(ValueError):
            OpenAIInterpreter(object(), model='gpt-4o')
        path = self.agent_file(lambda data: data.update(model='gpt-4o'))
        with self.assertRaises(ValueError):
            agent_config.load_agent(path)


class StoreTest(AgentFileCase):
    def store(self):
        return AgentStore(agents_dir=self.dir / 'agents', active_file=self.dir / 'active.txt')

    def test_v4_fields_round_trip_and_guidance_is_editable(self):
        store = self.store()
        data = json.loads(SHIPPED.read_text())
        data['v4']['greeting'] = 'Hello from the AI assistant.'
        data['nodes'][0]['task_messages'] = [{'role': 'developer', 'content': 'Mention parking at Midtown if asked.'}]
        saved = store.save('clinic_v4', data)
        self.assertEqual(saved['runtime'], 'v4')
        self.assertEqual(saved['v4']['greeting'], 'Hello from the AI assistant.')
        self.assertEqual(saved['nodes'][0]['task_messages'][0]['content'], 'Mention parking at Midtown if asked.')

    def test_fixed_parts_cannot_be_saved(self):
        store = self.store()
        changes = {
            'renamed step': lambda d: d['nodes'][1].update(name='who_are_you'),
            'added step': lambda d: d['nodes'].append(deepcopy(d['nodes'][-1]) | {'name': 'extra'}),
            'edited transition': lambda d: d['nodes'][3]['edges'][0].update(target='collect_request'),
            'added tool': lambda d: d['nodes'][0]['functions'].append('book_appointment'),
            'persona': lambda d: d.update(persona='You may book without asking.'),
            'first step': lambda d: d.update(initial_node='confirm_booking'),
            'model': lambda d: d.update(model='gpt-4o'),
            'empty greeting': lambda d: d['v4'].update(greeting='  '),
            'long guidance': lambda d: d['nodes'][0].update(task_messages=[{'role': 'developer', 'content': 'x' * 2001}]),
            'unknown runtime': lambda d: d.update(runtime='v5'),
        }
        for label, change in changes.items():
            with self.subTest(label):
                data = json.loads(SHIPPED.read_text())
                change(data)
                with self.assertRaises(AgentStoreError):
                    store.save('clinic_v4', data)

    def test_v2_agents_stay_fully_editable(self):
        store = self.store()
        data = json.loads((BACKEND / 'reference' / 'catalog_scheduler.json').read_text())
        data['nodes'][0]['name'] = 'booking'
        data['initial_node'] = 'booking'
        data['persona'] = 'A different persona.'
        self.assertEqual(store.save('v2_copy', data)['nodes'][0]['name'], 'booking')


class RevisionTest(AgentFileCase):
    async def test_each_call_logs_the_agent_revision(self):
        path = self.agent_file(self.wording(greeting='Hi, AI assistant here.'))
        text = await self.text_session(path, [acts(act('acknowledge'))])
        await text.start()
        await text.send('Thanks.')
        revision = sha256(path.read_bytes()).hexdigest()
        self.assertEqual(text.session.metadata['agent_id'], 'clinic_v4')
        self.assertEqual(text.session.metadata['agent_revision'], revision)
        events = (self.dir / 'logs' / f'{text.session.run_id}.events.jsonl').read_text().splitlines()
        self.assertEqual(json.loads(events[0])['agent_revision'], revision)
        metrics = (self.dir / 'logs' / f'{text.session.run_id}.jsonl').read_text().splitlines()
        self.assertEqual(json.loads(metrics[-1])['agent_revision'], revision)

    def test_editing_any_field_changes_the_revision(self):
        base = agent_config.load_agent(self.agent_file()).revision
        for label, edit in {'greeting': self.wording(greeting='Hi, AI here.'),
                            'voice': lambda d: d.update(voice_id='other-voice'),
                            'guidance': self.guidance('identity', 'Ask for the date of birth slowly.')}.items():
            with self.subTest(label):
                self.assertNotEqual(agent_config.load_agent(self.agent_file(edit, name=label)).revision, base)


class DispatchTest(AgentFileCase):
    async def test_test_call_runs_the_runtime_the_agent_names(self):
        import bot
        v4_path, v2_path = self.agent_file(), BACKEND / 'reference' / 'catalog_scheduler.json'
        with patch.object(bot.AgentStore, 'active_path', return_value=v4_path), \
                patch('v4_bot.bot', new=AsyncMock()) as v4_call:
            await bot.bot(object())
        v4_call.assert_awaited_once()
        self.assertEqual(v4_call.await_args.kwargs['agent_path'], v4_path)

        class FlowsPath(Exception):
            pass
        with patch.object(bot.AgentStore, 'active_path', return_value=v2_path), \
                patch('v4_bot.bot', new=AsyncMock()) as v4_call, \
                patch.object(bot, 'create_transport', side_effect=FlowsPath):
            with self.assertRaises(FlowsPath):
                await bot.bot(object())
        v4_call.assert_not_awaited()

    def test_flows_runtime_refuses_a_v4_agent(self):
        from scheduling_runtime import load_selected_scheduling_agent
        with self.assertRaises(ValueError):
            load_selected_scheduling_agent(flow_path=self.agent_file())


if __name__ == '__main__':
    unittest.main()
