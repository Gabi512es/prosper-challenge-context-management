# Serialization and evidence fix: external-infra-v1.2

2026-11-10. Infrastructure-only work, within the 45-minute timebox. **No paid
calls.** Both agents, shared scheduling engine/runtime/tools/guards, scenarios,
patient behavior, model configuration, scoring and frozen rubric remain unchanged.
Evaluator semantics stay `external-eval-v1.1`; infrastructure is separately
versioned **external-infra-v1.2**. Restart is prepared, not approved or executed.
Voice Call B remains pending independently.

## Exact failure and fix

The old checkpoint at `backend/evals/external_eval.py:298` called
`json.dumps(report, default=list)`. Its observation came from
`asdict(engine.state)` and included `SessionState.last_horizon_end`, an aware
`datetime` set by slot search. JSON sent that value to `list`, raising
`TypeError: 'datetime.datetime' object is not iterable` before the report write.
The source and original traceback are retained in the v1.1 archive/history.

The active [checkpoint](../backend/evals/external_eval.py) now uses
[external_io.py](../backend/evals/external_io.py):

- `datetime` → ISO 8601 with its **original UTC offset preserved**, including
  nested values. Naive datetimes fail visibly; no timezone is inferred.
- `date` → ISO calendar date. Sets/frozensets → sorted arrays; normal JSON
  containers retain their structure. The in-memory result/state is not mutated.
- Every other unsupported object still raises `TypeError`. There is no catch-all
  `str`/`repr` conversion and non-finite floats are rejected.
- Reports serialize completely before touching the previous checkpoint, then
  write a temporary file, flush/fsync and atomically replace the report. Failed
  serialization/replacement leaves the previous valid checkpoint intact.

## Evidence survives final-report failure

Existing `TurnMetricsObserver` JSONL is reused unchanged. The evaluation-only
wrapper pattern already used for voice tool tracing is reused with explicit JSON
and durable start/result events; the unchanged fault wrapper remains inside it.
No new agent message is injected and tool inputs/results are not modified.

Each run writes an append-only, fsynced `<run_id>.events.jsonl`, independently
of the final report:

1. Attempt identity and original-attempt replacement link before starting.
2. Patient text before send; actual completed assistant text and context after
   each turn; turn start/finish and a session snapshot in `finally`.
3. Tool name/arguments **before** invocation, result/exception and elapsed time
   **before** handing the result back to the agent.
4. Every SDK admission: unique request ID, call/attempt/batch IDs, actual messages,
   model/limit and $0.32512 reservation **before** HTTP. No auth/header secrets.
5. Provider request ID when available, streamed raw model/tool deltas, SDK usage,
   exception/cancellation status, stream close and current separate budget ledgers.
   Raw model deltas are labeled separately from the actual code-generated
   assistant message; they are not assumed to have been shown to the patient.
6. Full completed conversation result before aggregate export, also saved as
   its own atomic `<run_id>.<attempt_id>.conversation.json` file. Batch completion
   or reporting abort includes final known budget state in the journal.

A request is never sent if its write-ahead evidence cannot be written. Journal
failure is sticky and stops further paid work. Existing model metrics remain a
second independent source, not a substitute for the request ledger. Checkpoints
require matching SDK admissions and complete SDK usage before certifying a
conversation's usage; a populated legacy row cannot turn missing cached usage
into zero or certify that every request was captured.

The arithmetic in `FinalSpendGuard` is unchanged: full $0.32512 per-request
reserve; complete usage releases excess; unknown/cancelled/failed usage retains
reserve. SDK/timeout retries remain off. Request IDs capture their call context,
so a later batch switch cannot reattribute an earlier request.

This protects against serialization/export failures and normal process exits.
A permanently full/unwritable disk still stops the run; it cannot be made to
produce new durable evidence. No hardware-loss guarantee is claimed. Extra
logging I/O may affect measured wall-clock latency; no extra model request is added.

## Offline validation

**49 tests passed, zero failures/errors, zero model/API calls.** Eleven new
persistence/request tests plus the 38 existing adapter/fault checks. [Machine
evidence](results/external-infra-v1.2-validation.json), [full test/replay record](results/external-offline-validation-v1.2.json),
[test implementation](../backend/tests/test_external_persistence.py).

