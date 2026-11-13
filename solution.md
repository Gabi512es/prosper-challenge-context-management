# Catalog-aware scheduling agent: solution

This is a prototype: availability, booking and human handoff are simulated,
and nothing here is a clinical or production service. Every number below is
taken from a file in `docs/` and listed in the Sources table at the end.
Anything not measured is marked as not measured. Setup, run and test
instructions are in [README.md](README.md).

All final results (x1 development comparison, scaling, held-out, robustness)
were measured on **v2**, the frozen tag `proposed-v2` with agent revision
`40db1b58...`. The later dialogue fixes, called **v2.1**, were checked only by
offline tests, one four-case smoke and manual voice calls, never by a full
matrix. No final result is attributed to v2.1.

## Summary

- At x1 the full-catalog baseline matches the proposed arm on accuracy (30/36 versus 29/36) at about twice the cost ($2.2780400 versus $1.0954425 known).
- At x5 the proposed arm passes 6/8 versus 5/8 at about a third of the cost ($0.689215 versus $2.348205), on 8 conversations per arm; no significance is claimed.
- Final held-out and robustness, 40 conversations: 7 passes, 21 confirmed agent failures, 12 evaluator or driver limitations; no wrong booking was observed.
- The failures come mostly from the shared dialogue layer, which both arms use, not from the context strategy.
- Live voice calls found defects the text evaluations missed (interruptions, mishearing, side questions during a choice).

## 1. The problem and the framing

A caller may ask by service, by clinician, by site or for the earliest slot.
The catalog has 8 locations, 50 providers, 82 appointment types and 6 policy
sentences. It is small but adversarial: 34 of the 50 providers work at several
sites, three full names are shared by two different providers, 215
provider/service pairs cross the provider's stated specialty, 36 services need
a referral, 31 do not accept new patients, 11 providers are not accepting new
patients, and 8 services have no provider at all. Those 8 stay unbookable; the
catalog is never repaired to improve a score.

**The naive baseline.** Put the whole catalog and the policies in the prompt
and let the model reason. The raw catalog JSON is 12,924 tokens and a compact
serialization 8,252 tokens. The readable rendering used for the baseline arm is
5,894 tokens. At this size the baseline fits comfortably and caches well, so
the cost argument for anything smarter is weak at x1. I treated the baseline as
a serious competitor, not a straw man.

**Hypotheses.**
1. A compact service index (ID and name only, 1,026 tokens) plus lookup tools
   keeps context cost low as the catalog grows, where the full catalog grows
   linearly. Adding specialty to the index costs 1,559 tokens and was rejected
   because specialty does not decide which services a provider offers.
2. If code, not the model, owns identity resolution, policy checks, slot search
   and booking, then invalid bookings become impossible regardless of what the
   model says. Observed: 0 wrong bookings. But the guarantee holds only
   relative to session state, and the facts in that state are written by the
   model. In HO-016 the model recorded a referral promised for tomorrow as
   already on file, and in HO-011 it set a location the patient never chose.
   The guards check state, not whether state matches what the patient said.
3. Accuracy on close options (duplicate names, near-duplicate services, gated
   sites) should be at least as good as the baseline. This hypothesis is the
   one the evidence does not settle (section 3).

**What I built.** A React Flow graph editor that saves JSON agents and starts a
test call; one shared runtime for voice and text; a pure-Python scheduling
core; four tools; code-owned dialogue guards; a text evaluation harness with
scripted patients; a full-catalog baseline arm; and a catalog expander for
scaling tests.

**What I mocked.** Availability: closed-world fixtures for every evaluation,
and generated demo availability for voice (760 valid provider/site/service
combinations). Booking is in memory and per session. "Referral on file" is a
stated fact, not an EHR lookup. Human handoff is simulated: no transfer, no
callback, no staff notification, and the agent must say so.

**What I left out.** Real calendar or EHR integration, cancellation and
rescheduling, authentication, multi-user agent selection, catalog editing,
clinical triage beyond an emergency instruction, and timezone normalization
across arbitrary offsets.

