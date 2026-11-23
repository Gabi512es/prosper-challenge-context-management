# Submission decisions

## Runtime and editor

Ship the current v4 sequential interpreter/reducer/composer and shared scheduling
engine without a behavior change. Interpreter v1.10 remains active, with
gpt-4o-2024-08-06 pinned. Scheduler v4 is the default and sole bundled editor agent.
The legacy JSON is retained under backend/reference/ for offline tests and logging
compatibility, outside the editor agent directory. Generic graph editing remains available.
V4 scheduling steps/consent are fixed; editable wording and voice remain in JSON.
The next-call pointer is a local, single-user mechanism.

## Measured claims

Original-size and x5 context/cost results belong to frozen proposed-v2 and its
full-catalog baseline, not current v4. Preserve unknown usage as null and retain
known subtotals separately. Small DEV samples do not establish equivalent accuracy
or a significant difference. See [the aggregate evidence](results/context-comparison.md).
Availability, bookings, referral status and human handoff remain simulated.

## V1.12 experiment closed, 2026-11-23

The pinned single-turn probe made 96 requests: 48 cases per interpreter, one attempt,
no retry. Both schemas were accepted by gpt-4o-2024-08-06. Outcomes: v1.10 39/48;
v1.12 43/48. Five assertions improved and one regressed; provider fell 9/9 to 8/9,
consent remained 3/4, so the predeclared adoption rule failed. V1.12 stays inactive.

The failing consent-labeled case actually collected identity and supplied no proposal.
The provider-regression case asked an information-clarification question. These
context/expectation limitations qualify the results; they were not rescored to adopt
the candidate. This is not evidence of an unsafe consent acceptance, nor a test of
complete booking or voice behavior. [Token-only probe summary](results/interpreter-probe.json).

### Probe hash provenance

The probe's `schema_sha256` hashes compact JSON produced by
`json.dumps(schema, ensure_ascii=False, separators=(',', ':'), allow_nan=False)`
without sorting keys. Runtime pins hash raw schema file bytes, including formatting.
Both probe hashes reproduce exactly from the shipped schemas: this is a serialization
difference, not different schema content. The summary now labels each representation
and adds `schema_file_sha256` for direct comparison with the runtime pins. Instruction
hashes cover the instruction file bytes. Recorded hashes, scores and usage are unchanged.
The stale “no measured model result” comment was corrected; v1.10 remains active.


## Packaging

This branch starts at verified starter 06571c8f4ac3b2b7595397b32add105532551294.
The scheduling runtime and agent JSON come from checkpoint 27d3c70, following
working source b04091b. Packaging only changes default selection and the legacy
reference file's path; its bytes and the active v4 agent are unchanged. Dependency pins match the tested runtime;
focused synthetic tests are included. Recorded call replays, private scenarios,
local paths, secrets, scratch reports and personal/project-time notes are excluded.
One live booking on pre-cleanup commit f5aad82 was confirmed by the caller and its
journal: Annual Physical, the Family Medicine Maria Garcia, Midtown, one successful
write after identity and booking consent. The STT service-name error was clarified.
This is one functional rehearsal, not an accuracy benchmark. Raw logs remain local.
The final packaging changes are checked offline, with no new paid call.
The submission remains one commit after the starter; working history and frozen refs
are preserved separately. Only concise setup, solution, decisions and aggregate evidence ship.


## Build verification

The initial clean install exposed npm advisories in the old Vite dev server.
Vite is pinned to 6.4.6, supported by the existing React plugin; the production
build passes and npm audit reports zero known advisories at verification.
No frontend application code or scheduling/runtime behavior changed for this patch.
Python dependencies are pinned to the versions used for the verified environment.

## Documentation clarity review

The main write-up now introduces the deliverable and four-step design sequence before
presenting the historical v2 comparison. It distinguishes application and interpreter
versions, fixed scheduling steps from editable generic graphs, and scripted conversation
results from single-turn probes and the manual voice rehearsal. Evidence values and
runtime behavior are unchanged. Changes were checked offline; no paid calls were made.
