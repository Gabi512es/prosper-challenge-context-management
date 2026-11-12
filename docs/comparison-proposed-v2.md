# Official proposed-v2 DEV measurement and offline baseline

## Measurement identity

Measured 2026-11-09. Frozen tag/commit: `proposed-v2`,
`a5b124f7aa3ffa9d7ebcd32a7f76c837c95486c8`. Agent JSON SHA-256:
`40db1b587b5790ab2c92bc642edbc55e67f0d44ebd8d4f1267de29e1e86ebdc5`.
Model: `gpt-4o`; scorer: unchanged `dev-v4-voice-gaps`.

Run: `dev-matrix-20261109-150315-454f33`. Only
`backend/evals/dev_scenarios.json` was used; its loader checked the catalog git
blob SHA. All 12 cases ran three times, sequentially. User ceiling: $2.50.
SDK retries and Pipecat timeout retries were disabled in the launcher in memory;
no failed run was repeated. The existing SpendGuard capped completions at 512
tokens, as in the recent smoke. Frozen source, scenarios and scorer were not edited.

Artifacts (ignored local logs, not committed):

- [Results, assertions and full model contexts](../backend/logs/evals/dev-matrix-20261109-150315-454f33.results.json)
- [Per-model-call usage and timing](../backend/logs/evals/dev-matrix-20261109-150315-454f33.jsonl)

## Scores and cost

**25/36 passed (69.44%), 11 failed; 204 model calls; $1.0117100.**
All calls reported prompt, cached and completion usage. There are no unknown-cost
runs. Prompt tokens include cached tokens; cached is not added again.

| Scenario | Passes / 3 | Model calls, runs 1/2/3 | Prompt | Cached | Completion | USD, all 3 | USD min–max per run |
|---|---:|---|---:|---:|---:|---:|---:|
| DEV-001 | 3 | 9 / 9 / 9 | 90,989 | 77,568 | 778 | 0.1382925 | 0.0444425–0.0481400 |
| DEV-002 | 1 | 6 / 6 / 11 | 75,729 | 63,488 | 527 | 0.1152325 | 0.0259925–0.0593500 |
| DEV-003 | 3 | 3 / 3 / 3 | 22,754 | 16,384 | 307 | 0.0394750 | 0.0121200–0.0149000 |
| DEV-004 | 3 | 3 / 3 / 3 | 22,546 | 19,328 | 289 | 0.0350950 | 0.0113100–0.0122325 |
| DEV-005 | 1 | 3 / 3 / 3 | 22,437 | 19,072 | 275 | 0.0350025 | 0.0114925–0.0117875 |
| DEV-006 | 2 | 3 / 3 / 3 | 22,692 | 16,640 | 267 | 0.0386000 | 0.0117525–0.0149875 |
| DEV-007 | 0 | 4 / 5 / 4 | 32,902 | 29,184 | 393 | 0.0497050 | 0.0143325–0.0203825 |
| DEV-008 | 3 | 9 / 9 / 9 | 90,966 | 77,312 | 935 | 0.1401250 | 0.0454400–0.0479325 |
| DEV-009 | 3 | 11 / 11 / 11 | 143,279 | 122,496 | 902 | 0.2140975 | 0.0697075–0.0745325 |
| DEV-010 | 3 | 3 / 3 / 3 | 22,410 | 19,072 | 213 | 0.0343150 | 0.0112150–0.0118450 |
| DEV-011 | 0 | 3 / 3 / 3 | 22,337 | 18,560 | 233 | 0.0349725 | 0.0114175–0.0118475 |
| DEV-012 | 3 | 9 / 9 / 9 | 90,435 | 77,696 | 783 | 0.1367975 | 0.0446125–0.0465875 |
| Total | 25 / 36 | 204 | 659,476 | 556,800 | 5,902 | 1.0117100 | — |

Uncached input: 102,676 tokens. Total input + output: 665,378 tokens.
Mixed pass/fail across repetitions: **DEV-002, DEV-005, DEV-006**. The other
scenarios agree on the recorded outcome signature, not necessarily wording.

