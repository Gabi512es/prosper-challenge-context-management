# Current reviewed-copy status: reviewed evaluation v1.1 (2026-11-10)

The user authorized proposed revised copies. Both complete copies pass offline
preflight; execution and review are **pending approval**. Held-out is now 32
conversations, robustness a separate eight. Proposed budgets: $1.51/$0.25
expected proxies, $4.50/$1.50 allowances, $5/$2 caps. No paid calls performed.
The complete current source-scope revision, hashes, 38 offline tests, actual-write
fault checks, unsupported/manual criteria and commands are in
[the consolidated preflight](revised-evaluation-preflight.md). Both arms remain
unchanged; Call B remains pending. **The older material below is historical**:
its original-copy blocker and 72-conversation proposal do not describe the
reviewed-copy plan. Historical external-eval-v1 is archived unchanged.

---

# Fixture compatibility: consolidated read-only report

2026-11-10. **Substantive blocker; no conversion implemented.** No paid calls,
agent/engine/scorer changes, scenario edits, normalization, record dropping or
new evaluator redesign. Historical external-eval-v1 remains pinned unchanged.
Voice Call B remains pending manual verification independently.

## 1. Exact diagnosis

The existing `SchedulingEngine._validate_slots` rejects four held-out fixture
records at these zero-based field paths:

```
scenarios[1].availability_fixture[0].location_id
scenarios[2].availability_fixture[0].location_id
scenarios[7].availability_fixture[0].location_id
scenarios[7].availability_fixture[1].location_id
```

Validator condition (`backend/scheduling/engine.py:566`):

```python
appointment_type.required_capability in location.capabilities
```

For these records the required capability is nonempty and that condition is
false. All referenced entities exist, and their provider/type and provider/site
relations pass. The service/site capability relation does not.

| Structure | Expected | Supplied |
|---|---|---|
| Fixture | Array of slot objects | Array of slot objects |
| Each object | slot_id, provider_id, location_id, appointment_type_id, start, end; all strings | Exactly those six fields, all strings |
| Time interval | Aware ISO start/end, start before end | All 42 intervals satisfy this structural check |
| location_id meaning | Existing catalog site with the appointment type's required capability | Existing catalog site without that capability, for four records |

This is **substantive data validity**, not a string/object/date formatting
issue. `malformed_availability` was the v1 adapter's broad error wrapper; it did
not prove formatting was wrong. This diagnosis exposes field names, types and
validator conditions, never dialogue, expected outcome values, entity values
or complete cases. Prior generic documentation mentioning duration validation
was overbroad: this engine initializer checks references, provider relations
and capability. Duration is not this failure condition.

## 2. No lossless mapping exists under the authorized constraints

Keeping the slot identity, provider, site, service, exact interval and timezone
unchanged leaves the failed capability condition unchanged. A representation
conversion cannot create a missing catalog capability. Moving the slot to a
different site, substituting a service, changing a catalog relation, bypassing
initialization or removing the record would change the data/contract or frozen
engine behavior. None was done.

**Required source-owner decision:** were these meant to be valid available slots,
or deliberately invalid candidate records? If the former, correcting and
refreezing fixtures with new hashes needs separate authorization. If the latter,
the source contract and frozen engine initializer disagree about what an
availability fixture may contain; accepting such records would need an explicit
contract/runtime decision beyond this lossless-boundary task. They cannot be
silently treated as unavailable or excluded from a partial final batch.

Adapter remains **external-eval-v1**, pin SHA-256:
`dbd24883c42ad0c0188bb8b9cc5dab0aa30b133a62195465c94787cdebc7efaa`.
Diagnostic version is `fixture-compatibility-audit-v1`; it does not convert or
grade inputs. Conversion version and normalized-input hashes are **not
applicable/null** because no normalized evaluation input was produced. Do not
mistake a source hash or diagnostic hash for a normalized-input hash.

Source files are unchanged; complete recorded SHA-256s still match:

- Held-out: `d41abdad3defe405a48becc55a97d4d153c3c3b27a4eff5f5518db8a2dedd1b6`
- Robustness: `c5de085b51996c51afaa9dbc3b40c392452d0eec28760b422ced2a6f74aa6c19`

## 3. Both complete datasets audited automatically

Every complete fixture array and every scenario body was checked independently,
in addition to existing adapter dataset validation. Source counts and label
uniqueness were checked without using labels to select behavior. No private
contents were printed/copied or used to tune. The diagnostic records its own
script hash separately and verifies source bytes before/after inspection.

| Compatibility metric, not outcome grading | Held-out | Robustness |
|---|---:|---:|
| Scenarios visited | 16 | 8 |
| Fixture records visited | 31 | 11 |
| Individual records accepted by engine | 27 | 11 |
| Individual records rejected by engine | 4 | 0 |
| Complete fixture arrays accepted / total | 13/16 | 8/8 |
| Aware, ordered ISO time intervals | 31/31 | 11/11 |
| Scenario bodies accepted by v1 | 6/16 | 0/8 |
| Complete dataset executable unchanged | No | No |