The fixture uses the real shared scheduling tool handlers and public DEV data:
identity confirmation → slot search → generated read-back → patient yes → booking.
It produces actual `asdict(SessionState)`, confirmation and booked slot types,
including the original problematic `last_horizon_end` datetime. Nested aware
clocks, dates, sets and tuples exercise recursive encoding.

Evidence includes:

- The exact old `default=list` failure is reproduced on that realistic result.
- Offsets survive ISO round-trip exactly; unknown objects and naive datetimes fail.
- Successful initial/per-conversation checkpoints and final batch export.
- Deliberate final-export `OSError`: prior aggregate checkpoint, **both** independent
  conversation files, patient/assistant messages, tool arguments/results, original
  metric rows, SDK admission/usage/close records and terminal budget survive.
- A separate invalid final object raises without deleting evidence/checkpoints.
- Cancelled streaming preserves the partial model delta and full unknown reserve.
- Missing cached usage remains null/unknown, even alongside a populated legacy
  metric row; insufficient cap and failed write-ahead logging prevent HTTP.
- Restart scope is exactly two infrastructure replacements first, followed by all
  38 unrun labels, with no outcome-based selection.

All SDK streams in these tests are stubs and their temporary usage records are
removed; they are not new billable logs. Existing saved-trace replay stays
59 review-required, 12 failed, one infrastructure failure across 72 attempts,
with no common automatic-assertion disagreements. This is not a new accuracy score.

## Version and unchanged identities

- Infrastructure: `external-infra-v1.2`; evaluator/patient/scorer semantics:
  `external-eval-v1.1` unchanged.
- Active pin: `backend/evals/external_pin_v1_2.json`, SHA-256
  `032f9418860c650afbe3771ca947f7afc15b82cc5cda5ebdae1b5fbaf04375c8` (37 source/config/plan/test files plus installed packages).
- Config SHA-256: `97e54fe59f65c3e931c1c4865d8bd74a99a79cd59f883c6186ca426376aa24e1`.
- Frozen rubric SHA-256: `054cbbd261440e29d0c7bdf6749bbff56ac38023f11cdf130d1efef31d08e686`.
- Restart plan SHA-256: `bf9674be6c7c71db9b6465332da22e123592578128381f081e98854ad6f1a8f7`.
- Original v1.1 executable/pin archived in
  `docs/results/archive/external-eval-v1.1.zip` with provenance; historical
  failed-attempt journals/console/usage and $0.0923300 remain untouched.
- All 33 previously pinned files other than the infrastructure entrypoint remain
  byte-identical, including patient/scorer/fault logic, agents, catalog, model
  config and shared runtime. Original/revised/boundary dataset hashes match the
  earlier preflight. Full identities are recorded in the validation/pin artifacts.

## Historical attempts and billing exposure

The original two agent outcomes remain **unknown**, not retrospectively scored.
Their 18 saved usage rows price to $0.0923300. No original row, journal or cost
entry was overwritten. Both processes exited; no local paid execution continues.
However, neither old request ledger nor final guarded admission count survived.
Populated metric rows alone cannot prove coverage or reconstruct missing requests.

Under the original configured provider limits, dated prices, zero retries and
full-reservation guard, the existing evidence supports only these bounds:

| Historical batch | Known receipts | Conditional total charge bound | Additional unobserved-charge bound |
|---|---:|---:|---:|
| Held-out | $0.0466975 | $0.0466975–$5.00 | ≤ $4.9533025 |
| Robustness | $0.0456325 | $0.0456325–$2.00 | ≤ $1.9543675 |
| Combined | $0.0923300 | $0.0923300–$7.00 | ≤ $6.9076700 |

These bounds concern API usage at the configured rates, excluding credits, taxes
or price changes; they are not invoice reconciliation.

These are conditional **upper bounds, not estimates or claims of pending charges**.
At most 15 held-out or six robustness missing-usage reservations could fit the
remaining guard accounting, but that does not bound the count of unlogged requests
whose SDK usage may have settled. Unlogged-request count, actual invoice charges
and certified unspent balances remain unknown. Billing reconciliation would be
needed to certify a tighter historical balance. The new request ledger prevents
this same reporting failure from erasing those accounting transitions in a restart.

