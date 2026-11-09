# Decision log

## 2026-11-07: persist Pipecat metrics with an observer

Observed in the first manual browser call:

- The playground reported aggregate OpenAI TTFB of 622.2 ms, prompt usage of 5,686 tokens, completion usage of 187 tokens, and total usage of 5,873 tokens.
- It also displayed aggregate ElevenLabs STT and TTS TTFB plus TTS character usage.
- The UI did not expose durable per-call rows, graph node attribution, the configured model, or cached tokens.
- Installed Pipecat 1.4.0 emits `TTFBMetricsData`, `ProcessingMetricsData`, and `LLMUsageMetricsData`. The OpenAI service passes through cached-token usage when OpenAI supplies it.

Choice: attach a pipeline observer that combines the three LLM metric frames and appends one JSONL line per model call. Use the runner session ID as `call_id`, record the active graph node, keep full processing latency and TTFB separate, and write unavailable usage as `null` rather than zero. Logs contain no prompts, transcripts, tool arguments, or keys.

Reason: the observer uses Pipecat's measured data without adding a processor to the audio path, and the JSONL output is suitable for later evaluation and cost analysis.

Live validation: the first logged browser call produced 11 real LLM processing attempts across four nodes. OpenAI reported usage for 9 attempts: 5,425 prompt tokens, 188 completion tokens, and 0 cached tokens. Two interrupted or otherwise incomplete attempts had processing metrics but no final usage report, so their token fields remain `null`. Mean processing latency across the 11 real attempts was 810.1 ms; mean TTFB across the 10 attempts that reached first byte was 771.1 ms. Pipecat also emitted one synthetic zero-valued startup metrics frame; the observer now filters that frame rather than counting it as a turn.

## 2026-11-07: catalog measurement with the configured model tokenizer

The configured model is `gpt-4o`. With `tiktoken` 0.14.0,
`encoding_for_model("gpt-4o")` resolves to `o200k_base`.

- Source size: 45,661 characters and 45,661 UTF-8 bytes.
- Raw formatted `catalog.json`: 12,924 tokens.
- The same JSON serialized compactly: 8,252 tokens.
- All 82 appointment type names: 368 tokens as a compact JSON array, or 365 as a newline-delimited list.

The raw-catalog estimate in AGENTS.md is confirmed. The names-only estimate is
not: it is about 365 to 368 tokens, not about 1,000 tokens. Structural checks
also confirmed all other section 3 counts and edge cases: 8 locations, 50
providers, 82 appointment types, 6 policies, 34 multi-location providers, 31
partially capability-gated provider/type pairs, no fully unbookable gated pair,
and exactly the 8 listed appointment types with no provider. There are no
dangling location or appointment-type references. The checks also reproduced
215 cross-specialty provider/type pairs, 36 referral-required types, 31
existing-patient-only types, 11 providers not accepting new patients, all
three duplicated full names, and the listed surname collisions: Nguyen 8,
Chen 7, Sato 6, and Patel 5.

## 2026-11-07: installed Flows context behavior

Installed `pipecat-ai-flows` 1.4.0 supports global and per-node context
strategies: `APPEND`, `RESET`, and `RESET_WITH_SUMMARY`. The default is
`APPEND`. Append transitions use `LLMMessagesAppendFrame`; reset variants use
`LLMMessagesUpdateFrame`. Role instructions are updated separately through a
persistent LLM settings frame, so a message reset does not clear the active
role instruction.

`RESET_WITH_SUMMARY` is deprecated for removal in 2.0.0. Its installed
implementation has a five-second summarization timeout and falls back to
`APPEND`. Pipecat 1.4.0 instead provides native context summarization frames
and optional automatic summarization on the assistant aggregator, disabled by
default.

The standalone `pipecat_flows` package also emits a deprecation notice in favor
of `pipecat.flows`. In this installed environment, the working Flows module is
still the standalone package, so changing import paths in this step would not
be a safe mechanical migration.

The current declarative agent schema does not expose `context_strategy`, so the
example voice and text agents both use Flows' default `APPEND`. This runner step
does not expand the schema. Context-strategy selection belongs with the later
catalog architecture and evaluation design.

