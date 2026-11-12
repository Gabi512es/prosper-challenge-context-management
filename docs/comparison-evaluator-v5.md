# Frozen proposed-v2 versus full-catalog baseline, evaluator v5

Official fresh DEV measurements, 2026-11-09. Both arms attempted all 12 scenarios three times. No repetition was retried. The proposed runtime, prompts, tools, guards and context handling stayed frozen at a5b124f; scenarios and expected outcomes were unchanged.

Evaluator: `dev-eval-v5-recovery`. Behavior SHA-256 (scorer and scripted-patient source): `97117348b6d00263d60c0561381841e3fc50e843873a53b60e827a8c7415a996`. Both reports also share execution SHA-256 `be63f5d4876dd066a96fdc2948d6a43c25df069c278b45e9ccb129d92e7a397e` for the final checkpoint/budget runner. The first two proposed attempts precede the operational pause; their unchanged patient/scorer code and original full-code hash are recorded in resume_provenance and the archived pause report.

## Overall comparison

| Metric | Proposed-v2 | Full catalog baseline |
|---|---:|---:|
| Raw passes | 29/36 (80.56%) | 30/36 (83.33%) |
| Raw failures | 7 | 6 |
| Successful bookings | 10 | 11 |
| Model calls, all admitted requests | 219 | 203 |
| Unnecessary factual/choice requests, reviewed | 9 | 5 |
| Of those, automatically logged | 6 | 1 |
| Invalid booking attempts observed | 0 | 0 |
| Wrong bookings created | 0 | 0 |
| Prompt tokens, including cached | 711,025 known + unknown | 1,625,524 |
| Cached input | 598,272 known + unknown | 1,482,240 |
| Uncached input | 112,753 known + unknown | 143,284 |
| Completion tokens | 6,572 known + unknown | 6,703 |
| OpenAI cost USD | $1.0954425 known + unknown; at most $1.4205625 | $2.2780400 |
| Entire-arm USD per successful booking | $0.10954425 known component; at most $0.14205625 | $0.20709455 |
| Completed patient turns | 93 | 91 |
| Text turn p50 / p95 | 2.619s / 3.208s | 2.634s / 3.420s |
| Incomplete patient turns | 1 | 0 |
| Authorized cap USD | $2.00 | $4.50 |

## Interpretation and limits

Baseline wins on the raw pass count (30 versus 29), total model calls (203 versus 219), and reviewed unnecessary requests (5 versus 9). It records the service directly in DEV-005/006: all three runs use three calls, versus proposed five/five/five and five/five/three, without re-asking the stated service. Proposed costs less even using the conservative bound for its one unreported request. Completed-turn latency is similar; the baseline has a slightly higher measured p95. These sequential, small DEV samples do not isolate model/provider jitter or establish statistical significance.

The one-pass raw score margin includes a proposed provider timeout. Each arm also has one manually identified evaluator false failure. Both have five remaining genuine agent-behavior failures, with different details. Raw scores above are preserved: no manual annotation promotes a run to pass. The previous 28/36 saved-transcript calculation remains counterfactual only, not an official result and not a run of the corrected harness.

Both arms retain the voice-driven refactor limitations: stated facts may be omitted from tool updates, missing-slot gates can ask again or suppress an explanation, the explicit clinical-distinction explanation was removed, and the guard misses the DEV-007 staff-confirmation wording. No agent fix or scenario-specific workaround was applied. Baseline has an additional invalid-ID resolution attempt; it is rejected before booking.

## Failure severity, manual review

One primary label per failed repetition; explanation omissions and infrastructure/evaluator artifacts are separated from false statements and wrong bookings. This is a manual audit of the scored failures, not a comprehensive automatic factuality guarantee.

| Primary failure severity/cause | Proposed | Baseline |
|---|---:|---:|
| Unnecessary question / blocked conversation | 2 | 1 |
| Internal/tool resolution error | 0 | 1 |
| False statement to patient | 1 | 0 |
| Missing explanation or next step | 2 | 3 |
| Wrong booking | 0 | 0 |
| Infrastructure timeout | 1 | 0 |
| Evaluator false failure | 1 | 1 |