## 2. Architecture

**Principle: the code owns the guarantees, the model owns the conversation.**
The model interprets what the caller means, picks tools and talks. Plain
Python owns everything that must be true: which provider is meant, which
policies apply, which slots exist, whether a booking is allowed. Session
state, not the transcript, is the source of truth. The core has no Pipecat or
OpenAI imports, so voice and text call the same code.

**The four tools.** They are node functions, not graph transitions, so a
lookup does not move the conversation to another node.

| Tool | What the code guarantees |
|---|---|
| `resolve_options` | Applies stated facts with invalidation of dependent choices; resolves service, provider and site without collapsing ambiguity; returns policy blocks with reasons, missing facts, eligible sites and valid alternatives |
| `get_details` | Returns authoritative catalog facts for a resolved ID; never infers missing facts |
| `find_slots` | Searches every slot in the availability universe, enforces relations, policies and opening hours, ranks globally before truncating, and offers alternatives that each relax exactly one constraint and need the patient's consent |
| `book_appointment` | Revalidates everything against current state and books only after a code-generated read-back and an explicit patient yes; idempotent |

**Session state.** Patient facts (name, date of birth, new-patient status,
referral), resolved service/provider/site IDs, hard constraints and soft
preferences, candidates, offered and selected slots, and a confirmation
snapshot. A change to any fact invalidates exactly what depends on it: a new
site clears the slot and the consent, never the service. Unknown is kept
distinct from false.

**Two-phase booking.** Phase one validates the chosen slot and returns a
read-back that code generates from engine data (service, provider, site,
weekday, date, time, then "Shall I book it?"). Phase two writes only after a
later affirmative patient turn that matches that read-back. A correction or a
"wait" cancels the consent. Identity is confirmed separately, once, before any
offer.

**Closed fields validated in code.** Where the model must classify, it fills a
closed field and code checks the value. Example: "nearest" is mapped by the
model to `location_preference` with values time, place or unclear; code then
widens the search, lists eligible sites, or asks once. Unknown values come
back with the list of valid values instead of being applied.

**Validate, don't enumerate.** I first exposed catalog-sized enums (all
specialties and IDs) in the tool schema so the model could not invent values.
That added 947 tokens to every request. I then removed the enums and validated
the same values in code, returning the valid list only when a value is wrong.
The empty-history startup prompt dropped by 924 tokens, and the mean per call
dropped by 931 tokens on DEV-002 and 928.83 on DEV-012's first six calls, with
the same protection.

**The editor and the JSON agent.** The scheduling agent is a JSON graph
(`backend/agents/catalog_scheduler.json`) that both voice and text compile
through the same builder. The editor lists, creates, duplicates and deletes
agents and edits nodes, edges, prompts and attached tools, validating before an
atomic save. "Test call" saves the agent, selects it for the next local call
and opens the Pipecat client. The safety guards live in the shared tool
registry: an agent built on the scheduling tool registry receives them automatically. Every session log records
the agent ID, a SHA-256 revision of its JSON and the availability mode, so a
voice call and a text run can be matched to the same agent.

## 3. Results

### 3.1 Development comparison at x1

Twelve development scenarios, three attempts each per arm, same model
(gpt-4o), same scripted patients, fixtures, guards and scorer. The only
difference is catalog access: the baseline reads the full catalog in its
prompt and resolves by ID only; the proposed arm uses the index and lookups.
No attempt was retried.

| Metric | Proposed (v2) | Full-catalog baseline |
|---|---:|---:|
| Raw passes | 29/36 (80.56%) | 30/36 (83.33%) |
| Successful bookings | 10 | 11 |
| Model calls | 219 | 203 |
| Unnecessary questions (reviewed) | 9 | 5 |
| Invalid booking attempts / wrong bookings | 0 / 0 | 0 / 0 |
| Prompt tokens, including cached | 711,025 known + 1 call unknown | 1,625,524 |
| LLM cost | $1.0954425 known, at most $1.4205625 | $2.2780400 |
| Cost per successful booking, whole arm | $0.10954425 known, at most $0.14205625 | $0.20709455 |
| Text turn latency p50 / p95 | 2.619 s / 3.208 s | 2.634 s / 3.420 s |
| Incomplete turns | 1 (timeout) | 0 |

