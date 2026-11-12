# Approved final text evaluation: interrupted execution

2026-11-10. Both approved batches were started exactly once using pinned
external-eval-v1.1. **Both stopped after their first conversation because the
report checkpoint could not serialize a datetime.** No agent, fixture, patient
driver, tool, guard, prompt, scorer or rubric was changed. No retries, selective
reruns or additional experiments were made.

The offline validation missed this report-writing defect. It is an evaluation
infrastructure failure, not evidence of an agent failure or a final score.

## Identities and authorization

Before spending, the executable verified all pinned sources/packages/config,
the full revised and original dataset hashes, rubric, catalog, git HEAD and
rebuilt arm identities. [Identity receipt](results/final-execution-identity-check.json).
Adapter pin: `529c0714f452d158d91fcde98237d0728fa17775e89ab3e7a84e5f34721259e5`.
Rubric SHA-256: `054cbbd261440e29d0c7bdf6749bbff56ac38023f11cdf130d1efef31d08e686`.
Git: `a5b124f7aa3ffa9d7ebcd32a7f76c837c95486c8`. Full agent/catalog/config identities and dataset hashes
remain in the receipt and raw result journals. The pre-run hashes also match
post-execution; no execution source was repinned or edited.

Approval reference used by both commands:
`user-approval-2026-11-10-heldout32-cap5-robustness8-cap2-once-no-retries`.
The user's approval supersedes the historical `paid_authorized: false` proposal
field in the immutable pinned configuration; that file was deliberately not edited.
Held-out cap $5; independent robustness cap $2. Both SDK and timeout retries
were disabled, with one active request at a time and the documented reserve.

## Coverage and every conversation's result

| Batch | Planned | Attempted | Durable conversation results | Infrastructure failures | Not run |
|---|---:|---:|---:|---:|---:|
| Held-out, both arms | 32 | 1: proposed HO-001 | 0 | 1 | 31 |
| Robustness, proposed only | 8 | 1: RW-001 | 0 | 1 | 7 |
| Total | 40 | 2 | 0 | 2 | 38 |

All 16 baseline conversations were never reached. There is no final comparison,
no final semantic pass rate and no conversation counted as passed. Neither
attempt has durable automatic assertions or booking outcomes; the raw journals'
empty `runs` arrays are **not** evidence that no model requests occurred.

The [40-row review table](results/final-evaluation/review-table.md) lists each
planned conversation, expected outcome label, execution/infrastructure status,
links to exact expected criteria and required semantic checks, and remaining
evidence. Its [machine inventory](results/final-evaluation/conversations.json)
preserves every review field path with assertions explicitly null where missing.
The automatically exported detailed review packet stays outside the repository
at `/Users/gabrielernoult/Desktop/Prosper AI/Evals/final-evaluation-review-v1.1/review-packet.md` (SHA-256 `ce7696b411b4a73d0ce8cd55f0e8f2f0759d8d702ca0b9cc763191b7b515f840`). It copies no
source patient dialogue or complete patient fact card and does not adjudicate
any outcome. Review requirements are not silently waived or marked passed.

RW-002/RW-003/RW-008 were not reached. Their intended write faults therefore
have **no live trigger/recovery result**, irrespective of the earlier offline
protocol proofs. No recovery pass is assigned.

## Known usage and cost

The saved JSONL rows are durable model-call receipts. All 18 have reported
prompt, cached and output usage. Prices are the pinned 2026-11-07 GPT-4o rates:
$2.50/M uncached input, $1.25/M cached input, $10/M output. These costs are
calculated from actual saved usage, not extrapolated to unrun conversations.

| Batch / arm | Model calls saved | Prompt | Cached input | Uncached input | Output | Known usage cost USD |
|---|---:|---:|---:|---:|---:|---:|
| Held-out / proposed | 9 | 29,747 | 24,064 | 5,683 | 241 | $0.0466975 |
| Held-out / baseline | 0, not run | — | — | — | — | $0, no execution |
| Robustness / proposed | 9 | 30,281 | 26,368 | 3,913 | 289 | $0.0456325 |
| Total recorded | 18 | 60,028 | 50,432 | 9,596 | 530 | **$0.0923300** |

Proposed, both batches combined: 60,028 prompt + 530 output = 60,558 tokens;
50,432 cached input tokens. Known charges: uncached input $0.0239900, cached
reads $0.0630400, output $0.0053000. Cache read shares: held-out
80.90%, robustness
87.08% of reported prompt tokens.
Additional cache-write fee is $0 under the configured rate card; separate
write-token counts and separately attributed population cost are **not reported**,
not guessed. Voice/STT/TTS, taxes, credits and invoice reconciliation are not measured.

