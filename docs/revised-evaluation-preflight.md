# Revised evaluation copies: consolidated offline preflight

2026-11-10. **Zero paid calls. Execution and manual review are pending approval.**
This report supersedes the original-copy compatibility blocker for these proposed
reviewed copies only. Historical audits remain valid for the unchanged originals.
Voice Call B is still pending manual verification and does not block approved text work.

## Scope and exact source changes

The independent source review, reported by the user, established that the four
capability-invalid fixtures were deliberate adversarial records. The frozen
engine rejects them during initialization. The conversational held-out copy
removes exactly `ho002-bad-site`, `ho003-bad-site`, `ho008-nocap-1`, and
`ho008-nocap-2`. All 16 scenarios, original expected fields, booking identities
and outcome labels remain. No remaining interval, timezone, provider/type/site
relation, duration or catalog record was repaired or moved.

**This is a reduced-scope source revision, not lossless normalization or full
preservation of the original test scope.** It no longer tests runtime ingestion
of capability-invalid availability. All four original records are preserved
outside the repository with their failing initializer condition. Offline checks
confirmed 4/4 reject because `appointment_type.required_capability` is absent
from `location.capabilities`; this is substantive catalog validity, not formatting.

The source-authoring script `backend/evals/revise_assets.py` makes the explicitly
authorized edits by source label. Executable patient behavior, scoring, fault
routing and runtime never dispatch on scenario IDs.

The exact private before/after manifest is
`../Evals/revised-evaluation-v1/exact-change-manifest.json`, SHA-256
`daf11cd1a7df1ca570b42c9cb766786628d8577b7aace75289f670e49c7b9f77`. The public
[redacted manifest](results/revised-assets-manifest.json) lists every JSON pointer,
operation and before/after value hash: **29 field-level edits**. It records:

- Three fixture-array edits remove only the four specified records; affected
  notes plus the contract declare the ingestion-test scope reduction.
- HO-004/005/006 accept honest staff-directed next steps without authorizing or
  requiring a callback/live transfer. Bounded explicit patient-script replies
  acknowledge that the patient can contact staff directly.
- HO-006 declines every substitute service. Its explicit service-question
  response declines substitutes; unsupported paraphrase handling remains review.
- HO-014 requires accurate location/referral information, with no spoken provider
  name requirement. The original provider identity reference remains unchanged;
  `provider_name_spoken_required: false` clarifies its interpretation.
- Robustness contract exceptions: requested human assistance, genuine technical
  failure and declared urgent-symptom escalation are not automatic false refusals.
- RW-003 explicitly requests earliest eligible availability and sets its private
  patient `preference` field to `soonest`; no booking expectation changes.
- Clarifications explicitly supersede conflicting old prose, not booking outcomes.
  RW-004's Saturday fixture is unchanged.

Removed-record evidence: `../Evals/revised-evaluation-v1/removed-initializer-records.json`,
SHA-256 `963e623e55b507022b881c8b451d87eb36b84d8c1b90b6e426e92679c3a705d8`. Full source contents,
private dialogues and expectations stay outside Git; only structural diagnostics,
hashes and aggregate counts are published here.

## Original, revised and boundary-input hashes

**Heldout**

- Original: `/Users/gabrielernoult/Documents/prosper_heldout_scenarios.json`
- Original SHA-256: `d41abdad3defe405a48becc55a97d4d153c3c3b27a4eff5f5518db8a2dedd1b6`
- Reviewed copy: `/Users/gabrielernoult/Desktop/Prosper AI/Evals/revised-evaluation-v1/heldout.reviewed.json`
- Reviewed SHA-256: `94dcf459ad8d0e13f89981aefb8afb6492982e3d611a0cd50a22a2bf7be72fea`
- Boundary input SHA-256: `94dcf459ad8d0e13f89981aefb8afb6492982e3d611a0cd50a22a2bf7be72fea`

**Robustness**