## 2026-11-07: one shared runtime for voice and text

Voice and text now call the same runtime factory. They share the actual
`AgentBuilder`, prompts, transition handlers, tool handlers, model settings,
FlowManager, empty initial context, session state, APPEND context behavior, and
metrics observer. Voice adds WebRTC, ElevenLabs STT/TTS, and VAD. Text supplies
explicit turn-boundary and transcription frames and collects text after the
LLM. It does not create a startup user message.

A text turn completes only after any model-requested tools finish, the node
transition completes, and a subsequent tool-free assistant response has passed
into the shared assistant context. This keeps scripted patient messages from
overlapping tool execution or follow-up generation. Every underlying model
call, including post-tool calls, remains visible to the existing JSONL metrics
observer.

Offline validation covers state population through the real transition
handlers and the post-tool completion boundary. The opt-in OpenAI integration
check is labeled as paid and variable. Its first run completed the example
booking through the expected four nodes, preserved the supplied facts, produced
the correct confirmation, contained no startup user message, and wrote one
metrics record for each of its seven model calls. This validates the runner
infrastructure only; it is not evidence that the scheduling approach handles
the real catalog.

## 2026-11-07: eval attribution and compact type index

After the shared-runtime voice refactor passed a user-run voice call, JSONL
records gained `run_id`, `patient_turn`, and `trigger`. Trigger values are
`startup`, `patient`, or `tool_result`; tool-result calls retain the patient
turn that caused the tool. A supplied eval `run_id` selects
`backend/logs/evals/<run_id>.jsonl`, so calls in one eval run append to one file
and separate runs do not mix. Missing usage remains `null` with
`usage_status="unavailable"`.

Using `tiktoken` 0.14.0 and the configured `gpt-4o` model's `o200k_base`
encoding, compact JSON for all 82 appointment types measured:

- `id+name`: 3,774 characters and 1,026 tokens.
- `id+name+specialty`: 5,855 characters and 1,559 tokens.

Choice: use `id+name` for the proposed cached type index. Specialty costs 533
additional tokens and cannot be used as a compatibility rule because the
catalog has 215 cross-specialty provider/type pairs. Specialty remains
available from authoritative tool results.

## 2026-11-07: pinned development scenarios and pure scheduling core

`backend/evals/dev_scenarios.json` is copied from the user-authored JSON source
without changing its data. It contains 12 development cases only. The loader
computes Git's blob SHA directly from the current catalog bytes and refuses to
load unless it equals the file's pinned
`8e5091080383d598ae18acce084c7dcd6522ab14`. Availability fixtures are treated
as complete, closed worlds. No held-out dataset is read or inferred.

The v1 scheduling core is plain Python with no Pipecat or LLM imports. It loads
and validates the catalog, preserves ambiguous identities, applies catalog
relations and policies, searches and globally ranks fixture slots, invalidates
stale selections and confirmations, and performs idempotent booking with final
revalidation. DEV-012, DEV-004, and DEV-008 are the first proof cases. The
catalog's eight providerless appointment types remain explicitly unbookable.

The opt-in OpenAI text integration passed those three cases in one eval run.
DEV-012 created the expected `dev012-s1` booking, DEV-004 created no booking,
and DEV-008 retained the corrected `loc_000` location while clearing the stale
slot and confirmation. The run logged 17 individual model calls across three
sessions: 3 startup, 7 patient-triggered, and 7 tool-result-triggered calls.
OpenAI reported prompt, cached, and completion usage for every call in this
run; the logger would preserve any missing values as `null`.

## 2026-11-07: visible text faults and opening-hours enforcement

Development scenarios may optionally declare session-local `error` and
`slot_taken` faults. The text runner wraps the same real tool handler exposed to
the model, so structured failures remain in the conversation context. A
slot-taken write permanently removes that fixture slot; later searches and
booking revalidation both observe the removal.

Availability fixtures remain closed worlds but are not sufficient authority to
offer a slot. The core also parses each location's catalog hours and requires
the entire slot interval to fit on an open day. Outside-hours fixture entries
are counted in the `find_slots` exclusion result, never offered, and rejected
again at selection and booking. General tool shutdowns cannot be reported as
success, and an explicit request for a human transitions to a terminal handoff
state without falsely claiming that the prototype completed a live transfer.

