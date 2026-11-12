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

# Current plan: reviewed evaluation v1.1 (2026-11-10)

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

# Final evaluation: preparation, not authorization

## Latest fixture-contract audit: substantive incompatibility

The user authorized structural inspection only. Both complete datasets have
now been audited automatically, without printing private values, dialogue or
expected outcomes. The held-out blocker is **not formatting**: four slots in
three scenarios reference existing locations missing the service's required
capability. All 42 slots across both sets have the expected six string fields
and aware, ordered intervals. No lossless mapping can make the failed catalog
condition true while preserving the slot's site/service identities.

No conversion or adapter change was made; external-eval-v1 and its historical
pin remain unchanged. No normalized input exists, so conversion version and
normalized-input hashes are null/not applicable. Original source SHA-256s
still match. Correcting sites/services/catalog relations, bypassing the engine
gate or dropping slots is outside the authorized constraints. Source-owner
intent/contract clarification is required before implementation can continue.

Independent complete-array validation: held-out 13/16 fixture arrays accepted,
four invalid records among 31; robustness 8/8 arrays accepted, 11/11 records.
Complete v1 schema audit accepts 6/16 held-out scenario bodies and 0/8 robustness
bodies; additional patient/expected fields and robustness metadata are not
supported. These are compatibility counts, not agent pass rates. No structured
criterion or record was removed, and no private assertion outcome was graded.

The current consolidated diagnosis, commands, unsupported-field inventory and
review checklist are in [fixture-compatibility-report.md](fixture-compatibility-report.md)
and [machine audit](results/fixture-compatibility-audit.json). Plan for 72
transcript reviews if the requested full batch becomes executable; review is
not automatic and incomplete review cannot count as a pass. The $3.27 estimate,
$9 allowance and $10 proposed cap remain unapproved and uncertain under the
changed driver. No paid run or selective subset is authorized. Call B remains
pending manual verification independently.

The earlier first-error preflight, implementation and preparation history below
are retained; the new audit supersedes the earlier "robustness not reached"
compatibility status without changing the historical result artifact.

## Current update: external-eval-v1 implemented and pinned

2026-11-10. The user authorized the isolated adapter and offline validation,
not paid execution or changes to evaluated arms. **The adapter is implemented**
as `external-eval-v1`; it changes field-driven patient behavior and grading,
not just input mapping, and is kept separate from legacy DEV v5 results.
Its complete source/configuration pin is
`dbd24883c42ad0c0188bb8b9cc5dab0aa30b133a62195465c94787cdebc7efaa`.

**Offline evidence:** 27 targeted tests passed, all public DEV scenarios
compiled, renamed IDs/shuffled order invariant, 72 saved attempts replayed with
no model calls. Directly comparable assertions agree. Old 59 passes become
review-required, not new passes; 12 failures and one infrastructure failure
remain. Prose rules/expectations/forbidden claims are mandatory review, not
silently ignored or automatically marked true. Both frozen agent revisions
and the legacy evaluator hash remain unchanged.

**Current blocker:** only after pinning, automated private schema preflight
stopped on held-out `availability_fixture`, code `malformed_availability`,
from the existing scheduling-engine fixture validator. Zero API calls, no
case contents printed; robustness schema validation was not reached. No
scenario, fixture, expectation, arm or adapter was patched around that result.
The source owner must resolve the contract mismatch. Final paid execution is
not authorized or ready. Voice Call B remains pending manual verification.

Current executable commands, predicate/script contract, changed semantics,
unsupported/manual criteria and reserve derivation are in
[external-adapter.md](external-adapter.md). The authoritative machine plan is
[results/final-evaluation-plan.json](results/final-evaluation-plan.json).

From backend, the already completed public-only validation/pin commands are:

```sh
LOGURU_LEVEL=WARNING .venv/bin/python -m evals.external_eval validate-dev
LOGURU_LEVEL=WARNING .venv/bin/python -m evals.external_eval pin
```