**The baseline wins on pass count (30 versus 29), on model calls (203 versus
219) and on unnecessary questions (5 versus 9).** The proposed arm costs less,
even at its worst-case bound for the one call with unreported usage. With
twelve scenarios and correlated repetitions, the accuracy difference is
inconclusive; no significance is claimed. Neither arm made a wrong booking.

Manual review of the failures (one primary label each):

| Primary cause | Proposed | Baseline |
|---|---:|---:|
| Unnecessary question / blocked conversation | 2 | 1 |
| Internal/tool resolution error | 0 | 1 |
| False statement to patient | 1 | 0 |
| Missing explanation or next step | 2 | 3 |
| Wrong booking | 0 | 0 |
| Infrastructure timeout | 1 | 0 |
| Evaluator false failure | 1 | 1 |

### 3.2 Scaling

The expander keeps every original record and relation and adds disconnected
synthetic distractors; it adds no availability and no new correct answer. This
tests context growth from irrelevant records, not harder near-neighbor cases.
Cases: DEV-002, DEV-003, DEV-009, DEV-012.

**Measured** (28 conversations, 201 model calls, $3.813240, all usage known):

| Arm / scale | Passes | Calls | Correct bookings | Cost | Cost per correct booking | Turn p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|
| Proposed (index) x5 | 6/8 | 60 | 4 | $0.689215 | $0.172304 | 2.593 s / 3.224 s |
| Baseline x5 | 5/8 | 56 | 3 | $2.348205 | $0.782735 | 2.871 s / 5.593 s |
| Proposed (index) x10 | 3/4 | 27 | 2 | $0.517805 | $0.258902 | 2.696 s / 3.753 s |
| Exploratory search-only x10 | 3/4 | 28 | 2 | $0.128555 | $0.064278 | 2.861 s / 4.272 s |
| Exploratory search-only x50 | 3/4 | 30 | 2 | $0.129460 | $0.064730 | 2.602 s / 3.535 s |

At x5 the baseline again used fewer calls (56 versus 60) but passed one fewer
case and cost more ($2.348205 versus $0.689215). Every arm failed DEV-002, mostly through the
"stated fact not recorded" family (section 4). Search-only is an exploratory
variant (no index, free-text lookup only), not a replacement for the frozen
arm, and one repetition per case cannot establish equal accuracy.

**Offline sizes** (exact tokenizer, no API call):

| Scale | Baseline catalog tokens | ID + name index tokens |
|---|---:|---:|
| x1 | 5,894 | 1,026 |
| x5 | 29,333 | 5,792 |
| x10 | 58,664 | 11,768 |
| x20 | 121,030 | 24,320 |
| x50 | 313,545 | 62,571 |

**Projections, not measurements.** Indexed proposed at x50 was not run; four
conversations project to $3.138741 with the observed cache profile or $5.336442
all cold. Baseline x10 and above was not run; at x10 four conversations project
to $2.764025 cached or $4.949680 cold. The baseline catalog alone exceeds
gpt-4o's 128K context at x22 (133,867 tokens), and the full request already
projects past the limit at x21 (128,669 input tokens). Dollar figures beyond
that point are arithmetic, not runnable costs.

### 3.3 Final held-out and robustness evaluation

Two evaluation sets were kept outside the repository until the final run, with
their SHA-256 hashes recorded beforehand (section 6). Held-out: 16 scenarios,
both arms. Robustness: 8 scenarios from publicly reported failure modes,
proposed arm only. **Each conversation ran exactly once.** 40 conversations,
211 model requests, $1.4072150, all usage reconciled, no infrastructure
failure or timeout.