Held-out first failure per scenario body: four unsupported patient-fact cases,
three unsupported-assertion cases, one unsupported factual-assertion case and
two fixture-validation cases. These are first-error buckets, not disjoint root
causes: the third capability-invalid case has an earlier unsupported-field
failure. Do not add those counts to the independent fixture totals.

Robustness has five additional contract fields and a string `source_basis`
scenario field not admitted by v1. Thus the full dataset header and each case
body stop before deeper validation. The independent field inventory also records
unsupported assertion/fact fields; fixture validity alone is not full adapter
compatibility. No metadata/criterion was discarded just to make preflight pass.

[Machine audit](results/fixture-compatibility-audit.json) includes all structural
paths/types and aggregate counts. All 24 cases were visited; no claim is made
that checks after a particular first failure ran or that any case passed an
agent evaluation. No final assertions or model outputs were generated.

## 4. Automatic checks versus required transcript review

Once inputs are compatible, the pinned adapter can automatically check the
declared supported booking count/fields, confirmation, provider-resolution
chronology, explicit earliest slot, ambiguity/correction state, supported
location/phone/hours facts, unknown-provider acknowledgement, structured policy
codes and structured text/tool predicates. General checks cover offer location,
unrecorded callback wording and a next step after no matching slots. These
heuristics are not a semantic guarantee about every spoken claim.

**Those checks were not executed on private cases in this structural audit.**
Automatic results and `required_review` remain separate. Required review blocks
pass; unsupported structured criteria block execution rather than vanish.

The field-only inventory records additional held-out requirements involving
decision-time provider identity, explaining a gate before alternatives, unknown
services, different factual fields, service corrections/candidate sets and
preference strength. Robustness additionally declares conduct, failure,
escalation, stale-slot, new-search and transfer-honesty requirements. V1 does not
automatically support those additional fields. Their exact field names and types
are in the machine report, without values or per-case outcome disclosure. They
were not mapped to weaker checks or used to modify either agent.

Concise remaining transcript-review checklist:

1. Patient-script fidelity: facts revealed only when appropriate; requested
   constraints, clarification, correction and consent preserved.
2. Complete/accurate identity and booking read-back; no unsupported booking,
   availability, provider/service or location claim.
3. Correct blocking explanation and alternatives/next step, including the
   scenario's declared factual and explanation requirements.
4. No invented clinical distinctions, human transfer, callback or follow-up;
   check any additional declared conduct/escalation obligations.
5. Distinguish wrong booking, wrong internal selection, spoken false statement
   and false refusal. Record infrastructure/evaluation-limit failures separately.
6. Close every prose `reply_rules`, `expected.explanation`, `forbidden`, notes
   and contract-review item explicitly; unresolved items are not passes.

All 16 held-out and eight robustness cases have prose review obligations.
For the proposed 16 x2 x2 plus 8 x1 batch, plan **72 transcript reviews**,
plus source-owner rubric clarification for unsupported fields. Illustratively,
2–4 minutes per transcript is **2.4–4.8 hours**, not measured review time and
not included in the LLM-dollar estimate. Repeated global contract items can
share one checklist, but each actual conversation still needs review. No review
has been completed and no final pass is assigned.

## 5. Executable commands and unchanged budget proposals

Reproduce this read-only complete structural audit from repo root:

```sh
LOGURU_LEVEL=WARNING PYTHONPATH=backend backend/.venv/bin/python \
  docs/results/fixture_contract_audit.py \
  --heldout-path /Users/gabrielernoult/Documents/prosper_heldout_scenarios.json \
  --robustness-path /Users/gabrielernoult/Documents/prosper_robustness_scenarios.json \
  --output docs/results/fixture-compatibility-audit.json
```

Exit 0 means the audit completed, not compatibility or an agent pass. The pinned
executable evaluator remains unchanged. From backend, its existing gate is:

```sh
LOGURU_LEVEL=WARNING .venv/bin/python -m evals.external_eval preflight \
  --heldout-path /Users/gabrielernoult/Documents/prosper_heldout_scenarios.json \
  --robustness-path /Users/gabrielernoult/Documents/prosper_robustness_scenarios.json
```

That command still exits 2; it stops at the first unsupported input. The
documented `run-paid` command is not ready or authorized. No selective subset
or failure retry is proposed. A source-owner decision, any separately approved
contract work and successful complete preflight must precede a new paid go.

Budget proposals remain **$3.27 expected, $9 allowance, $10 model-cost cap**.
They are based on earlier complete-usage DEV means, not this new driver or
private-case execution. Changed patient recovery/consent, unsupported criteria,
unseen conversation lengths and manual grading make the estimate uncertain;
there is no new measured final-batch cost. The conditional $0.32512 per-request
exposure reserve and its price/limit assumptions remain documented in
[external-adapter.md](external-adapter.md). No dollars were spent on this work.
