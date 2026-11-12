# Final restart completed; semantic review pending (2026-11-10)

All 40 planned attempts completed once with unchanged pinned v1.2 infrastructure,
including two linked replacements first. Measured model cost $1.4072150; all 211
requests accounted, no new outstanding exposure. Raw statuses 24 review-required,
16 failed; 15 held-out runs are driver-limited and all semantic review remains
pending. [Current measured report](final-evaluation-restart-v1.2.md). Old statuses
below are historical. No further paid calls or reruns are authorized. Voice Call B
remains pending independently.

---

# Infrastructure fix prepared, restart unapproved (2026-11-10)

Serialization and independent durable evidence are fixed in **external-infra-v1.2**;
patient/scorer semantics remain external-eval-v1.1. Forty-nine offline checks pass,
including real searched/booked state, nested dates and deliberate final-export
failure. No paid calls. Two linked replacements followed by 38 unrun conversations
are prepared. The original failed attempts, unknown outcomes and costs remain in
history. [Fix, validation, billing bounds and restart commands](external-infrastructure-v1.2.md).
Fresh restart approval is required. Earlier execution/preparation below is historical.

---

# Execution update: interrupted, no retries (2026-11-10)

Both paid batches were explicitly approved and started with the pinned v1.1
adapter. Both failed at their first report checkpoint on datetime serialization.
Two attempts/18 model-call usage rows survive; no conversation result or transcript
was saved, and the other 38 planned conversations never ran. Nothing was modified
or rerun. Known usage $0.0923300; final semantic results unavailable.
See [the execution report](final-evaluation-execution.md). Earlier preparation
proposals and statuses below are historical. Voice Call B remains pending.

---

# Current adapter: reviewed evaluation v1.1 (2026-11-10)

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

# Isolated external-contract adapter v1

Current compatibility update: [fixture-compatibility-report.md](fixture-compatibility-report.md)
records the subsequently authorized structural audit of both complete sets.
The held-out fixture failure is substantive missing-capability consistency,
not formatting. No lossless mapping or adapter change was made. Robustness
fixture arrays pass initialization but its additional metadata/criteria are
not accepted by v1. Historical first-error preflight below is preserved;
full-batch execution remains blocked, with no new paid authorization.

2026-11-10. Evaluation infrastructure only. No scheduling-agent, baseline,
runtime, booking/handoff guard, prompt, tool or legacy v5 scorer/patient change.
No paid calls, retries or new matrix execution. Scaling is closed. Voice Call B
is **pending manual verification** and does not gate this infrastructure work.

## Version and pin

Executable evaluator: **external-eval-v1**. This is a new evaluator version,
not a claim of unchanged v5 semantics or a continuation of the old DEV scores.

- CLI/execution/pin: `backend/evals/external_eval.py`.
- Validation and private patient driver: `external_contract.py`.
- Field-driven three-state checks: `external_score.py`.
- Budget admission: `external_budget.py`, isolated from the legacy spend guard.
- Complete configuration: `external_config.json`.
- Source/configuration/dependency/agent pin: `external_pin.json`.

Pin SHA-256:
`dbd24883c42ad0c0188bb8b9cc5dab0aa30b133a62195465c94787cdebc7efaa`.
Configuration SHA-256:
`31fa3c9d33b729d26a55bedee938c303fe0c0dc283f543cae51facb8660e591f`.
Offline evidence SHA-256:
`b44b41c039a6478ab3dc6ca691bb8e04379d9f6d58e98b75e0059b52c460d6e6`.

The pin covers 29 files, installed package versions, original catalog blob,
compiled agent identities and the legacy evaluator hash. The offline report
records the same tested source fingerprints. Pinning rejects a code change
after validation. External access first checks the pin and source hash.

