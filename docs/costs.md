# Logged API costs

Snapshot: 2026-11-09, through smoke-20261109-120039-2466b7. Built offline from all usage JSONL files currently present in `backend/logs/`. No API calls were made for this audit.

**Known OpenAI cost: $7.7238625. Complete project/API spend: not measured.** Missing usage, unlogged calls, ElevenLabs and coding-agent usage are excluded rather than estimated. The known subtotal is not an invoice reconciliation.

## Prices and accounting

All recorded model rows say `gpt-4o`. Apply the repository's **2026-11-07** recorded rates from `backend/evals/dev_matrix.py`: input $2.50, cached input $1.25, output $10.00 per million tokens. Recorded source: [OpenAI model page](https://developers.openai.com/api/docs/models/gpt-4o). These are historical rates already recorded in the project; no live price lookup was performed.

`USD = ((prompt − cached) × 2.50 + cached × 1.25 + completion × 10) / 1,000,000`.

Prompt tokens **include** cached tokens. “Total tokens” means prompt + completion; do not add cached again. Every JSONL model-call row is counted once using (call_id, turn); 0 duplicate rows found. Report JSON, rescored reports, transcript exports and voice tool traces are not additional charges. Rows without all three usage fields have unknown cost, never zero. Asterisks mark partial known token/cost subtotals. No-usage runs remain “not measured”, including interrupted runs without reports. Classification below describes the run's purpose; it does not imply a final frozen arm.

## One ledger by step and purpose

Each eval run ID links to its raw usage file. Default-log session IDs link to `turns.jsonl`. Legacy IDs are call IDs because run_id was absent. Columns are known quantities; “unknown rows” counts calls without complete usage.