Catalog opening hours are local wall-clock hours. The current catalog does not
carry an IANA timezone field, so the core compares them with the wall-clock date
and time on each offset-aware fixture slot; the supplied `-08:00` slots therefore
represent Los Angeles standard time directly. The interval is closed at the end:
a slot ending exactly at `17:00` is allowed, while one ending at `17:05` is not.
Production data should add an explicit `America/Los_Angeles` field so offsets can
be derived and daylight-saving transitions validated rather than trusted.

The first paid regression exposed an ambiguity in the model-facing
`resolve_options.name` property: the model used it for an appointment name.
The adapter now exposes `patient_name` and maps it to the core's patient state.
A subsequent paid run of DEV-012, DEV-004, and DEV-008 passed. Human handoff is
terminal to the agent but does not emit Pipecat's immediate end action, allowing
the final limitation and handoff explanation to reach output first.

## 2026-11-08: catalog-first resolution and authoritative booking state

Pre-fix transcripts showed that the booking failures were not merely model
variance. The model sometimes received a patient's name and date of birth in
conversation, then called `find_slots` without first persisting those facts
through `resolve_options`. Slot search allowed the incomplete state, but the
booking tool's final revalidation correctly rejected it as `missing_identity`.
The agent then offered a human handoff. A separate provider-resolution defect
treated practitioner nouns such as “pediatrician” as unequal to catalog labels
such as `Pediatrics`.

Choice: session state, not conversation text, remains authoritative. Slot search
now requires persisted identity; after identity is supplied, the agent must call
`resolve_options` before `find_slots`. Catalog entities are resolved before name
and date-of-birth collection, and no-match results explicitly direct the agent
to explain the missing provider or service first. Specialty matching derives
ordinary practitioner nouns from catalog specialty labels without embedding
scenario identities or catalog IDs.

“Any clinician” and “any location” are represented by explicit scope flags,
rather than by silently missing filters. When a selected location is blocked by
provider coverage or a required capability, the resolver returns catalog-valid
alternative locations for the same provider and appointment type. The agent may
offer only those returned alternatives. Catalog-information questions resolve
the named entity and then use `get_details`; they do not enter the booking fact
collection flow.

The final three-run development matrix passed 34 of 36 runs. All 12 expected
bookings across DEV-001, DEV-002, DEV-009, and DEV-012 completed. The two
remaining failures disagreed with their sibling runs: one model response failed
to map an explicitly named consultation to the exact type index, and one
prematurely selected a service for an intentionally ambiguous request before
handoff. Those are retained as observed variability rather than hidden by
scenario-specific rules.

## 2026-11-08: one scorer for both arms and complete explanation checks

Choice: `backend/evals/scorer.py` is the single deterministic scorer for every
evaluation arm. Reports record scorer version `dev-v3-explanations`; proposed
and full-catalog baseline runners must import `evaluate_run` from this module,
not copy assertion logic. This keeps arm comparisons from drifting because of
different scoring code.

Scorer changes, with no scenario or expected-outcome edits:

- DEV-007 adds `undocumented_distinction_explained`. It requires both ambiguous
  service names and an explicit statement that the catalog does not document,
  specify, or distinguish their clinical difference. A handoff alone is not an
  explanation.
- DEV-008 adds `corrected_location_explained`. It derives the final location and
  required capability from scenario facts plus the catalog, then requires the
  assistant to identify that location, the capability, and its absence.
- DEV-010 retains the separate phone and hours assertions and adds
  `location_details_explained`, requiring the named location and both facts in
  the answer.
- DEV-011 retains unknown-provider acknowledgement and non-invention checks and
  adds `unknown_provider_explained`, requiring the response to identify the
  requested unknown provider rather than refer only to an unspecified entity.
- Typography normalization remains limited to case-folding and straightening
  apostrophes. It does not add semantic synonyms or change scenario facts.

Reason: the earlier scorer checked core state well but could pass a response
that reached the correct no-booking outcome without communicating the expected
reason. Offline positive and negative tests now exercise each new explanation
assertion. The development scenario JSON remains unchanged.

