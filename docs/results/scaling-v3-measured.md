# Step 6b: revised scaling experiment results

2026-11-10. All 28 authorized conversations completed for **$3.813240**, below the global $8 cap. Expected cost was $4.704535. There were 201 admitted/model-usage rows, no missing usage, no SDK/timeout retries, and no indexed x50 API run. The frozen-82 secondary arm was dropped.

## Scope and method

Cases: DEV-002, DEV-003, DEV-009, DEV-012. Indexed proposed x5 and baseline x5 each have two repetitions per case; indexed proposed x10 and exploratory search-only x10/x50 each have one. These subset results do not replace the official x1 12 x3 comparison or demonstrate held-out accuracy.

Frozen proposed source, instructions, model, core, guards, original catalog and scenario source are unchanged. Indexed copies replace only the index data with the same ID + name format. No specialty field. Expander catalog-disjoint-v1, fixed seed 20261109; index/plan version scaled-index-v3-id-name-search-only. All original entities/relations/policies persist; synthetic research-service records are disconnected distractors, no availability is added, and the eight original orphan types remain unbookable. No scenario facts, fixture or expected result changed.

Search-only is exploratory, not a change to proposed-v2: its experiment copy removes the type index, replaces the one index-access sentence with free-text query access, and its experiment registry omits/rejects catalog IDs in resolve_options. The handler, get_details/find_slots/book_appointment and mandatory dialogue/consent guards stay shared. Actual traces confirm no resolve_options catalog IDs in search-only. get_details IDs and booking slot IDs remain supported.

The experiment harness injects the expanded catalog with a scoped override of the unchanged v5 patient-driver catalog loader. Original scenario loading still validates the source catalog blob before each case. Same evaluator **dev-eval-v5-recovery**, behavior SHA `97117348b6d00263d60c0561381841e3fc50e843873a53b60e827a8c7415a996`, for all arms. No rescoring or patient changes after observing failures.

The installed request serializer was checked offline for all five phases with different histories: identical system/task prefixes and tool-schema hashes, zero API calls. That enables caching; the actual measured reads below determine its realized benefit. Paid order was indexed x5, baseline x5, indexed x10, search-only x10, search-only x50. Prefix/cache sharing between sessions or phases was allowed; no cache clearing or paid prewarming.

## Actual results

| Arm / scale | Passes | Calls | Correct bookings | Invalid booking attempts | Cost USD | Cost/correct booking USD, failures included | Patient-turn p50 / p95 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| proposed-indexed x5 | 6/8 | 60 | 4 | 0 | 0.689215 | 0.172304 | 2.593 / 3.224 |
| baseline x5 | 5/8 | 56 | 3 | 0 | 2.348205 | 0.782735 | 2.871 / 5.593 |
| proposed-indexed x10 | 3/4 | 27 | 2 | 0 | 0.517805 | 0.258902 | 2.696 / 3.753 |
| exploratory-search-only x10 | 3/4 | 28 | 2 | 0 | 0.128555 | 0.064278 | 2.861 / 4.272 |
| exploratory-search-only x50 | 3/4 | 30 | 2 | 0 | 0.129460 | 0.064730 | 2.602 / 3.535 |

Correct booking count requires the original booking-field and consent assertions. No wrong booking or invalid booking attempt was observed. Text latency covers complete patient turns, including all model/tool follow-ups; it excludes startup, STT and TTS. No patient turn timed out in this experiment. Conversation failures were scored failures, not transport timeouts.

At x5, baseline used fewer aggregate model calls (56 vs 60), but passed one fewer case (5/8 vs 6/8). Successful comparable DEV-003/009/012 paths used the same call counts; early failures contribute to the lower aggregate. Baseline cost and latency were higher in this sample. Exploratory search-only matched indexed x10 raw score (3/4) at lower cost, but with a different DEV-002 failure and one repetition each. This is evidence for further investigation, not equivalent accuracy or a replacement/fix of the frozen arm.

Actual total cost below the projection reflects changed call counts, including
early failed conversations, as well as cache behavior. It is not attributed to
caching alone.