| Step | Purpose / run ID | Calls | Prompt | Cached (included) | Completion | Total tokens | Known USD | Unknown rows |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 4. Scheduling regression | Development iteration (no results report present)<br>[dev-matrix-20261107-190336-d3aace](../backend/logs/evals/dev-matrix-20261107-190336-d3aace.jsonl) | 157 | 334,925 | 217,728 | 5,413 | 340,338 | $0.6192825 | 0 |
| 4. Scheduling regression | Development iteration<br>[dev-matrix-20261107-190558-7e3f9e](../backend/logs/evals/dev-matrix-20261107-190558-7e3f9e.jsonl) | 54 | 116,971 | 79,360 | 1,873 | 118,844 | $0.2119575 | 0 |
| 4. Scheduling regression | Development iteration<br>[dev-matrix-20261107-190721-72fce3](../backend/logs/evals/dev-matrix-20261107-190721-72fce3.jsonl) | 185 | 434,074 | 281,984 | 6,253 | 440,327 | $0.7952350 | 0 |
| 4. Scheduling regression | Development iteration<br>[dev-matrix-20261107-192904-7e4b2c](../backend/logs/evals/dev-matrix-20261107-192904-7e4b2c.jsonl) | 210 | 569,997 | 342,144 | 7,123 | 577,120 | $1.0685425 | 0 |
| 4. Catalog-first resolution | Final measurement of development snapshot (superseded)<br>[dev-matrix-20261107-193131-c96e6c](../backend/logs/evals/dev-matrix-20261107-193131-c96e6c.jsonl) | 205 | 556,152 | 428,800 | 6,897 | 563,049 | $0.9233500 | 0 |
| 5. Proposed-v2 | Development iteration<br>[dev-matrix-20261108-122031-20e4ff](../backend/logs/evals/dev-matrix-20261108-122031-20e4ff.jsonl) | 186 | 538,889 | 446,592 | 6,768 | 545,657 | $0.8566625 | 0 |
| 5. Proposed-v2 | Final measurement of development snapshot (not frozen)<br>[dev-matrix-20261108-122231-91750a](../backend/logs/evals/dev-matrix-20261108-122231-91750a.jsonl) | 192 | 607,546 | 480,896 | 7,062 | 614,608 | $0.9883650 | 0 |
| 4. Initial scheduling text | Development iteration<br>[first-three-182806b1](../backend/logs/evals/first-three-182806b1.jsonl) | 1 | not measured | not measured | not measured | not measured | not measured | 1 |
| 4. Initial scheduling text | Development iteration<br>[first-three-3730687c](../backend/logs/evals/first-three-3730687c.jsonl) | 8 | 24,442 | 19,840 | 295 | 24,737 | $0.0392550 | 0 |
| 4. Initial scheduling text | Development iteration<br>[first-three-4a504e73](../backend/logs/evals/first-three-4a504e73.jsonl) | 11 | 27,108 | 20,096 | 300 | 27,408 | $0.0456500 | 0 |
| 4. Initial scheduling text | Development iteration<br>[first-three-822a32dd](../backend/logs/evals/first-three-822a32dd.jsonl) | 17 | 40,804 | 30,208 | 696 | 41,500 | $0.0712100 | 0 |
| 4. Initial scheduling text | Development iteration<br>[first-three-d7dbbb9c](../backend/logs/evals/first-three-d7dbbb9c.jsonl) | 18 | 50,261 | 37,760 | 767 | 51,028 | $0.0861225 | 0 |
| 4. Booking/resolution investigation | Diagnostic<br>[pre-fix-booking-trace-20261107](../backend/logs/evals/pre-fix-booking-trace-20261107.jsonl) | 31 | 69,633 | 44,800 | 1,018 | 70,651 | $0.1282625 | 0 |
| 4. Booking/resolution investigation | Diagnostic<br>[pre-fix-trace-20261107](../backend/logs/evals/pre-fix-trace-20261107.jsonl) | 21 | 43,221 | 26,240 | 678 | 43,899 | $0.0820325 | 0 |
| 5. JSON graph/editor integration | Diagnostic smoke<br>[smoke-20261108-113800-a9e5e4](../backend/logs/evals/smoke-20261108-113800-a9e5e4.jsonl) | 1 | not measured | not measured | not measured | not measured | not measured | 1 |
| 5. JSON graph/editor integration | Diagnostic smoke<br>[smoke-20261108-113839-a15cf4](../backend/logs/evals/smoke-20261108-113839-a15cf4.jsonl) | 27 | 74,478 | 59,264 | 869 | 75,347 | $0.1208050 | 0 |
| 5. JSON graph/editor integration | Diagnostic smoke<br>[smoke-20261108-113955-ea7210](../backend/logs/evals/smoke-20261108-113955-ea7210.jsonl) | 3 | 6,450 | 5,376 | 82 | 6,532 | $0.0102250 | 0 |
| 5. Resolution/consent fixes | Diagnostic smoke<br>[smoke-20261109-114359-49b9ee](../backend/logs/evals/smoke-20261109-114359-49b9ee.jsonl) | 55 | 217,719 | 193,664 | 1,705 | 219,424 | $0.3192675 | 0 |
| 5. Resolution/consent fixes | Diagnostic smoke<br>[smoke-20261109-114541-8b41e2](../backend/logs/evals/smoke-20261109-114541-8b41e2.jsonl) | 34 | 112,080 | 90,880 | 1,163 | 113,243 | $0.1782300 | 0 |
| 5. Two-phase booking, fixtures | Diagnostic smoke<br>[smoke-20261109-120033-f175d3](../backend/logs/evals/smoke-20261109-120033-f175d3.jsonl) | 41 | 147,202 | 117,760 | 1,338 | 148,540 | $0.2341850 | 0 |
| 5. Two-phase booking, generated demo | Diagnostic smoke<br>[smoke-20261109-120039-2466b7](../backend/logs/evals/smoke-20261109-120039-2466b7.jsonl) | 23 | 84,573 | 72,576 | 774 | 85,347 | $0.1284525 | 0 |
| 1–5. Default log (step not recorded) | Diagnostic: session; I/O/purpose not recorded<br>[legacy-call:ffeeae4b-cb5a-4006-a7bf-2106c69e8183](../backend/logs/turns.jsonl) | 12 | 5,425* | 0* | 188* | 5,613* | $0.0154425* | 3 |
| 1–5. Default log (step not recorded) | Diagnostic: session; I/O/purpose not recorded<br>[legacy-call:f36602df-dae3-4515-ab96-941ce1565305](../backend/logs/turns.jsonl) | 6 | 2,411 | 0 | 91 | 2,502 | $0.0069375 | 0 |
| 1–5. Default log (step not recorded) | Diagnostic: session; I/O/purpose not recorded<br>[legacy-call:7f6cf13e-b477-4d8f-9e45-b4598ad0e98a](../backend/logs/turns.jsonl) | 9 | 5,694 | 0 | 196 | 5,890 | $0.0161950 | 0 |
| 1–5. Default log (step not recorded) | Diagnostic: session; I/O/purpose not recorded<br>[legacy-call:839109d0-d8c9-473f-9e4a-72f2600766b3](../backend/logs/turns.jsonl) | 1 | 150 | 0 | 25 | 175 | $0.0006250 | 0 |
| 1–5. Default log (step not recorded) | Diagnostic: session; I/O/purpose not recorded<br>[legacy-call:f41d44b6-83c7-447e-842e-032f56130216](../backend/logs/turns.jsonl) | 1 | 150 | 0 | 26 | 176 | $0.0006350 | 0 |
| 1–5. Default log (step not recorded) | Diagnostic: session; I/O/purpose not recorded<br>[legacy-call:f7beb88f-6f35-4edf-a329-e1c46599f821](../backend/logs/turns.jsonl) | 1 | 150 | 0 | 25 | 175 | $0.0006250 | 0 |
| 1–5. Default log (step not recorded) | Diagnostic: session; I/O/purpose not recorded<br>[3815ed93-796a-4319-b950-d8a848ad3fb5](../backend/logs/turns.jsonl) | 8 | 3,495* | 0* | 131* | 3,626* | $0.0100475* | 2 |
| 1–5. Default log (step not recorded) | Diagnostic: session; I/O/purpose not recorded<br>[04d9647f-774f-4816-a507-7988f6b28c59](../backend/logs/turns.jsonl) | 12 | 19,803* | 15,360* | 315* | 20,118* | $0.0334575* | 1 |
| 1–5. Default log (step not recorded) | Diagnostic: session; I/O/purpose not recorded<br>[f1a5c9cf-1675-42fb-9c47-c53b6b786a16](../backend/logs/turns.jsonl) | 26 | 34,718* | 21,376* | 490* | 35,208* | $0.0649750* | 6 |
| 1–5. Default log (step not recorded) | Diagnostic: session; I/O/purpose not recorded<br>[f5f58ca7-d2c7-4d2e-a44a-aaab239ae2e5](../backend/logs/turns.jsonl) | 20 | 38,780* | 31,104* | 431* | 39,211* | $0.0623800* | 3 |
| 1–5. Default log (step not recorded) | Diagnostic: session; I/O/purpose not recorded<br>[92190137-924c-40bc-9b63-cd0f861da19b](../backend/logs/turns.jsonl) | 1 | not measured | not measured | not measured | not measured | not measured | 1 |
| 1–5. Default log (step not recorded) | Diagnostic: session; I/O/purpose not recorded<br>[736086e8-0999-484a-8856-79d45d0c2d6c](../backend/logs/turns.jsonl) | 3 | 1,037* | 0* | 39* | 1,076* | $0.0029825* | 1 |
| 5. Voice verification | Diagnostic: voice, OpenAI component<br>[50331fcc-a19a-43a5-b029-a7770dc04621](../backend/logs/turns.jsonl) | 22 | 47,491* | 40,960* | 501* | 47,992* | $0.0725375* | 3 |
| 5. Voice verification | Diagnostic: voice, OpenAI component<br>[29ec30f7-3e7e-48b9-a060-e437a5453e1a](../backend/logs/turns.jsonl) | 9 | 15,532 | 9,344 | 317 | 15,849 | $0.0303200 | 0 |
| 5. Voice verification | Diagnostic: voice, OpenAI component<br>[df88c81d-e29d-4f7d-adc0-3eed727e25d5](../backend/logs/turns.jsonl) | 22 | 56,191* | 48,896* | 469* | 56,660* | $0.0840475* | 5 |
| 5. Voice verification | Diagnostic: voice, OpenAI component<br>[8f9fcdd8-a64e-497a-a903-0ffea953f123](../backend/logs/turns.jsonl) | 21 | 51,055* | 44,288* | 517* | 51,572* | $0.0774475* | 2 |
| 5. Voice verification | Diagnostic: voice, OpenAI component<br>[ccf218e3-9bd3-442f-9da5-f6a3449870a5](../backend/logs/turns.jsonl) | 15 | 16,191* | 10,496* | 383* | 16,574* | $0.0311875* | 1 |
| 5. Voice verification | Diagnostic: voice, OpenAI component<br>[70ca9d26-bad9-4c37-8e61-eb5a5be5cdf0](../backend/logs/turns.jsonl) | 23 | 73,305* | 59,520* | 553* | 73,858* | $0.1143925* | 3 |
| 5. Voice verification | Diagnostic: voice, OpenAI component<br>[be070748-88e6-48b3-ade9-f21159611fb7](../backend/logs/turns.jsonl) | 3 | 7,078 | 4,096 | 117 | 7,195 | $0.0137450 | 0 |
| 5. Voice verification | Diagnostic: voice, OpenAI component<br>[abbf5267-7fba-4f54-904f-d8576794d8e2](../backend/logs/turns.jsonl) | 13 | 39,273* | 35,328* | 339* | 39,612* | $0.0574125* | 1 |
| 5. Voice verification | Diagnostic: voice, OpenAI component<br>[33382990-bb0c-4148-8a62-05a287b55f81](../backend/logs/turns.jsonl) | 21 | 83,887* | 75,008* | 542* | 84,429* | $0.1213775* | 4 |
| **Eval/text subtotal** | **Known quantities only; complete spend unknown** | **1480** | **4,056,525*** | **2,995,968*** | **51,074*** | **4,107,599*** | **$6.9070925*** | **2** |
| **Default/voice OpenAI subtotal** | **Known quantities only; complete spend unknown** | **249** | **501,816*** | **395,776*** | **5,695*** | **507,511*** | **$0.8167700*** | **36** |
| **ALL RECORDED MODEL CALLS** | **Known quantities only; complete spend unknown** | **1729** | **4,558,341*** | **3,391,744*** | **56,769*** | **4,615,110*** | **$7.7238625*** | **38** |

