# Final approved text restart: measured results, semantic review pending

2026-11-10. **Completed all 40 planned attempts once.** No extra experiments,
outcome-based retries, source changes, cap stops or execution/logging defects.
Two infrastructure replacements ran first, linked to the original failed run/call
IDs, then all 38 previously unrun conversations. The old attempts remain in history
with unknown agent outcomes and separate billing uncertainty.

Run: `external-infra-v1.2-restart-20261110-175004-ec9627`. Approval reference:
`user-approval-2026-11-10-1649UTC-restart40-v1.2-fresh-heldout5-robustness2`. Executable exit status 0;
40 per-conversation files and the final report were saved. Runtime sources,
scenarios, patient behavior, scoring and frozen rubric were unchanged throughout.
Voice Call B remains **pending manual verification**.

## Results: automatic checks are not semantic passes

| Dataset / arm | Attempts | All auto checks true | Any auto failure | Driver-limited / not assessable | Model calls | Actual model cost USD |
|---|---:|---:|---:|---:|---:|---:|
| heldout/proposed | 16 | 9 | 7 | 7 | 76 | $0.3566525 |
| heldout/baseline | 16 | 8 | 8 | 8 | 62 | $0.6712800 |
| robustness/proposed | 8 | 7 | 1 | 0 | 73 | $0.3792825 |

Overall raw status: **24 review-required, 16 failed**. Every conversation still
has mandatory semantic review. None is counted as a final pass. Two held-out
correction cases (one per arm) also have unknown automatic checks for an
unsupported correction dimension. All frozen assertion results are retained.
**Final semantic pass rates are pending**, not 9/16 versus 8/16 accuracy.

Fifteen held-out attempts are explicitly `evaluation_limited=true` and
`agent_assessment=not_assessable`: the scripted interaction stopped without
achieving the expected booking. Their automatic failures must be reviewed for
agent behavior versus patient-driver capability/fidelity; they are not all
confirmed agent failures. There were no model/transport errors or turn timeouts.
This run completed attempt coverage; it does not make unsupported criteria
automatically scorable or establish a valid semantic accuracy comparison alone.

The proposed arm has one more automatically satisfied held-out set and a lower
measured cost. **Baseline used fewer model calls, 62 versus 76**. These are
one-repetition, review-pending observations, not significant accuracy differences.
Low cost partly reflects early unsuccessful/driver-limited conversations; it
must not be attributed to context design or caching alone.

## Complete evidence and per-conversation review

- [40-row manual-review table](results/final-restart-v1.2/review-table.md): each
  case/arm, expected outcome, all automatic failures/unknowns, runtime/driver status,
  calls/cost, transcript and exact expected semantic criteria links.
- [Per-conversation machine inventory](results/final-restart-v1.2/conversations.json)
  and [machine summary](results/final-restart-v1.2/summary.json).
- [All patient/assistant transcripts and tool arguments/results](</Users/gabrielernoult/Desktop/Prosper AI/prosper-challenge-context-management/backend/logs/evals/external-infra-v1.2-restart-20261110-175004-ec9627.exports/all-transcripts-and-tools.md>).
  Individual `.transcript.md` and `.evidence.json` files are in
  `/Users/gabrielernoult/Desktop/Prosper AI/prosper-challenge-context-management/backend/logs/evals/external-infra-v1.2-restart-20261110-175004-ec9627.exports`. Forty conversations exported, including startup,
  actual generated speech, every tool call/result/exception and replacement links.
- [Original result report](</Users/gabrielernoult/Desktop/Prosper AI/prosper-challenge-context-management/backend/logs/evals/external-infra-v1.2-restart-20261110-175004-ec9627.results.json>),
  [model-call usage/timing JSONL](</Users/gabrielernoult/Desktop/Prosper AI/prosper-challenge-context-management/backend/logs/evals/external-infra-v1.2-restart-20261110-175004-ec9627.jsonl>),
  [append-only message/tool/SDK request journal](</Users/gabrielernoult/Desktop/Prosper AI/prosper-challenge-context-management/backend/logs/evals/external-infra-v1.2-restart-20261110-175004-ec9627.events.jsonl>).
  SHA-256 provenance is in summary.json. Raw model deltas are separate from actual
  assistant messages; discarded drafts are not presented as spoken claims.