## Actual tokens and cache charges

Dated GPT-4o prices: 2026-11-07 ledger, verified unchanged 2026-11-10: $2.50/M uncached input, $1.25/M cached reads, $10/M output. [Official pricing](https://developers.openai.com/api/docs/models/gpt-4o). Costs below are calculated from actual per-call reported usage, including post-tool calls, not tokenizer estimates or projected cache fractions.

| Arm / scale | Total prompt | Actual cached reads | Uncached prompt | Completion | Cached-read USD | Uncached-input USD | Output USD |
|---|---:|---:|---:|---:|---:|---:|---:|
| proposed-indexed x5 | 500,482 | 462,976 | 37,506 | 1,673 | 0.578720 | 0.093765 | 0.016730 |
| baseline x5 | 1,775,158 | 1,685,376 | 89,782 | 1,703 | 2.106720 | 0.224455 | 0.017030 |
| proposed-indexed x10 | 387,438 | 366,848 | 20,590 | 777 | 0.458560 | 0.051475 | 0.007770 |
| exploratory-search-only x10 | 71,610 | 46,976 | 24,634 | 825 | 0.058720 | 0.061585 | 0.008250 |
| exploratory-search-only x50 | 75,032 | 52,992 | 22,040 | 812 | 0.066240 | 0.055100 | 0.008120 |
| Total | 2,809,720 | 2,615,168 | 194,552 | 5,790 | 3.268960 | 0.486380 | 0.057900 |

Cache-write accounting: GPT-4o Chat Completions does not expose separate write-token usage here; write tokens and separately attributed write-input cost are null. The additional write fee is **$0**, per [OpenAI cache billing](https://developers.openai.com/api/docs/guides/prompt-caching). Cache-populating work is already included in the measured uncached-input column. Do not treat all uncached input as a known cache write, charge it twice, or claim populating the cache was free. Voice/ElevenLabs cost is not measured by this text experiment.

## Per-scenario receipts

| Arm / scale | Scenario | Passes | Model calls per repetition | Prompt tokens | Cached reads | Total USD | Min / max repetition USD |
|---|---|---:|---|---:|---:|---:|---:|
| proposed-indexed x5 | DEV-002 | 0/2 | 7/7 | 109,013 | 96,128 | 0.155502 | 0.073955 / 0.081547 |
| proposed-indexed x5 | DEV-003 | 2/2 | 3/3 | 43,749 | 39,936 | 0.061463 | 0.030627 / 0.030835 |
| proposed-indexed x5 | DEV-009 | 2/2 | 11/11 | 200,402 | 188,544 | 0.271415 | 0.135008 / 0.136407 |
| proposed-indexed x5 | DEV-012 | 2/2 | 9/9 | 147,318 | 138,368 | 0.200835 | 0.100157 / 0.100678 |
| baseline x5 | DEV-002 | 0/2 | 6/6 | 370,536 | 336,000 | 0.509830 | 0.236125 / 0.273705 |
| baseline x5 | DEV-003 | 2/2 | 3/3 | 184,644 | 180,736 | 0.237950 | 0.118828 / 0.119123 |
| baseline x5 | DEV-009 | 2/2 | 11/11 | 717,100 | 704,256 | 0.918860 | 0.459430 / 0.459430 |
| baseline x5 | DEV-012 | 1/2 | 7/9 | 502,878 | 464,384 | 0.681565 | 0.318232 / 0.363333 |
| proposed-indexed x10 | DEV-002 | 0/1 | 4 | 53,542 | 45,312 | 0.078095 | 0.078095 / 0.078095 |
| proposed-indexed x10 | DEV-003 | 1/1 | 3 | 39,821 | 38,016 | 0.053172 | 0.053172 / 0.053172 |
| proposed-indexed x10 | DEV-009 | 1/1 | 11 | 166,075 | 159,872 | 0.218427 | 0.218427 / 0.218427 |
| proposed-indexed x10 | DEV-012 | 1/1 | 9 | 128,000 | 123,648 | 0.168110 | 0.168110 / 0.168110 |
| exploratory-search-only x10 | DEV-002 | 0/1 | 5 | 8,981 | 5,760 | 0.016682 | 0.016682 / 0.016682 |
| exploratory-search-only x10 | DEV-003 | 1/1 | 3 | 4,456 | 1,152 | 0.010780 | 0.010780 / 0.010780 |
| exploratory-search-only x10 | DEV-009 | 1/1 | 11 | 36,262 | 25,600 | 0.061695 | 0.061695 / 0.061695 |
| exploratory-search-only x10 | DEV-012 | 1/1 | 9 | 21,911 | 14,464 | 0.039398 | 0.039398 / 0.039398 |
| exploratory-search-only x50 | DEV-002 | 0/1 | 7 | 13,855 | 10,368 | 0.023158 | 0.023158 / 0.023158 |
| exploratory-search-only x50 | DEV-003 | 1/1 | 3 | 4,458 | 2,304 | 0.009365 | 0.009365 / 0.009365 |
| exploratory-search-only x50 | DEV-009 | 1/1 | 11 | 36,290 | 25,728 | 0.061545 | 0.061545 / 0.061545 |
| exploratory-search-only x50 | DEV-012 | 1/1 | 9 | 20,429 | 14,592 | 0.035393 | 0.035393 / 0.035393 |

The repeated x5 outcomes agree on every indexed case. Baseline DEV-012 disagrees across repetitions (fail/pass). One-repetition phases cannot establish run-to-run agreement.

## Offline failure review, no changes

All eight raw failures were reviewed. Manual severity annotations are separate from the immutable scored report. Seven are unnecessary-question/resolution failures, one is a patient-facing false unavailability statement; no wrong booking. The driver logs five redundant questions; manual review adds seven (five final unanswered repeated status questions and two unnecessary provider questions), total twelve. These annotations do not turn failures into passes.

- **proposed-indexed x5 DEV-002/1: unnecessary question**. Patient twice says I am a new patient. No subsequent resolve_options update; is_new_patient remains null. The code-generated question repeats three times, including a final unanswered repeat beyond the driver reply limit.
- **proposed-indexed x5 DEV-002/2: unnecessary question**. Patient twice says I am a new patient. No subsequent resolve_options update; is_new_patient remains null. The code-generated question repeats three times, including a final unanswered repeat beyond the driver reply limit.
- **baseline x5 DEV-002/1: unnecessary question**. Patient twice says I am a new patient. No subsequent resolve_options update; is_new_patient remains null. The code-generated question repeats three times, including a final unanswered repeat beyond the driver reply limit.
- **baseline x5 DEV-002/2: unnecessary question**. Patient twice says I am a new patient. No subsequent resolve_options update; is_new_patient remains null. The code-generated question repeats three times, including a final unanswered repeat beyond the driver reply limit.
- **baseline x5 DEV-012/1: false statement to patient**. Knee MRI requested, but resolve_options uses appt_064 (MRI - Spine), not appt_065 (MRI - Knee). No fixture slot fits the wrong service. Patient hears: No matching slots are available. Would you like to change your search constraints? No booking created.
- **proposed-indexed x10 DEV-002/1: unnecessary question**. After Maria Garcia, Family Medicine nurse practitioner and Midtown are supplied, no second resolve_options call occurs, provider stays unresolved, and the agent asks to spell the first name and surname. DEV-002 driver has no reply for that spelling question.
- **exploratory-search-only x10 DEV-002/1: unnecessary question**. resolve_options provider_query is Dr. Maria Garcia, Family Medicine. Shared resolver returns original prov_019 Dr. Maria Martinez (ENT), with requires_confirmation and a specialty filter_no_match. Agent asks Did you mean Dr. Maria Martinez? No provider is selected or booked. Specialty was embedded in the name query; no synthetic provider caused the collision.
- **exploratory-search-only x50 DEV-002/1: unnecessary question**. Patient twice says I am a new patient. No subsequent resolve_options update; is_new_patient remains null. The code-generated question repeats three times, including a final unanswered repeat beyond the driver reply limit.

The repeated-status failures reproduce a known frozen voice-refactor limitation; patient answers were supplied but not recorded. Indexed x10 and search-only x10 also expose patient-driver limits on unexpected follow-up questions. The observed agent/resolver mistakes precede that exhaustion, so no counterfactual pass is claimed. Search-only’s Maria Martinez candidate is an original catalog entity, not a generated name collision. No fix, retry, alias, prompt rule, scenario change or scorer correction followed these observations.

## Offline sizes and projection-only results

Exact tokenizer: tiktoken o200k_base for gpt-4o. Baseline catalog sizes include all readable fields/policies; index sizes include only compact ID + name JSON, excluding instructions, tools and history.

| Scale | Locations / providers / types | Baseline catalog tokens | Complete two-field index tokens |
|---|---:|---:|---:|
| x1 | 8/50/82 | 5,894 | 1,026 |
| x5 | 40/250/410 | 29,333 | 5,792 |
| x10 | 80/500/820 | 58,664 | 11,768 |
| x20 | 160/1000/1640 | 121,030 | 24,320 |
| x50 | 400/2500/4100 | 313,545 | 62,571 |

**Indexed proposed x50 is projection only:** four conversations would project to $3.138741 with the prior cache/call profile, or $5.336442 all-cold. Longest observed-history shape plus 512 output reserve projects to 68,173 tokens. No indexed x50 API usage, cost, pass rate or latency was measured.

Baseline x10+ costs are likewise projections only, four conversations (one per case):

| Scale | Full request + output reserve, projected | Cached-profile USD projection | All-cold USD projection | Fit? |
|---|---:|---:|---:|---|
| x10 | 64,193 | 2.764025 | 4.949680 | Conditional on saved history |
| x20 | 126,559 | 5.576722 | 9.990932 | Conditional on saved history |
| x21 | 132,984 | 5.866489 | 10.510286 | No; dollars hypothetical with unlimited context |
| x22 | 139,396 | 6.155669 | 11.028589 | No; dollars hypothetical with unlimited context |
| x50 | 319,074 | 14.259122 | 25.552561 | No; dollars hypothetical with unlimited context |

Catalog alone first exceeds 128K at x22 (133,867 tokens); x21 is 127,455 catalog tokens but already projects to 128,669 initial input before output reserve. x20 has only 1,441 tokens beyond the longest saved history/output shape. No truncation or replacement model is proposed. Costs at infeasible sizes are token-price extrapolations, not runnable GPT-4o estimates.

Flat search-only prompt/cost at x10/x50 is observed only for four original requests against disconnected distractors and unchanged closed-world fixtures. No queries asking for generated services, held-out accuracy, adversarial near-neighbor realism, constant Python lookup time or general flat-cost guarantee were tested.

## Reproduction and provenance

`make test`: 128 tests, 126 passed, two opt-in paid integrations skipped. Offline expanded serializer checks: ten serializations, all five phase prefixes/tool schemas stable, zero API requests. Original source pin/config bytes and evaluator hash remain unchanged. Each of the 28 phase/scenario/repetition keys is unique; all 201 admitted requests have JSONL usage and matching saved agent id/revision/fixture mode.

Experiment entrypoint: backend/evals/scaling_matrix.py; offline generator: backend/evals/catalog_scaling.py. The CLI only runs with --run-paid, rejects an expected cost >= $6, uses one global $8 guard, and offers no resume/retry option. This completed authorization is not permission for a later repeat.

Results: backend/logs/evals/scaling-v3-20261110-092924-e2cde6.results.json. Manual review/aggregates: backend/logs/evals/scaling-v3-20261110-092924-e2cde6.analysis.json. Each phase has its own run-id JSONL under backend/logs/evals/. All are local ignored artifacts. The machine report contains each phase metrics path and all transcripts/tool results. Offline data/manifests/agent copies/serializer evidence: backend/logs/evals/scaling-catalog-disjoint-v1-seed20261109-scaled-index-v3-id-name-search-only/. No other scenario source was inspected.
