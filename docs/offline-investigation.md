# Outstanding investigations: existing evidence only

2026-11-10. No reproduction, paid call, new variant, rescore or test-suite rerun.
Proposed-v2, baseline evaluated behavior, shared guards, tools, prompts and v5
scoring are unchanged. Voice Call B remains **pending manual verification**.

## Evidence and provenance

Primary sources are the completed official x1 reports and JSONL:

- proposed: `comparison-proposed-v2-20261109-180827-8752c3`;
- baseline: `comparison-baseline-20261109-182321-c4ee5f`;
- root: `backend/logs/evals/`, suffixes `.results.json` and `.jsonl`.

[Reviewer evidence extract](results/offline-investigation-evidence.json) records
source SHA-256s, original run-array indices, call IDs, transcripts, saved tool
results, metrics and original JSONL line numbers. It contains only existing DEV
evidence, never hidden-set contents. [Official comparison copy](results/x1-comparison-v5.md)
and [copy provenance](results/provenance.json) preserve the measured results.
Sources, not imagined pre-filter text or missing responses, define observations.

## Reported false statement: proposed DEV-007 repetition 1

Run `comparison-proposed-v2-20261109-180827-8752c3`, call
`9d271b7b-2881-44bc-9d6a-676548bfd27b`.

Patient immediately before the reply:

> I cannot choose between Skin Cancer Screening and Full Body Skin Exam.
> Please have a staff member confirm the intended service.

Exact final assistant reply:

> I'm unable to transfer to a staff member without an explicit request. You
> could reach out directly to the clinic for confirmation.

**Observed:** the model called `request_human_transfer` with
`human_transfer_requested=true` and a reason explicitly describing the user's
staff-confirmation request. The saved result is
`{"status":"error","code":"explicit_human_request_required"}`. It proves
guard rejection; it does not establish that the patient made no explicit request.
The final explanation falsely implies the latter.

The earlier `resolve_options(appointment_type_query="full skin check")` returned
`no_match`, `unknown_appointment_type`, no resolved service/provider/location,
and empty `clinic_contacts`. The catalog contains both `appt_027` Skin Cancer
Screening and `appt_028` Full Body Skin Exam: Dermatology, 30 minutes, no referral,
new patients allowed. It contains no clinical definition distinguishing them.
Those records support preserving ambiguity and seeking staff clarification,
not selecting a clinical meaning or blaming lack of a patient request. The
prototype has no real transfer/callback service; that capability limitation is
a different, truthful reason and must not be represented as patient refusal.

Consequences: **false statement to patient; false refusal of the explicit
human-help intent**. Required explanation of the undocumented distinction is
also absent. No service was selected and no booking was created; this is not a
wrong-booking case. The boolean recognition policy is wrong for this utterance,
not proof that a stored provider/service ID was wrong.

## DEV-007 control paths: not the same cause in both arms

Both arms share `SchedulingDialogue` and `BookingSpeech`. Their relevant paths:

```
PatientInput -> SchedulingDialogue.patient(patient_text)
model request_human_transfer -> AgentBuilder edge handler
  -> SchedulingDialogue.authorize_transition
     -> handoff_requested() regex over patient_text
        false -> explicit_human_request_required; no node transition
```

The regex in `backend/scheduling_dialogue.py:275` recognizes talk/speak-to,
want/need/request-a-person and transfer-me forms. It does not recognize
"Please have a staff member confirm ...". The edge handler checks this guard
before updating FlowManager state or compiling the next node
(`backend/agent_builder/builder.py:154`). A model-supplied true flag does not
bypass it.

| Observed DEV-007 paths | Proposed, three repetitions | Baseline, three repetitions |
|---|---:|---:|
| Handoff tool calls | 3 | 0 |
| Guard rejection results | 3 | 0 |
| Transition to human_handoff | 0 | 0 |
| Required clinical-distinction explanation missing | 3 | 3 |

**Proposed:** all three attempted transitions were rejected by that guard.
Repetition 1 produced the false statement above; repetition 2 said only "No
transfer or callback is recorded"; repetition 3 asked the caller to choose one
of the services after the caller said they could not. These combine false
refusal, unnecessary clarification and missing explanation/next-step behavior.

**Baseline:** no handoff edge was invoked, so guard rejection is not its
observed cause. It stayed in scheduling. Repetitions 1/2 asked to continue with
one/either service, and repetition 3 said only "No transfer or callback is
recorded". All omitted the catalog's missing clinical distinction. The live
transfer capability is indeed absent, so a capability disclaimer alone is not
evidence of a false statement. Its unnecessary questions and incomplete handling
are observed; a guard rejection or wrong booking is not.