The schema-only command currently exits 2 for the mismatch; do not repeatedly
probe or tune to private inputs:

```sh
LOGURU_LEVEL=WARNING .venv/bin/python -m evals.external_eval preflight \
  --heldout-path /Users/gabrielernoult/Documents/prosper_heldout_scenarios.json \
  --robustness-path /Users/gabrielernoult/Documents/prosper_robustness_scenarios.json
```

The implemented `run-paid` command is documented separately and requires an
explicit approval reference and shared cap. It must not be executed now. All
input sets must pass schema preflight first. Requested scope remains 72
conversations, no automatic/selective retries. **$3.27 expected, $9 allowance,
$10 proposed cap remain proposals**, not authorization or measured costs.

The $0.32512 reserve is 128000 x $2.50/M + 512 x $10/M. It is reserved before
every request, retained on missing usage, and conditional on the recorded
provider limits/prices and absence of extra fees. It is not a charge estimate
or unconditional billing guarantee; full assumptions are in the adapter doc.

## Historical pre-adapter preparation

The sections below preserve the earlier preparation and its then-unimplemented
adapter decision. That decision is superseded by the current update above;
the frozen identities, hashes and historical cost-projection inputs remain.

2026-11-10. **No final paid run has started.** Scaling is complete and will not
be rerun or extended. Its conditional authorization is exhausted. Search-only
remains exploratory and is excluded from this final batch. Voice Call B is
pending manual verification; that is not a prerequisite for an approved text
evaluation and must not be reported as voice verification.

## External files: full hashes verified, contents untouched

The decision log recorded full hashes on 2026-11-08. It contained only filenames;
the user supplied `/Users/gabrielernoult/Documents` on 2026-11-10. Only the two
exact paths below were opened, in binary chunks for SHA-256. Neither file was
displayed, JSON-parsed, searched, copied into the repo or used to tune behavior.
The recorded scenario counts are not a claim of content validation.

| Set | Exact path | SHA-256, expected = observed | Status |
|---|---|---|---|
| Held-out, recorded 16 | /Users/gabrielernoult/Documents/prosper_heldout_scenarios.json | `d41abdad3defe405a48becc55a97d4d153c3c3b27a4eff5f5518db8a2dedd1b6` | Verified bytes only |
| Robustness, recorded 8 | /Users/gabrielernoult/Documents/prosper_robustness_scenarios.json | `c5de085b51996c51afaa9dbc3b40c392452d0eec28760b422ced2a6f74aa6c19` | Verified bytes only |

Source: docs/decisions.md:442-454. Actual verification and content-access flags:
[final-evaluation-plan.json](results/final-evaluation-plan.json).

## Reproducible preparation command

Run from the repository's backend directory:

```sh
.venv/bin/python -m evals.final_preflight \
  --heldout-path /Users/gabrielernoult/Documents/prosper_heldout_scenarios.json \
  --robustness-path /Users/gabrielernoult/Documents/prosper_robustness_scenarios.json \
  --output ../docs/results/final-evaluation-plan.json
```

This metadata-only command has no API client or execution mode. It hashes only
explicit external paths, never parses their contents, and recomputes versions
and estimates from saved DEV logs. **Exit code 2 is intentional**: even when
both hashes match, execution readiness is blocked by the evaluator issue below.
No unchanged suite or paid matrix was rerun to prepare this document.

## Material evaluator compatibility issue: decision required

The existing evaluator is `dev-eval-v5-recovery`. It is not currently a generic
external-scenario executor:

- `evals/loader.py` accepts only `dataset_role=development_only` and development
  splits, and defaults to the DEV file.
- `evals/comparison_matrix.py` has no external path/repetition options; it always
  runs the twelve DEV cases three times. **Do not use it as a final-set command.**
- `_PatientDriver.reply` and `_conversation_complete` in
  `evals/text_integration.py` have ID-specific disambiguation, staff request,
  correction, FAQ and unknown-provider behavior. `reply_rules` text is not a
  general executable patient contract.
