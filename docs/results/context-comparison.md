# Measured catalog-context comparison

This is a curated aggregate record of the completed experiments, not a new run.
[Machine-readable values and provenance](context-comparison.json) retain exact selected
fields from the original reports. No score or expected outcome was changed. Individual
transcripts, private evaluation assets and local paths are excluded from this package.

## Exact evaluated versions

- Historical proposed source: locally preserved tag proposed-v2, commit a5b124f7aa3ffa9d7ebcd32a7f76c837c95486c8.
- Proposed agent revision: 40db1b587b5790ab2c92bc642edbc55e67f0d44ebd8d4f1267de29e1e86ebdc5.
- Generated baseline agent revision: 68d02acb9a89a72c279c3410001e2b184438abce7f7c714ce39a0e87ddf4f623.
- Configured model for both measured arms: gpt-4o (alias, not the current v4 dated snapshot).
- Evaluator: dev-eval-v5-recovery; behavior SHA-256
  97117348b6d00263d60c0561381841e3fc50e843873a53b60e827a8c7415a996.
- Same scripted patients, fixtures, policies, find_slots/book_appointment/get_details,
  booking safeguards and APPEND context. Baseline resolver is ID-only; its stable prefix
  contains the complete readable catalog and policies. Proposed uses the ID/name index
  and search. This compares whole context strategies, not isolated model components.

The current submission runs v4 with interpreter v1.10. Its later dialogue/recovery
changes have not received this matched comparison. These measured charges must not be
attributed to v4, v2.1 or the demo-final build.

## Original catalog, 2026-11-09

Twelve DEV scenarios, three attempts per arm: 36 conversations each. Every planned
attempt ran once; no outcome-based retry.

| Measure | Proposed-v2 | Baseline |
|---|---:|---:|
| Scripted conversation passes | 29/36 | 30/36 |
| Model requests | 219 | 203 |
| Prompt tokens, cached included | 711,025 known subtotal; total unknown | 1,625,524 |
| Cached prompt | 598,272 known subtotal | 1,482,240 |
| Completion | 6,572 known subtotal | 6,703 |
| Calculated LLM charge, USD | 1.0954425 known subtotal; full total unknown | 2.2780400 |
| Conservative full-charge bound, USD | 1.4205625 | 2.2780400 |
| Successful bookings | 10 | 11 |
| Invalid booking attempts observed | 0 | 0 |
| Wrong bookings observed | 0 | 0 |
| Reviewed unnecessary questions | 9 | 5 |
| Completed patient turns | 93 | 91 |
| Text-turn p50 / p95, seconds | 2.619 / 3.208 | 2.634 / 3.420 |

One proposed request lacks usage after an infrastructure timeout. Its measured aggregate
usage and full charge remain null in JSON; known subtotals and bounds are separate.
There was one censored patient-turn timeout and a 23.910-second completed-turn outlier.
Percentiles cover completed turns, not STT, TTS, interruptions or perceived voice delay.
Each arm also has an evaluator false failure; raw scores were not promoted after review.
Baseline wins raw pass count, model-call count and redundant-question count. Accuracy
is inconclusive on this small development sample.

## Five-times catalog, 2026-11-10

Four DEV cases (002, 003, 009, 012), two repetitions per arm: eight conversations each.
The seeded expander keeps every original relation/outcome and adds disconnected
location/provider/service distractors. It adds no availability. Indexed experiment
copies change only index data in the same ID/name format. No near-neighbor realism or
performance on generated services is established.

| Measure | Indexed proposed x5 | Baseline x5 |
|---|---:|---:|
| Scripted conversation passes | 6/8 | 5/8 |
| Model requests | 60 | 56 |
| Prompt tokens | 500,482 | 1,775,158 |
| Cached prompt, included above | 462,976 | 1,685,376 |
| Uncached prompt | 37,506 | 89,782 |
| Completion | 1,673 | 1,703 |
| Calculated LLM charge, USD | 0.689215 | 2.348205 |
| Successful bookings | 4 | 3 |
| Invalid attempts / wrong bookings observed | 0 / 0 | 0 / 0 |
| Text-turn p50 / p95, seconds | 2.593 / 3.224 | 2.871 / 5.593 |

All usage is reported. Failure costs remain in the totals; early failures affect call
counts. The repeated proposed failures involved supplied patient facts not reaching
state. One baseline failure selected MRI Spine for a knee request and falsely reported
no availability; no booking resulted. No post-result fix or selective retry changed
these measurements. Scores are too small to establish an accuracy advantage.

## Cost and context accounting

Historical rate date: 2026-11-07, confirmed in the experiment on 2026-11-10. Charge in
USD is ((prompt-cached) × 2.50 + cached × 1.25 + completion × 10) / 1,000,000.
Caching is allowed in both arms. Cached reads are measured; cache writes are not
separately exposed and cache-populating work is included in uncached input. There is
no separately charged write surcharge in these reports. Voice-provider and total
voice-call charges are not measured.

Tokenizer: o200k_base. Original readable catalog: 5,894 tokens; ID/name index: 1,026.
At x5: 29,333 and 5,792 respectively. Higher-scale projections and exploratory search-only
variants are not represented as measured comparisons in this summary.
