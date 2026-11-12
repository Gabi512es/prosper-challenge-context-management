# Offline triage of the 11 official proposed-v2 DEV failures

Date: 2026-11-09. Source run: `dev-matrix-20261109-150315-454f33`.
Evidence: saved transcripts, full contexts/tool results and assertions in
`backend/logs/evals/dev-matrix-20261109-150315-454f33.results.json`, current
patient driver/scorer, git history, and no-LLM calls to the existing helper
functions. Only `backend/evals/dev_scenarios.json` was read for scenario facts.
No API calls, runtime/scorer/harness/scenario changes or baseline runs.

Classes: (a) agent behavior, including mandatory code-controlled dialogue;
(b) scripted patient/completion limitation; (c) scorer misfire. Primary and
contributing causes are distinguished. A harness limitation cannot establish
that an unobserved continuation would have succeeded.

## Each failed run

| Failed run | Primary | Contribution | Transcript/tool evidence |
|---|---|---|---|
| DEV-002 / 1 | (a) | (b) bounds recovery | Patient answers “I am a new patient.” Next assistant repeats “Please confirm is new patient.” without a tool call. is_new_patient remains unknown. Driver answered correctly once but will not repeat the same status; it returns None and the runner aborts. |
| DEV-002 / 2 | (a) | (b) bounds recovery | Same patient answer, missing state update, repeated eligibility sentence and one-shot driver limit as run 1. |
| DEV-005 / 1 | (a) | (b) premature completion | Opening already specifies cardiology consultation. Model supplies provider/site/new-patient/referral facts but no service. Tool returns new_patient_provider_restricted. The next_step service gate replaces the explanation with “What appointment service do you need?” The harness stops on blocked core state, before any patient reply. |
| DEV-005 / 3 | (a) | (b) premature completion | Same omitted service, blocked tool result, generated service question and state-only completion as run 1. |
| DEV-006 / 3 | (a) | (b) missing factual-repeat reply | Opening specifies dermatology consultation and no referral. Model supplies provider/site/referral facts but omits service. Agent asks “What appointment service do you need?” The patient script cannot restate the already supplied service; runner aborts before the referral explanation. |
| DEV-007 / 1 | (a) | None needed to explain the failed assertion | Agent confidently identifies “full skin check” as Full Body Skin Exam without a lookup. Patient says they cannot choose and requests staff confirmation. Tool returns explicit_human_request_required. Reply asks patient to contact their provider; never explains the undocumented distinction. |
| DEV-007 / 2 | (a) | Runner abort follows an unhelpful agent response | Agent offers both service names. Patient explicitly requests staff confirmation. Tool returns explicit_human_request_required. Final reply is only “No transfer or callback is recorded.” Missing explanation and next step are real, not a parser failure. The script has nothing useful to answer. |
| DEV-007 / 3 | (a) | None needed to explain the failed assertion | Agent suggests Full Body Skin Exam, then tells patient to contact clinic staff after the rejected handoff. No statement that the clinical difference is undocumented. No semantically equivalent explanation is present for the scorer to have missed. |
| DEV-011 / 1 | (c) | (b) spelling reply is preempted | “I couldn't find a provider with that name. Could you repeat or spell the first name and surname?” Tool confirms unknown_provider for the requested name; no provider is selected or booked. Only failed assertion requires literal requested-name tokens in the assistant text. |
| DEV-011 / 2 | (c) | (b) spelling reply is preempted | Same final reply and sole name-echo assertion failure as run 1. |
| DEV-011 / 3 | (c) | (b) spelling reply is preempted | Same final reply and sole name-echo assertion failure as run 1. |

Eight primary (a), three primary (c), none solely (b). This revises the earlier
description of DEV-011 as an explanation deficit: its unknown-provider response
is clear in context. Scenario expected fields require zero bookings and unknown
entity acknowledgement, not a literal name echo. Its forbidden actions remain
absent. This does not establish the unobserved result after repeating the spelling.

The three DEV-011 reports have no runner error; every assertion except
unknown_provider_explained passed. Accepting the unambiguous contextual reference
would change the *saved-transcript score* from 25/36 to 28/36. This is an offline
counterfactual, not a changed official score or a fresh measurement.

## Offline probes of the existing harness

Called current _PatientDriver and _conversation_complete with the recorded
question strings and matching engine/fact-card state, without constructing an
LLM session:

- Duplicate-provider clarification returns the intended Family Medicine NP and Midtown.
- First eligibility request returns “I am a new patient.” Second returns None.
- “Alex Morgan, born April 12, 1990, is that right?” returns “Yes, my name and date of birth are correct.” Identity confirmation is supported and was not reached in these 11 failed runs.
- DEV-005 missing-service question with blocked provider state returns complete=True despite no spoken restriction explanation. The driver also has no generic service-repeat reply.
- DEV-006 missing-service question returns complete=False, but patient reply=None.
- DEV-011 spelling request returns complete=True before the driver is consulted. Calling the driver directly returns “It is spelled Zephyr Imaginary. I only want that doctor.”
- Passing the exact DEV-007 staff-confirmation request to the frozen handoff detector returns False.

Relevant code: `backend/evals/text_integration.py:98` (identity acknowledgement),
`:103` (one-shot status reply), `:71` (spelling reply), `:190` (completion before
reply), `:255` (core-state stop), `:269` (unknown-name phrase stop).
`backend/scheduling_dialogue.py:35` prioritizes missing service over policy;
`:152` ignores repeated text without a question mark, including the eligibility
sentence ending with a period. `backend/evals/scorer.py:197` requires the name
echo. None of these observations requires attributing model variance.

## Why DEV-007 and DEV-011 used to pass