## Coverage and things not measured

- Eval/text logs: $6.9070925 known, with 2 unknown-usage rows. All 21 raw eval run IDs present are included, even failed/unfinished runs. Rescoring existing responses adds no model calls.
- Default/voice log: $0.8167700 in recorded OpenAI usage, with 36 unknown-usage rows. Some sessions have no I/O label; matching call IDs in `voice-tools.jsonl` identify the voice rows above. Complete voice-call cost is **not measured**, even when its OpenAI component is fully reported.
- ElevenLabs STT and TTS: **not measured**. Tool logs record timing and arguments/results, not billable audio/character usage. No duration-based or character-based price estimate is substituted.
- Calls before logging, calls whose usage never reached disk, and missing/deleted log files: **not measured**. This audit cannot prove that all historical API calls are present.
- Coding-agent subscriptions/API usage, infrastructure, taxes and credits: **not measured** by these runtime logs.
- An unknown-usage row may be an interrupted request; missing usage does not establish either zero charge or a charge. No guessed amount is added.

## Future spend rule

Current rule in AGENTS.md: before any paid run, show an estimate and wait for
explicit authorization, regardless of amount. Batch booking/resolution-path
fixes before an approved smoke; no paid runs for docs, logs, tests or prompt
wording alone. Full matrices need explicit approval. The conditional 2026-11-10
scaling authorization applied only to the completed step below.