| Arm / failed repetition | Primary label | Transcript / tool evidence |
|---|---|---|
| proposed-v2 DEV-001/2 | infrastructure_timeout | First patient turn exceeded 45 seconds; response usage arrived after about 61 seconds; one cleanup follow-up request has unknown usage. No retry. |
| proposed-v2 DEV-002/3 | unnecessary_question | Three status requests; the patient answered twice. The driver logged the second request; the exhausted third request is counted here. |
| proposed-v2 DEV-007/1 | false_patient_statement | After Please have a staff member confirm the intended service, agent says unable to transfer without an explicit request. The requested catalog-distinction explanation is also missing. |
| proposed-v2 DEV-007/2 | missing_explanation_or_next_step | After the staff-confirmation request the only reply is No transfer or callback is recorded. |
| proposed-v2 DEV-007/3 | missing_explanation_or_next_step | Tells the patient to choose either service after the patient explicitly said they cannot choose; never explains the undocumented distinction. |
| proposed-v2 DEV-011/1 | unnecessary_question | After the requested spelling is supplied, the controller asks for a service instead of finishing the hard-provider no-match. |
| proposed-v2 DEV-011/3 | evaluator_false_failure | Final reply clearly says I didn't find any provider with the name Dr. Zephyr Imaginary. All assertions except runner_completed pass. Completion matcher lacks didn't find, so the script exhausts. No result is promoted to pass. |
| baseline DEV-002/1 | unnecessary_question | Three status requests; the patient answered twice. The driver logged the second request; the exhausted third request is counted here. |
| baseline DEV-007/1 | missing_explanation_or_next_step | After cannot choose and a staff request, asks to search earliest appointments for either service; missing clinical-distinction explanation. |
| baseline DEV-007/2 | missing_explanation_or_next_step | After cannot choose and a staff request, asks to proceed with one of the services; no catalog-distinction explanation. |
| baseline DEV-007/3 | missing_explanation_or_next_step | After the staff request, reply is only No transfer or callback is recorded; no explanation or next step. |
| baseline DEV-011/1 | evaluator_false_failure | Does not match any provider in our catalog is a valid named no-match but is absent from acknowledgement/completion phrase lists. Verify the name also lacks the spelling trigger. Raw failure retained. |
| baseline DEV-011/3 | internal_tool_resolution_error | Model submits provider_id=prov_unknown. Runtime rejects it. Patient sees provider id filter didn't match and Which catalog option did you mean instead of an unknown-provider explanation. No booking attempt. |

Residual evaluator limitations were discovered during this locked measurement and left unchanged for both arms. Proposed DEV-011/3 says "I didn’t find any provider with the name Dr. Zephyr Imaginary"; all assertions except runner_completed pass, but completion omits that synonym. Baseline DEV-011/1 says "does not match any provider in our catalog" and asks to verify the name; acknowledgement/completion omit that synonym, and verify does not trigger the spelling response. These are evaluator artifacts. Proposed DEV-011/1 instead asks for a service after the supplied spelling, a genuine controller limitation. Baseline DEV-011/3 submits provider_id=prov_unknown; runtime rejects it and the patient sees a technical filter clarification rather than an unknown-provider explanation.

## Per-scenario outcomes, model calls and costs

Calls show repetitions 1 / 2 / 3. USD is the sum of all three attempted conversations, including failures. An asterisk marks an incomplete known subtotal, never an assumed zero.

| Scenario | Proposed pass | Baseline pass | Proposed calls | Baseline calls | Proposed USD | Baseline USD |
|---|---:|---:|---|---|---:|---:|
| DEV-001 | 2/3 | 3/3 | 9 / 3 / 9 | 9 / 9 / 9 | 0.1028925* | 0.3072225 |
| DEV-002 | 2/3 | 2/3 | 11 / 11 / 7 | 6 / 11 / 11 | 0.1549100 | 0.3030750 |
| DEV-003 | 3/3 | 3/3 | 3 / 3 / 3 | 3 / 3 / 3 | 0.0398950 | 0.1019175 |
| DEV-004 | 3/3 | 3/3 | 3 / 3 / 3 | 3 / 3 / 3 | 0.0363175 | 0.0915900 |
| DEV-005 | 3/3 | 3/3 | 5 / 5 / 5 | 3 / 3 / 3 | 0.0648675 | 0.0926175 |
| DEV-006 | 3/3 | 3/3 | 5 / 5 / 3 | 3 / 3 / 3 | 0.0565425 | 0.0930575 |
| DEV-007 | 0/3 | 0/3 | 5 / 4 / 5 | 3 / 3 / 3 | 0.0597200 | 0.0897900 |
| DEV-008 | 3/3 | 3/3 | 9 / 9 / 9 | 9 / 9 / 9 | 0.1418225 | 0.3120650 |
| DEV-009 | 3/3 | 3/3 | 11 / 11 / 11 | 11 / 11 / 11 | 0.2138025 | 0.4181625 |
| DEV-010 | 3/3 | 3/3 | 3 / 3 / 3 | 3 / 3 / 3 | 0.0346000 | 0.0923675 |
| DEV-011 | 1/3 | 1/3 | 5 / 4 / 4 | 2 / 2 / 3 | 0.0520375 | 0.0695750 |
| DEV-012 | 3/3 | 3/3 | 9 / 9 / 9 | 9 / 9 / 9 | 0.1380350 | 0.3066000 |

