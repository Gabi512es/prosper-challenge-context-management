# Catalog-aware voice scheduling

This submission combines a visual editor for voice agents with a browser test-call
workflow and a scheduler backed by a synthetic clinic catalog. The scheduler can
clarify a clinician or site, explain a policy restriction and record a simulated
appointment after explicit confirmation.

## Design and why it changed

The earlier scheduler (**v2**) compared an appointment-type index plus catalog search
against a full-catalog prompt. Live calls then exposed recovery failures, including
side questions changing booking state. The current scheduler (**v4**) retained the
catalog-backed engine and booking checks, but replaced mixed model/tool and transcript-rule
orchestration with structured model interpretation feeding code-owned dialogue state,
replies and consent. It also omits the old index. The historical cost comparison below
therefore describes v2, not the shipped scheduler.

| Step | What changed and why |
|---|---|
| Build the demo | Added a visual editor and browser test calls for configurable voice agents and simulated clinic bookings. |
| Measure catalog access | Compared a compact appointment-type index plus lookup with the complete catalog in context. Scoped access cost less in both tested sizes; accuracy remained inconclusive. |
| Test real calls | Found failures missed by scripted tests, including a clinic-hours question changing the booking site. |
| Change dialogue control | Kept catalog validation in Python; structured caller acts now feed explicit state updates, code-rendered replies and proposal-bound confirmation. |

## Current architecture and booking checks

Speech recognition supplies caller turns to one sequential interpreter using
**gpt-4o-2024-08-06**. The interpreter converts them into typed actions; Python validates
references and applies state changes. Omitted fields stay unchanged, information
questions do not select a booking site, and corrections retire dependent offers and
consent. One deterministic composer answers questions and chooses the next step;
there is no second narration model. Its context contains known facts, the pending
question, ordered choices and the current read-back, rather than the complete catalog
or the old index. Voice and controlled text sessions share this path.

The interpreter's internal prompt/schema version is **v1.10**, separate from the v4
application label. Experimental interpreter results and the decision to retain this
version are in [the decision record](docs/decisions.md).

Catalog lookup narrows candidates using explicit provider/service/site relationships
and preserves duplicate-name ambiguity. The Python engine checks site capability,
new-patient and referral rules, local opening hours and current availability. Specialty
helps disambiguation but cannot substitute for a provider's actual service relationships.
The eight appointment types without a provider stay unbookable. Eligible slots are
filtered before truncation; booking rechecks availability and uses idempotency.

Identity confirmation is separate from booking consent. Critical read-backs are
rendered from state, and consent refers to the current proposal. Voice delivery tracks
matching audio draining through the server transport, not browser speaker playback.
Code validates state; it cannot make an incorrect model interpretation correct.

The editor lists, creates, duplicates, validates, saves and deletes JSON agents.
**Scheduler v4** is the sole bundled agent: greeting, voice and clinic guidance are
editable, while scheduling steps and consent checks are fixed. Generic Flows agents
support editable nodes, tools and transitions. **Test call** saves and selects the JSON;
its `runtime` field dispatches the next connection. Selection is process-global in this
single-user demo. [README.md](README.md) gives a concrete graph edit and two call examples.

## Historical catalog-context comparison

Both historical arms used the same model configuration (`gpt-4o`), scripted patients,
fixtures, booking checks and scorer. The scoped v2 arm supplied an ID/name index and
catalog search; the baseline supplied the complete readable catalog as a stable prefix.

| Catalog | Conversations per arm | Scripted conversation passes: scoped v2 / baseline | Model charges, USD: scoped v2 / baseline |
|---|---|---|---|
| Original: 8 sites, 50 providers, 82 services | 12 cases × 3 = 36 | 29/36 / 30/36 | 1.0954 known subtotal / 2.2780 |
| 5×: 40 sites, 250 providers, 410 services | 4 cases × 2 = 8 | 6/8 / 5/8 | 0.6892 / 2.3482 |

Charges include failures and cached input. One original-size scoped request has unknown
usage: its full charge is unknown; the report records a conservative bound of 1.4206
above the 1.0954 known subtotal. All other table usage is complete. These are model
charges, not total voice-call costs. Exact measured versions, tokens, prices and source
identities are in [the aggregate evidence](docs/results/context-comparison.md).

The baseline won the original raw pass count, used fewer model calls and asked fewer
unnecessary questions. Accuracy is inconclusive on these small development samples.
At 5×, unrelated catalog entries were added while the original booking tasks, relationships
and availability stayed fixed. This tests context growth, not performance on new clinics.
Caching materially benefits both strategies. The readable catalog/index measured
5,894/1,026 tokens originally and 29,333/5,792 at 5× with `o200k_base`.

## Voice verification, mocks and limits

There are three distinct evidence types: the historical scripted conversation comparison;
single-turn interpreter probes, which do not test booking or voice; and one functional
voice booking rehearsal on `f5aad82`. That call clarified an STT service-name error,
confirmed identity and wrote one correct booking after consent. Later packaging changes
were checked offline. A fresh clone of the published `015d0e1` passed installation,
242 tests (two paid tests skipped), the frontend build and service startup. This is not
a matched accuracy benchmark of the current scheduler. Published evidence consists of
aggregates and a rehearsal summary; original run and voice logs are not included.

Demo availability is generated deterministically within the next two weeks; evaluation
fixtures define closed-world availability. Bookings are session-local, referral status
is caller-supplied, and human assistance means giving a clinic phone. No EHR, real calendar,
existing-appointment lookup, transfer, callback or production authentication is implemented.
English and one clinic timezone are supported; general timezone conversion and geographic
ranking are deferred. Interpretation and recovery can still fail. Synthetic identities
are used, but local logs contain clear-text names/DOB; production needs redaction,
retention, access control and review of third-party processing.