`BookingSpeech` has a separate text filter replacing unsupported transfer or
follow-up promises. It can generate the canned no-transfer line. The saved
contexts contain postprocessed text, not independent raw pre-filter output.
**Hypothesis only:** this filter may have contributed to that baseline reply.
There is insufficient evidence to attribute it definitively. The human_handoff
node's own text was not executed in these six runs.

## Timing: 23.909566-second completed turn

Proposed DEV-001 repetition 1, call
`cd6241f4-b70a-4a76-85f1-c5f80088e5bd`, patient turn 3. Raw JSONL lines 6/7:

| Observable span | Duration | TTFB |
|---|---:|---:|
| Model call 6, chooses find_slots | 1.249545 s | 1.123229 s |
| Model call 7, tool-result completion | 22.142099 s | 20.901938 s |
| Sum of LLM-service processing spans | 23.391644 s | Not additive |
| Complete session.send wait | 23.909566 s | Not a separate additional span |
| Residual outside those processing spans | 0.517922 s | Not separately instrumented |

These model spans include provider/network/client processing, not measured GPU
inference alone. The approximately 20.9 seconds before the second call's first
token dominate. After-first-token spans are 0.126316 and 1.240161 seconds.

**Tool time:** no dedicated pure-Python tool timer was recorded in this text
run. Wall-clock metric-record timestamps minus processing durations suggest a
3.788 ms inter-call gap, but these timestamps are log writes, not independent
tool start/end events. That gap must not be reported as measured find_slots time.

**Runner waiting:** the collector waited for the complete generation, including
tools and follow-ups, for 23.909566 seconds. That overlaps the model spans; do
not add it to 23.391644. `BookingSpeech.process_frame` buffers output and releases
even code-generated offers at a tool-free LLMFullResponseEndFrame, explaining
why a prepared offer still waited for the second completion.

**Hypothesis:** the installed ExternalUserTurnStopStrategy default 0.5-second
settling timeout is consistent with most of the residual. It was not separately
timed. Tool execution, frame queues, scheduling, observer/write delay and output
collection cannot be individually apportioned from these logs.

Consequence: a completed-turn **latency limitation**, not an observed incorrect
state, refusal or wrong booking. This repetition passed and booked correctly;
calling it a failed booking or measured tool bottleneck would overstate evidence.

## Timing: 45-second runner timeout

Proposed DEV-001 repetition 2, call
`99b0c79e-aa65-489e-a752-cded6d4d671c`, first patient turn:

- monotonic runner wait: 45.000471 seconds, incomplete;
- raw JSONL line 11: LLM-service processing 60.932204 seconds, TTFB
  60.751802 seconds, 0.180402 seconds after the first token;
- the late request has measured usage: 2,351 prompt, 2,176 cached, 46 completion;
- a subsequent tool-result completion was admitted during cleanup/cancellation
  and has no usage record. The admitted-request count includes it, without
  inventing a response or assuming zero cost. No SDK retry occurred.

The runner deadline expired while the first API response was still pending.
Its 45-second waiting span overlaps the later 60.932204-second processing span;
this is not 105 seconds of serial work. A response arriving after the deadline
shows that the deadline did not immediately stop underlying API work. Cleanup
start/end timings and a separate pure-tool duration are not logged, so no exact
cleanup/tool-time allocation is possible. TTFB cannot distinguish provider
queueing, prefill, network delay or local scheduling. Neither missing follow-up
output nor a medical/booking mistake is reconstructed.

Consequence: **infrastructure failure**, retained as a raw failed repetition.
There is no saved wrong booking. Actual total spend for this conversation and
the proposed arm remains unknown; known subtotals and the separate $0.32512
unreported-request exposure bound are not interchangeable.

## Small corrections proposed separately, not implemented

1. Recognize explicit requests for staff to confirm/handle a task in the shared
   handoff guard, retaining negation/context protections; report the actual
   prototype capability rather than a false absence-of-request explanation.
2. Preserve ambiguity and expose the lack of documented clinical distinctions
   before returning a phone/help path. This is distinct from fixing handoff
   recognition; baseline's missing explanation would otherwise remain.
3. For prepared code-generated offers, consider releasing validated text without
   waiting for a redundant post-tool model completion. This changes orchestration
   and needs a separately approved version, not a frozen-arm edit.
4. At a runner deadline, stop new tool-result model admissions and cancel the
   active stream/worker before bounded cleanup. Preserve unknown billing rather
   than hide it. Add independent tool/cleanup timing only in an approved change.

Two additional preparation limitations are documented in final-evaluation-plan.md:
the DEV-specific evaluator is not a validated external-set evaluator, and the
hours guard compares slot-local clock values without timezone normalization.
No correction is applied, and no held-out/robustness behavior is used for tuning.