There were 10 successful bookings, all matching the required booking IDs.
Observed explicit book_appointment results: 10 booked, 3 needs_confirmation,
no validation/error refusals. The latter is not an exhaustive count of phase-one
preparations: find_slots can prepare a sole slot internally. No wrong bookings
were created. Entire-arm cost / successful booking, including every failed run
and non-booking case in the numerator: **$0.101171** (1.011710 / 10).

Historical pricing recorded in `backend/evals/dev_matrix.py`, dated 2026-11-07:
$2.50/M uncached input, $1.25/M cached input, $10/M completion.
Cost = ((prompt − cached) × 2.50 + cached × 1.25 + completion × 10) / 1,000,000.
This is logged OpenAI text cost, excluding speech services and unlogged usage.

## Manual failure severity and evidence

The four requested severity labels are retained. Two additional descriptive
labels below prevent explanation omissions and an overstrict handoff guard from
being misreported as factual falsehoods or purely internal failures. Counts:
5 unnecessary-question failures, 1 unsupported/false patient statement,
4 explanation omissions, 1 blocked-recovery failure, 0 internal-state-only
failures, 0 wrong bookings. These are manual annotations, not scorer changes.

| Scenario / run | Severity | Evidence |
|---|---|---|
| DEV-002 / 1 | Unnecessary question | After “I am a new patient,” no tool records the fact; the reply repeats “Please confirm is new patient.” Script cannot continue; no booking. |
| DEV-002 / 2 | Unnecessary question | Same repeated eligibility question and absent state update as run 1. |
| DEV-005 / 1 | Unnecessary question | Tool returns new_patient_provider_restricted, but no service ID was supplied; controller's first missing slot replaces the explanation with “What appointment service do you need?” |
| DEV-005 / 3 | Unnecessary question | Same missing service ID and suppressed existing provider restriction as run 1. |
| DEV-006 / 3 | Unnecessary question | Model records provider/site/referral facts but omits the stated dermatology service; controller asks for the already supplied service. No referral block is evaluated. |
| DEV-007 / 1 | False statement to patient (unsupported certainty) | Calls “full skin check” definitively “Full Body Skin Exam,” without a tool lookup or a documented distinction from Skin Cancer Screening. Does not explain that distinction is absent. |
| DEV-007 / 2 | Blocked recovery / missing next step | “Please have a staff member confirm the intended service” is rejected by the shared explicit-human-request guard; output is only “No transfer or callback is recorded.” Missing staff-guidance and distinction explanation; script cannot continue. |
| DEV-007 / 3 | Explanation omission | Asks to proceed with a tentative Full Body Skin Exam, then tells caller to contact the clinic. Does not state the catalog lacks the distinction. Handoff tool was also rejected. |
| DEV-011 / 1 | Explanation omission | Correctly says provider cannot be found and asks to repeat/spell; never names the requested provider in that explanation. No invented provider or booking. |
| DEV-011 / 2 | Explanation omission | Same omitted requested name as run 1. |
| DEV-011 / 3 | Explanation omission | Same omitted requested name as run 1. |

Harness limits matter: for DEV-005, the script stops when core policy state is
blocked, even if the spoken explanation is missing. DEV-011 completion detects
“couldn't find” before sending the available spelling reply. These remain failed
under the unchanged scorer; no transcript was repaired or rescored with different
rules. DEV-007's guard rejects the staff-confirmation request in all three runs.
No proposed-arm fixes were made after this measurement.

## Offline baseline implementation

`backend/baseline_agent.py` renders all catalog fields and six policies as readable
Markdown tables, with all 8 locations, 50 providers and 82 services. Lists retain
every ID, language and capability; absent optional capability is rendered as none.
A round-trip test checks every source field/value, including empty lists and
booleans. No catalog facts are repaired or excluded.

The baseline builder uses the same AgentBuilder, configured model, scheduling
registry, patient-state initialization, controller, APPEND context, availability,
find_slots, two-phase book_appointment, identity/consent/transition guards and
get_details. resolve_options accepts IDs/facts/scopes only; free-text search and
specialty-filter arguments are neither advertised nor accepted. Its wrapper
delegates accepted updates, validation, block reasons and alternatives to the
existing handler. Transcript-derived safeguards remain shared between arms.