- `evals/scorer.py` has shared booking/general checks, but its capability,
  referral, ambiguity, correction, FAQ and provider-explanation checks dispatch
  on DEV IDs. Generic non-booking cases are not guaranteed the declared
  explanation/assertion coverage. The external contracts have not been parsed,
  so compatibility cannot be claimed.
- The current driver fixes simulated time at 2026-11-07T00:00:00-08:00. External
  fixture clock compatibility is also unverified; do not silently move fixtures.

Blindly patching the loader or renaming external IDs to DEV IDs would create
misleading scores and may supply wrong patient facts. No such change is made.

**Smallest proposed correction, awaiting the user's decision:** an isolated
external-contract loader/driver/assertion dispatcher, preserving original IDs,
fixtures and expected values and reusing existing predicate functions. Keep
the frozen v5 source files and historical results intact. Version/hash the
adapter separately, use exactly the same dispatch for both final arms, validate
contract/count/pin/clock and assertion coverage before the first paid request,
and fail on unsupported contract elements rather than skip or reinterpret them.
Only an approved final execution may consume the external JSON; do not manually
inspect cases to build aliases or adapt agent behavior. If the files cannot be
executed from an existing machine-readable contract, stop and report the
unsupported fields without printing cases or spending on a partial evaluation.

This is an evaluator decision, not an approved behavior/scoring change. It may
require a new outer evaluator version; it must not be silently labeled identical
to v5. Alternatives are supplying an already compatible evaluator or reporting
final evaluation unavailable. No runnable final paid command exists yet.

## Frozen versions to preserve

| Identifier | Value |
|---|---|
| Current HEAD and proposed-v2 tag | `a5b124f7aa3ffa9d7ebcd32a7f76c837c95486c8` |
| Both official x1 report commits | Same commit above |
| Proposed agent JSON SHA-256 | `40db1b587b5790ab2c92bc642edbc55e67f0d44ebd8d4f1267de29e1e86ebdc5` |
| Evaluated/current compiled baseline SHA-256 | `68d02acb9a89a72c279c3410001e2b184438abce7f7c714ce39a0e87ddf4f623` |
| Baseline catalog-prefix SHA-256 | `baea1382762b1177e7f21a5070a6dd38724fc910c965905b9eb9f96458436e4f` |
| Catalog Git blob SHA-1 | `8e5091080383d598ae18acce084c7dcd6522ab14` |
| Evaluator/scorer | `dev-eval-v5-recovery` |
| Evaluator behavior SHA-256 | `97117348b6d00263d60c0561381841e3fc50e843873a53b60e827a8c7415a996` |
| Historical measurement execution SHA-256 | `be63f5d4876dd066a96fdc2948d6a43c25df069c278b45e9ccb129d92e7a397e` |
| Model | `gpt-4o` alias, provider snapshot not recorded/pinned |
| Configuration | APPEND; parallel_tool_calls=false; streaming; 512 completion-token cap for evaluation |
| Sampling | Temperature/top-p not explicitly set by the runtime; no determinism claim |
| Availability | `eval_fixture`, original x1 catalog, each fixture a complete universe |
| Planned operational limits | Sequential; SDK retries=0; timeout retries=false; 45-second patient-turn deadline |

[Builder identity evidence](results/agent-identities.json) was calculated without
creating a text session or API request; both revisions match the official x1
reports. Packages: Pipecat 1.4.0, Flows 1.4.0, OpenAI SDK 2.54.0, tiktoken 0.14.0.
The manifest includes catalog-file SHA-256 and per-source hashes, including the
baseline factory, evaluator, runtime and spend guard. Git commit alone is
insufficient: the baseline/evaluator/preparation include uncommitted worktree
files. Include those exact sources in the submission; do not claim a clean
checkout of the tag alone reproduces the whole comparison.

