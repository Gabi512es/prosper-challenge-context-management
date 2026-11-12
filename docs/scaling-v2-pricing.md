# Step 6b: approved input variant, offline measurements and pending pricing

Historical pricing, superseded by the user's 2026-11-10 revised plan: ID + name
only, no frozen-index secondary, indexed x50 projection-only, exploratory
search-only x10/x50 added. See the newest docs/decisions.md entry and
docs/scaling-v3-results.md for the current plan and execution evidence.

2026-11-09. **No scaling API call has been made or authorized.** This supersedes
the two-field index estimates and pending input choice in scaling-v1.md.
Evaluator remains `dev-eval-v5-recovery`; no agent/core/scorer correction is made.

## Experiment inputs and preservation

The user selected complete regenerated index data in experiment copies.
Expander `catalog-disjoint-v1`, seed `20261109`, is unchanged. Index variant is
`scaled-index-v2-id-name-specialty`. Each entry contains exactly `id`, `name`,
`specialty`, in that order, serialized as compact JSON. One important format
finding: the frozen source actually contains **id + name only**, 82 entries and
1,026 tokens. Adding the explicitly requested specialty field makes the original
82 entries 1,559 tokens. These are data changes in derived experiment copies,
not an assertion that the original already had three fields.

The generator writes agent-xNN-expanded-index.json in the ignored experiment
directory. Only the data following `Appointment type index:` changes. Tests
restore that data and compare the entire config to the original: every role/task
instruction, function, edge, model and other setting is identical. Copies pass
the existing AgentStore/AgentBuilder validation. The original source agent is
untouched. Each manifest records source/derived agent hashes, index hash/fields,
catalog hashes, scenario-source hash, expander version/source hash and seed.

Synthetic providers reference only synthetic sites and synthetic types. Every
original record, relation and policy remains exact. No synthetic availability is
created; original scenario fixtures remain the complete availability universe.
Names avoid original catalog entities and DEV patient/provider names. Generated
service names describe unrelated fictional research activities. The experiment
measures irrelevant distractors and context capacity, not clinical realism or
same-service expansion.

Offline checks at x50 preserve all 12 fact-card resolution/slot outcomes and
original positive booking fields, including DEV-012. DEV-004 stays blocked for a
new patient with no new alternative answer. DEV-008's location correction still
invalidates the old slot and confirmation and prevents booking; its original
blocking/alternative results are unchanged. All eight original providerless
types still have no provider. These checks preserve expected answers, not a
prediction that the LLM will always find them. No scenario, fixture, expected
outcome or source catalog pin changes.

## Exact offline sizes

Model `gpt-4o`; tokenizer `tiktoken` / `o200k_base`. Index counts include the JSON
data only. Baseline counts include the entire existing readable catalog render
and all policies, not request framing, tools or conversation history.

| Scale | Locations / providers / types | Baseline catalog tokens | Primary three-field index tokens |
|---|---:|---:|---:|
| x1 | 8 / 50 / 82 | 5,894 | 1,559 |
| x5 | 40 / 250 / 410 | 29,333 | 8,457 |
| x10 | 80 / 500 / 820 | 58,664 | 17,098 |
| x20 | 160 / 1,000 / 1,640 | 121,030 | 34,980 |
| x50 | 400 / 2,500 / 4,100 | 313,545 | 89,221 |

At x50, the primary proposed request projects to 94,823 tokens including the
longest selected prior history and a 512-token output reserve, within 128K.
That is a projection, not an API-measured expanded request. Growing tool results
or longer recovery can add context. The baseline catalog alone first exceeds
128K at x22 (133,867); prior-history request size first projects over at x21.
Baseline x10+ remains projection only; the detailed numbers in scaling-v1.md
still apply because the complete baseline render did not change.

## Pricing for approval

