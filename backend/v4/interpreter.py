"""The single v4 model request: one versioned instruction file and one act schema.

The model interprets a caller turn into acts; it never speaks, chooses the next
question, calls tools or authorizes a write. Both files are pinned by SHA-256.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

MODEL = 'gpt-4o-2024-08-06'
OUTPUT_LIMIT = 1024
# v1.9 instructions: v1.8 plus contrastive examples from real failures (Step 3).
# v1.10: one more example and one schema delta, date_shift (relative dates).
INSTRUCTIONS_VERSION = 'v1.10'
SCHEMA_VERSION = 'v1.10'
ASSET_VERSION = INSTRUCTIONS_VERSION
ASSETS = Path(__file__).parent
INSTRUCTIONS_FILE = ASSETS / f'interpreter.{INSTRUCTIONS_VERSION}.txt'
SCHEMA_FILE = ASSETS / f'acts.{SCHEMA_VERSION}.schema.json'
INSTRUCTIONS_SHA = '1bfdb9b6a1f4c206fa5e48b30c032e30069318cb78cd9ca8199f756276238682'
SCHEMA_SHA = '81869e96db1bae14e3246f49f64ef374b767486a1774a95a97068b3e5a6bb277'
SCHEMA_NAME = 'v4_dialogue_acts_reduced_v1'


# Every version the code can build, pinned: (instructions file, sha256, schema file, sha256).
# v1.11 (not active): the same rules in sections, schema descriptions, clinic vocabulary in a
# delimited section, and recent_turns in the envelope.
VERSIONS = {
    'v1.10': ('interpreter.v1.10.txt', INSTRUCTIONS_SHA, 'acts.v1.10.schema.json', SCHEMA_SHA),
    'v1.11': ('interpreter.v1.11.txt', 'f08d309514a5de9d3837682980ac064fcdc3aa800dedab723c882d9952967e45',
              'acts.v1.11.schema.json', '68cdabd204f097bdd706262ae89ef33e0fd2cec454ab97018467622576b9c144'),
    # v1.12 (inactive; rejected after a single-turn probe): earlier dates and explicit block reasons.
    'v1.12': ('interpreter.v1.12.txt', '64e9412b02f845968d4730504d9b206a2935a4ac856dea7cbd3019dfdacd8651',
              'acts.v1.12.schema.json', '646971790fc28e5650b06a5b2f1e00b68676ba855f3106c2379d4513eac589cd'),
}
VOCABULARY_SLOT = '{CLINIC_VOCABULARY}'
RECENT_TURNS = {'v1.11'}  # Versions whose envelope carries context.recent_turns.


def assets(version=INSTRUCTIONS_VERSION):
    """(schema, instructions) of a version, refused if either file differs from its pin."""
    instructions_file, instructions_sha, schema_file, schema_sha = VERSIONS[version]
    schema, instructions = (ASSETS / schema_file).read_bytes(), (ASSETS / instructions_file).read_bytes()
    if sha256(schema).hexdigest() != schema_sha or sha256(instructions).hexdigest() != instructions_sha:
        raise ValueError('Pinned interpreter schema/instructions changed; refusing interpretation')
    return json.loads(schema), instructions.decode()


def with_guidance(instructions, guidance):
    """The clinic's editor guidance: inside the delimited vocabulary section when the
    version has one (it cannot close the section early), else appended (v1.10)."""
    if VOCABULARY_SLOT not in instructions:
        return instructions + guidance
    notes = (guidance or '').replace('<clinic_vocabulary>', '').replace('</clinic_vocabulary>', '').strip()
    return instructions.replace(VOCABULARY_SLOT, notes or '(none)')


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def request(schema, instructions, payload, model=MODEL):
    """The chat-completions parameters for one interpretation."""
    return dict(model=model, temperature=0, max_completion_tokens=OUTPUT_LIMIT,
                messages=[{'role': 'system', 'content': instructions},
                          {'role': 'user', 'content': compact(payload)}],
                response_format={'type': 'json_schema', 'json_schema': {
                    'name': SCHEMA_NAME, 'strict': True, 'schema': schema}})


@dataclass(frozen=True)
class Interpretation:
    raw: dict
    prompt_tokens: int | None = None
    cached_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: float | None = None


class InterpretationError(ValueError):
    def __init__(self, code, receipt):
        super().__init__(code)
        self.code = code
        self.receipt = receipt


def usage_counts(response):
    usage = response.usage
    return dict(prompt_tokens=usage.prompt_tokens if usage else None,
                cached_tokens=getattr(getattr(usage, 'prompt_tokens_details', None), 'cached_tokens', None),
                completion_tokens=usage.completion_tokens if usage else None)


class OpenAIInterpreter:
    def __init__(self, client=None, *, request_limit=None, guidance='', model=MODEL, version=INSTRUCTIONS_VERSION):
        """guidance: the agent file's clinic guidance, placed as vocabulary notes (or
        appended for v1.10); it never changes the schema. model: only the pinned
        snapshot. version: a pinned instruction/schema version (default: the active one)."""
        if model != MODEL:
            raise ValueError(f'The v4 interpreter is pinned to {MODEL}.')
        self.version = version
        self.schema, self.instructions = assets(version)
        self.instructions = with_guidance(self.instructions, guidance)
        self.recent_turns = version in RECENT_TURNS
        if request_limit is not None and (type(request_limit) is not int or request_limit < 1):
            raise ValueError('request_limit must be a positive integer')
        self.request_limit = request_limit
        self.requests = 0
        if client is None:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(max_retries=0, timeout=30)
        self.client = client

    async def interpret(self, envelope, record):
        if self.request_limit is not None and self.requests >= self.request_limit:
            record('request_not_admitted', reason='request_limit')
            raise InterpretationError('request_not_sent', None)
        params = request(self.schema, self.instructions, envelope, MODEL)
        record('request_started', request=params)
        self.requests += 1
        start = perf_counter()
        try:
            response = await self.client.chat.completions.create(**params)
        except Exception as error:
            record('request_failed', error_type=type(error).__name__, usage=None,
                   latency_ms=(perf_counter() - start) * 1000)
            raise
        latency = (perf_counter() - start) * 1000
        # The full receipt is durable before parsing, refusal or usage checks.
        record('response_received', response=response.model_dump(mode='json'), latency_ms=latency)
        counts = usage_counts(response)
        record('request_usage', **counts, latency_ms=latency)
        raw = self._accepted_content(response, counts, latency, record)
        record('request_finished', status='received', **counts, latency_ms=latency)
        return Interpretation(raw, **counts, latency_ms=latency)

    @staticmethod
    def _accepted_content(response, counts, latency, record):
        """The parsed acts, or InterpretationError with the receipt recorded first."""
        def reject(code):
            record('request_finished', status=code, **counts, latency_ms=latency)
            raise InterpretationError(code, Interpretation({}, **counts, latency_ms=latency))
        if response.model != MODEL:
            reject('snapshot_mismatch')
        choice = response.choices[0] if response.choices else None
        if not choice or choice.finish_reason != 'stop' or choice.message.refusal or not choice.message.content:
            reject('unusable_interpretation')
        if any(value is None for value in counts.values()):
            reject('usage_unknown')
        try:
            return json.loads(choice.message.content)
        except json.JSONDecodeError:
            reject('invalid_json')

    async def close(self):
        await self.client.close()