## 2026-11-10: step 6b scaling addendum

The earlier audit tables are their historical snapshot, not a current all-time
total. This addendum covers the revised scaling experiment only; comparison
measurements are separately documented in docs/comparison-evaluator-v5.md.
Purpose: development scaling measurement, with the search-only variant
explicitly exploratory. No held-out evaluation or voice/audio charge included.

| Phase | Model calls | Prompt tokens | Actual cached reads | Completion tokens | Actual USD |
|---|---:|---:|---:|---:|---:|
| Indexed proposed x5 | 60 | 500,482 | 462,976 | 1,673 | 0.689215 |
| Full-catalog baseline x5 | 56 | 1,775,158 | 1,685,376 | 1,703 | 2.348205 |
| Indexed proposed x10 | 27 | 387,438 | 366,848 | 777 | 0.517805 |
| Exploratory search-only x10 | 28 | 71,610 | 46,976 | 825 | 0.128555 |
| Exploratory search-only x50 | 30 | 75,032 | 52,992 | 812 | 0.129460 |
| **Step 6b total** | **201** | **2,809,720** | **2,615,168** | **5,790** | **3.813240** |

All usage known. At dated GPT-4o rates (2026-11-07, reverified 2026-11-10),
cached reads cost $3.268960, uncached input $0.486380, output $0.057900. No
additional cache-write charge; cache population is included in ordinary input.
Separate cache-write tokens/cost attribution are not reported, therefore null.
ElevenLabs/voice cost: not measured. Indexed x50: projection only, no API charge.