| Set / arm | Conversations | Model calls | Cost | Turn p50 / p95 | Cached share of prompt |
|---|---:|---:|---:|---:|---:|
| Held-out / proposed | 16 | 76 | $0.3566525 | 2.470 s / 3.460 s | 82.10% |
| Held-out / baseline | 16 | 62 | $0.6712800 | 2.621 s / 4.160 s | 91.01% |
| Robustness / proposed | 8 | 73 | $0.3792825 | 2.384 s / 3.187 s | 88.29% |

Automatic checks alone are not a pass rate: all 40 conversations required
semantic review. **Adjudicated semantic review:**

| Arm | Pass | Confirmed agent failure | Evaluator or driver limitation | Not assessable |
|---|---:|---:|---:|---:|
| Held-out / proposed | 2 | 7 | 7 | 0 |
| Held-out / baseline | 4 | 8 | 4 | 0 |
| Robustness / proposed | 1 | 6 | 1 | 0 |
| Total | 7 | 21 | 12 | 0 |

Method: labels proposed by two LLM reviewers, disagreements adjudicated by the
author; the two reviewers agreed on 37 of 40 conversations. The author
re-checked the 7 passes and proposed HO-016 against the full transcripts.

**Driver limitations.** The table counts 11 held-out driver limitations (7
proposed, 4 baseline) plus 1 in robustness (RW-005). They come from two
sources:
- **The harness flagged 15 held-out conversations as driver-limited**: the
  scripted patient stopped without reaching the expected booking. Review split
  them into 8 genuine driver gaps (the patient script had the right reply for
  the question asked and never gave it) and 7 agent failures (the agent's own
  question was wrong or could not be answered).
- **3 more were never flagged**: proposed HO-004, HO-006 and HO-014. Their
  automatic checks all passed, so the harness did not flag them, but the
  conversation stopped on a question the script did not answer, before the
  criteria under test could be observed.

8 plus 3 gives the 11. A driver limitation means the behavior under test was
never observed, not that the agent passed.

What this shows honestly: on held-out the baseline has more passes (4 versus
2) and fewer evaluator or driver limitations (4 versus 7); the proposed arm
cost less ($0.3566525 versus $0.6712800). Neither arm made a wrong booking
in held-out. The booking guards are shared by both arms, so "no wrong booking"
is a property of the shared core, not of the context strategy: in HO-007 the
baseline called book_appointment on an unconsented slot of the wrong type
after the patient rejected the offer, and the guard refused to book it. In
robustness, all three injected write failures really fired after the patient's
consent; the agent never claimed a failed booking as done, but it often failed
to tell the patient what had changed (section 4). The misleading replies in
RW-002 and RW-003 came from the canned "Your details are confirmed. I'll check
the available appointments." line that v2.1 removed; those two scenarios have
not been re-run since. RW-007
(chest pain and arm numbness) was escalated to emergency services immediately.
RW-005 carries a raw wrong-booking flag that review attributed to the driver:
the scripted request for a human was never delivered and the recorded patient
explicitly consented. The raw flag is kept.

### 3.4 Costs

All prices are the recorded 2026-11-07 gpt-4o rates: $2.50 per million
uncached input tokens, $1.25 cached, $10 output. These are LLM costs only.

| Ledger | Known LLM cost |
|---|---:|
| All recorded model calls up to the 2026-11-09 snapshot (1,729 calls, 38 with unknown usage) | $7.7238625 |
| x1 comparison, proposed / baseline | $1.0954425 known / $2.2780400 |
| Scaling (step 6b) | $3.813240 |
| First final-evaluation attempts, stopped by a serialization bug | $0.0923300 |
| Final evaluation restart (40 conversations) | $1.4072150 |
| v2.1 four-case smoke | $0.2417925 |

**Total measured OpenAI spend to date: $18.4804700.** It sums the 2026-11-09
ledger snapshot ($7.7238625) and every paid run logged after it ($10.7566075),
line by line, in docs/costs.md; each later run was recomputed from its raw
usage log and matched its documented figure. It is a lower bound of known
charges, not an invoice. The API keys were provided by Prosper, so this total
comes only from my own usage logs and was not checked against the provider
dashboards.