**Missing-usage/exposure distinction:** zero of the 18 saved rows have missing
usage. However, both terminal checkpoints failed, so the final guarded admission
count and exposure balance were lost. The initial journals' $0/zero requests
are stale pre-attempt snapshots, not the actual spend. Complete request coverage
cannot be certified from those snapshots; unlogged request count, final actual
total charge and final in-flight/unknown reserve stay **unknown**, not zero.

The immutable guard reserves $0.32512 before every request (128000 × $2.50/M
+ 512 × $10/M), settles on complete usage and retains the full reserve on missing
usage/cancellation. No cap-stop error appears in either console; the observed
stop reason is serialization. Under the documented provider-limit/pricing/guard
assumptions, total allowed exposure remains bounded by the separate $5/$2 caps.
The most conservative additional unobserved-spend envelopes are
$4.9533025 and
$1.9543675, respectively (cap minus
known receipts). **These envelopes are not measured pending charges or an
assertion that usage was missing.** The actual final reserve ledger is unavailable.

## Latency and infrastructure visibility

| Batch / proposed | Saved LLM calls | LLM processing p50 | LLM processing p95 | Maximum | End-to-end patient-turn latency |
|---|---:|---:|---:|---:|---|
| Held-out | 9 | 1.061 s | 1.519 s | 1.698 s | unavailable |
| Robustness | 9 | 1.141 s | 1.909 s | 2.162 s | unavailable |

These are per-model-call processing durations, **not completed text turns or
voice latency**. Quantiles use linear interpolation at `(n−1) × p`; startup calls
are included. Model processing sums are 10.377 s and 11.321 s; each saved call
also has a TTFB receipt. Patient-turn groups 0–4 appear in each log, but no
wall-clock turn timings survived. Tool time and runner waiting are unobserved;
no synthetic end-to-end latency is reconstructed from call sums or timestamps.

There are two confirmed writer infrastructure failures. Neither console contains
a model timeout message, and all saved rows have completed model metrics; because
the conversation-level result is missing, this does not certify a zero timeout
count for all attempted work. Baseline latency is not measured, because no
baseline conversation ran.

## Transcript/tool evidence availability

[Transcript and tool availability manifest](results/final-evaluation/transcripts-and-tools.md).
**No complete patient/assistant transcript or tool arguments/results survived**
either first-attempt checkpoint. Both runtime context and grading result existed
only in memory until that checkpoint. The model-call JSONL contains metadata,
not dialogue. The two raw journals, both console tracebacks and all 18 usage
rows are preserved verbatim with provenance hashes in
[summary.json](results/final-evaluation/summary.json). Individual priced model
receipts are [model-call-receipts.json](results/final-evaluation/model-call-receipts.json).
No missing conversation has been reconstructed from expected facts, model tokens,
previous DEV runs, tool behavior or a paid reproduction.

## Factual failure inventory

| Category | Evidence-supported result |
|---|---|
| Infrastructure failure | 2: held-out proposed HO-001 and robustness proposed RW-001; checkpoint datetime serialization |
| Wrong booking | Unassessable: actual bookings were not persisted |
| False refusal | Unassessable: no assistant transcript persisted |
| Incorrect internal selection | Unassessable: final state/tool results were not persisted |
| False statement to patient | Unassessable: no assistant transcript persisted |
| Unnecessary clarification | Unassessable: patient/assistant exchanges were not persisted |
| Not run | Remaining 38 planned conversations; no agent judgment |

**Observed control path:** `run_one` returns an observation containing
`asdict(engine.state)`; `SessionState.last_horizon_end` is a datetime after a
slot search. `run_batch` appends that result in memory, removes `pending_attempt`
in memory, then calls `checkpoint`. At `backend/evals/external_eval.py:298`,
`json.dumps(report, default=list, indent=2)` sends the datetime to `list`, which
raises `TypeError: 'datetime.datetime' object is not iterable`. Serialization
fails before `write_text`, so only the older pending-attempt journal survives.
The traceback proves failure occurs at that checkpoint; the frozen model schema
and code explain the unsupported datetime path. Exact patient behavior, tool
sequence and booking outcome cannot be established from the surviving data.

This is a missing end-to-end checkpoint test in the evaluation infrastructure:
the DEV/synthetic checks exercised agent and fault behavior, but did not prove
that a real searched-session report could be serialized and durably saved.
The offline test count did not establish that property.

No repair was made. A future evaluation-only correction would need explicit
serialization of datetime/set values and durable conversation/tool evidence
before aggregate checkpointing, plus a zero-cost serialization check. Any
version change or further paid execution requires a new decision/authorization;
neither failed batch has been resumed or silently rerun.

Voice Call B remains **pending manual verification**, independently of these
infrastructure failures. Final held-out/robustness semantic results remain
unavailable, with all required review incomplete or unassessable.