## Prepared restart and remaining cost estimate

`backend/evals/external_restart_v1_2.json` addresses attempts by labels only. It is
pinned against the immutable historical inventory and summary hashes. Order:

1. Proposed held-out HO-001 replacement, linked to original run/call ID.
2. Proposed robustness RW-001 replacement, likewise linked.
3. All 38 unrun conversations: remaining 15 held-out proposed, all 16 baseline,
   and remaining seven robustness. Each once. No case is selected because its
   agent passed or failed; those original outcomes are unknown.

This yields the original intended coverage: 32 held-out and eight separate
robustness conversations. History retains two original infrastructure failures
in addition to these 40 planned new attempts; they are not silently replaced in
costs or the audit trail. Frozen review requirements remain mandatory.

| Restart batch | New conversations | Expected incremental cost | Allowance proposal | Fresh cap proposal |
|---|---:|---:|---:|---:|
| Held-out | 32 | $1.51 | $4.50 | $5.00 |
| Robustness | 8 | $0.25 | $1.50 | $2.00 |
| Total | 40 | **$1.76** | $6.00 | $7.00 |

These remain historical x1 usage projections, not revised-set measurements.
Expected new cost plus known old receipts is about **$1.85**, excluding unknown
old charges. Cold-cache + 50% more-call proxies are $4.00946/$0.62778; the same
allowances include recovery headroom. Cache/turn/timeout variation and unknown
usage can cause early admission stops. Voice/STT/TTS cost remains unmeasured.

The proposed $5/$2 limits are **fresh incremental approval limits**, not a claim
that the earlier caps are unspent. Combined old and new conditional maximum
would be $14 if those fresh caps were approved; expected spend is not that upper
bound. If the original $5/$2 must instead remain lifetime caps, the old evidence
does not certify a positive remaining balance without billing reconciliation.
No assumption or new approval has been made on the user's behalf. Detailed
[budget proposal](results/external-restart-budget-v1.2.json).

## Reproducible commands

```sh
cd '/Users/gabrielernoult/Desktop/Prosper AI/prosper-challenge-context-management/backend'
HELDOUT='/Users/gabrielernoult/Desktop/Prosper AI/Evals/revised-evaluation-v1/heldout.reviewed.json'
ROBUSTNESS='/Users/gabrielernoult/Desktop/Prosper AI/Evals/revised-evaluation-v1/robustness.reviewed.json'
RESTART_PLAN='/Users/gabrielernoult/Desktop/Prosper AI/prosper-challenge-context-management/backend/evals/external_restart_v1_2.json'

# Free preparation, already completed. No patient dialogue or outcomes printed.
LOGURU_LEVEL=ERROR .venv/bin/python -m evals.external_eval prepare-restart \
  --heldout-path "$HELDOUT" --robustness-path "$ROBUSTNESS" \
  --restart-plan "$RESTART_PLAN"
```

The following command is **prepared only**. Do not run before a new explicit
approval. Set `RESTART_APPROVAL_REF` to that approval reference first; an empty
reference is rejected before any request. The proposed caps below are fresh
incremental limits, not verified balances left from the earlier approvals.

```sh
LOGURU_LEVEL=WARNING .venv/bin/python -m evals.external_eval run-paid \
  --batch restart --restart-plan "$RESTART_PLAN" \
  --heldout-path "$HELDOUT" --robustness-path "$ROBUSTNESS" \
  --heldout-max-cost-usd 5 --robustness-max-cost-usd 2 \
  --approval-ref "$RESTART_APPROVAL_REF"
```

One command is used so the two independent budget ledgers persist while the job
order alternates between datasets. It executes the two replacements first,
then the remaining 38. If either cap cannot admit a request or evidence/reporting
fails, the job stops and preserves partial output. No automatic resume/retry,
selective rerun, or outcome-dependent job selection exists.


No paid restart was run. The completed DEV comparison/scaling evidence remains
available for submission, final semantic pass rates remain unavailable/pending,
and Voice Call B remains pending manual verification.