Only baseline catalog-access instructions change: permit facts from the full
reference, replace the type-index/search instructions with ID selection from
that reference, and remove the duplicate compact type index. All other safety
and booking instructions remain. The reference precedes role/task/history text;
it contains no run ID, timestamp, fixture or patient state.

Paid baseline entrypoint, **not run**:
`cd backend && .venv/bin/python -m evals.baseline_matrix --run-paid --max-cost-usd <approved ceiling>`.
It runs the same run_dev_case/scripted patient, fixtures, current scorer and
SpendGuard, 12 × 3 sequentially with both retry layers disabled. Each run's results
record the baseline config hash, reference hash and availability mode. JSONL rows
retain the shared observer's agent ID/config hash/availability fields. Source JSON SHA
is also recorded by the offline check.

## Tokenization and prefix evidence

`gpt-4o`, `tiktoken.encoding_for_model`, **o200k_base**:

- Rendered catalog/policies only: **5,894 tokens**, 16,848 UTF-8 bytes/characters.
- Catalog + baseline role message: **6,085 tokens**.
- System and initial task text: **6,626 tokens**, excluding tool schemas and API framing.
- Catalog SHA-256: `baea1382762b1177e7f21a5070a6dd38724fc910c965905b9eb9f96458436e4f`.
- Baseline config SHA-256: `68d02acb9a89a72c279c3410001e2b184438abce7f7c714ce39a0e87ddf4f623`.

Offline command: `cd backend && .venv/bin/python -m evals.baseline_check`.
Four independently constructed sessions vary state and history (startup, patient,
multi-turn, post-tool). The installed Pipecat adapter and OpenAI request serializer
produce identical system + initial-task prefixes and identical tool schemas.
AsyncCompletions.create is mocked and asserted never called: **zero network/API
calls, zero charge**. Prefix hash is
`229a149aaac9713487c58316390530f326048ec7f1fa0ef51197036132556eda`;
tool-schema hash is
`2a67a007bbb9a45add832a6b365357ec358fbc9d0284b2cf8ad46350cea433e8`.
This demonstrates stable serialization for cache eligibility, not actual server
cache hits. Terminal nodes retain the reference but can change task/tools.

Artifacts: [readable catalog](../backend/logs/evals/baseline-catalog-20261109.md),
[offline check](../backend/logs/evals/baseline-prefix-check-20261109.json).
Offline tool tests also complete identity confirmation, generated offer, consent
and exactly one booking through both arms without an LLM.

Final `make test`: 102 tests, 100 passed, 2 opt-in paid integrations skipped.
Six new baseline tests passed. `git diff --exit-code proposed-v2 -- backend`
was empty for tracked files: baseline additions leave the frozen implementation,
agent JSON, patient script, scorer and scenarios unchanged.

## Updated step 3 estimate — awaiting approval

Planning estimate: **$2.30–$3.30** for 36 baseline conversations with substantial
prefix caching and roughly 200–260 model calls. Suggested ceiling: **$5.50**,
no retries. No baseline paid calls are authorized or started yet.

Basis: proposed measured 204 calls/$1.01171. Offline serialized-text proxy:
initial message content 1,789 → 6,626 tokens; compact tool-schema JSON
643 → 594 tokens. Net approximately +4,788 input tokens/call. This proxy excludes
API framing and later history differences, so is an estimate, not billable usage.
At identical 204-call behavior, added input costs approximately $1.22 fully
cached or $2.44 uncached. Estimated total with all input cold is about $4.15;
260 calls at the same average size would approach $5.30. Actual baseline calls,
history growth and caching may differ, hence the allowance and explicit gate.

Frozen harness limitation for the final comparison: JSONL measures individual
model calls and groups patient turns; it does not directly time session.send's
complete wall-clock span. Any reconstructed turn span must be labeled with its
definition and must not be presented as voice end-of-speech latency.