Estimate $4.704535; authorized hard global cap $8; actual $3.813240. No retries.
Run prefix scaling-v3-20261110-092924-e2cde6, with phase suffixes
proposed-indexed-x05, baseline-x05, proposed-indexed-x10,
exploratory-search-only-x10 and exploratory-search-only-x50. Each has its own
JSONL under backend/logs/evals/. Raw report is the same prefix plus
.results.json; manual analysis .analysis.json. Full receipts and findings:
docs/scaling-v3-results.md. These charges are not added to the historical grand
total above, which predates other separately recorded runs.


## 2026-11-10: approved final-evaluation attempts (infrastructure failures)

This addendum is separate from the historical ledger snapshot above. Both batches
stopped on the first report checkpoint; no retries, repairs or extra experiments.
Purpose: final measurement attempt, not a successful completed measurement.

| Batch / arm | Saved model calls | Prompt | Cached input | Completion | Known USD |
|---|---:|---:|---:|---:|---:|
| Revised held-out / proposed (HO-001 attempt only) | 9 | 29,747 | 24,064 | 241 | 0.0466975 |
| Revised robustness / proposed (RW-001 attempt only) | 9 | 30,281 | 26,368 | 289 | 0.0456325 |
| **Recorded subtotal** | **18** | **60,028** | **50,432** | **530** | **0.0923300** |

All saved rows have complete usage. Complete request coverage/final exposure is
unknown because terminal checkpoints failed; the raw zero-cost initial journals
are stale. No missing request is priced as zero. Dated 2026-11-07 rates: uncached
input $2.50/M, cached $1.25/M, output $10/M. Cached reads $0.0630400, uncached input
$0.0239900, output $0.0053000. Additional cache-write fee $0 under that rate card;
separate write-token and population attribution unreported. No baseline calls;
voice/STT/TTS not measured. Separate approved caps were $5 and $2, with full
$0.32512 per-request reserves. Final ledger/reserve unknown; see execution report.

Raw run IDs: external-v1.1-heldout-20261110-153532-72eb74 and
external-v1.1-robustness-20261110-153646-ed8563. Complete surviving receipts and
provenance: docs/results/final-evaluation/summary.json; narrative:
docs/final-evaluation-execution.md. These are partial infrastructure attempts,
not a completed held-out or robustness accuracy measurement.


## 2026-11-10: serialization repair and offline restart preparation

No new paid calls or spend. Tests use public DEV/synthetic data and SDK stubs;
their temporary usage logs are not billable receipts and are excluded. Prior
$0.0923300 known partial-attempt subtotal remains unchanged; original agent outcomes
are unknown. Historical total exposure can only be conditionally bounded by the
$5/$2 original caps, not certified from populated metric rows. New restart expected
incremental cost $1.76, fresh cap proposals $5/$2, all pending new approval.
Full bounds and budget caveats: docs/external-infrastructure-v1.2.md and
`docs/results/external-restart-budget-v1.2.json`. No old cost entry is overwritten.


## 2026-11-10: completed approved external-infra-v1.2 final restart

Purpose: final evaluation measurement, separate from DEV/scaling and the two
historical failed infrastructure attempts. Run `external-infra-v1.2-restart-20261110-175004-ec9627`, forty unique jobs once,
two linked replacements first. Fresh caps held-out $5, robustness $2; no retries.

| Batch / arm | Requests | Prompt | Cached | Uncached | Completion | USD |
|---|---:|---:|---:|---:|---:|---:|
| Held-out proposed | 76 | 228,081 | 187,264 | 40,817 | 2,053 | 0.3566525 |
| Held-out baseline | 62 | 478,056 | 435,072 | 42,984 | 1,998 | 0.6712800 |
| Robustness proposed | 73 | 256,473 | 226,432 | 30,041 | 2,114 | 0.3792825 |
| **Restart total** | **211** | **962,610** | **848,768** | **113,842** | **6,165** | **1.4072150** |

All admissions, usage, closed statuses and metric rows reconcile; no missing
usage or outstanding new exposure. Dated rates unchanged. Cache reads $1.0609600,
uncached input $0.2846050, output $0.0616500. Additional cache-write fee $0 under
that rate card; separate write tokens/population attribution unreported. No
voice/STT/TTS cost measured. Prior $0.0923300 known partial-attempt cost remains
separate with unresolved coverage; cumulative known $1.4995450, not a certified
old invoice total. Raw status 24 review-required/16 failed, not semantic accuracy.
No extra calls are authorized by unused caps. Details: docs/final-evaluation-restart-v1.2.md.


