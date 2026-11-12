# Completed final restart, semantic review pending (2026-11-10)

- [Measured results, limitations and accounting](../final-evaluation-restart-v1.2.md)
- [40-conversation manual-review table and trace links](final-restart-v1.2/review-table.md)
- [Per-conversation automatic results](final-restart-v1.2/conversations.json)
- [Usage/cache/latency and provenance summary](final-restart-v1.2/summary.json)
- [Failure flags and driver-fidelity caveat](final-restart-v1.2/failure-inventory.json)

All 40 attempts ran once, replacements first. $1.4072150 measured model cost,
211 completely accounted requests, no new retained exposure. Raw status 24
review-required/16 failed, not a semantic pass rate. All semantic review remains
pending. Fifteen held-out attempts are driver-limited; preserve the RW-005
booking-count/driver-fidelity discrepancy rather than silently rescoring it.
Older failed-attempt costs and missing coverage below remain historical facts.

---

# Current infrastructure repair, no paid restart (2026-11-10)

- [Fix, validation, billing bounds, restart commands](../external-infrastructure-v1.2.md)
- [49 offline tests and unchanged-source evidence](external-infra-v1.2-validation.json)
- [Full test/replay record](external-offline-validation-v1.2.json)
- [Hash-verified restart preparation: 2 replacements + 38 unrun](external-restart-preflight-v1.2.json)
- [Remaining budget proposal and historical exposure bounds](external-restart-budget-v1.2.json)
- [Archived v1.1 executable provenance](archive/external-eval-v1.1.provenance.json)

Semantic evaluator/rubric remain unchanged. Old failed-attempt records below are
historical and unmodified. No paid call or restart was made during this repair.

---

# Current final execution (2026-11-10)

- [Interrupted approved execution report](../final-evaluation-execution.md)
- [Usage, exposure, latency and failure summary](final-evaluation/summary.json)
- [All 40 planned conversations and review links](final-evaluation/review-table.md)
- [Per-conversation machine inventory](final-evaluation/conversations.json)
- [Transcript/tool availability, with no reconstruction](final-evaluation/transcripts-and-tools.md)
- [All 18 priced model-call receipts](final-evaluation/model-call-receipts.json)
- [Pre-execution identity verification](final-execution-identity-check.json)

No final semantic passes are assigned. Both attempts stopped after their first
conversation at the immutable evaluator's datetime checkpoint serialization.
Known usage cost $0.0923300; complete request coverage cannot be certified because
terminal accounting was lost. No repair, retry or new paid run was made.

---

# Reviewer evidence index

All copied measurements below are existing development/scaling evidence.
**Final evaluation was attempted and interrupted by report-writing failures.**
Two conversations produced 18 usage rows but no durable conversation results;
38 planned conversations never ran. Final semantic results remain unavailable.
The current report and all surviving evidence are linked below. Earlier
preparation and x1/scaling artifacts retain their historical provenance.

## Official x1 comparison

- [Readable tables and limitations](x1-comparison-v5.md)
- [Machine summary](x1-summary.json)
- [Manual failure/question annotations](x1-manual-review.json), not a rescore
- [Proposed raw report with transcripts/tool contexts](comparison-proposed-v2-20261109-180827-8752c3.results.json)
- [Proposed raw model-call usage/timing](comparison-proposed-v2-20261109-180827-8752c3.jsonl)
- [Baseline raw report with transcripts/tool contexts](comparison-baseline-20261109-182321-c4ee5f.results.json)
- [Baseline raw model-call usage/timing](comparison-baseline-20261109-182321-c4ee5f.jsonl)
- [Selected false-statement, handoff and slow-turn evidence](offline-investigation-evidence.json)
- [Investigation, observed versus inferred](../offline-investigation.md)

Raw scores are 29/36 versus 30/36. Accuracy is inconclusive on this small DEV
set. One proposed request has missing usage; its actual charge stays unknown.
The historical 28/36 calculation is counterfactual only.

## Completed scaling

- [Measured subset results, projections separated](scaling-v3-measured.md)
- [Saved aggregate/manual analysis](scaling-v3-analysis.json)

Search-only is exploratory and does not replace proposed-v2. Indexed x50 and
baseline x10+ costs are projections, not paid measurements. Scaling is closed;
no additional variant or repeat is authorized.

## Final preparation, not paid results

- [Current byte-hash verification, versions and budget](final-evaluation-plan.json)
- [Offline builder identities and installed package versions](agent-identities.json)
- [Execution compatibility decision and preparation command](../final-evaluation-plan.md)
- [Pinned external adapter, contract and exact commands](../external-adapter.md)
- [Public/synthetic offline validation and saved replay](external-offline-validation.json)
- [Sanitized external schema preflight failure](external-preflight.json)
- [Latest complete structural compatibility audit](fixture-compatibility-audit.json)
- [Read-only audit command source](fixture_contract_audit.py)
- [Consolidated compatibility diagnosis and review checklist](../fixture-compatibility-report.md)

The adapter changes patient/grading semantics and is a new version, not a
replacement score for v5. It passed 27 public/synthetic checks before any
private schema access. The subsequent automated preflight stopped on a held-out
availability-fixture validation mismatch; robustness schema was not reached
in that historical first-error command. The later authorized complete
structural audit identifies substantive capability-invalid held-out records,
not a formatting issue. Robustness fixture arrays initialize, but additional
metadata and criteria remain unsupported. No lossless conversion was made.
No private scenario contents were printed or copied. Final paid execution is
blocked; arbitrary prose criteria still require review and cannot be passed
automatically. No final model calls were made.

Call A was user-reported verified in voice. **Call B remains pending manual
verification** and does not gate an approved text evaluation.

## Copy provenance

[provenance.json](provenance.json) records each copied file's original repo path,
SHA-256, size and evidence label. Copies are byte-identical to their source;
no score or wording is rewritten. Relative links inside verbatim copied
Markdown retain the original source directory context; this index provides
working navigation to the included files. Raw reports also retain their
original local metrics paths; use the matching JSONL copy here for review.
Full ignored local scaling logs are not bundled; their original locations and
run IDs remain recorded in the scaling report. Selected investigation evidence
was extracted only from saved data, with original hashes/indices/line numbers.


Reviewed evaluation copies (2026-11-10), no paid execution:

- `external-preflight-v1.1.json`: consolidated complete-dataset compatibility, hashes, write-fault proofs and mandatory-review inventory.
- `revised-assets-manifest.json`: exact redacted source-change index; private full before/after manifest and scenario copies remain outside Git.
- `external-offline-validation-v1.1.json`: 38 DEV/synthetic tests and 72 saved-trace replays; no final scores.
- `revised-evaluation-pricing.json`: 32 held-out + 8 separate robustness projections; proposals only.
- `revised-evaluation-integrity.json`: frozen arms/shared files/legacy evaluator unchanged against historical pin.
- `archive/external-eval-v1.zip` and provenance: original executable v1/pin/evidence, no private scenarios.
- `archive/final-evaluation-plan-external-v1.json`: superseded 72-conversation preparation.

Current narrative, review rubric and commands: `../revised-evaluation-preflight.md`.