**Caching caveat.** Evaluations ran conversations back to back, so cache hit
rates were probably higher than sparse real traffic would give. This is a
hypothesis, not a measurement. The baseline, with its large stable prefix,
benefits most. The production cache hit rate is not measured.

**Not measured:**
- voice sessions after the 2026-11-09 snapshot, including the November 9 to 12
  calls;
- usage rows with unknown usage (38 in the snapshot, one in the proposed
  comparison);
- ElevenLabs speech-to-text and text-to-speech;
- end-to-end voice latency;
- coding-agent usage, infrastructure and taxes.

## 4. What failed and why

**Four failure families** identified in the final review:

1. **Silent deviation.** A change or failure is never told to the patient: the
   requested time or day was impossible, the accepted slot was taken, or the
   write failed. The booking itself was usually correct (RW-001, RW-003,
   RW-004) but the patient was not told why it changed. This is the main
   robustness weakness: disclosure, not recovery mechanics.
2. **The guard asks instead of explaining.** The code-owned dialogue
   controller asked for the next missing field even when the same tool result
   already contained a decisive block (for example "Which provider would you
   like?" for a service no provider offers).
3. **The guard swallows the patient's question.** A scripted next question
   replaced the answer the patient needed, including one direct "am I talking
   to a real person?" that was never answered (RW-006).
4. **State does not match what the patient said.** Two sub-families:
   - **(a) Stated facts not recorded.** The patient said it, the model did not
     write it to state, and the controller asked again. This explains five of
     the eight scaling failures and the DEV-002, DEV-005 and DEV-006 failures.
   - **(b) Recorded facts the patient never stated.** The model wrote a fact
     the patient did not give: a referral promised for tomorrow recorded as
     already on file (HO-016), a location the patient never chose (HO-011).
     This sub-family is the more dangerous one, because a wrong fact in state
     can bypass a guard that checks state. In HO-016 the referral gate never
     fired.

My reading of families 2 and 3: they are a direct cost of my design. Moving the conversation's
next step into code made bookings safe but made the agent rigid when the
patient's turn did not fit the expected slot.

**What voice found that text did not.** My live calls from November 8 to 12
are summarized line by line in [docs/voice-findings.md](docs/voice-findings.md)
(date, what happened, cause, fix). The calls found defects the scripted text
runs never triggered:
- a promise of staff follow-up and a transfer nobody asked for;
- the agent speaking twice in a row;
- a Midtown request booked at North Beach;
- a misheard date of birth hidden inside a long read-back;
- valid "yes" replies refused by the consent gate;
- 12 seconds of silence after "1991." was dropped as a non-word;
- after the final evaluation, a slot choice lost after an interruption, with a
  canned "I'll check" line repeated five times and no tool call;
- the slots presented twice after "Sorry, what did you say?".

Voice call A passed on November 9. The final November 12 call handled an
interruption, repeated the choice once, booked and gave a short recap. The
scripted patients never interrupt, never mishear and never ask a side question
in the middle of a choice, which is exactly where these bugs lived.

**Bugs caused by code interpreting language.** The same class of error
appeared three times:
- **"ENT" inside "patient".** A substring check for specialty names matched
  "ENT" inside the word "patient" and overwrote Radiology. Fixed by
  whole-token matching against catalog specialties.
- **The "nearest" handling.** Code first parsed "closest" and "nearest" from
  the transcript to ask "time or place?". A transcript keyword could keep
  re-triggering that state, and a related location rule treated every
  mentioned site as a positive choice. Replaced by a closed field the model
  fills (`location_preference`) and code validates; a repeated "nearest" in
  speech can no longer reset it.
- **The invented "primary care" filter.** Here the code did not parse the
  transcript; it trusted free text from the model. The model added
  `provider_specialty="primary care"`, which matches no catalog specialty; code
  applied it as a filter, emptied the candidate list and told the patient the
  correctly named provider did not exist. Fixed by validating filters against
  the catalog and reporting, not applying, unknown values.

The lesson I take from these: code should validate model output against closed
sets, and should parse raw speech as little as possible. The repeat-request
detector added for v2.1 follows that rule: it only fires when the whole
utterance is a repeat request.

## 5. Limitations and next steps

**Limitations.**
- Every final conversation ran once; the development comparison has twelve
  scenarios. No accuracy difference between arms is established.
- 12 of 40 final conversations ended in driver limitations: their behavior
  under test is unobserved.
- v2.1 fixes are verified by offline tests, one four-case smoke and manual
  voice calls only. Voice behavior is not measured by any automatic metric.
- Opening-hours checks compare the slot's own local clock to catalog hours;
  there is no per-site timezone or daylight-saving handling.
- Availability, booking, referral status and handoff are all simulated.

**Next steps (v3).**
- **The model converses, the code keeps the guarantees.** Keep booking,
  policy and identity checks in code, but stop letting code choose the next
  question. Families 2 and 3 come from that rigidity.
- **Mandatory disclosures as tool-result fields.** When a requested time is
  unavailable, a slot is lost or a write fails, the tool result should carry a
  required disclosure that the output layer checks was spoken. This targets
  family 1.
- **A runtime monitor** that flags, during the call, unanswered patient
  questions, repeated statements and offers without a site.
- **Varied simulated patients** that interrupt, ask side questions, answer out
  of order and restate facts, so the text evaluation reaches the bugs that only
  voice found.
- **Test whether the index is needed at all.** The most interesting
  exploratory finding: at x10, removing the index (search-only) cost $0.128555
  versus $0.517805 for the indexed arm, with the same 3/4 passes. This is one
  run per case, with disconnected distractors only, so it is not evidence of
  equal accuracy. It is the first experiment I would repeat at scale, with
  realistic near-neighbor services.

## 6. Process

**Tools.** Coding agents wrote most of the code: Codex first, then Claude Code
after Codex usage limits were reached. Two LLM reviewers proposed the semantic
review labels independently. Text evaluations used scripted patients and a
deterministic scorer shared by both arms.

**What I verified myself.** All voice calls were placed and judged by me. I
adjudicated the review disagreements, re-checked the 7 passes and proposed
HO-016 against the full transcripts. Since 2026-11-09, every paid run needed a
written cost estimate and my explicit go before it started.

**Time.** About 10 hours of active time: 9h51 recorded by timer, plus roughly
30 minutes not timed (a few short voice calls and review). Agent compute time
in the background is not counted. The brief suggests 8 to 12 hours.

**Frozen evaluation files.** Both evaluation sets stayed outside the
repository until the final run. Their SHA-256 hashes were recorded on
2026-11-08, before the first final run:
- Held-out set (`prosper_heldout_scenarios.json`), 16 scenarios:
  `d41abdad3defe405a48becc55a97d4d153c3c3b27a4eff5f5518db8a2dedd1b6`
- Robustness set (`prosper_robustness_scenarios.json`), 8 scenarios:
  `c5de085b51996c51afaa9dbc3b40c392452d0eec28760b422ced2a6f74aa6c19`

The coding agents did not read either file during development. The review
criteria were read only after the frozen final run, for the semantic review.

## Sources

| Figure | Value | Source file |
|---|---|---|
| Catalog size | 8 locations, 50 providers, 82 types, 6 policies | docs/decisions.md (2026-11-07, catalog measurement) |
| Multi-site providers, cross-specialty pairs, referral/new-patient counts, duplicate names, providerless types | 34; 215; 36 / 31 / 11; 3; 8 | docs/decisions.md (2026-11-07, catalog measurement) |
| Raw / compact catalog tokens | 12,924 / 8,252 | docs/decisions.md (2026-11-07, catalog measurement) |
| Readable baseline catalog | 5,894 tokens | docs/comparison-evaluator-v5.md; docs/scaling-v3-results.md |
| ID + name index; with specialty | 1,026; 1,559 tokens | docs/decisions.md (2026-11-07, eval attribution and compact type index) |
| Demo availability combinations | 760 | docs/decisions.md (2026-11-08, proposed-v2 after real voice failures) |
| Enum overhead; savings after removal | +947; -924 startup, -931 and -928.83 per call | docs/decisions.md (2026-11-09, logged enum overhead; lazy catalog validation) |
| x1 comparison table and failure labels | all values in 3.1 | docs/comparison-evaluator-v5.md |
| Scaling measured table, totals | all values in 3.2 (28 conversations, 201 calls, $3.813240) | docs/scaling-v3-results.md; docs/costs.md (step 6b addendum) |
| Offline sizes and projections | all values in 3.2 | docs/scaling-v3-results.md |
| Stated-fact family in scaling and DEV failures | 5 of 8 scaling failures; DEV-002/005/006 | docs/decisions.md (2026-11-10, revised 6b completed); docs/failure-triage-proposed-v2.md |
| Spend rule start date | 2026-11-09 | docs/costs.md (Future spend rule); docs/decisions.md (2026-11-09, API spend policy) |
| Final run: conversations, requests, cost, calls, latency, cached share | all values in 3.3 first table | docs/final-evaluation-restart-v1.2.md |
| Semantic labels, 37 of 40, re-checks, 15 driver-limited split 8/7 | all values in 3.3 second table | docs/semantic-review.md |
| Faults fired, RW-005, RW-007 | 3 faults | docs/final-evaluation-restart-v1.2.md; docs/semantic-review.md |
| Prices | $2.50 / $1.25 / $10 per million | docs/costs.md |
| Ledger: snapshot, unknown rows | $7.7238625; 1,729 calls; 38 unknown | docs/costs.md |
| Ledger: scaling, first attempts, restart | $3.813240; $0.0923300; $1.4072150 | docs/costs.md |
| Ledger: x1 comparison | $1.0954425 / $2.2780400 | docs/comparison-evaluator-v5.md |
| v2.1 smoke | $0.2417925, 42 calls, 4/4 | docs/decisions.md (2026-11-12, v2.1 working-tree smoke) |
| Total measured OpenAI spend; snapshot and post-snapshot parts | $18.4804700; $7.7238625 + $10.7566075 | docs/costs.md (2026-11-12, total measured OpenAI spend to date) |
| Voice findings, 12 seconds of silence, call A and final call | (one line per call finding) | docs/voice-findings.md |
| Agent revisions v2 / v2.1 | 40db1b58... / 478567bc... | docs/decisions.md (2026-11-12, v2.1 working-tree smoke) |
| Failure families | 4 | docs/semantic-review.md (S1 to S4) |
| Voice fix implementation details | (qualitative) | docs/decisions.md (2026-11-08 to 2026-11-12 voice entries) |
| ENT, nearest, primary care bugs | (qualitative) | docs/decisions.md (2026-11-09 entries) |
| Active time; brief's suggested range | about 10 hours (9h51 timed plus roughly 30 minutes not timed); 8 to 12 hours | docs/decisions.md (2026-11-12, active time update; time statement for submission) |
| Summary ratios "about twice", "about a third" | rounded from $2.2780400 / $1.0954425 and $0.689215 / $2.348205 | docs/comparison-evaluator-v5.md; docs/scaling-v3-results.md (inputs) |
| Driver limitations 11 held-out = 8 flagged + 3 unflagged (HO-004, HO-006, HO-014 proposed) | 11; 8; 3 | docs/semantic-review.md (label rows and Notes) |
| HO-016, HO-011, HO-007 state and guard observations | (qualitative) | docs/semantic-review.md |
| RW-002 and RW-003 caused by the removed canned line | (qualitative) | docs/decisions.md (2026-11-12, voice call B stuck-choice fix) |
| x10 index versus search-only | $0.517805 versus $0.128555, 3/4 each | docs/scaling-v3-results.md |
| Evaluation file hashes | as listed | docs/decisions.md (Frozen evaluation files) |