## 2026-11-12: total measured OpenAI spend to date

One total of the OpenAI (gpt-4o) spend measured so far: the 2026-11-09 ledger
snapshot above plus every paid run recorded after it. No API calls were made
for this calculation. Each later line was also recomputed offline from its raw
usage JSONL in backend/logs/evals/ (deduplicated by call_id and turn, dated
2026-11-07 rates) and matches its documented figure exactly. A file listing of
backend/logs/evals/ found no paid eval run after the snapshot other than these.

| # | Line | USD | Source |
|---:|---|---:|---|
| 1 | Ledger snapshot through smoke-20261109-120039-2466b7 (1,729 model calls, 38 with unknown usage) | 7.7238625 | docs/costs.md (snapshot above) |
| 2 | smoke-20261109-122509-3adf22 | 0.1543100 | docs/decisions.md (2026-11-09, geographic site choice and approved capped smoke) |
| 3 | smoke-20261109-123934-da8fb2 | 0.1707825 | docs/decisions.md (2026-11-09, approved recovery-v6 four-case smoke) |
| 4 | smoke-20261109-124555-cc5280 | 0.1139125 | docs/decisions.md (2026-11-09, closed catalog filters and capped two-case smoke) |
| 5 | smoke-20261109-124918-eeeec1 | 0.0404675 | docs/decisions.md (2026-11-09, DEV-012-only $0.08 smoke) |
| 6 | smoke-20261109-125320-fae71b | 0.1100000 | docs/decisions.md (2026-11-09, lazy catalog validation and observed-cost admission) |
| 7 | smoke-20261109-131238-90cbfb | 0.2273650 | docs/decisions.md (2026-11-09, approved slots-v7 four-case smoke) |
| 8 | dev-matrix-20261109-150315-454f33 (first official proposed matrix) | 1.0117100 | docs/decisions.md (2026-11-09, official frozen proposed measurement) |
| 9 | comparison-proposed-v2-20261109-180827-8752c3 (known part) | 1.0954425 | docs/decisions.md (2026-11-09, completed fresh v5 comparison); docs/comparison-evaluator-v5.md |
| 10 | comparison-baseline-20261109-182321-c4ee5f | 2.2780400 | docs/decisions.md (2026-11-09, completed fresh v5 comparison); docs/comparison-evaluator-v5.md |
| 11 | Scaling step 6b, five phases | 3.8132400 | docs/costs.md (2026-11-10, step 6b scaling addendum) |
| 12 | First final-evaluation attempts, stopped by a serialization bug | 0.0923300 | docs/costs.md (2026-11-10, approved final-evaluation attempts) |
| 13 | Final evaluation restart, 40 conversations | 1.4072150 | docs/costs.md (2026-11-10, completed approved external-infra-v1.2 final restart) |
| 14 | smoke-20261112-164821-2fe6d5 (v2.1) | 0.2417925 | docs/decisions.md (2026-11-12, v2.1 working-tree smoke) |
| | Lines 2 to 14, after the snapshot | 10.7566075 | sum |
| | **Total measured OpenAI spend** | **18.4804700** | sum of lines 1 to 14 |

**Total measured OpenAI spend to date: $18.4804700.** This is a sum of known,
logged charges at the recorded rates, not an invoice. It is a lower bound:

- **Not measured, so not included:**
  - the 38 snapshot rows with unknown usage;
  - one comparison-proposed request with unreported usage (maximum exposure
    $0.32512, documented separately);
  - the unresolved request coverage of the first final-evaluation attempts
    (line 12 counts only their saved rows).
- **Voice sessions after the 2026-11-09 snapshot are not measured in this
  total.** That includes the voice calls of November 9 to 12. Their OpenAI rows
  exist in the local, git-ignored turns.jsonl but were never ledgered.
- **ElevenLabs speech-to-text and text-to-speech are not measured** anywhere in
  this project. Neither are coding-agent usage, infrastructure or taxes.
- **Local refusals are not charges.** The three null-usage rows in the
  budget-stopped smokes (lines 4 and 5) are requests refused by the local
  budget guard before dispatch.

The API keys were provided by Prosper. This total therefore comes only from the
author's own usage logs. It was not checked against the OpenAI or ElevenLabs
provider dashboards.