## 2026-11-08: editable JSON graph and local next-call selection

Choice: the scheduling graph is persisted in
`backend/agents/catalog_scheduler.json` and both the voice entrypoint and the
text scheduling runner compile it with `AgentBuilder`. The four scheduling
operations remain non-transition functions in a session-local registry; JSON
nodes reference those functions by name. Transition handlers, prompts, model
configuration, node tools, and context behavior therefore come from the same
saved graph in both paths. The Python scheduling engine remains the shared
authoritative implementation behind the tools.

The editor uses the existing `AgentConfig` plus `AgentBuilder` validation before
an atomic save. It additionally rejects duplicate node names, duplicate edge
function names within a node, unknown targets, unregistered tool names, and
edge/tool name collisions. The React Flow UI is deliberately limited to agent,
node, edge, message, and attached-tool editing; catalog management, auth, and
layout persistence are outside this prototype.

Choice for **Test call**: save the graph, write its agent id to the local
next-call selection file, and open the existing Pipecat client. Every newly
connected voice session reads that selection and the JSON from disk and creates
fresh state plus a fresh tool registry. This reuses the already-working WebRTC
client and voice pipeline, so the editor does not need a second call transport
or changes to the prebuilt client. The selection is intentionally process-global
and suitable only for this single-user local prototype; concurrent or hosted
use would require a per-session signed agent id.

A paid four-scenario smoke run after the JSON conversion passed DEV-001,
DEV-009, and DEV-012. DEV-003 still showed the previously observed model
variance: the model asked for clarification instead of mapping the caller's
explicit knee MRI wording. The smoke run also exposed a general resolution
order defect: resolving type after location could silently clear an incompatible
location. Explicit selections are now retained so policy evaluation can return
the capability block and valid alternatives, with an offline regression test.
The remaining DEV-003 variance was not hidden with scenario-specific prompt or
code changes.

## 2026-11-08: proposed-v2 after real voice failures

Observed: the handoff prompt instructed staff follow-up although no callback
record exists. Removed this instruction and prohibited callback promises in the
shared saved agent. Blocking reasons and catalog clinic phones are returned in
tool results. Complete offers and confirmations must include service, provider,
location, date and time; identity read-back requires a spoken DOB confirmation.
Booking replies recap, offer further help, then close on caller completion.
These conversational requirements remain model-driven and require voice review.

Shared find_slots now returns at most three deterministic alternative previews,
each changing exactly one of location, provider, or date range (14 extra days).
Soft constraints rank before hard constraints, then location/provider/date range,
then start and slot id. Every preview requires consent and does not authorize a
booking: the request must be updated and searched again. Patient eligibility,
catalog relationships and opening hours remain enforced. No catalog repairs.

Voice and interactive demo generate seed-42 synthetic availability covering all
760 valid provider/location/type combinations in the next two weeks, with local
America/Los_Angeles dates and explicit offsets. Evaluation code continues to use
only each scenario's complete closed-world fixture. Slots are synthetic and do
not represent a real calendar.

Installed Pipecat 1.4 provides ElevenLabs realtime Settings.language and
MinWordsUserTurnStartStrategy. Voice pins Language.EN, uses a word-filtered
minimum of two words during bot speech (one word when idle), replacing the
default VAD-triggered interruption start. A 2.5-second recovery prompt handles
interruption without a recent real transcript; real speech cancels it. This
requires live acoustic validation and can delay a one-word interruption.
Voice tool traces record call id, node, name, arguments, actual result/error,
timestamp and duration in ignored logs/voice-tools.jsonl. These logs include
patient data and should stay local.

Scorer version dev-v4-voice-gaps is shared by both arms. Added general checks for
location on time-bearing slot offers, no callback promise (no callback recording
exists), and a question or explicit next step after no-availability wording.
These are deterministic language heuristics, not proof of semantic completeness;
seeded bad examples are tested. Existing scenario assertions remain in force.
Scripted patients now acknowledge DOB read-back without changing scenario facts,
fixtures or expected outcomes. Reports tag this architecture proposed-v2.