DEV-001 proposed repetition 2 has three admitted model calls, two with usage and one unreported; its first patient turn timed out. No attempt is replaced by another repetition. Mixed pass/fail scenarios in each arm: DEV-001/002/011 for proposed, DEV-002/011 for baseline. DEV-007 fails all three in both.

| Booking scenario | Proposed successful bookings | Baseline successful bookings | Proposed USD per success | Baseline USD per success |
|---|---:|---:|---:|---:|
| DEV-001 | 2 | 3 | 0.05144625 known; ≤0.21400625 | 0.10240750 |
| DEV-002 | 2 | 2 | 0.07745500 | 0.15153750 |
| DEV-009 | 3 | 3 | 0.07126750 | 0.13938750 |
| DEV-012 | 3 | 3 | 0.04601167 | 0.10220000 |

Per-scenario cost per success uses every attempted repetition of that scenario in the numerator. The overall cost-per-booking row uses the entire arm, including legitimate refusals/FAQ cases and every failure, divided by correct, consented bookings. Non-booking scenarios have no booking-cost denominator.

## Proposed per-scenario usage

| Scenario | Prompt incl. cached | Cached | Uncached | Completion | USD min–max per run |
|---|---:|---:|---:|---:|---:|
| DEV-001 | 65,757* | 53,888* | 11,869* | 586* | unknown (one unreported call) |
| DEV-002 | 102,224 | 86,272 | 15,952 | 719 | 0.0310975–0.0643400 |
| DEV-003 | 23,026 | 16,768 | 6,258 | 329 | 0.0121400–0.0153075 |
| DEV-004 | 22,811 | 18,816 | 3,995 | 281 | 0.0117975–0.0124225 |
| DEV-005 | 41,095 | 34,560 | 6,535 | 533 | 0.0211125–0.0220275 |
| DEV-006 | 35,097 | 28,416 | 6,681 | 432 | 0.0118925–0.0224550 |
| DEV-007 | 36,608 | 28,928 | 7,680 | 436 | 0.0176700–0.0212675 |
| DEV-008 | 91,813 | 78,080 | 13,733 | 989 | 0.0453500–0.0496050 |
| DEV-009 | 143,289 | 122,880 | 20,409 | 918 | 0.0699325–0.0738975 |
| DEV-010 | 22,412 | 18,816 | 3,596 | 209 | 0.0112350–0.0118450 |
| DEV-011 | 34,155 | 29,440 | 4,715 | 345 | 0.0156625–0.0206850 |
| DEV-012 | 92,738 | 81,408 | 11,330 | 795 | 0.0454425–0.0469650 |
## Baseline per-scenario usage

| Scenario | Prompt incl. cached | Cached | Uncached | Completion | USD min–max per run |
|---|---:|---:|---:|---:|---:|
| DEV-001 | 219,245 | 199,808 | 19,437 | 887 | 0.0992275–0.1081175 |
| DEV-002 | 221,770 | 207,616 | 14,154 | 817 | 0.0607025–0.1220600 |
| DEV-003 | 65,963 | 52,992 | 12,971 | 325 | 0.0311650–0.0395325 |
| DEV-004 | 65,740 | 60,800 | 4,940 | 324 | 0.0297050–0.0311700 |
| DEV-005 | 65,719 | 59,776 | 5,943 | 304 | 0.0295975–0.0321625 |
| DEV-006 | 65,683 | 59,904 | 5,779 | 373 | 0.0309550–0.0311400 |
| DEV-007 | 64,436 | 59,904 | 4,532 | 358 | 0.0299025–0.0299475 |
| DEV-008 | 219,746 | 197,504 | 22,242 | 958 | 0.1012500–0.1070575 |
| DEV-009 | 301,817 | 276,608 | 25,209 | 938 | 0.1368875–0.1416325 |
| DEV-010 | 65,335 | 58,880 | 6,455 | 263 | 0.0302975–0.0317075 |
| DEV-011 | 50,662 | 47,616 | 3,046 | 244 | 0.0189650–0.0305100 |
| DEV-012 | 219,408 | 200,832 | 18,576 | 912 | 0.1004650–0.1035200 |

## Per-scenario completed text-turn latency