- The private expected-criteria packet remains outside Git at
  `../Evals/final-evaluation-review-v1.1/review-packet.md`; review links point there.
  Source scenarios were not copied into the agent or altered.

Raw evidence/exports under `backend/logs/` are ignored by Git: preserve them
separately when transferring the repo. No missing trace has been reconstructed.

## Usage, cache and billing exposure

| Dataset / arm | Prompt including cache | Actual cached reads | Uncached prompt | Completion | Cached share |
|---|---:|---:|---:|---:|---:|
| heldout/proposed | 228,081 | 187,264 | 40,817 | 2,053 | 82.10% |
| heldout/baseline | 478,056 | 435,072 | 42,984 | 1,998 | 91.01% |
| robustness/proposed | 256,473 | 226,432 | 30,041 | 2,114 | 88.29% |

**Restart total: $1.4072150**, split held-out **$1.0279325** under fresh $5 and
robustness **$0.3792825** under fresh $2. Token totals: **962,610 prompt**,
**848,768 cached input**, **113,842 uncached input**, **6,165 output**.
Dated 2026-11-07 rates, unchanged from the approved pin: $2.50/M uncached input,
$1.25/M cached input, $10/M output. Actual charges at those rates: uncached
$0.2846050, cache reads $1.0609600, output $0.0616500. These are usage-priced model
costs, not a reconciled cash invoice (taxes/credits/price changes excluded).

Additional cache-write fee is $0 under that rate card. Separate cache-write tokens
and separately attributed cache-population cost are not exposed and stay null.
Uncached input is not assumed to be all cache-write work. No STT/TTS, ElevenLabs
or total voice-call cost is measured by this text run.

**Request accounting is complete for this restart:** 211 durable reservations,
211 complete SDK usage records, 211 closed requests and 211 model metric rows.
Each conversation's SDK admission/usage coverage matches its guarded count.
There are no SDK exceptions, missing usage, unresolved IDs or retained reserves.
Final accounted amounts equal actual usage-priced costs; **new outstanding
exposure is $0**. The $0.32512 full-request reservation was retained before HTTP
and released only on complete usage. No cap was reached. The fresh allowances
have not authorized any further requests after these 40 jobs.

Historical attempts remain separate: **$0.0923300 known**, with final request
coverage/ledger lost. Combined known model cost is **$1.4995450**. The earlier
additional unobserved-charge bound is still **$6.9076700** under the old $5/$2 guard
assumptions; that is a bound, not an estimate of pending charges. Thus the combined
old-plus-new configured-rate cost is conditionally between $1.4995450 and
$8.4072150. The restart does not resolve or guess the old invoice total.

Automatically correct booking-field/confirmation counts: held-out proposed two,
baseline one; robustness four (five actual bookings). Whole-group cost per such
booking, including failed/no-booking cases: $0.17832625, $0.6712800 and $0.094820625.
These are **automatic booking-field metrics**, not final semantic success costs.

## Measured text-mode latency and infrastructure

| Dataset / arm | Complete patient turns | p50 s | p95 s | Max s | Infra failures | Incomplete turns/timeouts |
|---|---:|---:|---:|---:|---:|---:|
| heldout/proposed | 33 | 2.470 | 3.460 | 4.816 | 0 | 0 |
| heldout/baseline | 27 | 2.621 | 4.160 | 4.437 | 0 | 0 |
| robustness/proposed | 33 | 2.384 | 3.187 | 3.847 | 0 | 0 |