First proposed-v2 matrix: 23/36 passed, 186 model calls, $0.85666250 using
the recorded dated gpt-4o rates. DEV-008 passed 2/3. Inspection showed contact
results supplied phone but no hours, and the model answered from that partial
result rather than calling get_details. Contact results now include catalog
hours. General prompts reinforce immediate provider resolution, preserving
clinical ambiguity, and returning valid capability alternatives. Handoff
instructions explicitly forbid invented numbers and notifications. The scorer
now accepts "unable to provide" as an absence explanation. (Corrected
2026-11-08: this entry previously said the scorer also distinguishes denial of a
recorded callback from a positive callback promise. It does not. The callback
check is a keyword pattern; it fires on negations such as "I can't promise
staff will call you" and misses promises such as "they'll be in touch". See the
review entry below.) The original
failed matrix is retained at dev-matrix-20261108-122031-20e4ff.results.json.

Final matrix: 192 model calls, $0.988365, 30/36 under the first vocabulary
pass, 32/36 after correcting two DEV-008 scorer false negatives for "does not
offer" and "cannot perform" imaging. Original raw report remains unchanged;
proposed-v2-rescored.json records the two corrections and recomputed agreement.
DEV-002, 003, 006 and 007 each retain one failure. All three new general checks
passed in the final matrix. DEV-008 passed 3/3 after the vocabulary correction,
but this does not establish voice reliability. Total paid cost of both matrices
was $1.84502750. Live interruption, speech recognition, DOB confirmation and
closing still require the user's acoustic retest. The selected next-call agent
was an older test copy; selection now points to the updated catalog_scheduler,
without altering that user-created copy.

## 2026-11-08: review fixes after agent handoff (no paid calls)

Offline review of the final proposed-v2 matrix traces and the code. No model
calls, no scenario or fixture changes. `make test`: 62 tests, 60 passed, 2 paid
checks skipped.

**Voice: short answers were dropped while the agent spoke.** Observed in code,
not acoustically. With `min_words=2`, Pipecat 1.4's
`MinWordsUserTurnStartStrategy` resets the user aggregation when a transcript
has fewer words than the threshold during bot speech, which discards it. "No",
"Stop" or "Midtown" said during a slot read-back was therefore lost, not
delayed. Choice: `VOICE_MIN_WORDS = 1`, counting only real words; punctuation
noise and filler sounds (um, uh, hmm, mm, mhm, huh) never start a turn. Risk to
check by ear: a backchannel "yeah" or "okay" now interrupts a read-back, and
"huh?" is ignored. Tests cover one-word answers and fillers during bot speech.

**False location claim (DEV-002 r2).** Provider candidates carried only
`location_ids`. In a turn with no tool call the model told the patient that
Family Medicine Maria Garcia (prov_003) practices at Mission District, North
Beach and North Gate, "not Midtown". Her catalog sites are North Beach, Midtown
and Richmond, so a valid booking was refused. Choice: provider summaries now
return `locations` as `{id, name}` pairs instead of bare IDs. A general persona
rule was added: a catalog fact (a provider's sites or services, a location's
capabilities, phone or hours, availability) is stated only when it appears in a
tool result earlier in the conversation; names come from returned pairs, never
from IDs or list order. DEV-007 r2 also made a claim in a turn without a tool
call. The rule is model-driven; only the tool contract is enforced in code.

**Capability alternatives no longer wait for patient facts (DEV-003 r2).**
The model did not persist the referral the patient stated. The resolver
returned no alternative sites until referral status was known, so Downtown was
never mentioned. A site's capability does not depend on patient facts. Choice:
capability-valid alternatives are returned with
`alternatives_pending_patient_facts` listing unknown facts that still gate
booking. A known fact that blocks the provider/type everywhere (no referral,
new patient not allowed) still returns no alternatives, since no site helps.

**Session identity in logs.** Text evals always loaded `catalog_scheduler.json`,
while voice loads the agent in `active_agent.txt`. No log tied a session to a
graph version. Choice: the scheduling loader reads the JSON bytes once and
records `agent_id` (file stem), `agent_revision` (SHA-256 of those bytes) and
`availability_mode` (`eval_fixture`, `demo_generated`, or `file:<name>`). These
fields are written on every `turns.jsonl` / eval JSONL row and every
`voice-tools.jsonl` row. Each scored run and the matrix report header
(`agent_versions`) carry them too. Unknown values stay null. Matching revisions
show that voice and text ran the same graph.