| Scenario | Proposed turns | Baseline turns | Proposed p50 / p95, seconds | Baseline p50 / p95, seconds |
|---|---:|---:|---:|---:|
| DEV-001 | 8 | 12 | 2.764 / 16.588 | 2.733 / 3.281 |
| DEV-002 | 14 | 16 | 2.605 / 2.864 | 2.400 / 2.870 |
| DEV-003 | 3 | 3 | 2.498 / 3.479 | 3.246 / 3.301 |
| DEV-004 | 3 | 3 | 2.439 / 2.604 | 2.640 / 2.705 |
| DEV-005 | 6 | 3 | 2.791 / 3.190 | 2.631 / 3.212 |
| DEV-006 | 5 | 3 | 2.467 / 2.622 | 3.276 / 3.758 |
| DEV-007 | 6 | 6 | 2.597 / 3.081 | 1.715 / 1.816 |
| DEV-008 | 12 | 12 | 2.698 / 3.535 | 2.844 / 3.772 |
| DEV-009 | 15 | 15 | 2.528 / 2.955 | 2.628 / 3.739 |
| DEV-010 | 3 | 3 | 2.394 / 2.682 | 2.670 / 2.948 |
| DEV-011 | 6 | 3 | 2.442 / 2.934 | 1.773 / 3.676 |
| DEV-012 | 12 | 12 | 2.778 / 3.019 | 2.627 / 3.083 |

## Metric definitions and integrity

- Unnecessary requests count assistant turns that re-request supplied facts, re-request a service choice after the caller said they cannot choose, or ask an irrelevant catalog/service choice after a hard unavailable-provider request. Useful first disambiguation/spelling checks, code-generated identity/booking consent and permission to change constraints are excluded. Driver logs find 6 proposed and 1 baseline; manual transcript review adds 3 and 4, with exact turn indices in the annotation artifact. The counts cover these concrete redundant requests; they are not an automatic general conversational-quality score.
- Invalid booking attempts mean observed book_appointment results rejected for invalid/stale/unavailable inputs (error, blocked, validation_required, slot_taken). Normal phase-one preparation, needs_confirmation, identity collection and consent requests are excluded. Both observed counts are zero. The baseline prov_unknown argument is a resolution error, not a booking attempt. Proposed’s cancelled unreported follow-up has no complete tool/output trace; zero observed is not proof about unobserved output. No wrong bookings are present in the saved outcomes.
- Latency uses monotonic session.send wall-clock time through tool calls, transitions and final assistant generation. It excludes startup, scripted-patient think time, inter-session pauses and incomplete turns. Percentiles pool completed turns, with linear interpolation at (n−1)p. Proposed has 93 completed turns and one censored 45.000-second timeout; baseline has 91 completed turns. The timeout’s API response arrived after about 61 seconds and its cancelled follow-up is counted as a model request. Proposed’s largest completed turn is 23.910 seconds. Percentiles should be read alongside that outlier and timeout, and do not measure STT/TTS, interruptions or perceived voice latency.
- One proposed request has no usage. Actual total prompt/cached/output tokens, total USD and actual USD per booking remain null in machine-readable data; known subtotals are separate. They are never filled with zero. $0.32512 is held only as the maximum possible charge (128K uncached GPT-4o context plus 512 capped output tokens), verified against [official model limits and rates](https://developers.openai.com/api/docs/models/gpt-4o). Therefore proposed’s actual USD is bounded by $1.0954425–$1.4205625, not measured exactly. Baseline usage is complete. Combined known cost is $3.3734825; combined maximum exposure is $3.6986025. Both authorized caps were respected.
- Prices are dated 2026-11-07: $2.50/M uncached input, $1.25/M cached input, $10/M output. Formula: ((prompt−cached)*2.50 + cached*1.25 + completion*10)/1,000,000. Cached tokens are included in prompt. Historical rates were also confirmed by the official model page on 2026-11-09. No speech-service cost is part of this text measurement.
- Baseline catalog remains the complete readable 5,894-token rendering measured with gpt-4o/o200k_base. It uses the same model, fixtures, patient source, scorer, find_slots/book_appointment/get_details, guards and APPEND behavior; resolver is ID-only. Prefix stability was proven offline; this paid run measures real cached tokens above.
- Both arms share evaluator behavior SHA, execution SHA, scenario SHA, catalog blob pin, model, one-at-a-time execution, 512-token completion cap and disabled SDK/timeout retries. Proposed source remains frozen. No scenario file beyond backend/evals/dev_scenarios.json was used. Development-only evidence does not establish held-out or voice performance.

## Artifacts

- [Proposed raw results](../backend/logs/evals/comparison-proposed-v2-20261109-180827-8752c3.results.json)
- [Baseline raw results](../backend/logs/evals/comparison-baseline-20261109-182321-c4ee5f.results.json)
- [Machine-readable comparison](../backend/logs/evals/comparison-v5-summary.json)
- [Manual severity/question annotations](../backend/logs/evals/comparison-v5-manual-review.json)
- Per-model JSONL files share each raw report’s run ID. Logs are ignored local artifacts; this Markdown preserves the main measured results.
