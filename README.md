# Prosper Challenge — Context Management

Voice AI for healthcare scheduling. An agent is a **graph of nodes** (Pipecat Flows), defined declaratively as JSON and compiled into a runnable voice pipeline.

- **Phase 1** — a UI to edit the node graph and place a test call.
- **Phase 2** — a context-management approach so a scheduling agent can reliably and cost-effectively navigate a large catalog of locations, doctors, and appointment types.

```
browser mic  ->  ElevenLabs STT  ->  OpenAI LLM  ->  ElevenLabs TTS  ->  browser
```

Pipecat's dev runner ships a **prebuilt browser client**, so the test-call UI comes for free — no frontend code to write yet.

## Quickstart

Requires **Python 3.11+** and **Node.js with npm** (for the graph editor).
`make install` uses `python3`: check that `python3 --version` is 3.11 or later
first, since some systems ship an older `python3`.

Put the API keys in `backend/.env` (never committed):

```bash
OPENAI_API_KEY=...
ELEVENLABS_API_KEY=...
```

Run from the repo root:

```bash
make install   # creates backend/.venv, installs Python and frontend dependencies
make run       # voice agent
```

Open the URL it prints (default `http://localhost:7860/client`), click **Connect**, allow mic access, and talk to the agent. `Ctrl+C` to stop. (`make help` lists all targets.)

Run the offline tests (no API calls, no cost):

```bash
make test
```

## Graph editor

The multi-slot demo integration smoke is run from `backend` with
`LOGURU_LEVEL=WARNING .venv/bin/python -m evals.smoke --demo DEV-012 DEV-002`.
It makes paid OpenAI calls and uses generated availability; ordinary smoke and
matrix runs retain closed-world fixtures. Booking uses two calls to the same
tool: prepare/read back, then book after patient consent. Restart the voice
process to load code version `scheduling-booking-v5` before testing it.

The current scheduling graph is **Catalog Scheduler proposed-v2**. For a voice
regression check, restart `make run` after changing Python code, then select this
agent in the editor and click **Test call**. Older duplicated agents retain their
own saved prompts. Demo voice/text sessions generate seeded synthetic slots for
every valid catalog combination over the next two weeks; development evaluations
continue to use only their scenario fixtures.

Voice tool traces are written to `backend/logs/voice-tools.jsonl`, with call id,
tool name, arguments, actual result/error and duration. Model usage remains in
`backend/logs/turns.jsonl`; join by call id. Logs contain patient data and stay
local/ignored. English STT is pinned. One real word interrupts the agent while
it speaks; filler sounds and punctuation noise do not.

Run the voice service and editor in separate terminals:

```bash
make run
```

```bash
make editor
```

Open `http://localhost:5173`. The editor lists JSON agents, edits their nodes,
tools and transition edges, validates through the same `AgentConfig` and
`AgentBuilder` used at runtime, and saves into `backend/agents/`.

**Test call** saves the current agent, marks it as the agent for the next local
call, and opens the prebuilt Pipecat client. Click **Connect** there. A new call
loads the saved JSON from disk, so prompt edits are reflected without restarting
the voice service. This next-call pointer is intentionally process-global for the
single-user local demo; auth and concurrent editor sessions are out of scope.

For a more controlled text conversation through the same agent runtime:

```bash
make text
```

Text mode removes speech recognition and audio playback variability, but it is
not deterministic because model outputs can still vary. The reusable interface
for an evaluation harness is `TextAgentSession` in `backend/text_runner.py`;
the interactive prompt is only a thin wrapper around `start()`, `send()`, and
`close()`.

`make test` runs offline tests without API calls. The opt-in OpenAI integration
check incurs cost and may vary:

```bash
cd backend
RUN_OPENAI_INTEGRATION=1 .venv/bin/python -m unittest tests/test_text_runner_integration.py -v
```

## Layout

| Path | Responsibility |
| --- | --- |
| `backend/bot.py` | The voice pipeline (WebRTC + ElevenLabs STT/TTS + OpenAI LLM). Loads an agent JSON via `AgentBuilder` and runs it. No graph logic lives here. |
| `backend/agent_runtime.py` | Shared construction of the model, context, builder, FlowManager, pipeline worker, state, and metrics for voice and text. Only the I/O processors differ. |
| `backend/text_runner.py` | Programmatic text session plus a thin interactive prompt. A turn waits for tools, transitions, and the resulting assistant generation. |
| `backend/scheduling/` | Pure-Python catalog loading, resolution, policy, closed-world slot search, invalidation, and booking. No Pipecat or LLM imports. |
| `backend/evals/dev_scenarios.json` | Development-only scenario source of truth, pinned to the catalog Git blob SHA. |
| `backend/agent_builder/` | All agent-building code. `schema.py` = the declarative `AgentConfig` / `Node` / `Edge` contract; `builder.py` = `AgentBuilder`, which loads + validates the JSON and compiles it into a Pipecat Flows graph. |
| `backend/agents/` | Saved JSON agents edited by the graph UI. `catalog_scheduler.json` is the scheduling agent used by voice and text. |
| `backend/editor_api.py` | Local CRUD, validation, persistence and next-call selection API for the graph editor. |
| `frontend/` | Minimal React Flow editor. No catalog CRUD, auth or layout-polish layer. |
| `backend/example_flow.json` | The example agent **as data** — a clinic scheduler. The starting point for the Phase 2 context-management work. |
| `backend/data/catalog.json` | A deliberately large, deliberately messy clinic catalog (locations, providers, appointment types, booking rules) for the Phase 2 work. See [`backend/data/README.md`](backend/data/README.md). |

To run a different agent programmatically, pass its path to `TextAgentSession` or
load it with `AgentBuilder` before calling `build_agent_runtime`.