**Remaining development failures (final matrix).** DEV-002 r2: false statement,
fixed above in the tool contract. DEV-003 r2: incomplete explanation, no false
claim, addressed above. DEV-006 r2: the clearly named service was not resolved
and the patient was asked to confirm it. This unnecessary clarification is a
documented limitation, not tuned. DEV-007 r2: suggested one of two
undistinguished services without a tool call and never said the catalog does
not document the difference. No callback was promised. None of the four
created a wrong booking.

**Coverage of three conversational requirements.**
(a) Location in every slot offer: automated in text evals
(`slot_offers_include_location`), manual for voice. Known misfires: short
names such as "the Midtown location" fail because every distinctive word of the
full name is required. Any catalog location satisfies the check, even the wrong
one. Offers without am/pm are not detected. Clinic hours worded with "available"
count as offers.
(b) No unrecorded callback promise: automated in text, manual for voice.
"Follow-up appointment" (hyphenated) does not fire. "Follow up visit", "your
visit will follow up" ("it" is matched inside "visit") and negations do fire.
"You'll get a call from our team" and "they'll be in touch" are missed.
(c) Block explained with a fitting next step: block explanations are checked
only by per-scenario keywords. The general next-step check fires only on
no-availability wording and accepts any question mark. Whether the next step
fits is not covered: manual review. Respecting a refused alternative under a
hard constraint is also not covered, because scripted runs stop at the first
block. DEV-008 r1 re-offered Downtown right after "I cannot go downtown". A
`dev-v5` scorer fixing (a) and (b) is deferred.

**Old matrix under the current scorer.** `backend/evals/rescore_saved.py`
rescored `dev-matrix-20261107-193131-c96e6c.results.json` (originally 34/36,
before scorer versions were recorded) under `dev-v4-voice-gaps` with no model
calls. Output:
`backend/logs/evals/dev-matrix-20261107-193131-c96e6c.rescored-dev-v4.json`.
Result: 24/36, or 26/36 after correcting the two location-check misfires
(DEV-002 r1 and r3 named "the Midtown location"), against 32/36 for proposed-v2.
Eight runs were flagged for a slot offer without a location: six genuine
omissions and the two misfires. All three DEV-007 runs failed the
catalog-distinction explanation, and two of them also promised a staff
follow-up ("They will follow up with you"). The DEV-006 r3 runner failure was already in the original 34/36.
Caveats: transcript-based assertions are recomputed with current code, but
state-based ones reuse the values saved by the original run, because engine
state is not persisted. The same script reproduces proposed-v2's 32/36 exactly.
The old run used older prompts and a scripted patient that did not acknowledge
DOB read-back, so this compares versions under one scorer, not identical
conversations.

**Baseline plan (not built).** For identical recovery behaviour, the baseline
arm will bind the same `build_scheduling_tool_registry` and engine. Its
`resolve_options` will run in an ID-only mode: it accepts `appointment_type_id`,
`provider_id`, `location_id`, patient facts, scope flags and hard constraints,
and rejects every `*_query` and `provider_specialty` field. It still performs
validation, invalidation, block reasons and capability alternatives. Unchanged
`find_slots` provides the slot alternatives and `book_appointment` the final
guard. The only difference is that the baseline reads the full catalog in
context instead of searching it. `dev_matrix.py` needs an `--arm` option, and
both arms keep the same scorer version.

## Frozen evaluation files

Two evaluation sets are kept outside the repository until the final run. Their
SHA-256 hashes are recorded here so they can't be changed without it being
visible.

- Held-out set (`prosper_heldout_scenarios.json`): 16 scenarios. SHA-256:
  `d41abdad3defe405a48becc55a97d4d153c3c3b27a4eff5f5518db8a2dedd1b6`
- Robustness set (`prosper_robustness_scenarios.json`): 8 scenarios. SHA-256:
  `c5de085b51996c51afaa9dbc3b40c392452d0eec28760b422ced2a6f74aa6c19`