Final execution must verify these pins again and record its actual commit,
dirty/source hashes, compiled agent revisions, external source hashes, outer
adapter version/hash, model request configuration, fixture mode and each unique
arm/scenario/repetition attempt. Actual final execution identifiers do not yet
exist and are not invented here.

## Paid batch and budget, awaiting explicit approval

| Requested phase | Conversations | Expected USD projection | Conservative allowance USD |
|---|---:|---:|---:|
| Held-out: proposed, 16 x2 | 32 | 0.995319 | 2.511127 |
| Held-out: baseline, 16 x2 | 32 | 2.024924 | 5.507787 |
| Robustness: proposed, 8 x1 | 8 | 0.248830 | 0.627782 |
| **Total** | **72** | **3.269073** | **8.646696** |

Rounded planning numbers: **expected $3.27; spending allowance $9; proposed hard
global cap $10**. No amount is authorized. These are mix-dependent projections,
not final measurements, guarantees, or a forecast based on inspecting the sets.

Method: use the actual mean cost of the 35 proposed conversations with complete
usage ($1.088630 total), excluding the entire incomplete-usage conversation,
and all 36 baseline conversations ($2.278040 total). Do not divide incomplete
known cost across all 36 and implicitly price the missing call at zero.
Conservative allowance reprices those measured prompt/output counts with all
input uncached and permits 50% more calls/output/history of the same mean shape.
It is a planning allowance, not a mathematical worst case. Unseen scenario mix,
tool-error loops, longer histories, fixture clocks and contract coverage may
change cost. Prices are the recorded 2026-11-07 GPT-4o rates ($2.50/M uncached,
$1.25/M cached, $10/M output), last verified in existing evidence on 2026-11-10.

Use one shared SpendGuard across all phases, strict cold-request admission and
unknown-usage bounds. Sequential request admission must leave room for at least
the $0.32512 absolute per-request exposure before sending: 128K uncached input
plus the 512-token output cap, deliberately loose. A request already in flight
can be billed after a runner timeout; cancellation is not a refund. Reserve
its exposure, stop new admissions on cap/stop, and keep actual unknown usage
and total costs null with separately labeled known subtotals and bounds. The
observed-cost forecast is not the hard protection by itself. A cap can stop
the batch before all 72 conversations finish; report that incompleteness.
Parallel execution would need summed in-flight reservations and is excluded.

No automatic retries, selective failure reruns, revised expectations or
post-outcome scorer fixes. Persist attempt keys before/at admission so a crash
cannot silently repeat a paid case. Keep both repetitions even when they differ.

## Execution recipe after the compatibility decision

There is deliberately no fake --heldout switch on the DEV runner and no
implemented paid placeholder here. The approved adapter's eventual command
must express this exact plan as **one invocation and one shared cap**:

```
held-out external path + verified SHA: proposed x2, baseline x2
robustness external path + verified SHA: proposed x1
catalog: original pinned x1; mode: eval_fixture; evaluator: same adapter in both arms
global cap: $10 only if approved; concurrency: 1; retries: 0
```

The executable command must be supplied and its version pinned when that
adapter is approved, before spending. Current preparation commands are runnable;
claiming an external paid execution command already exists would be inaccurate.

## Remaining checklist

Agent can do independently now: preserve evidence/provenance, draft solution,
record known limitations and this budget. Completed in this preparation.

After the user's evaluator decision: implement/validate only the approved
external-contract adapter offline, keep frozen arm behavior unchanged, pin the
actual command/version, and stop for final paid authorization. After that go:
consume external files only inside the approved harness, execute once, and
report all attempts/unknowns without tuning or selective repeats.

User/manual: decide the evaluator compatibility approach and paid cap; re-test
voice Call B when possible (segmented name/DOB including numeric year, Midtown
retained, identity confirmation, offer/consent, no alternating-question loop).
Call A was reported verified in voice. Pending Call B does not block approved
text evaluation, but prevents claiming that voice path is verified.