Preserved identities: HEAD `a5b124f7aa3ffa9d7ebcd32a7f76c837c95486c8`;
proposed `40db1b587b5790ab2c92bc642edbc55e67f0d44ebd8d4f1267de29e1e86ebdc5`;
baseline `68d02acb9a89a72c279c3410001e2b184438abce7f7c714ce39a0e87ddf4f623`;
legacy v5 behavior `97117348b6d00263d60c0561381841e3fc50e843873a53b60e827a8c7415a996`.
The original catalog and `eval_fixture` mode, GPT-4o alias, APPEND context,
parallel_tool_calls=false, 512-output-token evaluation cap and disabled retry
layers remain. Model snapshot/temperature are not newly pinned or changed.

## Explicit data drives execution; labels do not

Scenario IDs are join/report labels only. Neither the new driver nor new scorer
dispatches on ID, category, provider/service names, scenario order or an ID map.
The optional split/category/notes/source labels do not select agent behavior.
Catalog names in replies are retrieved using the fact card's explicit IDs.

The public schema 0.1 remains accepted; `external-contract-v1` also names the
documented optional structured additions below. No source scenario was edited.
Required scenario fields are id, opening, patient_facts, expected_outcome,
expected and availability_fixture. Dataset metadata must include the catalog
pin, contract, schema_version, dataset_role and scenarios. English,
America/Los_Angeles and synthetic identities are the supported configuration.
The simulated clock is explicitly 2026-11-07T00:00:00-08:00, as in v5.

| Explicit field | Automatic behavior/check |
|---|---|
| opening | Only initial patient message sent to the agent |
| patient_facts name/DOB/status/referral | Reveal in responses to relevant questions; bounded recovery |
| intended/provider/location IDs | Respond to an appropriate clarification with catalog names, specialty/title; no pre-seeding live state |
| initial_location_id + final_location_id | Correct after a matching complete offer, before consent |
| ambiguous_type_ids | Preserve inability to choose and request staff clarification |
| preference=soonest | Patient-side eligibility oracle rejects later offers and asks once for earlier availability |
| patient_script | Explicit event-triggered replies, bounded by max_uses |
| expected booking/bookings/confirmation flags | Compare observed booking fields/count and confirmation evidence |
| expected ambiguity/correction/unknown-entity flags | Check observed state and corresponding evidence |
| expected required_facts | Dynamic location/phone/hours formatting checks; no clinic-ID constants |
| expected assertions | Closed, explicit predicate set below |
| faults | Existing structured tool fault injector, unchanged tools exposed to agent |

Automatic assertion kinds are `policy_block(code)`,
`transcript_contains(text)`, `catalog_distinction(ids)`, `staff_request`,
`no_identity_collection`, `no_tool(tool)` and `review(text)`. The last kind is
explicitly manual, never an automatic true. Unknown fields, kinds or arguments,
malformed fixtures/facts and missing required fields fail visibly. Boolean
requirement flags request the check when true, matching v5's opt-in convention.
Global ranking without an explicit expected slot ID is marked missing evidence
for review rather than guessed from scenario ordering.

Structured patient trigger names: `first_offer`, `identity_question`,
`identity_confirmation`, `provider_question`, `location_question`,
`service_question`, `booking_offer`, `name_spelling`, `human_help_offer`,
`no_availability`, `tool_error`, and `assistant_contains` (literal `match`). Each
rule supplies `response`, with optional `max_uses` from 1 to 3. These rules may
contain authored patient responses; they are never constructed from gold
expected results. Arbitrary code/regex/actions are not executed from data.

## What changed from v5

This is **not input mapping alone**:

- Recovery retains v5's status/referral question patterns and limits, first
  identity response plus one bounded repeat, and identity-confirmation flow.
  Explicit fields replace DEV-specific branches.
- Provider and location facts are answered when appropriately requested, rather
  than a special-case bundled reply. This can change subsequent turns.
- Identity consent checks the actual name/DOB read-back. Slot consent checks
  patient facts, complete service/provider/site/date/weekday/time, and soonest
  preference. v5 could consent based only on the offered-slot state.
- Corrections are field-driven and dynamically named; the default does not
  invent an inability to visit the old location or add an "only" constraint
  unless supplied. Prose-specific wording is not automatically interpreted.
