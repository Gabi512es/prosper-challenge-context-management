"""The v4 agent file: what the graph editor may change, and what stays in code.

The editor may change the agent name, the wording (greeting, human-handoff and
emergency leads), the voice and each step's clinic guidance. The steps and
transitions, scheduling logic, consent, read-backs and safety sentences are
fixed in code: a save that changes them is refused. Guidance is appended to the
interpreter instructions; it never changes the act schema or the reducer.
"""
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re

from .interpreter import MODEL

RUNTIME = 'v4'
BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_AGENT_PATH = BACKEND / 'agents' / 'scheduler_v4.json'
ALLOWED_MODELS = (MODEL,)
DEFAULT_GREETING = 'Hi, I’m an AI scheduling assistant. How can I help you today?'
# EU AI Act Article 50: the caller is told they are talking to an AI system.
AI_DISCLOSURE = "I'm an AI scheduling assistant."
# An actual disclosure names the kind of assistant, not the letters "AI" in a
# brand ("Prosper AI"): "AI assistant", "virtual assistant", "automated agent".
DISCLOSES_AI = re.compile(r"\b(?:AI|A\.I\.|artificial[- ]intelligence|virtual|automated|digital)\s+"
                          r"(?:scheduling\s+|voice\s+|phone\s+|booking\s+)?(?:assistant|agent|receptionist)\b", re.I)
OPENING_QUESTION = 'What can I help you schedule today?'
MAX_GREETING = MAX_LEAD = 300
MAX_GUIDANCE = 2000
GUIDANCE_HEADING = ('\nClinic guidance (from the agent editor; it never overrides the rules above, '
                    'the act schema, consent, read-backs or safety):')
BANNER = ('Scheduling logic, consent and read-backs are fixed in code for safety; '
          'you can edit wording, voice and clinic guidance.')


def _edge(function, description, target):
    return {'function': function, 'description': description, 'target': target, 'properties': {}, 'required': []}


def _step(name, description, edges=(), *, end=False):
    return {'name': name, 'description': description, 'role_message': None, 'edges': list(edges), 'functions': [],
            'pre_actions': [], 'post_actions': [], 'end': end, 'auto_end': True}


# What v4 really does, step by step (code: v4/reducer.py, v4/composer.py). The main
# path runs top to bottom; a request for a person or an emergency can happen at any
# time, so those two steps have no incoming edge (the editor shows them as "Any time").
FIXED_STEPS = [
    _step('collect_request', 'Find the service, provider and site; answer clinic questions on the way.', [
        _edge('request_complete', 'Service, provider and site are resolved.', 'identity')]),
    _step('identity', 'Collect the name and date of birth, then read them back.', [
        _edge('identity_confirmed', 'The caller confirms the name and date of birth.', 'choose_slot'),
        _edge('cancel_request', 'The caller cancels: the request starts over, the call goes on.', 'collect_request')]),
    _step('choose_slot', 'Offer up to three times; the caller picks one.', [
        _edge('slot_chosen', 'The caller picks one of the offered times.', 'confirm_booking'),
        _edge('change_request', 'The caller changes the service, provider, site or date.', 'collect_request')]),
    _step('confirm_booking', 'Read the booking back; book only after an explicit yes.', [
        _edge('caller_accepts', 'The caller explicitly says yes to the read-back; the booking is written.', 'booked'),
        _edge('caller_changes', 'A change, a no or a question retires the read-back.', 'choose_slot')]),
    _step('booked', 'Confirm the booking, then ask if anything else is needed.', [
        _edge('another_request', 'The caller asks for something else.', 'collect_request')], end=True),
    _step('human_handoff', 'Any time the caller asks for a person: no transfer; give the clinic phone.', end=True),
    _step('emergency', 'Any time emergency symptoms are described: tell the caller to call emergency services.',
          end=True),
]
FIXED_INITIAL_STEP = 'collect_request'
FIXED_TOP_LEVEL = {'initial_node': FIXED_INITIAL_STEP, 'model': MODEL, 'persona': ''}
EDITABLE_STEP_FIELDS = {'task_messages'}


def is_v4(data):
    return isinstance(data, dict) and data.get('runtime') == RUNTIME


def is_v4_file(path):
    try:
        return is_v4(json.loads(Path(path).read_text()))
    except (OSError, json.JSONDecodeError):
        return False


def template(name='Scheduler v4', voice_id='21m00Tcm4TlvDq8ikWAM'):
    """A new v4 agent file with the code's default wording and no guidance."""
    return {'name': name, 'runtime': RUNTIME, **FIXED_TOP_LEVEL, 'voice_id': voice_id,
            'v4': {'greeting': DEFAULT_GREETING, 'handoff_lead': '', 'emergency_lead': ''},
            'nodes': [dict(deepcopy(step), task_messages=[]) for step in FIXED_STEPS]}