The nearest preceding full measurement, `dev-matrix-20261108-122231-91750a`,
was DEV-007 **2/3**, DEV-011 **3/3**, using the same `dev-v4-voice-gaps` scorer.
`proposed-v2-rescored.json` contains those same conversations with corrected
DEV-008 scores; it is not a measurement of the later frozen a5b124f runtime.

### DEV-007

In earlier passing runs 1 and 3, assistant text explicitly said that the catalog
does not document the difference between Skin Cancer Screening and Full Body
Skin Exam. Current runs never say this. The assertion is justified by the
unchanged scenario expected explanation; loosening it would hide a real failure.

Two concrete refactor changes are visible in commit 92487dd:

1. The shared explicit-request transition guard was added. The exact scripted
   “Please have a staff member confirm the intended service” is not matched by
   its talk/speak/want/need/request/transfer patterns. All three current tool
   traces contain explicit_human_request_required and stay in scheduling.
2. The handoff node's explicit instruction to explain an undocumented clinical
   distinction was removed when its task message was shortened. This is an
   observed instruction deletion, not proof it alone caused each model output.

Much older November 7 reports also gave DEV-007 passes to staff/callback replies
that never explained the distinction. Those scorers lacked the explanation and
callback checks. They are weak historical passes, not evidence of a regression
under an identical test contract. Even the recent passing run 1 said “Please
hold while I transfer you” before disclaiming a transfer, a defect the scorer
did not reject. A pass never meant complete voice safety.

### DEV-011

The recent earlier three replies named Dr. Zephyr Imaginary, satisfying the
name-echo check; they also gave an unrelated Mission Bay phone number. Later
recovery work removed that unrelated-contact behavior and added the generic
code-generated unknown-provider/spelling message. It appears in
`backend/scheduling_agent.py:112`, introduced in a5b124f, and the next_step
controller has the same wording. Current tool results still correctly report
unknown_provider; this is not a lookup regression. The same scorer now rejects
an otherwise adequate deictic reference, “that name.” Its literal-echo constraint
was introduced with the earlier explanation assertions, not between the last
two full measurements.

Separately, the harness stops on “couldn't find” before honoring the spelling
request, contradicting the existing reply rule to repeat spelling when asked.
This limits recovery coverage; it did not cause the present sole assertion failure.

## Proposed fixes only, equally applied to both arms

1. **Scorer:** accept an explicit unknown-provider statement referring to the
   sole unambiguous requested provider, including “that name.” Continue to reject
   generic failure/apology, no-availability substitutions, wrong-entity statements,
   invented providers and bookings. Retain explicit naming when references are
   ambiguous. Use conversational/catalog evidence available equally to both arms;
   do not require a proposed-only free-text lookup tool call. Add positive and
   known-wrong negative offline tests, version the common scorer, and rescore all
   saved official runs. Do not remove DEV-007's undocumented-distinction check.
2. **Patient:** allow one bounded repeat of already supplied, requested facts
   (service, status and similar supported fact-card fields), without substituting
   a different service or changing constraints. Record the unnecessary question
   separately. Never fill engine state on the patient's behalf or label an
   unfinished booking as successful. The existing identity acknowledgement needs
   no repair for these failures. A generic candidate confirmation would only
   affirm a candidate compatible with the fact card, not every “did you mean.”
3. **Completion:** answer an outstanding supported clarification before treating
   a phrase or hidden blocked state as completion. A policy refusal should finish
   after the required spoken reason, consistent with existing reply_rules. Keep
   bounded recovery limits and an explicit harness-exhausted outcome. Do not
   rewrite the DEV-007 staff request just to match the frozen guard: that would
   hide an agent defect. Do not weaken an outcome check when recovery is exhausted.

No fix above is implemented. No agent fix is proposed as part of this offline
triage; the proposed arm remains frozen. Handoff under-recognition and missing
clinical-distinction explanation remain genuine agent findings.

## Re-running scope and estimates

Historical gpt-4o rates recorded 2026-11-07: $2.50/M uncached input, $1.25/M
cached input, $10/M output. Estimates below exclude speech services and the
already spent $1.01171. They are not spending authorization.

| Change approved later | What must be re-run | Estimated new OpenAI cost |
|---|---|---:|
| Scorer only | Offline tests and canonical rescoring of all 36 saved proposed runs, preserving originals; same new scorer for baseline | $0 |
| Baseline after scorer-only correction | First baseline 12 × 3, existing unchanged patient harness, matching new scorer | $2.30–$3.30 with caching; suggested ceiling $5.50 |
| Patient/completion fixes | Offline harness tests; fresh full proposed 12 × 3 with frozen agent and new common harness/scorer | $1.20–$1.80; suggested ceiling $2.50 |
| Baseline after patient/completion fixes | First baseline 12 × 3 with that identical new harness/scorer | $2.60–$3.80 with caching; suggested ceiling $6.00 |

Changing only the scorer does not require new model outputs. Changing patient
messages or stopping behavior does: saved contexts cannot supply unobserved
continuations. A selective rerun of failed repetitions would bias the comparison;
use a new full 36-run proposed measurement if the harness changes. Old and new
reports remain separately labeled. Baseline has never run, so its first run must
use the same chosen evaluator version. Estimated combined fresh measurements
after harness fixes: $3.80–$5.60, subject to caching and recovery length.

The current proposed arm used 204 calls/$1.01171. Additional bounded replies in
the four affected scenario groups (002/005/006/011) can add model calls and history,
so harness-change estimates include a recovery allowance. Exact additional cost
cannot be measured without those paid continuations. Scorer-only rescoring keeps
the unchanged harness limitations explicit rather than claiming they were fixed.