- Scoring uses explicit expected fields/predicates, not DEV-specific assertions
  implicitly attached by scenario ID. Existing general callback/offer/next-step,
  unknown-provider, name and clinical-distinction helpers are reused where
  applicable. Explicit before-booking identity checks also use tool chronology.

**Unsupported automatic semantics:** arbitrary free-text `reply_rules`,
`expected.explanation`, `forbidden`, notes and prose contract grading/behavior
requirements. Each is recorded as a required review pointer. No prose is
silently compiled to an invented assertion or dropped. Supported predicates
are limited heuristics: e.g. hours checks spoken opening/closing clock values,
not a general semantic proof of all weekday/timezone claims. Unsupported
structured criteria fail preflight; unproven or absent evidence requires review.

Statuses distinguish `passed`, `failed`, `review_required`,
`infrastructure_failure`, and budget-incomplete/not-admitted execution. A pass
requires every automatic criterion true, no missing evidence, and **no pending
required review**. The current adapter has no automatic prose-review completer.
It cannot assign a final pass to such cases. Driver exhaustion is separately
marked evaluation-limited, not automatically blamed on the agent or provider.

Wrong observed booking fields/unexpected bookings can be labeled wrong_booking.
Wrong observed internal selection without a booking is a separate label. A
missing booking is not automatically a false refusal, and an incorrect internal
ID is not automatically a spoken false claim. Those semantic consequences are
transcript-review categories. Transport/deadline failures are infrastructure,
not an agent accuracy pass. Attempted tools count for no-tool checks even when
no finished result was recorded.

## Offline evidence completed before private schema access

[Validation and replay artifact](results/external-offline-validation.json):
**27 targeted tests passed**, all 12 unchanged public DEV scenarios compiled,
zero OpenAI calls (API creation mocked to fail), no external contents accessed
during this phase. No unchanged full suite was rerun for a fresh timestamp.

Tests cover renamed IDs and seeded shuffled order with identical patient
replies/scoring; valid booking, policy block, factual answer, ambiguity,
correction and infrastructure failure; missing/malformed/unsupported fields;
wrong booking versus absent booking, internal state versus spoken assertion;
mandatory review blocking pass; bounded recovery, accurate consent, earliest
slot behavior; no expected-outcome leakage and private identity only after a
relevant question; full unknown-usage reservation and stop on limit violations.

Saved-trace replay uses existing 72 x1 DEV attempts only. **It is not a new run
or a replacement score.** The old 59 passes become 59 review-required results;
12 old failures remain automatic failures and one remains infrastructure failure.
All directly comparable automatic assertions agree. Old ID-attached policy/
explanation checks not executable from explicit structured fields are listed
per trace and moved to required prose review, never silently called checked.
Missing trace state is not reconstructed from expected fields; directly saved
legacy final-state observations are reused when available. The artifact lists
every disagreement/missing automatic criterion and its source run/hash.

## Pinned private schema preflight: stopped, no changes made

After those checks and pinning, the automated preflight verified the held-out
source SHA and parsed it internally. It stopped with this sanitized result:

```
external_set: heldout
status: unsupported
code: malformed_availability
field: availability_fixture
api_calls: 0
scenario_contents_printed: false
```

[Machine preflight result](results/external-preflight.json). This means a fixture
was rejected by the unchanged scheduling-engine fixture validator; it is an
input-contract/compatibility failure, **not an observed agent failure**. That
validator checks catalog references and provider/service/site/capability
consistency. The sanitized output does not identify the failing case
or establish which check failed, so no cause or case details are guessed here.
Robustness schema validation was **not reached**. Its earlier byte-only hash
verification remains recorded separately. Neither set was manually inspected,
displayed, copied, searched or used to tune. No adapter, fixture, expectation or
arm was patched after this result. A source-owner contract decision is required;
the final batch is blocked and no unscored case is passed.

## Exact commands