GPT-4o rates: $2.50/M uncached input, $1.25/M cached input, $10/M output.
Repository price date 2026-11-07; verified unchanged on 2026-11-09 against the
[official GPT-4o model page](https://developers.openai.com/api/docs/models/gpt-4o).
No Batch API discount is assumed.

DEV-002/003/009/012 are the four paid cases. Projections reuse their actual
previous v5 call/output/history shapes across three repetitions per arm. Cache
shares were 85.07% proposed and 91.23% baseline. Prefix-token deltas are applied
per model call, including post-tool calls, with one cold-scale-prefix premium
per phase. Primary deltas are relative to the actual old 1,026-token index, so
the cost of adding specialty to original entries is included. These estimates
do not guarantee cache hits, unchanged model call counts or pass rates.

| Primary phase | Conversations | Prior-cache-profile USD projection | All input uncached, same calls USD projection |
|---|---:|---:|---:|
| Proposed x5, two runs each | 8 | 1.072537 | 1.834265 |
| Baseline x5, two runs each | 8 | 2.848151 | 5.157515 |
| Proposed x10, one run each | 4 | 0.956298 | 1.622814 |
| Proposed x50, one run each | 4 | 4.417788 | 7.512859 |
| **Primary total** | **24** | **9.294774** | **16.127453** |

Suggested primary ceiling for approval: **$18, no retries**, with admission
stopping before the cap. No ceiling is currently authorized. Cold pricing is
conditional on the old call/output shape, not a worst-case spending bound.

Secondary arm, clearly separate: literal **frozen 82-entry id+name index** at all
three scales. The exact source agent bytes are copied to
agent-secondary-frozen-82.json. This tests original-answer isolation under Python
catalog growth, not complete expanded-index coverage. It is also a narrower
index format than the requested primary arm, so it is not a pure index-length
ablation. Baseline is not rerun for this secondary arm.

| Optional additional proposed-only phase | Conversations | Prior-cache-profile USD projection | All input uncached USD projection |
|---|---:|---:|---:|
| Frozen index x5, two runs each | 8 | 0.367148 | 0.620535 |
| Frozen index x10, one run each | 4 | 0.184934 | 0.310267 |
| Frozen index x50, one run each | 4 | 0.184934 | 0.310267 |
| **Secondary increment** | **16** | **0.737016** | **1.241069** |
| **Primary + secondary** | **40** | **10.031790** | **17.368522** |

The secondary costs about 8% extra under these projections; it is optional,
not silently included as negligible. Suggested combined ceiling if selected:
**$20, no retries**. Both ceilings await an explicit go.

## Actual cached usage and cache-write accounting

There is **no actual scaling usage yet**. The report stores new-scale actual
cached tokens as null. A future paid report must use each call's actual
`prompt_tokens_details.cached_tokens` via the shared metrics observer, not a
tokenizer estimate or expected hit rate. Missing reads/usage remain null.

The installed GPT-4o Chat Completions SDK usage exposes cached-read tokens but
no separately metered cache-write tokens. Pipecat has a generic
cache_creation_input_tokens field, but its installed OpenAI adapter does not
populate it. [OpenAI's cache documentation](https://developers.openai.com/api/docs/guides/prompt-caching)
specifies no additional cache-write charge for this earlier model family.
Therefore: write tokens and separately attributed write-input cost are **unknown
(null)**; the additional write fee is **$0**. Cache-populating work is already
charged as ordinary uncached input. Do not label every uncached token a cache
write, invent a write count, or add another write charge to input cost.

Actual saved-log usage used for projection, **not a new scaling measurement**:

| Arm, previous four cases x3 | Calls | Actual cached tokens | Cached-read USD | All uncached-input USD, including any cache population | Output USD | Total USD |
|---|---:|---:|---:|---:|---:|---:|
| Proposed | 98 | 307,328 | 0.384160 | 0.1348725 | 0.027610 | 0.5466425 |
| Baseline | 97 | 738,048 | 0.922560 | 0.1772750 | 0.029920 | 1.1297550 |

Source runs: comparison-proposed-v2-20261109-180827-8752c3 and
comparison-baseline-20261109-182321-c4ee5f. Usage is known for every selected
call; the earlier missing-usage DEV-001 request is outside these four cases.

## Validation and reproduction

`make test`: 125 tests, 123 passed, two paid integrations skipped. Twelve
expander/index/accounting tests pass. Repeated measurement with
AsyncCompletions.create mocked/asserted unused makes zero model requests.
Frozen agent, scheduling/core, runner, builder, source catalog and scenario
diffs are empty. Only evaluation preparation/tests and documentation changed.

Offline command: `cd backend && .venv/bin/python -m evals.catalog_scaling`.
Artifacts: backend/logs/evals/scaling-catalog-disjoint-v1-seed20261109-scaled-index-v2-id-name-specialty/.
The offline-measurements.json report separates measured sizes, historical
actual usage, projected future cache/token/dollar totals, optional secondary
pricing and context overflow. This command never runs evaluations.