Recorded on 2026-11-08. The coding agents did not read either file during
development.

## Time spent (build only, excluding preparation)

Active time measured with a timer. Coding agents also ran in the background between sessions; that compute time is not counted.

- Steps 1 and 2 (setup, metrics and text runner; design v1 and scheduling core): 1h00, Nov 7
- Steps 3 and 4 (DEV evaluation and root-cause fixes, 26/36 to 34/36; graph editor and JSON agent): 2h00, Nov 7
- Step 5 (real voice testing and fixes, in progress): 1h44 so far, Nov 8
- Total so far: 4h44

Work continued with Claude Code during Step 5, after reaching usage limits on Codex.

## 2026-11-09: voice trace review and code-owned booking read-back

All three supplied session traces used catalog_scheduler_test revision e3822739.
That copy's handoff task still instructed staff follow-up. Both saved handoff
tasks are corrected. A transition guard now checks the actual last patient
transcript for a human request, rather than trusting the model's boolean.
Call 2 (29ec30f7) handed off with reason "Patient prefers to book with
cardiologist", which is not a human request. Call 3 (df88c81d) never persisted
Midtown; its resolver first selected loc_002 (North Beach). It has exactly one
book_appointment trace and one booking ID. Duplicate speech is not evidence of
two bookings. No client event logs were attached, so precise audio/completion
timing cannot be reconstructed from tool traces alone.

Shared scheduling_dialogue.py now observes final patient transcripts before
aggregation. Explicit location names override model-supplied location IDs;
stated specialty disambiguates cached provider candidates. Code renders offers
and final recaps from the engine's names, DOB, weekday/date/time. The adapter no
longer manufactures a confirmation inside book_appointment: a rendered read-back
and subsequent affirmative patient turn are required; correction/interruption
invalidates consent. Raw core confirmation methods remain available to unit tests.

OpenAI parallel_tool_calls is disabled. Installed Flows runs inference after
each non-transition result; parallel resolver calls were observed in calls 2/3.
BookingSpeech suppresses pre-tool prose and retains one code-owned offer until
the final assistant response. The independent silent-cutoff TTS processor is
removed from voice wiring to eliminate its separate speech source; the class
remains available but unused. Wait/stop produces a change question, not a recap.
Speech is buffered to response completion, adding latency; acoustic delivery
and interruptions still need a real voice test. No paid calls were made.

Prompt counts (characters, excluding JSON syntax): canonical persona 1373 to
1065; all task contents 7667 to 6992. Test copy persona 530 unchanged; tasks
325 to 251. Removed redundant model-owned offer/confirmation/closing directions.
New offline regressions cover specialty disambiguation, false handoff, transcript
Midtown precedence, read-back consent, wait and idempotent booking.

## 2026-11-09: offline negation, conflict and consent follow-up

The previous location loop treated every mentioned site as positive and chose
by catalog iteration order. It now excludes negated clauses, distinguishes
Mission Bay from Mission District, and asks on multiple positive sites. A
transcript/model location mismatch returns location_conflict without applying
the model update; find_slots and booking remain blocked until the caller names
the location again. BookingSpeech emits the clarification from code. This is
bounded lexical parsing, not general natural-language understanding.

Handoff checks request verbs rather than bare mentions. Tests accept "can I talk
to someone?" and "I'd like to speak to a person", and reject the front-desk
anecdote. Consent uses an explicit phrase allowlist with a correction/negation
veto: yes, yeah/sure, that's fine and okay/book it are covered; no, wait and
actually never authorize booking. Consent still requires a prior matching
read-back. No silent-cutoff speaker is wired: noise/fillers should not interrupt,
but if a false real-word transcript causes a cut-off, there is no automatic
recovery speech; the session waits for patient input or its idle timeout.

Offline suite: 69 collected, 67 passed, 2 paid checks skipped. No paid calls.
Buffering delays TTS submission from first token to model-response completion.
Historical voice model timings (128 nonempty calls with both metrics) show a
116 ms median and 210 ms p90 for processing latency minus TTFB. These pre-change
timings estimate generation-tail overhead, not measured additional audio latency;
TTS already buffers text and tool calls are included in this aggregate.