From the repository's backend directory. Development/replay only, zero paid
calls; the source pin will reject edits after the validated snapshot:

```sh
LOGURU_LEVEL=WARNING .venv/bin/python -m evals.external_eval validate-dev
LOGURU_LEVEL=WARNING .venv/bin/python -m evals.external_eval pin
```

The already executed automated schema preflight (no API calls); it currently
exits **2** for the compatibility failure above. Do not repeatedly probe private
inputs or change the adapter to fit them:

```sh
LOGURU_LEVEL=WARNING .venv/bin/python -m evals.external_eval preflight \
  --heldout-path /Users/gabrielernoult/Documents/prosper_heldout_scenarios.json \
  --robustness-path /Users/gabrielernoult/Documents/prosper_robustness_scenarios.json
```

Executable paid command exists but is **not authorized and is currently blocked
by that preflight**. It validates all input sets before creating a session, uses
one global cap, journals attempts, and has no resume/selective-rerun switch:

```sh
LOGURU_LEVEL=WARNING .venv/bin/python -m evals.external_eval run-paid \
  --heldout-path /Users/gabrielernoult/Documents/prosper_heldout_scenarios.json \
  --robustness-path /Users/gabrielernoult/Documents/prosper_robustness_scenarios.json \
  --max-cost-usd 10 --approval-ref 'REPLACE_WITH_EXPLICIT_USER_APPROVAL'
```

Flags and a placeholder approval reference do not grant authorization. Do not
run until the contract mismatch is resolved with the source owner and a new
explicit paid go is recorded. The requested batch remains 16 x2 in each frozen
arm plus eight robustness cases x1 proposed: 72 conversations, no retries.

## Reserve derivation and budget exposure

Proposals unchanged: **expected $3.27; allowance $9; hard global cap $10**,
pending approval. The new evaluator may have different conversation lengths;
these remain projections from prior complete-usage DEV conversations, not new
measurements or authorization.

The configuration reserves the full model-token exposure **before each API
request**, including requests following tools:

```
configured maximum input allowance: 128,000 tokens
configured maximum output:              512 tokens
uncached input rate:                    $2.50 / 1,000,000
output rate:                           $10.00 / 1,000,000

128000 * 2.50 / 1000000 + 512 * 10 / 1000000 = $0.32512
```

Cached input cannot exceed the uncached rate under these prices. The provider's
128K combined context limit would allow a tighter maximum, $0.32384 with 512
output tokens; the chosen bound deliberately allows 128K input **plus** output.
It is a **conditional upper bound**, not an observed charge or cost forecast.

Conditions: GPT-4o really enforces its recorded context limit; the API honors
the enforced 512-output cap; dated prices remain applicable; no extra fees;
all requests pass through this guard; SDK and timeout retries stay disabled.
Input framing is not proven by a local exact tokenizer count: the 128K premise
depends on the provider limit. Model-alias/price/limit changes or charges outside
this model endpoint invalidate a billing guarantee. Reconfirm those premises
before an approved batch; do not describe this as an unconditional account cap.

Known usage replaces its reservation with actual cached/uncached/output cost.
Missing usage/cancellation keeps the full $0.32512 held and actual cost null.
In-flight requests remain reserved, so a caller deadline or cleanup cannot
make them free. Post-tool requests during existing runtime cleanup are separate
guarded admissions, not retries. The guard does not release an unknown reserve
to squeeze in another case. A token-limit violation stops admissions and marks
the bound uncertified. Pricing changes/undocumented fees are not detectable
from token counts and remain outside this conditional protection. A cap may
stop the batch before completion; budget-incomplete cases are not agent passes.

## Next decisions

The source owner must resolve the availability-contract mismatch; no correction
is inferred from hidden contents. Arbitrary prose still needs human grading or
an explicitly approved structured contract, never expectation edits for a score.
Any further adapter revision requires public/synthetic validation and a new pin
before private access. The frozen arms and known DEV-007 defect remain intact.
No final paid run is approved. Voice Call B remains pending independently.