- Original: `/Users/gabrielernoult/Documents/prosper_robustness_scenarios.json`
- Original SHA-256: `c5de085b51996c51afaa9dbc3b40c392452d0eec28760b422ced2a6f74aa6c19`
- Reviewed copy: `/Users/gabrielernoult/Desktop/Prosper AI/Evals/revised-evaluation-v1/robustness.reviewed.json`
- Reviewed SHA-256: `2c2ce46ce4864b7b6a18153ffa1a353d279b67f3c340155f0b1712937f3ebebd`
- Boundary input SHA-256: `3bdc968cabea2a5825e30b0e1003eeea6a7631d5580e6a7364fe726ee9eb60ed`

The originals still match their recorded hashes. Boundary files live beside the
reviewed copies as `heldout.boundary-v1.1.json` and `robustness.boundary-v1.1.json`.
That **second** transformation changes only fault aliases/stage declarations;
it preserves all availability and expected fields exactly. The held-out boundary
bytes are identical to its reviewed copy. This limited mapping must not be
confused with the earlier, explicitly lossy source-scope revision.

## Adapter and offline evidence

Adapter: **external-eval-v1.1**. Pin:
`529c0714f452d158d91fcde98237d0728fa17775e89ab3e7a84e5f34721259e5`.
Configuration SHA-256: `97e54fe59f65c3e931c1c4865d8bd74a99a79cd59f883c6186ca426376aa24e1`.
Rubric: `external-review-v1.1`, SHA-256 `054cbbd261440e29d0c7bdf6749bbff56ac38023f11cdf130d1efef31d08e686`,
frozen in `backend/evals/review_rubric_v1_1.json` before any execution.
The complete source/configuration/package pin is
`backend/evals/external_pin_v1_1.json` (34 files). Historical external-eval-v1,
its original pin, evidence and code are preserved in
`docs/results/archive/external-eval-v1.zip`; provenance is alongside it.

This version changes evaluation semantics as well as mapping:

- Unknown/unimplemented semantic fields and all prose are retained as mandatory
  review requirements, never silently discarded or treated as passed assertions.
- Private `requested_location_id` aliases an initial site when paired with an
  explicit `final_location_id`. The source field stays intact. Unimplemented
  preference/correction dimensions remain review requirements; an unsupported
  correction is not fabricated into a failed location-correction assertion.
- A brief option choice requests the full read-back before consent. Earliest
  consent respects explicit provider/site facts and observed unavailable slots.
- Supported patient replies continue before basic zero-booking assertions can
  prematurely terminate a conversation. Recovery replies stay bounded.
- Booking faults activate only at the guarded write; fault activation is now a
  required automatic recovery assertion. Patient behavior/grading therefore
  differ from historical DEV v5 and external-v1 and must be reported separately.

[Offline evidence](results/external-offline-validation-v1.1.json): **38 targeted
DEV/synthetic tests pass**, no API requests; IDs renamed and order shuffled
without behavioral/scoring changes. Tests include booking, blocks, facts,
ambiguity, correction, infrastructure failure, missing/malformed inputs,
unsupported assertions, private-data isolation, aliases, post-consent write
faults, persistent slot loss and incomplete-review exclusion. All 12 DEV cases
compile. Saved-trace replay covers 72 historical attempts: 59 previous passes
remain review-required, 12 fail and one is an infrastructure failure; no common
automatic-assertion disagreement. This replay is not a new accuracy score.

[Consolidated machine preflight](results/external-preflight-v1.1.json):

| Dataset | Scenarios compatible | Slots | Engine initialization | Mandatory review |
|---|---:|---:|---:|---:|
| Reviewed held-out | 16/16 | 27 | 16/16 | 16/16 |
| Reviewed robustness | 8/8 | 11 | 8/8 | 8/8 |

## Fault checks

The boundary maps `times` to `attempts`, `slot taken` to `slot_taken`, and declares
`stage: write` for booking faults. Conflicting aliases or invalid stages fail
visibly. Error faults repeat on every actual write attempt. Slot loss marks the
named slot permanently unavailable at its first intercepted write.

The evaluation-only controller intercepts the session-local in-memory booking
dictionary insertion **after all unchanged engine validation/consent checks**.
It returns the structured failure to the model. No engine or tool source is
modified; no offer-preparation call triggers a booking fault.