## 2026-11-09: JSON-independent scheduling safeguards and code identity

User confirmed the later calls selected catalog_scheduler_test revision 785633b1,
not canonical revision 40db1b58. Agent JSON identity cannot prove which Python
process was running. voice-tools rows now include process-start git_commit,
code_version (scheduling-guards-v3), and code_revision (SHA-256 of backend Python
source snapshot, excluding tests/hidden directories/logs). Startup reports those
values too. Git HEAD alone cannot identify uncommitted code; source hash provides
that distinction. Historical rows remain unchanged and cannot establish this
identity retroactively. Restart the voice process to load these changes.

Consent and generated speech were already code-owned, but attaching their
controller depended on build_scheduling_agent. The scheduling tool registry now
carries the controller to any AgentBuilder, including arbitrary UI-created JSON.
Runtime rejects scheduling tools without a policy-bearing registry. Handoff
guards cover the standard tool and edges targeting handoff nodes, including
renamed edges. Accepted handoff speech is generated by code rather than the
node's editable task. JSON can still change conversation instructions, but it
cannot manufacture booking consent through the scheduling tool. Parallel calls
are disabled by shared runtime settings, independent of JSON. This is one tool
per model emission, not one per patient turn: sequential resolve/search calls
are still required for a complete turn. This is not a sandbox for arbitrary
Python tool implementations.

Call 3 (70ca9d26) find_slots was blocked on missing name and DOB yet exposed
alternative slot IDs. The model offered those previews, then booking correctly
rejected Richmond and North Beach as not offered. Missing required facts now
suppress alternative previews. Shared speech names remaining alternatives only
as constraint changes requiring consent and a fresh search, never as bookable
slot offers. The booking guard remains intact.

Capability blocks now generate an explanation before patient eligibility rules,
and contact results filter out sites lacking the service capability. Mission Bay
cannot be recommended as a knee MRI booking contact. Generated read-back uses
the actual stored DOB (including an STT error such as 1994); a DOB change
invalidates old consent, and booking needs a matching read-back plus a later yes.
This exposes the error for patient correction, not automatic DOB verification.
Offline suite: 73 collected, 71 passed, 2 paid checks skipped. No paid calls.

## 2026-11-09: ENT substring regression and paid smoke gate

Trace be070748 ran canonical JSON 40db1b58 and scheduling-guards-v3. Exact
utterance "I'm an existing patient with a referral on file, and I need a knee
MRI with Linda Ramirez in radiology at Downtown" reproduced specialty ENT:
the old substring predicate matched ENT inside "patient", overwriting Radiology
by catalog iteration order. Location resolved correctly to Downtown. Removed
substring specialty detection in favor of whole-token catalog specialty matching;
multiple matches preserve ambiguity. Regression test runs a TranscriptionFrame
through the voice PatientInput processor and the same registry resolver with
the trace's arguments, proving radiologist/provider/type/location resolution.

The first requested smoke passed DEV-008 but failed all three booking cases:
the consent allowlist rejected explicit multi-sentence read-back confirmation.
It now accepts a bounded confirmation grammar referring to the exact read-back
and requesting booking, without weakening negation/correction vetoes. Both
scripted confirmation forms have offline regression coverage. Scenario data
and expected outcomes are unchanged. User requires the four-scenario paid smoke
after every code-change batch before voice retesting; no matrix is authorized.

Validation: make test collected 74 tests, 72 passed and 2 paid integrations
skipped. First smoke smoke-20261109-114359-49b9ee: 1/4 passed, $0.31926750.
Final smoke smoke-20261109-114541-8b41e2: 4/4 passed, 34 model calls, $0.17823000.
Per-case final costs: DEV-012 $0.03683750 (8 calls), DEV-002 $0.05770000
(10 calls), DEV-008 $0.04078750 (8 calls), DEV-009 $0.04290500 (8 calls).
Total both smokes $0.49749750. Costs use logged prompt/cached/completion tokens
and existing dated 2026-11-07 gpt-4o rates, not estimates. Raw reports and JSONL
are in backend/logs/evals/ with those run IDs. Existing deletion of
catalog_scheduler_test.json was preserved, not performed by this fix.