Monotonic complete patient-turn latency includes tools, follow-up model calls and
instrumentation, excludes startup and close, and excludes STT/TTS. Quantiles use
linear interpolation at `(n−1) × p`. LLM processing/TTFB and startup summaries are
in summary.json. Zero incomplete turns and zero infrastructure/runner errors were
observed; driver-limited conversations are a different category. No time is
imputed to unsupplied patient answers or unobserved voice behavior.

## Fault recovery and factual failure inventory

All three intended robustness faults were actually exercised **once at booking
write after patient consent**: RW-002 technical error, RW-003 slot loss, RW-008
slot loss. Each has a true `triggered` and `write_after_consent` assertion and a
persisted tool failure result. Their other automatic checks pass; semantic
recovery quality remains review-required. No recovery pass is inferred merely
from the earlier offline protocol proofs.

[Failure inventory](results/final-restart-v1.2/failure-inventory.json) preserves
all 16 raw automatic failures and distinguishes automatic flags from semantic
judgments:

| Category | Observed evidence / review status |
|---|---|
| Wrong booking | **One frozen automatic flag: RW-005**, because one booking was written while zero was expected. Agent-level attribution unresolved; see below. |
| Incorrect internal selection | Three flags per held-out arm, listed with actual state evidence in the per-case files. These are not automatically spoken false claims. |
| False refusal | Not adjudicated; do not infer from a missing booking. |
| False statement to patient | Not adjudicated; do not infer from an internal ID mismatch. |
| Unnecessary clarification | Driver logs one per held-out arm; complete semantic review may identify more. |
| Infrastructure failure | None in this restart. Two previous report-writer failures remain separate historical infrastructure failures. |
| Patient-driver limitations | 15 held-out runs marked limited/not assessable; review actual supplied replies before assigning agent blame. |

**RW-005:** the actual patient requests a flu shot, supplies identity, confirms
identity, then explicitly says “Please book it.” The booking matches that recorded
service/provider/site and the patient-visible read-back. No human/staff/transfer
request appears in the actual patient messages. Yet frozen expected booking
count is zero and semantic criteria include a patient-requested handoff. This is
an observed **driver-fidelity/test-intent discrepancy**, not enough evidence of a
confirmed agent wrong booking. The raw failure/flag remains untouched; it is not
promoted to pass, and no rule or expectation was changed. The full transcript and
criteria packet support manual review of why the intended request was not delivered.

No behavior/scorer changes or reproductions followed any finding. Unknown semantic
judgments stay pending under the frozen rubric; any proposed correction requires
a separate decision and new version, not post-hoc tuning of these results.

## Reproducibility and remaining work

Infrastructure `external-infra-v1.2`; evaluator semantics `external-eval-v1.1`.
Pin `032f9418860c650afbe3771ca947f7afc15b82cc5cda5ebdae1b5fbaf04375c8`;
plan `bf9674be6c7c71db9b6465332da22e123592578128381f081e98854ad6f1a8f7`;
rubric `054cbbd261440e29d0c7bdf6749bbff56ac38023f11cdf130d1efef31d08e686`.
Configured alias `gpt-4o`; SDK responses reported `gpt-4o-2024-08-06`.
Git `a5b124f7aa3ffa9d7ebcd32a7f76c837c95486c8`; exact agent revisions, model config, package versions,
fixture clock/mode and original/revised/boundary hashes are in summary.json and
[pre-run verification](results/restart-v1.2-identity-check.json). Post-run pin/hash
verification succeeded; no source or scenario changes.
[Post-run integrity and request reconciliation](results/final-restart-v1.2/post-run-integrity.json). No retries or additional
experiments. Do not reuse unused caps as authorization for another run.

Next work is frozen-rubric semantic review of all 40 transcripts, including driver
fidelity and missing/unsupported criteria. Final semantic pass rates stay pending
where any required review is incomplete. Keep the small DEV comparison and scaling
claims separate from these review-pending private results. Voice Call B remains a
separate pending manual check. No automatic repeat is scheduled or authorized.