| Label (reporting only) | Offline tool-protocol evidence | Triggers | Booking created |
|---|---|---:|---:|
| RW-002 | Error at actual write after generated read-back and patient yes; repeated write errors | 2 | 0 |
| RW-003 | Earliest eligible slot lost at write after consent; remains unavailable | 1 | 0 |
| RW-008 | Named slot lost at write after consent; remains unavailable | 1 | 0 |

In every check, phase one and a missing-consent call caused zero triggers.
These are **offline protocol proofs, not evidence of agent recovery**. Every
paid attempt must separately record `fault_evidence` and `fault_events`. If the
agent never reaches the intended failure, `fault:…:triggered` fails; a booking
fault also requires `write_after_consent`. It cannot pass recovery by avoiding
the injected failure. The Saturday fixture survives exactly and is filtered by
the unchanged opening-hours policy when searching/booking.

## Automatic assertions and required review

Automatic checks run on explicit supported fields: declared booking count and
identity, recorded confirmation, earliest slot, supported ambiguity/correction
state, factual location/phone/hours, supported structured assertions, general
location/callback/next-step checks, and actual fault activation/stage. The
preflight lists the exact automatic names and every review field path per set.

Required manual checklist, applied identically to both arms:

1. Follow all original/revised reply rules, forbidden items, notes, contract
   prose and unsupported structured requirements; verify patient-driver fidelity.
2. Check explanations, capability/referral gates and factual answers against
   the catalog/tool evidence, including required location/referral details.
3. Check genuine decline of substitutes, honest staff-directed next steps,
   human/urgent escalation, no callback/transfer fiction and no medical advice.
4. For fault recovery, verify trigger evidence, disclosed failure, any required
   re-search/consent invalidation and a valid next step. Avoided fault is not pass.
5. Classify unnecessary clarification, incorrect internal selection, spoken
   falsehood, false refusal, wrong booking and infrastructure failure separately.
   Apply the declared refusal exceptions. Do not infer spoken falsehood from an
   internal ID or false refusal from missing booking alone.
6. Record reviewer, rubric version, each required item's evidence and
   pass/fail/unassessable result. **No pass while required review is pending.**

Unsupported semantic examples: clinical/service distinctions; service-type
corrections; soft-preference meaning; gate-before-alternative explanations;
provider identity before a non-booking decision; location/referral answer
content beyond the implemented factual subset; emergency, AI disclosure,
requested human assistance and recovery quality. These remain explicit review
items, not compatibility waivers. A driver that cannot provide a required reply
makes that aspect unassessable; it cannot be counted as an agent success.

Review workload estimate: **40 transcripts, about 2–3.3 hours** at 3–5 minutes
each (32 held-out plus eight robustness). This is an estimate, not measured work.

## Frozen execution identifiers

- Git HEAD and proposed-v2 tag: `a5b124f7aa3ffa9d7ebcd32a7f76c837c95486c8`.
- Proposed JSON revision: `40db1b587b5790ab2c92bc642edbc55e67f0d44ebd8d4f1267de29e1e86ebdc5`.
- Baseline revision: `68d02acb9a89a72c279c3410001e2b184438abce7f7c714ce39a0e87ddf4f623`.
- Catalog blob: `8e5091080383d598ae18acce084c7dcd6522ab14`; catalog SHA-256:
  `5837bc09e8337f469dccd649f408b9f69f8f11a5741856deb3b02e604867902a`.
- Legacy evaluator behavior hash: `97117348b6d00263d60c0561381841e3fc50e843873a53b60e827a8c7415a996`;
  no legacy scorer/driver changes in this work.
- Model `gpt-4o` alias (provider snapshot unpinned), temperature not explicitly set,
  APPEND context, parallel tools disabled, `eval_fixture`, clock
  `2026-11-07T00:00:00-08:00`, nine patient turns, 45s timeout, output cap 512.
- Packages: pipecat-ai=1.4.0, pipecat-ai-flows=1.4.0, openai=2.54.0, tiktoken=0.14.0.
- [Integrity comparison](results/revised-evaluation-integrity.json) confirms both
  arms, the shared execution files and legacy evaluator remain byte-identical
  to the historical pin. DEV-007's shared-guard defect remains a known limitation.