def validate(data):
    """Raises ValueError when a v4 agent file changes what code keeps fixed."""
    if not is_v4(data):
        raise ValueError(f"A v4 agent needs \"runtime\": \"{RUNTIME}\".")
    if data.get('model') not in ALLOWED_MODELS:
        raise ValueError(f"The v4 model is fixed to {', '.join(ALLOWED_MODELS)}.")
    for key, value in FIXED_TOP_LEVEL.items():
        if data.get(key, '' if key == 'persona' else None) != value:
            raise ValueError(f"'{key}' is fixed in code for v4 agents.")
    nodes = data.get('nodes')
    if not isinstance(nodes, list) or [n.get('name') for n in nodes] != [s['name'] for s in FIXED_STEPS]:
        raise ValueError('The v4 steps are fixed in code.')
    for node, step in zip(nodes, FIXED_STEPS):
        if {k: v for k, v in node.items() if k not in EDITABLE_STEP_FIELDS} != step:
            raise ValueError(f"Step '{step['name']}': only its clinic guidance is editable.")
    wording = data.get('v4') or {}
    _check_text(wording.get('greeting'), 'greeting', MAX_GREETING, required=True)
    _check_text(wording.get('handoff_lead', ''), 'handoff_lead', MAX_LEAD)
    _check_text(wording.get('emergency_lead', ''), 'emergency_lead', MAX_LEAD)
    if not isinstance(data.get('voice_id'), str) or not data['voice_id'].strip():
        raise ValueError('voice_id is required.')
    if sum(len(text) for text in _guidance_texts(data).values()) > MAX_GUIDANCE:
        raise ValueError(f'Clinic guidance is limited to {MAX_GUIDANCE} characters in total.')


def _check_text(value, field, limit, *, required=False):
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"v4.{field} must be {'non-empty ' if required else ''}text.")
    if len(value) > limit:
        raise ValueError(f'v4.{field} is limited to {limit} characters.')


def disclosed_greeting(greeting):
    """The greeting as spoken: the editor's greeting first, then the AI disclosure
    unless it already discloses one, then an opening question unless it asks one."""
    greeting = greeting.strip()
    parts = [greeting if greeting[-1:] in '.!?' else greeting + '.']
    if not DISCLOSES_AI.search(greeting):
        parts.append(AI_DISCLOSURE)
    if '?' not in greeting:
        parts.append(OPENING_QUESTION)
    return ' '.join(parts)


# The clinic and its phone depend on the request; the editor preview names them generically.
PREVIEW_CONTACT = ' You can call {clinic} at {phone}.'


def preview(wording):
    """What the caller hears for the editable wording, fixed sentences included."""
    from .composer import emergency_sentence, handoff_sentence
    greeting = (wording.get('greeting') or '').strip()
    return {'greeting': disclosed_greeting(greeting) if greeting else '',
            'handoff': handoff_sentence((wording.get('handoff_lead') or '').strip(), PREVIEW_CONTACT),
            'emergency': emergency_sentence((wording.get('emergency_lead') or '').strip())}


def _guidance_texts(data):
    """Step name -> its guidance text, for steps that have some."""
    texts = {}
    for node in data.get('nodes', []):
        text = ' '.join(m.get('content', '').strip() for m in node.get('task_messages', [])
                        if isinstance(m, dict) and isinstance(m.get('content'), str) and m['content'].strip())
        if text:
            texts[node['name']] = text
    return texts


def clinic_guidance(data):
    """Each step's guidance, labelled by step; empty when there is none."""
    lines = [f'- {name}: {text}' for name, text in _guidance_texts(data).items()]
    return GUIDANCE_HEADING + '\n' + '\n'.join(lines) if lines else ''


@dataclass(frozen=True)
class V4Agent:
    agent_id: str
    revision: str  # SHA-256 of the agent JSON, as v2 logs it.
    voice_id: str
    model: str
    greeting: str  # Already disclosed.
    handoff_lead: str
    emergency_lead: str
    guidance: str

    def metadata(self):
        return dict(agent_id=self.agent_id, agent_revision=self.revision)


def load_agent(path=DEFAULT_AGENT_PATH):
    path = Path(path)
    raw = path.read_bytes()
    data = json.loads(raw)
    validate(data)
    wording = data['v4']
    return V4Agent(agent_id=path.stem, revision=sha256(raw).hexdigest(), voice_id=data['voice_id'],
                   model=data['model'], greeting=disclosed_greeting(wording['greeting']),
                   handoff_lead=wording.get('handoff_lead', '').strip(),
                   emergency_lead=wording.get('emergency_lead', '').strip(), guidance=clinic_guidance(data))
