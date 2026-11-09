# Project handoff — 2026-11-08

Repository: `/Users/gabrielernoult/Desktop/Prosper AI/prosper-challenge-context-management`.
Paths below are relative to this root. Read `AGENTS.md` and `docs/decisions.md`.

## Goal and scope

Prosper scheduling-agent challenge, with an approximately 16-hour project budget.
Phase 1 is a local graph editor: create/edit/save JSON agents and test them by
voice. Phase 2 is catalog-aware scheduling with measured accuracy and context
cost, comparing the proposed approach against a full-catalog baseline using the
same model, shared slot/booking core, final guard, and scorer. The catalog has
8 locations, 50 providers, 82 appointment types; 8 types have no provider and
remain unbookable. Availability and booking are simulated, not a real calendar.

## Architecture and evidence

- `backend/scheduling/`: pure Python catalog loading/search, session models,
  resolution, policies, opening hours, slots and booking (`engine.py`);
  `demo.py` generates seeded demo availability. Catalog: `backend/data/catalog.json`.
- `backend/scheduling_agent.py`: session-local registry for `resolve_options`,
  `get_details`, `find_slots`, `book_appointment`; these are non-transition tools.
  `backend/agents/catalog_scheduler.json`: current proposed-v2 prompts/graph.
  `backend/agent_builder/`: JSON schema, validation and Flows compilation;
  graph edges compile to transition functions, including human handoff.
- `backend/scheduling_runtime.py`: selected saved agent plus fresh demo engine.
  `backend/agent_runtime.py`: shared LLM/context/Flows pipeline construction.
  `backend/bot.py`: voice I/O. `backend/voice_support.py`: word-based turn start,
  silent interruption recovery, voice tool tracing.
- `frontend/src/App.jsx`: React Flow editor. `backend/editor_api.py` and
  `backend/agent_store.py`: local CRUD, validation, atomic saves and agent selection.
- `backend/text_runner.py`: evaluation-facing text session and thin interactive
  CLI; waits for tool execution and subsequent assistant generation. Fault
  injection supports structured tool errors and slot-taken writes.
- `backend/evals/text_integration.py`: scripted patients;
  `dev_matrix.py`: paid matrix and cost aggregation;
  `scorer.py`: canonical scorer, `dev-v4-voice-gaps`.
- `backend/logs/turns.jsonl`: voice model usage; `voice-tools.jsonl`: voice tool
  arguments/results/errors/durations; join by call id. Missing usage stays null.
  `backend/logs/evals/`: per-run usage, reports and readable transcripts.
  Logs are ignored by git, contain patient data, and must be copied separately
  if the next agent uses another checkout.

## Run commands

From the repository root, dependencies already exist locally:

```sh
make test                         # offline; paid integrations skipped
make text                         # interactive scheduling, paid OpenAI
make run                          # voice server, localhost:7860/client/
make editor                       # API :8000 + React editor :5173
cd backend
LOGURU_LEVEL=WARNING .venv/bin/python -m evals.dev_matrix --repetitions 3 --concurrency 3
```

Spend rule updated 2026-11-09: estimate before any paid run; wait for the user's
go above $1. Smoke only after booking/resolution changes, once per selected case.
A full matrix always requires explicit approval. See `AGENTS.md` and `docs/costs.md`.
Keys belong only in `backend/.env`, never committed or printed. To build the
editor: `npm --prefix frontend run build`. Python tests must run via `make test`
or from `backend`; root unittest discovery without PYTHONPATH fails imports.
Restart `make run` after Python changes. Test Call saves/selects an agent and
opens the existing client; the user clicks Connect. Selection is process-global
in ignored `backend/logs/active_agent.txt`, read for every new session. It currently
points to `catalog_scheduler`. Older user-created `catalog_scheduler_test` is
preserved with its own earlier prompts; choose **Catalog Scheduler proposed-v2**.

## Current status and remaining work

Proposed-v2 is implemented but **not frozen**. Latest offline run collected 51
tests: 49 passed, 2 paid checks skipped; voice imports and frontend build passed.
Latest paid 12 × 3 matrix: 192 model calls, $0.988365, raw 30/36; corrected
scoring gives 32/36. Two DEV-008 replies correctly said “does not offer” / “cannot
perform” imaging; general absence vocabulary was expanded and saved responses
rescored without more model calls. DEV-008 is 3/3 after that correction.
Raw: `backend/logs/evals/dev-matrix-20261108-122231-91750a.results.json`.
Corrected: `backend/logs/evals/proposed-v2-rescored.json` (omits full contexts).
Table: `backend/logs/evals/proposed-v2-report.md`. Earlier iteration was 23/36,
$0.85666250; total for both iterations $1.84502750. Costs use recorded
2026-11-07 gpt-4o prices: $2.50 uncached input, $1.25 cached input, $10 output
per million tokens. All final-run costs are known. Scenarios below each pass 2/3:

- DEV-002: provider/location confusion; model claimed the clarified provider
  was unavailable at requested Midtown and offered other locations.
- DEV-003: explained missing imaging but omitted returned Downtown alternative.
- DEV-006: unnecessarily asked to confirm the already-stated service; scripted
  patient had no further reply, so referral explanation was not completed.
- DEV-007: omitted the catalog's undocumented clinical-distinction explanation.

All three new general checks passed in the final matrix: offer location,
no unrecorded callback promise, next step after no availability. These are language
heuristics, not semantic guarantees. Prior voice calls exposed false follow-up
promises, unrequested handoff, incomplete offers and transcription problems.
V2 removes the follow-up instruction, adds catalog phones/hours and named slot
fields, consent-only one-constraint alternatives, full read-back/DOB confirmation
and closing instructions. These conversational rules remain model-driven.

User's next planned action is three real voice retests. English STT, two-real-word
interruptions while speaking, 2.5-second silent recovery, DOB read-back and closing
are not acoustically verified. One-word interruptions may be delayed. Demo uses
seed 42 and 760 valid combinations over two weeks in America/Los_Angeles;
evals keep fixtures. Opening-hours validation otherwise trusts slot-local offsets;
catalog has no timezone field. Handoff is simulated: no live transfer, callback,
notification or staff follow-up is recorded. Test Call selection is local and
single-user. The baseline comparison and proposed freeze are still outstanding.

## Mandatory rules and gotchas

- Never change scenario facts, fixtures or expected outcomes. Only inspect
  `backend/evals/dev_scenarios.json`; do not seek other eval files or held-out data.
  Loader checks the catalog git blob SHA against the scenario pin and fails on mismatch.
- Both arms must use the same canonical scorer version. Preserve raw failed runs;
  disclose scorer corrections. Follow the spend rule above. Log decisions in
  `docs/decisions.md`. Never repair catalog gaps or silently relax hard constraints.
- Explicit resolved choices remain in state even when incompatible, so policy
  results explain the block. Alternative previews do not authorize booking;
  consent, request update and a fresh search are required.
- Most work is uncommitted and many files are untracked; preserve the worktree.
  Do not reset it. An earlier Python process occupied port 7860; its continued
  status was not checked in the latest turn. Do not kill an unidentified process.
- No client event-log attachment was present in the latest voice-failure request;
  implementation used the user's description. Do not claim those logs were inspected.
  No further implementation was started after the user requested this handoff.