## Proposed paid batches and cost, awaiting approval

| Batch | Conversations | Expected proxy | Spending allowance | Proposed hard cap |
|---|---:|---:|---:|---:|
| Held-out, both frozen arms, once each | 32 | $1.51 | $4.50 | $5.00 |
| Separate robustness, proposed only, once | 8 | $0.25 | $1.50 | $2.00 |
| Total | 40 | $1.76 | $6.00 | $7.00 |

[Pricing calculation](results/revised-evaluation-pricing.json) uses only existing
x1 logs: 35 complete-usage proposed conversations ($0.031104 mean) and 36 baseline
($0.063279). The entire incomplete-usage proposed conversation is excluded, not
priced as zero. All-cold pricing with 50% more calls yields proxies $4.00946 and
$0.62778; robustness allowance adds further recovery headroom. Rates are the
recorded **2026-11-07** GPT-4o rates: $2.50/M uncached input, $1.25/M cached input,
$10/M output. Actual cached tokens will be reported; extra cache-write fee is
$0 under this configured rate card, not an independently metered write count.

These are mix-dependent projections, not measurements of the revised private
sets. The revised driver can change turn count, error recovery can require extra
round trips, caches may be cold and usage may be missing. Prior $3.27/$9/$10
proposals for 72 conversations are superseded by this 40-conversation proposal.
No budget is approved by this document; LLM cost excludes unmeasured voice/STT/TTS.

Before every request the budget guard reserves **$0.32512**:
`128000 × $2.50 / 1e6 + 512 × $10 / 1e6 = $0.32000 + $0.00512`.
Known complete usage releases excess reserve. Missing usage, including missing
cached-token details, errors, cancellation and requests still in flight retain
the whole reserve, never become zero usage. Admission stops before another full
reserve cannot fit. Concurrency is one and retries are off. This is a conditional
upper bound under configured provider input/output limits and the dated prices,
not an estimate of actual missing charges. If those assumptions fail, the bound
is not certified; the guard stops on observed limit violations. Provider billing
outside reported requests remains unobservable. Unknown requests can stop a
batch well below its apparent known-cost subtotal; no automatic retries or
selective failure reruns will fill gaps.

## Commands

```sh
cd '/Users/gabrielernoult/Desktop/Prosper AI/prosper-challenge-context-management/backend'
HELDOUT='/Users/gabrielernoult/Desktop/Prosper AI/Evals/revised-evaluation-v1/heldout.reviewed.json'
ROBUSTNESS='/Users/gabrielernoult/Desktop/Prosper AI/Evals/revised-evaluation-v1/robustness.reviewed.json'

# Free, already completed. Hashes, pin, complete schema and write-fault protocol.
LOGURU_LEVEL=ERROR .venv/bin/python -m evals.external_eval preflight \
  --heldout-path "$HELDOUT" --robustness-path "$ROBUSTNESS"
```

**The following are prepared commands, not authorization. Do not execute before
explicit approval. Set `APPROVAL_REF` to that approval message reference first.**
An unset/empty approval reference fails before any model request. Each batch
gets its own run ID, JSONL, results journal and cap. No resume, selective rerun,
SDK retry or timeout retry.

```sh
# Held-out: 16 cases x 2 arms x 1 run = 32 conversations, proposed cap $5.
LOGURU_LEVEL=ERROR .venv/bin/python -m evals.external_eval run-paid \
  --batch heldout --heldout-path "$HELDOUT" --robustness-path "$ROBUSTNESS" \
  --max-cost-usd 5 --approval-ref "$APPROVAL_REF"

# Separate robustness: 8 cases x proposed only x 1 run, proposed cap $2.
LOGURU_LEVEL=ERROR .venv/bin/python -m evals.external_eval run-paid \
  --batch robustness --heldout-path "$HELDOUT" --robustness-path "$ROBUSTNESS" \
  --max-cost-usd 2 --approval-ref "$APPROVAL_REF"
```

Final held-out and robustness results remain **pending execution and review**.
