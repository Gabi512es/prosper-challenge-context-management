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

## 2026-11-09: two-phase booking and multi-slot demo regression

Observed voice failures: abbf5267 returned confirmation_required after the MRI
offer; 33382990 requested Midtown but the output layer had selected the first
North Beach slot, causing slot_not_selected. A bare InterruptionFrame also
cleared consent regardless of whether its transcript was an affirmative yes.

book_appointment is now a two-phase tool with the same slot_id argument. Phase
one revalidates the requested slot against session constraints, patient facts,
opening hours and availability, selects internally, returns a generated readback
and queues it for speech. Phase two books only after that readback and a later
affirmative transcript. find_slots speech offers a slot but does not select or
authorize it. Repeated calls without consent return needs_confirmation and the
readback again, not a clinic referral. Validation failures return
validation_required and a fresh-search next step. These protocol results carry
technical_failure=false and are not technical errors. No numerical retry counter
existed in the runtime; model instructions previously conflated status:error
protocol refusals with real failures. Fault injection remains structured error
output; it is separate from normal consent/selection/validation states.

Interruption frames now cancel buffered text only. The actual patient transcript
controls consent: veto/correction does not authorize booking; a plain yes across
interruption frames remains valid. "Yeah, so yeah, you can book it" is accepted.
Offline test covers both interruption/transcript orderings and choosing the
second of several slots. Spoken service names generically reverse a spaced
hyphen descriptor (MRI - Knee -> a knee MRI); no appointment-specific table.
Code version is scheduling-booking-v4.

Demo generation adds a second occurrence one week later when within the same
two-week window: 760 valid combinations, 1,520 slots for these runs. Both demo
smokes returned two eligible slots for the actual requested combination. Fixture
evaluation still uses only the pinned scenario availability. No scenario or
expected-outcome changes. `evals.smoke --demo DEV-012 DEV-002` uses generated
availability with the same patient facts and canonical scorer; it is a separate
demo integration, not a replacement for the fixture evaluations.

Validation: make test collected 76 tests, 74 passed, 2 paid checks skipped.
Fixture smoke smoke-20261109-120033-f175d3 passed DEV-012/002/008/009, with
costs $0.052375/$0.078985/$0.04467250/$0.05815250 (total $0.234185).
Demo smoke smoke-20261109-120039-2466b7 passed DEV-012/002, costs
$0.050595/$0.07785750 (total $0.12845250). Total $0.36263750 using logged
tokens and cached tokens at the recorded 2026-11-07 gpt-4o prices. Raw reports
and per-model-call JSONL are in backend/logs/evals/ under those run IDs.
Both demo transcripts show a separate offer, prepared readback with name/DOB,
patient confirmation, then one booking recap. Real acoustic validation remains
pending; no voice calls were placed by the coding agent.

## 2026-11-09: API spend policy and retrospective cost ledger

User policy supersedes the previous automatic smoke-after-every-change rule:
show an estimate before any paid run; above $1 wait for the user's go. Smoke
only for booking/resolution changes, once per selected case. Full matrices need
explicit approval at any estimated cost. Documentation changes need no smoke.

Built docs/costs.md offline from all existing usage JSONL, including runs without
reports and default/voice sessions. Deduplicated by (call_id, turn), zero duplicates.
1,729 model-call rows, 38 with incomplete usage. Known gpt-4o cost at the recorded
2026-11-07 prices: eval/text $6.90709250; default/voice OpenAI component
$0.81677000; combined known subtotal $7.72386250. This is not total billed spend:
unknown-usage calls, complete voice costs, ElevenLabs and coding-agent usage are
not measured. Report/rescore copies are not additional calls. No paid API calls,
runtime code changes or scenario changes were made for this ledger.

## 2026-11-09: separate identity confirmation and one booking offer

User requested removing repeated full read-backs. Code now confirms the captured
name and DOB once: "Alex Morgan, born April 12, 1990, is that right?". The
confirmed identity is a tuple compared with current patient state. Changes to
either field require a new code-generated identity question and affirmative
patient response before slot search or booking; identity consent cannot also
serve as booking consent in the same turn.

For one matching slot, find_slots invokes phase-one booking preparation in code
and queues the sole offer: service, provider, location, weekday/date/time and
"Shall I book it?". Name/DOB are not repeated. Model output is replaced by that
prepared offer. For several slots, code lists up to three brief date/time/site
choices; book_appointment prepares the chosen slot after selection. One later
yes books. The recap contains date/time/location and "Is there anything else I
can help with?", without repeating service, provider or identity. Tool policies
are shared across JSON agents. Code version scheduling-booking-v5.

Offline tests cover identity capture, corrected DOB requiring another yes,
blocking booking before identity approval, merged single offer/consent/short
recap, and brief multi-slot choices. No scenarios, fixtures, scorer or expected
outcomes changed. No paid run performed: the user requires an estimate and go.
Estimated usual four-case fixture smoke: $0.30–$0.45, with a $0.50 planning
allowance, based on the last $0.234185 four-case run plus identity-confirmation
turns and cache/model variability. This is an estimate, not a measured charge.

## 2026-11-09: soonest versus geographic proximity (offline)

Inspection: core find_slots already ranks all eligible matches by start time
before truncating, but global search required the model to set both any_provider
and any_location. No distance/geocoding implementation exists, and the dialogue
had no guard for "closest". Added bounded transcript handling for "whichever is
soonest" and similar short time replies: explicitly widen provider/site scope,
retain service and patient eligibility, and prevent model tool arguments from
accidentally re-narrowing it. Existing hard provider/site constraints require a
permission question before widening. Slot ranking remains core code.

"Closest"/"nearest" now asks whether the patient means time or place and blocks
resolution/search/booking until clarified. Geographic intent asks for the
neighborhood; a supplied neighborhood is not used to invent distances. Code
lists up to four sites with eligible available slots for the current request,
or asks for a preferred clinic if eligibility is not yet known. The patient
chooses a site. No nearest-site claim or geographic ranking is computed.

Offline tests traverse PatientInput and actual tool handlers: global soonest
returns DEV-009's earliest eligible slot; closest asks time/place; place asks
neighborhood and lists capability-valid sites without choosing one; hard
constraints need permission. make test: 82 collected, 80 passed, 2 paid checks
skipped. No paid run; four-case smoke still awaits the user's explicit go.

## 2026-11-09: geographic site choice and approved capped smoke

Removed the neighborhood question: geographic proximity immediately says the
code cannot determine the nearest clinic and lists eligible sites for patient
choice. Offline suite: 82 collected, 80 passed, 2 paid checks skipped.

User approved one usual four-case smoke with a $0.50 ceiling. Ran once each,
using a temporary launcher that reserves a conservative uncached input/output
allowance before every SDK call, settles reported usage, and limits completion
to 512 tokens; it refuses calls whose reservation exceeds remaining budget.
No usage means retaining the reservation. No paid retry was performed.

smoke-20261109-122509-3adf22: DEV-012 PASS ($0.0425900), DEV-002 FAIL
($0.0030900), DEV-008 PASS ($0.0435475), DEV-009 PASS ($0.0650825).
30 model calls, total recorded cost $0.1543100, equal to launcher accounting,
below $0.50. DEV-002 timed out during startup: one 14-token model completion
was logged but no initial assistant response reached the text-session transcript;
no patient opening or booking was attempted. Cause of that delivery timeout is
not established. Do not classify it as a demonstrated provider/booking failure,
nor call the smoke fully passing. Raw report and JSONL are under backend/logs/evals/.

## 2026-11-09: tolerant provider lookup, scoped sites and bounded recovery

Observed call B a8aecc8a: "maria m garcia" with specialty "family medicine
nurse practitioner" returned unknown_provider; "maria garcia" then resolved
prov_003, but clinic_contacts still contained all eight locations. Provider name
normalization now removes titles/credentials, single-letter initials and adjacent
stutter prefixes, then matches first name and surname. Duplicate full names
remain ambiguous unless specialty disambiguates them. Approximate name fallback
returns up to three candidates at SequenceMatcher similarity >=0.65, explicitly
marked suggestion/requires_confirmation; even a single suggestion never resolves
the provider automatically. Other catalog entities retain exact matching behavior.

Resolver now returns eligible_locations, computed by joining the resolved
provider, service, provider sites, required capabilities and known patient policy
facts. Unknown provider or unconfirmed provider suggestions return no contact
phone; resolved provider/service contacts use the same scoped join. Code-generated
name/site questions use these results, not all catalog sites. No catalog repairs.

Removed transcript keyword interpretation of time/place proximity. The model
fills resolve_options.location_preference, a closed enum (time, place, unclear).
Tool description explicitly classifies "near me", "to where I live" and "nearest
clinic geographically" as place. Code validates the enum, asks time/place once
for unclear, then lists scoped sites on another unclear result. Place lists sites
without distance claims or a neighborhood question; time enables global eligible
slot search, subject to explicit permission for hard-constraint widening. Repeated
"nearest" in patient speech cannot reset this code state. Interpreting meaning
into the closed field remains a model task and is not established by offline tests.

A generic output guard prevents the same question being spoken consecutively:
switch to eligible site choices, then a scoped clinic contact when available.
If a replacement changes an identity/booking question, pending consent markers
are cleared so a yes to the replacement cannot approve an unspoken read-back.
Code version scheduling-recovery-v6. Offline tests traverse PatientInput plus
actual tools, cover stutters/initials/titles, specialty disambiguation, fuzzy
suggestions, no unrelated phones, scoped sites, enum validation, repeated place
answers and the generic repeat guard. make test: 87 collected, 85 passed, two
paid integrations skipped. No scenario, expected outcome or scorer changed.

No paid calls. Proposed one usual four-case smoke (DEV-012/002/008/009, once
each) estimated $0.30–$0.45, $0.50 planning allowance. This is based on recent
$0.15431–$0.234185 four-case runs plus clarification/cache variability. Awaiting
the user's explicit go, including DEV-002 to check its prior startup timeout;
that timeout's cause is still unestablished.

## 2026-11-09: approved recovery-v6 four-case smoke, no retries

User approved one usual four-case smoke, maximum $0.50. Used the capped temporary
launcher with per-request reservations and 512-token completion limit. Run
smoke-20261109-123934-da8fb2 completed 32 model calls for $0.17078250:
DEV-012 PASS $0.04627250; DEV-002 FAIL $0.01124000; DEV-008 PASS
$0.04455500; DEV-009 PASS $0.06871500. All usage is reported; launcher accounting
matches the raw model usage. Reports/JSONL are in backend/logs/evals/.

DEV-002 was not a startup timeout. The opening was "I'd like an annual physical
with Dr. Maria Garcia." The model added provider_specialty="primary care" to
resolve_options. No catalog specialty matched that filter, so the provider
collection became empty before name matching, and the tool falsely returned
unknown_provider despite the correct name. The scripted patient had no response
to the resulting spelling request; no booking was created. This is distinct
from the prior startup-delivery timeout, whose cause remains unknown. No retry,
scenario changes or runtime fixes were performed during this smoke-only turn.

## 2026-11-09: closed catalog filters and capped two-case smoke

resolve_options schema now enumerates catalog provider specialties and provider,
service and location IDs. Free-text names remain search queries, not categorical
filters. Runtime validation rejects unknown enum values with valid_values and
records filter_issues; they never enter catalog filtering. A valid specialty
that eliminates every named candidate returns the candidates without that
filter, marked for confirmation, with filter_no_match. Name suggestions remain
non-authoritative; no silent identity selection or constraint relaxation.
Transcript-derived canonical specialty is separate from the model argument;
invalid raw model filters remain reported even when transcript facts disambiguate.

Offline regressions cover primary care/family doctor rejection with the full
valid specialty list, preserving both Maria Garcia candidates, valid-but-mismatched
Dermatology on Linda Ramirez, catalog ID enums and rejected invented IDs.
make test: 90 collected, 88 passed, 2 paid integrations skipped. No scenario,
expected outcome or scorer changes.

User authorized DEV-002 and DEV-012 once each, maximum $0.15; estimate provided
was $0.08–$0.13. Run smoke-20261109-124555-cc5280: DEV-002 PASS (12 calls,
$0.0808600); DEV-012 stopped by the budget guard (6 dispatched calls,
$0.0330525). Total dispatched/reported cost $0.1139125, 18 paid requests,
matching launcher accounting. The next conservative request reservation exceeded
the remaining $0.0360875, so it was refused before dispatch. Two resulting
Pipecat metrics rows have null usage for these local denials; they are not two
additional paid requests. The raw scorer marks DEV-012 failing/incomplete; this
does not establish a booking regression. No retry or cap increase. Raw report
and JSONL are in backend/logs/evals/. The filter regression is fixed offline
and DEV-002 now books; DEV-012's final paid check is incomplete.

## 2026-11-09: DEV-012-only $0.08 smoke and logged enum overhead

User approved one DEV-012 run, maximum $0.08. Run
smoke-20261109-124918-eeeec1 dispatched seven requests, all with reported usage:
27,643 prompt tokens (24,832 cached), 240 completion tokens, $0.04046750.
The conservative reservation for the next request exceeded the remaining
$0.03953250; it was refused locally before dispatch. One corresponding metrics
row has null usage. No retry. The transcript reached successful identity
confirmation and the prepared knee-MRI offer; the booking did not complete.
Raw scorer marks it failed/incomplete, but this is a budget-guard stop, not
evidence that the booking code rejected valid consent. The $0.08 ceiling was
not exceeded; actual spend did not exhaust it.

Offline comparison uses pre-enum smoke-20261109-123934-da8fb2 and post-enum
smoke-20261109-124555-cc5280, same agent JSON revision 40db1b58. Both DEV-002
and DEV-012 startup prompts increased from 2,283 to 3,230 tokens: +947 tokens,
41.48%. Empty-history startup is the cleanest logged comparison of the tool
schema overhead, including the enum lists and revised specialty description;
logs do not independently isolate the enum arrays alone. DEV-012's first six
reported calls total 16,994 pre versus 22,741 post, averages 2,832.33 versus
3,790.17: +957.83 per call, also including small message/result differences.
Do not compare whole-run averages as a causal estimate: lengths and outcomes
differ. At the recorded rates, 947 extra tokens cost $0.0023675 uncached or
$0.00118375 cached per model call, conditional on that cache treatment.

## 2026-11-09: lazy catalog validation and observed-cost admission

Context-cost decision: removed catalog-sized provider specialty, provider ID,
location ID and appointment-type ID enums from the tool schema. Runtime catalog
validation and filter_no_match fallback remain unchanged. Unknown values still
return valid_values only when needed; no silent filtering or fuzzy identity
selection. Retained small structural enums (location preference and entity kind)
and the specialty description instructing the model not to infer a specialty.
Offline primary care/family doctor rejection tests remain passing. No scenario,
expected outcome or scorer changes.

Compared enum run smoke-20261109-124555-cc5280 with list-free run
smoke-20261109-125320-fae71b, same agent JSON revision 40db1b58:

| Prompt measurement | With catalog enums | Without catalog enums | Difference |
|---|---:|---:|---:|
| Empty-history startup, both cases | 3,230 | 2,306 | -924 (-28.61%) |
| DEV-002 mean, 12 calls in each run | 4,516.67 | 3,585.67 | -931.00 |
| DEV-002 first-six-call mean | 3,752.17 | 2,821.17 | -931.00 |
| DEV-012 first-six-call mean | 3,790.17 | 2,861.33 | -928.83 |

Startup is the cleanest logged comparison: the previous +947 included the
specialty description; removing enum lists saves 924 while retaining that
description's 23-token difference from the older 2,283-token prompt. Later-call
comparisons also include slightly different assistant/tool messages. Do not
compare DEV-012 full-run means as causal: enum run was budget-stopped after six
reported calls, while the new run completed in nine.

Added reusable evals/spend_guard.py, exposed via evals.smoke --max-cost-usd.
Instead of reserving full uncached context plus maximal output, it reserves
1.5 times the highest observed actual cost in the last five calls of this run;
bootstrap is $0.015 before an observation. Reported stream usage settles the
reservation, unknown usage prevents further requests, and additional requests
are denied if the forecast does not fit the remaining budget. Output cap stays
512 tokens. This is a forecast plus margin, not a mathematical guarantee of an
unseen API request's charge. The observed run completed below its authorized cap.

Offline: 93 tests collected, 91 passed, 2 paid integrations skipped. User
approved DEV-002 and DEV-012 once each, maximum $0.20, estimate $0.09–$0.15.
smoke-20261109-125320-fae71b: both PASS; DEV-002 12 calls, 43,028 prompt
(36,224 cached), 328 completion, $0.0655700; DEV-012 nine calls, 29,616 prompt
(25,984 cached), 287 completion, $0.0444300. Total 21 requests, $0.1100000,
all usage reported; budget accounting and JSONL agree. No retries. Raw report
and JSONL are in backend/logs/evals/ under that run ID.

## 2026-11-09: ordered slot filling and numeric final transcripts

Code confirmed the turn-start filter accepted letters only. A final transcript
"1991." became empty and MinWordsUserTurnStartStrategy could reset aggregation.
real_words now includes numeric tokens, ordinal dates, numeric dates and times.
Offline tests prove these start a user turn instead of resetting aggregation;
precise acoustic behavior still needs a real call, and no client event log was
attached in this request.

Voice-tool trace 837b8f69 shows Midtown was stored as loc_005 at 11:56:53 UTC
and retained in the later identity update. The observed repeated site questions
were not evidence of a missing location in core state. Independent proximity,
identity and repeat-output gates could ask for sites despite that filled slot;
the repeat fallback also cleared an identity consent marker when it changed
the question.

SchedulingDialogue.next_step is now the ordered source of the next missing
slot: service, provider, location/proximity clarification, required eligibility
facts, identity collection/confirmation, offer/consent, complete. It derives
the stage from authoritative engine state; it does not duplicate resolved IDs.
Tool results expose dialogue_step; availability/booking use the same gate and
output generation follows it. A chosen location is pinned through identity
updates and clears stale proximity questions. Only an actual location correction
or explicit scope change invalidates it. Catalog-information replies bypass the
scheduling question gate.

Bounded English identity-segment capture retains "Alex Morgan, April 12th."
as name plus an incomplete month/day draft, then completes it with "1991.".
It asks for the year rather than inventing one. "Hello?" does not clear these
facts. This is a narrow parser for that structured form, not general identity
understanding; normal model/tool fact collection still accepts other phrasings.

Repeat handling retains the last six questions, including non-consecutive
repeats, and changes strategy based on the current missing slot. It no longer
uses site choice as a generic fallback after location is filled. Rephrasing an
identity confirmation preserves consent only if the same name/DOB is actually
spoken; switching to unrelated recovery clears the consent marker.

New no-LLM multi-turn tool tests cover provider/service -> geographic site list
-> Midtown -> two identity segments with an intervening Hello -> identity yes
-> Midtown-only offers -> phase-one read-back -> yes -> one Midtown booking.
Additional tests cover alternating questions and affirmative response to a
rephrased identity question. Code version scheduling-slots-v7. make test:
96 collected, 94 passed, 2 paid integrations skipped. No scenario, fixture,
expected outcome or scorer changed. No paid calls. Estimated usual four-case
smoke: $0.20–$0.35 from recent measured runs and anticipated call counts;
awaiting the user's explicit go.

## 2026-11-09: approved slots-v7 four-case smoke

User authorized the usual four cases once each, maximum $0.40, no retries.
smoke-20261109-131238-90cbfb passed all four with 40 model calls and fully
reported usage: DEV-012 PASS, nine calls, $0.04575250; DEV-002 PASS, eleven
calls, $0.05942500; DEV-008 PASS, nine calls, $0.05231000; DEV-009 PASS,
eleven calls, $0.06987750. Total $0.22736500, below $0.40; observed-cost
guard accounting matches the JSONL usage. No retries or runtime changes.
Raw report and usage: backend/logs/evals/smoke-20261109-131238-90cbfb.smoke.json
and the corresponding .jsonl. Text smoke success does not establish acoustic
behavior; numeric interruptions and segmented identity still need live checking.

## 2026-11-09: proposed-v2 freeze, voice status and comparison authorization gate

User froze the proposed arm at tag proposed-v2 (a5b124f). Do not change its
behavior, prompts or shared guards without explicit user authorization. The
next official proposed measurement must use this frozen revision and current
scorer dev-v4-voice-gaps. Earlier full matrices predate the latest fixes.

Verification status: call A was verified in real voice by the user. Call B fixes
(ordered next_step controller, numbers/dates/times as real words, six-question
loop history) are verified offline and by the four-case smoke, but have NOT yet
been re-verified in voice. Passing text smoke does not close this voice gate.

### Demo checklist

- [x] Call A verified by the user in real voice.
- [x] Call B fixes verified offline and by the approved four-case text smoke.
- [ ] Re-test call B by voice: segmented identity, numeric year, Midtown retained,
  identity confirmation followed by offer, no alternating question loop.

### Step 6 estimates, provided before either paid matrix

| Paid step | Scope | Estimated OpenAI cost | Suggested planning allowance |
|---|---|---:|---:|
| 1: official proposed measurement | 12 DEV scenarios × 3, frozen proposed-v2/current scorer | $1.20–$2.20 | $2.50 |
| 3: baseline measurement | Same 36 conversations, full readable catalog/policies prefix | $3.00–$5.00 | $6.00 |
| Combined | 72 conversations | $4.20–$7.20 | $8.50 |

Estimates use existing dated gpt-4o rates ($2.50 uncached input, $1.25 cached
input, $10 output per million) and the latest 40-call/$0.227365 four-case smoke,
plus prior full-matrix call counts. Allow roughly 200–260 model calls per arm;
the full DEV mix includes cheaper refusal/FAQ cases as well as bookings. These
are estimates, not measured charges or automatic spending authorization.

Baseline estimate assumes substantial reuse of the stable prefix. Its readable
catalog has not been built/tokenized yet; budget provisionally assumes about
6K–10K catalog/policy tokens. Existing measurements are raw JSON 12,924 and
compact JSON 8,252; neither is the proposed readable baseline representation.
Weak caching or longer recovery conversations could put baseline cost around
$6–$8. Re-measure the rendered prefix offline in step 2 and refresh the estimate
before step 3 if necessary. STT/TTS costs are excluded: these are text runs.

User requested both estimates and a pause BEFORE step 1. No matrix, baseline
implementation or paid call was started in this turn. Await explicit go and
spending ceiling. Step 1 must classify failures as unnecessary question,
internal-state-only, false patient statement or wrong booking, with trace
evidence. Baseline must share model, scripted patients, fixtures, scorer,
availability/booking tools and guards; only catalog access differs (readable
complete stable context prefix; resolve_options ID-only). Report baseline wins
plainly and leave the frozen proposed arm unchanged.

## 2026-11-09: official frozen proposed measurement and offline full-catalog baseline

User authorized step 1, all 12 DEV cases × 3, ceiling $2.50 and no retries;
then baseline construction/tokenization/prefix checks offline. Baseline paid
matrix remains unapproved. Frozen proposed-v2 commit a5b124f and source JSON
40db1b587b5790ab2c92bc642edbc55e67f0d44ebd8d4f1267de29e1e86ebdc5,
current scorer dev-v4-voice-gaps, sequential execution, same closed-world
fixtures and patient driver. The launcher's in-memory settings disabled both
SDK retries and Pipecat timeout retries; no frozen source was edited. Existing
SpendGuard imposed the same 512 completion-token cap as the preceding smoke.

Official run dev-matrix-20261109-150315-454f33: 25/36 PASS (69.44%),
11 FAIL, 204 model calls, 659,476 prompt tokens including 556,800 cached,
5,902 completion tokens, $1.0117100 at the recorded 2026-11-07 rates.
All usage is known; no retries. Ten correct bookings, none wrong. Mixed
outcomes on DEV-002/005/006; DEV-007/011 fail all three. Full table, trace-based
manual severities and harness stopping limitations are recorded in
docs/comparison-proposed-v2.md. Explanation omissions are distinguished from
false statements; no scoring rules or scenario outcomes were relaxed.

Baseline is additive code in backend/baseline_agent.py, with an explicit paid
entrypoint backend/evals/baseline_matrix.py. It reuses AgentBuilder, runtime,
controller, model, APPEND context, scripted patients, fixtures, scorer, shared
find_slots/book_appointment/get_details and all identity/consent/handoff guards.
resolve_options is an ID-only wrapper over the shared handler; queries and
specialty search arguments are rejected before delegation. Validation, block
reasons and alternatives stay identical. Shared transcript safeguards remain;
no separate baseline orchestration or booking implementation was introduced.
Only the baseline catalog-access messages differ: full reference instead of
the compact type index and free-text resolver instructions.

Complete readable Markdown catalog/policies: 5,894 o200k_base tokens for
configured gpt-4o; 16,848 bytes. Catalog+role 6,085 tokens; system+initial task
content 6,626 tokens (excludes API framing/tools). Round-trip tests check every
source field, relationship, record and policy. The offline installed-adapter
check constructs four requests with different histories/state, including a
post-tool history, and verifies identical system/task prefixes and schemas.
AsyncCompletions.create was mocked/asserted unused. This proves prefix stability
with zero paid calls; it does not claim measured OpenAI cache hits.
Evidence: backend/logs/evals/baseline-prefix-check-20261109.json and
backend/logs/evals/baseline-catalog-20261109.md. Both are ignored local artifacts.

Updated step 3 estimate: $2.30–$3.30 with substantial caching, suggested ceiling
$5.50, no retries. Based on measured 204 proposed calls and approximately
4,788 extra serialized input tokens/call; cold input at identical call counts
would be about $4.15, and 260 similar calls about $5.30. Actual baseline behavior
is unmeasured. Await explicit user go; no paid baseline run yet. Neither proposed
arm nor scorer nor scenarios were changed.

Final offline validation: make test ran 102 tests, 100 passed and 2 opt-in paid
integrations skipped. Six new baseline tests cover full rendering fidelity,
stable installed-adapter serialization without HTTP, ID-only rejection/runtime
validation, shared guards/policy alternatives, unchanged source configuration,
and identity -> offer -> consent -> one booking in both arms. Tracked backend
diff against proposed-v2 is empty; new files are additive baseline/eval/test code.

## 2026-11-09: offline triage before baseline authorization

Reviewed all 11 failures in the official frozen proposed run with saved
transcripts/tool results, original scenario requirements, current helpers and
git history. No paid calls or runtime/harness/scorer/scenario edits. Findings
and per-run evidence: docs/failure-triage-proposed-v2.md.

Primary attribution: eight agent-behavior failures, three DEV-011 name-echo
scorer misfires. Patient limitations additionally bound recovery: status can be
answered once, service re-confirmation lacks a reply, blocked core state can
stop before the spoken explanation, and unknown-provider acknowledgement stops
before an explicitly requested spelling reply. Existing identity confirmation
already gets an affirmative patient reply; none of the 11 failures reached it.

DEV-007's nearest earlier full matrix was 2/3, not 3/3; it now lacks the required
catalog-distinction explanation in all three runs. The 92487dd refactor shortened
the handoff message, removing that instruction, and added a guard that rejects
the exact staff-confirmation request in all three current traces. These are
agent defects, not a reason to change the patient wording or relax its scorer.
DEV-011 used to echo the requested name (and give an unrelated clinic phone);
the later generic code-generated spelling request correctly acknowledges an
unknown provider but fails a literal-echo assertion beyond the scenario outcome.
Accepting that unambiguous reference would yield 28/36 on the saved text, an
offline counterfactual, not a replaced official measurement.

Proposed, not implemented: one common versioned scorer accepting unambiguous
unknown-provider references; bounded same-fact patient repeats; completion that
lets supported outstanding clarifications run before stopping. Scorer-only
correction: rescore all 36 saved runs for $0, no proposed paid rerun needed;
baseline estimate remains $2.30–$3.30 with caching. Patient/completion changes:
fresh full 36 proposed and 36 baseline using the identical new harness/scorer,
estimated $1.20–$1.80 plus $2.60–$3.80 with caching. Do not cherry-pick retries
of the failed repetitions. No implementation or paid-run approval inferred;
proposed remains frozen, and baseline run remains unapproved.

## 2026-11-09: approved common evaluator corrections and two fresh matrices

User selected harness plus scorer corrections, equally for both arms, then
fresh proposed 12 × 3 capped at $2.00 and baseline 12 × 3 capped at $4.50.
No retries. Stop if a cap is reached; do not start the second arm if the first
stops for budget or unknown usage. This is explicit authorization for those
two measurements, not additional smokes or failed-case retries.

Evaluator label: dev-eval-v5-recovery. Both reports include the same evaluator
SHA-256 over version/scorer/patient/measurement/budget code, scenario SHA-256,
catalog pin, source git commit, model and agent revisions. Runtime agent,
prompts, tools, guards, APPEND handling and source scenarios remain frozen.

Corrections in backend/evals/text_integration.py: one bounded same-fact repeat
for service, identity and eligibility/referral facts (an initial answer plus
one repeat when the opening did not already supply that fact); no engine state
is filled by the patient driver. The same spelling reply is allowed before an
unknown-provider completion predicate. Hidden blocked state alone cannot end
a refusal before its required spoken explanation. The DEV-007 patient wording
is unchanged; no wording is tailored to bypass its handoff guard. Unsupported
or exhausted replies remain explicit failures. Unnecessary factual questions
are logged in driver_events even when the booking later succeeds.

Common scorer dev-eval-v5-recovery accepts a clear unknown-provider explanation
referring to the sole requested provider as "that provider" or "a provider with
that name". It rejects wrong-entity statements and no-availability substitutes.
No booking, state, clinical-distinction or other explanation assertion is
relaxed. The previous 28/36 calculation is a counterfactual on saved transcripts
only, not an official score, nor a run of this corrected patient harness. The
old 25/36 report is preserved without rewriting it.

Known agent limitations from the voice-driven refactor, documented rather than
fixed: stated patient status/service facts are not always recorded (DEV-002,
005,006); the handoff message's undocumented-service-distinction explanation
was removed (DEV-007); and the handoff regex rejects the existing explicit
staff-confirmation request. The added next_step gate can repeat a known service
or suppress a policy explanation while that service is absent from core state.
Neither these limitations nor the literal source JSON are repaired for this
comparison. Both arms retain the shared dialogue/booking guard limitations.

Measurement: backend/evals/comparison_matrix.py checkpoints each finished
scenario, runs sequentially, disables both retry layers, uses the same 512-token
completion cap and budget policy, and stops scheduling cases when budget/usage
admission stops. The observed-cost reservation remains; a conservative cold-input
admission check adds near-cap protection without assuming a future cache hit.
Missing usage remains unknown. Per-patient-turn latency now measures monotonic
session.send wall-clock duration through all tools and final generation;
startup and incomplete turns are separately marked and excluded from completed
patient-turn percentiles. This instrumentation is evaluation-only, with no
speech or runtime-behavior changes. Text remains controlled, not deterministic.

### Operational pause after the first two attempted cases

DEV-001 repetition 1 passed. Repetition 2's first patient turn exceeded the
45-second text deadline. Its model response arrived after about 61 seconds;
a subsequent automatic tool-result completion was cancelled without returning
usage. This was not an SDK retry. The initial guard paused the measurement:
12 admitted requests, 11 usage records, $0.0564600 known cost. No failed case
was retried and the original paused report is preserved separately.

To continue only unattempted cases without guessing the missing charge, verified
the official GPT-4o model page (https://developers.openai.com/api/docs/models/gpt-4o)
on 2026-11-09: 128,000-token context, $2.50/M input and $10/M output. With the
existing 512-output-token cap, an unreported request costs at most $0.32512
(128,000 * 2.50/M + 512 * 10/M), deliberately double-allowing output within the
context ceiling. This bound is held against the authorized cap; actual usage
and actual cost remain null. It is a spending-exposure bound, not a measured
charge or a cost estimate. New unknown requests receive the same treatment in
both arms, and no call is admitted if its full bound cannot fit. Observed-cost
reservations remain unchanged for ordinary reported calls.

Added checkpoint resume support that skips every already attempted
(scenario,repetition), including failures. Scorer.py and text_integration.py
are byte-for-byte unchanged from the first two attempts. The evaluator behavior
hash now explicitly covers those two files; operational checkpoint/budget code
has its separate execution hash. The archived pause retains the initial broader
full-code hash. Evaluator label stays dev-eval-v5-recovery; these are budget and
provenance corrections, not a scoring/patient or agent revision. Both arms use
the same final operational code. Per-run known usage subtotals are retained,
with unknown requests included in model-call counts and total usage/cost null.

## 2026-11-09: completed fresh v5 comparison, no retries or agent fixes

Both 12 × 3 DEV matrices completed under dev-eval-v5-recovery. Evaluator
behavior SHA-256: 97117348b6d00263d60c0561381841e3fc50e843873a53b60e827a8c7415a996.
Final execution SHA-256: be63f5d4876dd066a96fdc2948d6a43c25df069c278b45e9ccb129d92e7a397e.
Common scenario pin, model, scorer/patient source, fixtures, guards, APPEND,
512-output-token cap and disabled SDK/timeout retries were checked. Frozen
agent/core/prompt files and source scenarios have no diff against proposed-v2.

Proposed run comparison-proposed-v2-20261109-180827-8752c3: 29/36 PASS,
7 FAIL; 219 admitted model calls (218 with usage). Known subtotals: 711,025
prompt, including 598,272 cached and 112,753 uncached, 6,572 completion;
$1.0954425 known cost. One unreported request keeps actual totals null, with
maximum total exposure $1.4205625 after its $0.32512 bound, under the $2 cap.
The initial timeout was retained, not retried. Continuation skipped both
already attempted repetitions; archived pause and resume provenance are kept.

Baseline run comparison-baseline-20261109-182321-c4ee5f: 30/36 PASS,
6 FAIL; 203 model calls, all usage reported. 1,625,524 prompt tokens including
1,482,240 cached and 143,284 uncached; 6,703 completion; $2.2780400, under
the $4.50 cap. No budget cap was reached. Combined known cost $3.3734825;
combined maximum exposure including the unreported request $3.6986025.

Ten correct bookings proposed, eleven baseline; zero wrong bookings and zero
observed invalid booking attempts. Baseline's prov_unknown argument is an
invalid resolution ID rejected before booking, not an invalid booking attempt.
Entire-arm cost divided by successful bookings, including failures and valid
non-booking conversations: proposed known component $0.10954425, maximum
$0.14205625; baseline $0.20709455. Proposed actual cost per booking stays null.

Manual redundant-clarification review totals nine proposed, five baseline:
driver_events log six/one and a separately saved, turn-indexed audit adds
three/four. Valid disambiguation, first spelling checks, consent and permission
to change constraints are excluded. Baseline records the stated services in
DEV-005/006 without the proposed arm's five extra repeat-service questions.
It uses 16 fewer model calls overall. Proposed remains cheaper even at the
unreported request's conservative upper bound; no architecture was changed
in response to these findings.

Completed text-patient-turn latency: proposed n=93, p50 2.619s, p95 3.208s;
baseline n=91, p50 2.634s, p95 3.420s. One proposed turn timed out at 45s,
excluded from completed-turn percentiles and reported separately; its response
arrived around 61s. Largest completed proposed turn: 23.910s. Startup, scripted
think time and operational pause time are excluded. This measures complete
session.send spans, not voice perceived latency. Sequential small samples and
provider jitter prevent a causal speed claim.

Raw failure primaries, manually reviewed: proposed two unnecessary-question
failures, one false patient statement, two missing-explanation/next-step failures,
one provider timeout and one evaluator false failure. Baseline: one unnecessary
question failure, one internal/tool resolution error, three missing-explanation
failures and one evaluator false failure. Each has five genuine agent failures.
DEV-007 remains 0/3 in both. No scorer/agent changes or paid repeats followed
inspection of these results, and no manual review promotes a raw failure to pass.

Remaining evaluator paraphrase limits, disclosed rather than silently fixed:
proposed DEV-011/3 correctly says "I didn't find any provider with the name..."
but completion misses didn't find; all assertions except runner_completed pass.
Baseline DEV-011/1 says "does not match any provider in our catalog" and asks to
verify the name; acknowledgement/completion miss that phrasing and verify is
not the spelling trigger. These are one false failure per arm. Proposed
DEV-011/1's service question after spelling and baseline DEV-011/3's invented
prov_unknown resolution argument are genuine agent failures. Raw 29/36 versus
30/36 therefore includes infrastructure/evaluator effects; baseline's one-pass
margin is not proof of a behavior-quality advantage. The earlier 28/36 remains
only the historical saved-text counterfactual, never an official measurement.

Full tables, per-scenario tokens/costs/calls and severity evidence:
docs/comparison-evaluator-v5.md. Machine summary and manual annotations:
backend/logs/evals/comparison-v5-summary.json and comparison-v5-manual-review.json.
Reports and raw JSONL use the two run IDs above. Logs are local ignored
artifacts. No held-out source was inspected; no voice call was run in this step.

## 2026-11-09: offline trace clarification and step 6b preparation, no paid go

False patient statement in proposed DEV-007 repetition 1 (call
9d271b7b-2881-44bc-9d6a-676548bfd27b): "I'm unable to transfer to a staff
member without an explicit request. You could reach out directly to the clinic
for confirmation." The patient had just explicitly asked staff to confirm the
intended service. Proposed called request_human_transfer three times across
DEV-007 and all three returned explicit_human_request_required. Baseline called
that tool zero times, so its failures cannot be attributed to that guard
rejecting a call. Both arms omit the required clinical-distinction explanation
in all three repetitions. This refines the earlier shared-limitation wording;
no agent or scorer is changed.

The 23.909566-second turn was proposed DEV-001 repetition 1, patient turn 3:
1.249545s for the find_slots model call, 22.142099s for its post-tool model
completion, and 0.517922s outside those processing windows. Post-tool TTFB was
20.901938s; the processing-window gap is about 3.8ms. The installed external
turn-stop strategy's default is 0.5s, consistent with most of the residual;
individual pure-tool time is not measured. Although offer text is code-generated,
BookingSpeech still waits for the post-tool LLM completion before releasing it.
The 45.000471s timeout was DEV-001 repetition 2's first patient turn; its API
TTFB was 60.751802s and full processing 60.932204s, observed during cleanup.
No retry occurred; the cancelled follow-up remains unreported. TTFB does not
separate provider, network and client scheduling delays. No runtime fix here.

New offline-only expander: backend/evals/catalog_expander.py,
catalog-disjoint-v1, fixed seed 20261109, hash-ranked name pools and sequential
IDs. Original records/policies are retained as exact prefixes; synthetic copies
have their own provider/location/type relations with no bridges into originals.
Names avoid original catalog entities and known DEV patient/unknown-provider
names. They are fictional research-service distractors, not a clinical-realism
or near-neighbor benchmark. No synthetic availability is added, no catalog is
repaired, and no scenario/fixture/expected outcome or original blob pin is edited.
Derived catalogs get separate source/output manifests. Original eight orphan
types remain unbookable.

Measured with gpt-4o/o200k_base using the existing full readable baseline
renderer: x1 5,894; x5 29,333; x10 58,664; x20 121,030; x50 313,545 tokens.
At x22 catalog alone first exceeds 128K: 133,867 tokens. At x21 catalog has
127,455 tokens but the initial full request projects to 128,669 input tokens;
the selected saved-history shape plus 512 output reserve projects to 132,984.
At x20 that latter projection is 126,559, leaving only 1,441 tokens for longer
history. Full request sizes are explicitly projections, not expanded API usage.

Material input decision requested from the user, still pending: frozen proposed
JSON contains a literal id+name index of 82 services (1,026 tokens). A complete
expanded index has x5 5,792; x10 11,768; x20 24,320; x50 62,571 tokens. Keeping
the original index tests original-answer distractor isolation, not complete
growing-index coverage. Recommendation: regenerate only that data in experiment
copies, preserving every instruction/tool/model/guard and the original source
agent file. Candidate index data files are generated for review; no agent-config
copy or frozen prompt was changed. Do not infer authorization from the pending
choice or from elapsed time.

backend/evals/catalog_scaling.py measures offline and projects cost from prior
v5 logs for DEV-002/003/009/012, all three prior repetitions, with dated
2026-11-07 prices and observed cache shares. It labels every expanded cost and
full-request projection. Baseline x10+ projections are four conversations, one
per selected case: x10 about $2.76 cached-profile/$4.95 cold; x20 $5.58/$9.99.
x50 cannot fit GPT-4o; $14.26/$25.55 is an unlimited-context price extrapolation,
not a runnable estimate. No truncation or replacement model is proposed.

Whole proposed 6b plan is 24 conversations: x5 both arms, four cases × two;
x10/x50 proposed only, four cases × one each. With complete-index experiment
inputs, phase projections are $0.82 proposed x5, $2.85 baseline x5, $0.70
proposed x10, $3.14 proposed x50, total $7.51 using prior cache/call profiles.
Planning range $7.50–$9.50; same-call-count all-cold projection $13.08;
suggested total cap $15, no retries. Keeping the frozen 82-type index instead
projects to $3.59 with caching/$6.40 cold, with its narrower coverage caveat.
Both are projections, not measured charges or spend authorization. Await
explicit go/ceiling and index-input choice before any scaling API call.

Offline verification: 121 tests, 119 passed, two paid integrations skipped;
eight new expander tests passed. All original details/searches and all 12 DEV
fact-card core outcomes, slots and positive booking fields are unchanged at
x50; structural preservation does not guarantee LLM outcomes. An unscoped
request may legitimately return more facets and an invalid ID may return more
valid values; no constant-output claim is made for those paths. Measurement
also ran with AsyncCompletions.create mocked/asserted unused. No paid calls.
Evaluator v5 and frozen agent/core/scenario sources remain unchanged.
Findings: docs/scaling-v1.md. Data, manifests and complete offline report:
backend/logs/evals/scaling-catalog-disjoint-v1-seed20261109/.

## 2026-11-09: scaling index choice and revised offline pricing, no paid go

User selected regenerated index data in experiment copies, with ID + name +
specialty, fixed seed and unchanged instructions/tools/source agent. The frozen
source actually contains ID + name only (82 entries, 1,026 tokens), so the new
three-field format is explicitly disclosed as an experiment data change. At x1
it is 1,559 tokens. Primary variant is scaled-index-v2-id-name-specialty with
catalog-disjoint-v1 seed 20261109. Only data after the existing index marker is
replaced in derived agent JSONs; whole-config tests restore that data and prove
everything else unchanged. Existing AgentStore/AgentBuilder validation passes.
Manifests fingerprint source/copy/index/catalog/seed/scenario source. Source
agent, core, prompts, tools, evaluator and source scenarios are untouched.

Measured three-field index sizes with gpt-4o/o200k_base: x5 8,457; x10 17,098;
x20 34,980; x50 89,221. Full readable baseline sizes are unchanged. Prior
two-field index estimates ($7.51 cached-profile/$13.08 cold) are superseded.
New primary 24-conversation projection: proposed x5 $1.072537, baseline x5
$2.848151, proposed x10 $0.956298, proposed x50 $4.417788, total $9.294774.
All-cold, same-call-shape projection $16.127453. Suggested cap $18, no retries,
awaiting explicit approval. x50 proposed full request plus output reserve
projects to 94,823 tokens, within 128K, conditional on the saved history shape.

Secondary option priced separately: exact frozen 82-entry, two-field index,
16 additional proposed conversations (x5 x2, x10/x50 x1 across four cases).
Increment $0.737016 with prior cache behavior or $1.241069 all-cold. Combined
40 conversations project to $10.031790/$17.368522; suggested combined cap $20,
no retries. At about 8% extra it is offered explicitly, not silently added as
negligible. It tests original-answer isolation, not expanded service coverage,
and its narrower field format prevents calling it a pure index-length ablation.

Pricing verified against official GPT-4o docs on 2026-11-09, unchanged from the
2026-11-07 ledger: $2.50/M input, $1.25/M cached input, $10/M output. Installed
GPT-4o Chat Completions reports cache reads, not a separate write count; the
Pipecat adapter leaves generic cache-creation usage unpopulated. Official docs
specify no extra write charge for this model family. Report actual cached reads
from each paid call. Write tokens and separately attributed write-input cost
are null, not zero or prompt-minus-cached. Additional write fee is $0; cache
population is already included in ordinary uncached-input charges. No double
charge. New-scale usage remains null until authorized runs. Historical selected
v5 profiles have actual cached tokens 307,328 proposed and 738,048 baseline;
these are projection inputs, never new scaling measurements.

Focused x50 tests additionally replay the DEV-008 location correction through
offer/snapshot invalidation and refused stale booking, and keep DEV-004 blocked
without new service/provider answers. The all-12 fact-card test includes the
same original valid DEV-012 booking; eight original orphan types remain without
providers. Original scenario/fixture/expected bytes and catalog blob pin are
unchanged. These preserve expected answers, not predicted LLM pass rates.
make test: 125 tests, 123 passed, two paid integrations skipped. Offline
measurement also passes with model-create mocked/asserted unused. No paid
calls or changes to the frozen arm. Details/prices: docs/scaling-v2-pricing.md.

## 2026-11-10: revised 6b scope, conditional paid authorization

User replaced the three-field index experiment with exactly the frozen ID +
name format, dropped the frozen-82 secondary arm, and made indexed x50
projection-only. Paid plan is proposed indexed x5 and baseline x5, four DEV
cases x2 each; proposed indexed x10 x1; exploratory search-only x10 and x50 x1
each. Cases remain DEV-002/003/009/012. Total 28 conversations, no retries.
Original frozen agent, runtime, tools/guards and evaluator v5 remain unchanged.

Index variant scaled-index-v3-id-name-search-only; same catalog-disjoint-v1
seed 20261109. Indexed copies replace data only. Search-only removes the index
and replaces its single access instruction with free-text resolve_options
queries. Its experiment-only registry omits/rejects service/provider/location
IDs in resolve_options, forwarding queries and patient facts to the unchanged
shared handler. get_details, find_slots, book_appointment and mandatory dialogue
guards are unchanged. Search-only is explicitly exploratory, not proposed-v2.

Expanded catalogs are injected only within the experiment harness using a
scoped override of the v5 driver's catalog loader. The original scenario loader
still validates the original source blob independently. Patient behavior,
fixture universe, expected outcomes, scorer and evaluator hash do not change.
No hidden or other scenario file is used. Registry and injection checks are
offline, with the frozen config/source pin preserved.

Revised projection: proposed x5 $0.819562, baseline x5 $2.848151, proposed x10
$0.700488, exploratory search-only x10/x50 $0.168167 each; total $4.704535.
Search-only has no observed profile: estimate allows two extra calls per
conversation and does not credit the smaller tool schema. All-cold same-call
projection $8.306690. Indexed x50 remains $3.138741 cached-profile/$5.336442
cold, projection only, excluded from paid budget. Prices verified 2026-11-10:
GPT-4o $2.50/M uncached, $1.25/M cached, $10/M output, unchanged from the ledger.

User explicitly authorized proceeding if expected spend is below $6, with a
hard global cap $8 and no retries. $4.704535 satisfies that condition; estimate
was reported before execution. SpendGuard strict cold-request admission and
unknown-usage bounds apply globally across all five phases; SDK and timeout
retries are disabled. Unknown usage stays null. Paid results will be recorded
separately from projections. No original proposed-arm fix is authorized.

## 2026-11-10: revised 6b completed, no retries or agent changes

Experiment scaling-v3-20261110-092924-e2cde6 completed all 28 unique attempts,
201 admitted requests/JSONL usage rows. Actual GPT-4o cost $3.813240, below the
$8 global cap; no missing usage, retry, timeout or indexed x50 API run. Original
source/scenario/evaluator hashes match the pre-run values. Every usage row has
the matching saved agent id/revision and eval_fixture mode. No alternative
scenario source was inspected. Raw results are not rescored or edited.

Results: indexed x5 6/8, 60 calls, $0.689215; baseline x5 5/8, 56 calls,
$2.348205; indexed x10 3/4, 27 calls, $0.517805; exploratory search-only x10
3/4, 28 calls, $0.128555; search-only x50 3/4, 30 calls, $0.129460.
Baseline used fewer aggregate calls at x5 but had one fewer successful booking;
earlier failed paths contribute to that apparent call-count advantage. All
successful comparable paths used the same call counts. Search-only raw scores
match indexed x10 with lower cost on this small original-request subset, not
evidence of general accuracy equivalence or a change to the frozen arm.

Actual usage totals: 2,809,720 prompt, 2,615,168 cached reads, 194,552 uncached
prompt, 5,790 completion. Cached-read charges $3.268960; uncached-input charges
$0.486380 (including any cache population); output $0.057900. Additional cache
write fee $0. Separate write-token count and attributable write-input cost
remain null, not inferred. Actual cost below projection reflects both changed
call counts/early failures and cache behavior, not caching alone. All LLM
follow-up calls are included; voice/ElevenLabs cost is not measured here.

All eight failures manually reviewed without fixes: every phase fails DEV-002.
Five repetitions fail on the known unanswered-state loop after new-patient
status was supplied; indexed x10 instead asks for spelling without applying
the provider clarification; search-only x10 embeds Family Medicine in the
provider name query and shared resolution proposes original Dr. Maria Martinez
(ENT), as a tentative candidate. Driver exhaustion follows the two unexpected
provider questions; no counterfactual pass is claimed. These are seven
unnecessary-question/resolution failures. Baseline DEV-012/1 submits appt_064
(MRI - Spine) for the knee request, then tells the patient no matching slots
are available: one patient-facing false refusal. Its second repetition passes.
No wrong booking or invalid booking attempt was observed; 13 correct bookings.
Manual redundant-question count 12, with its logged/manual components disclosed.

Indexed x50 is projection only: complete ID + name index 62,571 tokens;
saved-history shape plus output reserve 68,173; four-conversation estimate
$3.138741 cached-profile/$5.336442 cold. Baseline x10+ remains projection-only,
with x21 projected full-request overflow and x22 catalog-only overflow.
Search-only's flat x10/x50 cost/context is limited to these four original
requests, disjoint distractors and unchanged closed-world fixtures. No new
synthetic-service queries or held-out accuracy/lookup-time claim is made.

Offline verification: 128 tests, 126 passed, two paid integrations skipped;
all five expanded request prefixes/tool schemas stable across two histories
each, with model-create mocked/asserted unused. Indexed copies match frozen
ID + name; search-only copies/registry changes are separately labeled. No
original proposed-agent/core, scenario, fixture, expected outcome, scorer or
patient-driver change. Details: docs/scaling-v3-results.md; exact raw/analysis
artifacts and per-phase JSONL paths are recorded there. docs/costs.md includes
this step as a separate dated addendum; its future-spend wording now matches
the already established AGENTS.md rule (estimate and explicit authorization
for any paid run). No further paid run is authorized by this completed go.

## 2026-11-10: submission draft and final-evaluation preparation only

User closed scaling: no more variants or scaling repeats. Search-only remains
exploratory, never a replacement for frozen proposed-v2. Call B cannot yet be
repeated and remains pending manual voice verification; independent text
preparation/approved execution need not wait for it. Call A remains
user-reported verified. No new paid run or unchanged test-suite rerun occurred.

Existing-evidence investigation is in docs/offline-investigation.md, with
saved transcript/tool/metric extracts in docs/results/. Proposed DEV-007/1,
call 9d271b7b-2881-44bc-9d6a-676548bfd27b, falsely said transfer was unavailable
without an explicit request after the explicit staff-confirmation request.
All three proposed handoff edge calls were rejected by handoff_requested's
regex; baseline made zero such calls. Both omitted the undocumented clinical
distinction, so a shared guard rejection is not the observed cause for both.
Unlogged pre-filter text is not reconstructed. Proposed consequences include
false patient statement and false refusal; baseline also has unnecessary
clarification/missing explanation, without an observed guard rejection.

The 23.909566s completed DEV-001/1 turn has 1.249545s plus 22.142099s in
LLM-service processing windows and 0.517922s residual. Post-tool TTFB is
20.901938s. The approximately 3.788ms inter-call gap is inferred from metric
log writes, not measured pure-tool latency. The installed 0.5s stop strategy
is a plausible contributor to the residual, not a measured allocation.
DEV-001/2 runner wait expired at 45.000471s; API TTFB/processing were
60.751802/60.932204s, overlapping that wait and observed during cleanup.
No exact tool/cleanup split, provider/network split, or missing follow-up
response is invented. Timeout is infrastructure failure; the slow completed
turn is a performance limitation with a correct booking. Proposed corrections
are separate and unimplemented, awaiting the user's decision.

External paths were absent from repository records (only filenames and full
hashes existed), so no directory was searched. User supplied Documents.
Exact byte-only SHA-256 verification passed for:
/Users/gabrielernoult/Documents/prosper_heldout_scenarios.json:
d41abdad3defe405a48becc55a97d4d153c3c3b27a4eff5f5518db8a2dedd1b6;
/Users/gabrielernoult/Documents/prosper_robustness_scenarios.json:
c5de085b51996c51afaa9dbc3b40c392452d0eec28760b422ced2a6f74aa6c19.
Neither was parsed, displayed, searched or copied. Recorded counts 16/8 were
not independently read/validated. No hidden-set or robustness result is used
for tuning. The new evals/final_preflight.py is stdlib metadata/hash/budget
preparation only, with no API/paid execution mode. It exits 2 intentionally
while execution compatibility remains blocked, even when file hashes match.

Material evaluator issue: current loader/driver/completion/scorer dispatch
are DEV-specific and comparison_matrix always runs DEV 12 x3. It cannot
honestly be presented as an external final-set command. Do not relabel hidden
IDs or silently skip explanation/correction/FAQ/ambiguity assertions. Proposed
smallest correction is an isolated external-contract adapter, reusing the
existing predicates and preserving original cases/expectations, with an
explicit outer version and identical dispatch for both arms. Validate contract
coverage and fixture clock before the first paid request within an approved
execution, fail on unsupported fields, and do not manually inspect cases to
tune. This evaluator/behavior decision is NOT implemented or authorized.
An existing compatible evaluator is another option. The metadata command is
ready; a valid final paid command is not, and no nonexistent CLI is claimed.

Final batch planned: held-out 16 x2 per frozen arm (64 conversations), plus
robustness 8 x1 proposed (8), total 72. Estimate from the 35 fully measured
proposed x1 conversations (whole incomplete-usage conversation excluded), and
all 36 baseline conversations: $0.995319 proposed held-out, $2.024924 baseline
held-out, $0.248830 robustness; total expected $3.269073. All-cold same-mean
usage plus 50% longer call shape gives planning allowance $8.646696, rounded
to $9; proposed global hard cap $10. These are projections with unknown case
mix/contract complexity, not measurements or a guarantee all cases complete.
One shared strict sequential guard must account for in-flight exposure and
reserve $0.32512 per unreported request; actual unknown costs stay null.
No automatic or selective retries. Prior scaling go does not authorize this.

Current and evaluated agent/core identities match: HEAD/tag a5b124f7...;
proposed JSON 40db1b58...; baseline compiled 68d02acb...; evaluator
dev-eval-v5-recovery behavior SHA 97117348...; original catalog blob
8e509108.... Full hashes, source fingerprints, versions/model/APPEND/fixture
mode, package versions and exact preparation commands are recorded in
docs/final-evaluation-plan.md and docs/results/final-evaluation-plan.json.
Builder identities were calculated without API sessions. Uncommitted evaluator
and baseline files mean a git tag alone does not reproduce all measurement
code; do not hide that provenance limitation. No frozen source was changed.

Draft solution.md now covers architecture/editor workflow, official x1
accuracy as inconclusive on a small DEV set, baseline wins, failure categories,
unnecessary questions, known/unknown cost, scaling versus projections,
exploratory search-only, cache dependence, total voice-cost limits, mocks,
voice-driven regressions and pending final/Call B verification. Existing key
reports/raw DEV logs are copied verbatim to docs/results/ with SHA provenance;
no external scenario content is copied. Small hours-guard limitation remains
explicit: slot-local clocks are compared without timezone normalization.
Final results and any behavior correction wait for separate explicit approval.

## 2026-11-10: isolated adapter v1, public validation, pinned schema stop

User authorized evaluation infrastructure only. Implemented external-eval-v1
in evals/external_contract.py, external_score.py, external_eval.py and
external_budget.py, with external_config.json and external_pin.json. No frozen
agent/baseline/runtime, booking/handoff guard, prompt, tool, original scenario,
legacy patient driver or legacy v5 scorer was changed. Known DEV-007 remains.
No paid calls/retries/matrix execution or additional scaling variant/run.

IDs are labels only. Public tests rename them and shuffle order without changing
driver replies/scoring. Explicit fact/expected/script fields select behavior;
no category/name/ordering/ID mapping. The agent gets only the opening and
appropriately requested scripted patient responses, catalog/fixtures and
unchanged tools. Gold expected outcomes and whole private fact cards are never
passed to its builder/context. Tests verify canaries and an instrumented fake
text session. A separate patient-side oracle checks earliest-slot consent;
it does not seed live agent state.

This changes semantics, not just input mapping: generic field-driven
disambiguation/correction, accurate identity/slot consent and explicit
assertions replace DEV-specific dispatch. Existing applicable recovery regexes
and bounds/general v5 predicates remain, but old v5 results are not relabeled.
Natural-language reply_rules, explanation, forbidden actions, notes and prose
contract grading/behavior requirements are required review, not interpreted or
silently dropped. Unknown structured fields/assertions or malformed inputs
fail visibly. Incomplete review/missing evidence cannot pass. Wrong booking,
internal selection, infrastructure failure and evaluation-limited exhaustion
are distinct; no-booking is not automatically a false refusal and an internal
ID mismatch is not automatically a patient-facing false statement.

Before private contents access: 27 targeted public/synthetic offline tests
passed; all 12 DEV scenarios compiled; 72 saved x1 attempts replayed with zero
model calls. Source fingerprints before/after checks match. All directly
comparable automatic assertions agree. Old 59 passes become review-required;
12 failures remain failed, one remains infrastructure failure. This is a
counterfactual evidence replay, not a new final score or matrix execution.
Missing evidence is not filled from gold; old ID-attached assertions not
automatically reproducible from explicit fields are listed for review.
Report: docs/results/external-offline-validation.json, including named tests,
source hashes and per-run disagreements/required reviews. No unchanged suite
was rerun merely to create a validation timestamp.

Pinned only after those checks: adapter pin SHA-256
dbd24883c42ad0c0188bb8b9cc5dab0aa30b133a62195465c94787cdebc7efaa;
configuration 31fa3c9d33b729d26a55bedee938c303fe0c0dc283f543cae51facb8660e591f;
offline evidence b44b41c039a6478ab3dc6ca691bb8e04379d9f6d58e98b75e0059b52c460d6e6.
The pin covers 29 files, dependency versions and compiled agent identities.
Proposed 40db1b58..., baseline 68d02acb..., legacy v5 behavior 97117348...
remain unchanged. No private contents informed implementation or validation.

Only then, ran the user-authorized automated schema preflight on the exact
external paths, verifying pin/hash before internal JSON parsing. It stopped
on heldout, field availability_fixture, code malformed_availability from the
existing scheduling-engine fixture validator. No case contents or failing
values were printed, inspected manually, copied, searched or used for tuning;
no case identity or precise underlying validity condition is guessed. Robustness
schema preflight was not reached. Both files' earlier byte-only SHA verification
remains separate. This is a structural input compatibility failure, not an
agent failure or score. Stopped: no fixture/expectation/adapter/arm patch after
the result. Metadata-only result: docs/results/external-preflight.json. Source
owner must resolve contract mismatch; final paid batch stays blocked.

Budget proposals unchanged, pending approval: expected $3.27, allowance $9,
global cap $10. New guard reserves full exposure before every API call, including
tool-result calls: 128000 input x $2.50/M + 512 output x $10/M = $0.32512.
This deliberately allows output beyond the 128K input allowance; combined
128K context with 512 output would give tighter $0.32384. It is a conditional
upper bound under recorded provider limits/prices, enforced max output, no
extra fees/retries and fully guarded admissions, not a measured charge or an
unconditional account-wide billing guarantee. Input limit relies on the provider
window; alias/price/fee changes can invalidate that premise. Known usage releases
the excess reserve; missing/cancelled requests retain it and actual cost null.
In-flight work and cleanup follow-ups stay guarded/billable. Limit-violating
usage stops admissions and marks the bound uncertified; undisclosed fees or
changed prices cannot be detected from token counts. Docs explain remaining
exposure and no guarantee all cases finish under cap.

Exact executable validation/pin/preflight/run-paid commands and unsupported
criteria: docs/external-adapter.md. The paid command requires an explicit
approval reference and all-set preflight, but flags do not grant authorization;
it is not run and currently cannot pass compatibility. Final-evaluation plan,
machine manifest and solution.md updated. Final results still pending. Voice
Call B remains pending manual verification independently of text preparation.

## 2026-11-10: fixture contract audit, substantive mismatch, no conversion

User authorized structural inspection and a boundary mapping only if unambiguous
and lossless. Read only the two exact recorded external files; source hashes
remain d41abdad3defe405a48becc55a97d4d153c3c3b27a4eff5f5518db8a2dedd1b6
and c5de085b51996c51afaa9dbc3b40c392452d0eec28760b422ced2a6f74aa6c19.
Printed no dialogue, expected outcome values or complete case. No paid call,
new matrix/scaling run, original scenario edit or evaluated behavior change.

Exact blocker is substantive capability consistency, not representation:
scenarios[1].availability_fixture[0].location_id,
scenarios[2].availability_fixture[0].location_id,
scenarios[7].availability_fixture[0].location_id and
scenarios[7].availability_fixture[1].location_id fail
appointment_type.required_capability in location.capabilities in the existing
SchedulingEngine._validate_slots. Referenced entities and provider relations
exist, but those locations lack the required service capability. Supplied slot
objects have exactly the expected six string fields; all 42 intervals across
the sets are timezone-aware and ordered. No private IDs or values are exposed.
Earlier generic documentation about duration validation was overbroad; duration
is not the failing gate, and this initializer's checks are references,
provider/type/site relations and capability.

No lossless boundary conversion can satisfy that predicate while preserving
the same provider, site, service and interval. Moving, replacing, dropping or
bypassing records would change data or frozen behavior. None was done. Source
owner must decide whether these are intended available slots or deliberately
invalid candidate records; correcting/refreezing data or changing that contract
requires separate authorization. No normalized evaluation input was produced;
conversion version and normalized-input hashes are null/not applicable.

Read-only audit fixture-compatibility-audit-v1 visits both complete datasets,
each complete fixture array and each scenario body independently. Diagnostic
code is docs/results/fixture_contract_audit.py, not an evaluator redesign or
converter. It verifies the unchanged v1 pin, source hashes, record counts and
label uniqueness, and records its own source SHA separately. Full metadata:
docs/results/fixture-compatibility-audit.json. No source contents are copied.

Held-out: 16 scenarios/31 records, 27 engine-valid records and four invalid
records across three cases; 13/16 complete fixture arrays initialize. V1
accepts 6/16 scenario bodies. First-error body counts: unsupported patient
facts four, unsupported assertions three, unsupported factual assertions one,
fixture errors two. Buckets overlap independent root causes: one capability
failure is behind an earlier unsupported field. Robustness: eight scenarios/
11 records, all fixture arrays initialize, but additional contract/scenario
metadata and grading fields are not admitted by v1; 0/8 complete bodies
accepted. Additional field names/types only are inventoried. This is structural
compatibility, not assertion grading or an agent pass rate. No criterion was
weakened or ignored and no partial final batch is proposed.

All 24 cases carry required prose review. Planned repetitions imply 72
transcript reviews, none completed; an illustrative 2–4 minutes each is
2.4–4.8 hours, not measured work or part of LLM cost. The consolidated report
separates automatic checks from script/explanation/factual/conduct/claim
review. Missing review cannot pass; unsupported structured criteria block
execution. New field handling/scenario-specific tuning is not implemented.

Historical external-eval-v1 pin remains
dbd24883c42ad0c0188bb8b9cc5dab0aa30b133a62195465c94787cdebc7efaa;
no evaluator/config/engine/agent source change was necessary or authorized to
repair substantive data. Current final plan, solution and evidence index are
updated, preserving the old first-error preflight artifact. Full consolidated
report and exact audit/preflight commands: docs/fixture-compatibility-report.md.
Proposals unchanged: $3.27 expected, $9 allowance, $10 cap, all unapproved and
uncertain under the changed patient driver. No new measured final cost exists.
Voice Call B remains pending and does not block independent offline work.


## 2026-11-10: source-authorized revised evaluation copies, external-eval-v1.1

User/source review: four capability-invalid held-out fixtures were deliberate
adversarial inputs; frozen engine rejects them at initialization. Chosen approach:
separate proposed conversational copies outside Git remove exactly the four
named records, retain all 16 held-out and eight robustness cases and all original
expected fields/booking identities/outcome labels. Original hashes unchanged.
Scope is explicitly reduced: no runtime ingestion test of invalid-capability
availability; **not lossless normalization**. Four records plus 4/4 initializer
rejections retained as separate offline evidence. RW-004 Saturday fixture unchanged.

Exact 29-edit manifest and original/revised/boundary hashes are in
`docs/results/revised-assets-manifest.json` and the private manifest it references.
Authorized clarifications: decline all substitutes where declared; accept honest
staff-directed next steps without callback/transfer invention; accurate location/
referral answer without mandatory spoken provider name; requested human help,
genuine technical errors and declared urgent escalation excepted from general
false-refusal rule; explicit earliest request for first-slot failure setup.
Source-edit script addresses authorized source labels; runtime never branches on IDs.

Adapter `external-eval-v1.1` is intentionally separate from historical DEV v5 and
external-v1. Changes include private requested/initial-site alias, brief option
selection before full consent, earliest consent after observed slot loss, bounded
patient replies before zero-booking early-stop, mandatory review for unimplemented
semantic/preference/correction requirements, and automatic actual-fault/stage
checks. No expectation is silently omitted or counted as a pass. Historical v1
executable/pin/evidence archived unchanged in `docs/results/archive/`.

Fault aliases mapped only at evaluation boundary (`times`→`attempts`, normalized
mode, explicit write stage). Session-local write interception runs after all
frozen engine guards, returns structured failure to the model and records triggers.
Offline protocol proofs: RW-002 two error writes after consent, RW-003/RW-008 one
slot-loss write each after consent, zero bookings, zero preparation/no-consent
triggers. These are not conversational recovery results. Every actual run must
exercise its declared fault or fail recovery assertions.

Evidence: 38 targeted DEV/synthetic tests pass, 12 DEV compile, 72 saved traces
replay (59 review-required, 12 failures, one infrastructure failure; no common
automatic disagreements). Both complete revised datasets initialize and compile:
16/16 with 27 slots; 8/8 with 11 slots. Every planned transcript needs semantic
review (40 total, estimated 2–3.3h). Frozen rubric external-review-v1.1 SHA-256
`054cbbd261440e29d0c7bdf6749bbff56ac38023f11cdf130d1efef31d08e686`; adapter pin
`529c0714f452d158d91fcde98237d0728fa17775e89ab3e7a84e5f34721259e5`. Source, configuration,
packages and rubric pinned before any paid execution. Arms/shared engine/tools/
guards/prompts and legacy evaluator unchanged; DEV-007 defect remains documented.

Paid proposal replaces the older 72-conversation plan: held-out 32 conversations
(one/case/arm), expected proxy $1.51, allowance $4.50, cap $5; separate robustness
eight proposed-only, expected $0.25, allowance $1.50, cap $2. Total expected $1.76,
allowance $6, caps $7. Based only on complete existing x1 usage, excluding the
entire incomplete-usage attempt; revised-driver/recovery/cache uncertainty remains.
$0.32512 is conditional full-request exposure (128000 uncached input at $2.50/M
plus 512 output at $10/M), not measured missing spend. Unknown/in-flight usage
retains reserve. No paid authorization, calls, retries or matrix execution.
Call B remains pending manual verification; neither final text score nor voice
verification is claimed. Details: `docs/revised-evaluation-preflight.md`.


## 2026-11-10: approved final batches interrupted by report serialization

User explicitly approved revised held-out 16 cases x two arms once, $5 cap,
and separate proposed-only robustness eight cases once, $2 cap, no retries.
Before spend verified exact v1.1 pin `529c0714f452d158d91fcde98237d0728fa17775e89ab3e7a84e5f34721259e5`,
rubric/source/config/package hashes, revised/original assets, catalog/git and
both rebuilt arm revisions. Identity receipt: docs/results/final-execution-identity-check.json.

Ran each batch command once, without changing any pinned file or repinning.
Held-out run `external-v1.1-heldout-20261110-153532-72eb74` stopped after proposed HO-001;
robustness `external-v1.1-robustness-20261110-153646-ed8563` stopped after RW-001. Both command exits 1.
Cause: checkpoint `json.dumps(report, default=list)` cannot serialize the
`datetime` in asdict(SessionState), such as last_horizon_end after find_slots.
Exception precedes write_text, losing the in-memory result/transcript/tool traces
and leaving the pre-attempt journal. This report-writing path was missed by the
offline tests. It is infrastructure failure, not agent failure. No patch or
reproduction was made. Remaining 38 planned conversations, including all baseline,
never ran. No live fault-recovery cases were reached.

Surviving usage: nine model rows per batch, all with prompt/cached/output counts;
held-out 29,747/24,064/241 tokens, $0.0466975; robustness
30,281/26,368/289, $0.0456325. Combined $0.0923300 known at pinned dated prices.
This is not certified complete billing: terminal guarded request counts/reserve
balances were lost. Observed missing-usage rows zero; unlogged request count,
final charge and final reserve unknown. Raw journal zero-cost snapshots are stale
and must not be reported as actual spend. No cap-stop error appears in either
console. Documented $0.32512 reserve and $5/$2 cap assumptions remain unchanged.
Per-model-call p50/p95: held-out 1.061/1.519s, robustness 1.141/1.909s.
Patient-turn/tool/wait timings and automatic outcomes unavailable. Wrong booking,
false refusal, incorrect internal selection and spoken falsehood counts are
unassessable, not assumed zero. Zero final semantic passes assigned, no score.

Surviving journals, metrics and console tracebacks copied verbatim with hashes to
docs/results/final-evaluation/. Full report docs/final-evaluation-execution.md,
40-row expected-outcome/review-check inventory, explicit missing transcript/tool
manifest and private automatically exported review packet outside Git. No expected
outcomes or rubric weakened, no missing trace reconstructed. Original/revised
scenario contents, agents/runtime/tools/guards/scorer and Call B status unchanged.
Potential evaluator-only datetime serialization/durable-trace repair documented
but **not implemented**; any future execution needs a new decision/authorization.
Voice Call B remains pending manual verification.


## 2026-11-10: serialization/durable-evidence repair, no paid restart

User authorized an infrastructure-only fix/offline check, timebox 45min; no changes
to agents, scenarios, patient behavior or scoring. Exact failure: old external_eval
checkpoint line 298 used json.dumps(default=list), which tried list() on aware
SessionState.last_horizon_end from asdict after slot search. Chosen fix: explicit
ISO datetime/date serialization preserving offset, sorted sets, reject naive
clocks/unknown objects (no catch-all string conversion); serialize-before-write,
fsynced temp file and atomic report replacement.

Reuse existing metrics observer unchanged and the voice tool-wrapper pattern.
Add independent append/fsync events for patient/actual assistant messages, context,
tool start/args/result/errors, turn status, snapshots and conversation results.
SDK write-ahead admission/reserve before HTTP, partial raw model/tool chunks,
usage/status/provider ID, exception/cancellation/close and terminal budgets are
durable independently of report export. Raw model drafts are separate from actual
code-generated output. Each conversation also has its own atomic result file
before aggregate export. Evidence failure is sticky/fail-closed; no further paid
request when its evidence cannot be written. Existing $0.32512 arithmetic/unknown
reserves and no-retry settings unchanged. Checkpoint usage requires SDK-admission/
usage reconciliation, not merely populated metric rows.

Version: external-infra-v1.2; evaluator semantics external-eval-v1.1 unchanged.
Pin `032f9418860c650afbe3771ca947f7afc15b82cc5cda5ebdae1b5fbaf04375c8`, rubric unchanged
`054cbbd261440e29d0c7bdf6749bbff56ac38023f11cdf130d1efef31d08e686`. Old v1.1 source/pin archived with provenance.
All 33 historical pinned files except external_eval entrypoint unchanged, including
patient/scorer/model/runtime/faults/agents/catalog. Original/revised/normalized
scenario hashes unchanged. New plan addresses labels only, not behavioral dispatch.

Evidence: 49 offline tests pass (11 new), zero model/API calls. Real shared-handler
booking generates actual nested dated state; reproduces old failure, exercises
successful checkpoints/final export and deliberate final-export OSError while
messages/tools/metrics/SDK ledger/budget/per-conversation files survive. Cancellation
retains partial delta/full reserve; missing cache stays null despite legacy row;
unknown object/naive timezone fail visibly; insufficient cap or evidence failure
prevents HTTP. Saved 72-trace replay unchanged; no new accuracy result. Details:
docs/results/external-infra-v1.2-validation.json and docs/external-infrastructure-v1.2.md.

Restart plan hash `bf9674be6c7c71db9b6465332da22e123592578128381f081e98854ad6f1a8f7`: first two replacements for the
recorded infrastructure failures, with original run/call links and outcomes unknown,
then every 38 not-run conversation, once. No result-dependent reruns. Same original
coverage 32 held-out + eight robustness. A single future command routes independent
$5/$2 proposed fresh caps so ledgers persist while dataset order alternates.
Prepared/validated, **not authorized or executed**. No new spend during this fix.

Historical known subtotal $0.0923300 retained. Complete request count/billing cannot
be inferred from the 18 populated rows. Under old guard/pricing/provider assumptions,
old total lies within known subtotal–$7, unobserved-charge bound $6.9076700; these
are bounds, not pending-charge estimates. No certified unspent balance. Proposed
restart expected incremental $1.76 (known old subtotal + estimate ≈$1.85), allowances
$4.50/$1.50 and fresh incremental caps $5/$2 await explicit approval. Fresh caps
would add exposure rather than silently reuse unverifiable old balances; lifetime
caps require historical billing reconciliation. Voice Call B remains pending.


## 2026-11-10: approved v1.2 restart completed, no behavior/scoring changes

User explicitly authorized fresh, additional $5 held-out/$2 robustness caps;
old attempts/billing uncertainty remain separate. Verified exact pin
`032f9418860c650afbe3771ca947f7afc15b82cc5cda5ebdae1b5fbaf04375c8`, plan/rubric/dataset/package/agent/catalog/git identities,
and no existing evaluator before starting. Ran `external-infra-v1.2-restart-20261110-175004-ec9627` once, exit 0,
40 unique jobs: linked proposed HO-001 and RW-001 replacements first, then all 38
previously unrun. Continued ordinary automatic failures; no retry, new experiment,
source edit, scenario/expectation/patient/scorer change or cap stop.

Fresh model cost $1.4072150: held-out proposed $0.3566525, baseline $0.6712800
(total $1.0279325); robustness proposed $0.3792825. Ledger reconciliation:
211 reservations=211 complete SDK usage=211 closed requests=211 metrics, no
unresolved IDs, exceptions, missing usage or retained exposure. Old known
$0.0923300 remains with lost request coverage; combined known $1.4995450 and old
conditional extra-unobserved bound $6.9076700, never guessed as zero. Cache counts:
962,610 prompt, 848,768 cached, 113,842 uncached, 6,165 output; dated rates unchanged.

Raw status 24 review-required/16 failed. Held-out automatic sets all true 9/16
proposed vs 8/16 baseline; failures 7/8 respectively, all 15 marked driver-limited/
not_assessable. Robustness seven all true/one booking-count failure. These are
not semantic pass rates. Baseline used fewer held-out model calls 62 vs76;
proposed lower cost. Completed patient turn p50/p95: P2.470/3.460s,
B2.621/4.160s, robustness2.384/3.187s; zero incomplete turns or infra/runner errors.
All mandatory semantic review remains pending, same rubric both arms.

Live write faults RW-002/003/008 all triggered once after consent and exposed
structured results. No recovery semantic pass assigned yet. RW-005 automatically
flags wrong_booking (one vs expected zero), but actual patient messages request
booking and explicitly consent; no human request was delivered. Record this
as a driver-fidelity discrepancy needing review, not a confirmed agent wrong
booking or counterfactual pass. Preserve raw failure. Six internal-selection
flags (three/arm) are not automatically spoken falsehoods; false-refusal/false-
statement counts pending review. No tuning/fix/rerun followed these observations.

Full measured report docs/final-evaluation-restart-v1.2.md; 40-row review table,
automatic inventory, usage/latency summary/provenance and failure inventory in
docs/results/final-restart-v1.2/. Complete actual patient/assistant and tool
args/results exports under backend/logs/evals/external-infra-v1.2-restart-20261110-175004-ec9627.exports/;
raw event journal, per-conversation files and metrics preserved. Logging/export
worked; no missing traces reconstructed. Handoff/status/solution updated.
Voice Call B remains pending manual verification. All approved jobs consumed;
no unused allowance authorizes more calls. Next is semantic review/submission.

## 2026-11-12: semantic review sheet prepared, criteria read post-freeze, no changes

With explicit user authorization, the private criteria packet
`../Evals/final-evaluation-review-v1.1/review-packet.md` was read on 2026-11-12,
AFTER the frozen final restart completed, solely to prepare the manual semantic
review. Nothing else outside the repository was opened. Because both arms, the
scenarios, the patient driver and the scorer were already frozen and all 40
approved conversations had run, this read cannot have influenced any evaluated
behavior; the freeze rules continue to forbid any agent, scenario, driver or
scoring change arising from this review. No paid call was made and no
evaluation was started or resumed.

Output: one proposed-label row per conversation (40 rows), each with the
expected outcome, the automatic result, the forbidden actions checked, the
decisive transcript/tool evidence and a one-line reason. All automatic scores
are untouched; the review is a separate column and every label awaits the
user's validation. Labels: pass / confirmed agent failure / evaluator-or-driver
limitation / not assessable. Full sheet with criteria text, outside Git:
`../Evals/final-evaluation-review-v1.1/semantic-review-full.md`. Index-only
repo copy without criteria text: docs/semantic-review.md.

Proposed counts, pending validation: 7 pass (P 2 / B 4 / R 1), 19 confirmed
agent failures (P 6 / B 7 / R 6), 14 evaluator-or-driver limitations
(P 8 / B 5 / R 1), 0 not assessable. The 15 auto driver-limited held-out runs
split 10 driver / 5 agent: a stall counts as an agent failure when the blocking
question was itself wrong or unanswerable. Recurring defects: silent deviation
(a changed time/day, a lost slot or a failed write is never told to the
patient: RW-001/002/003/004/008); the dialogue guard asking a question instead
of explaining a block already present in the same tool result (HO-005 P,
HO-004/005 B, HO-012 both, HO-010 both via the hard-constraint widening
question); a guard question swallowing the patient's own question (RW-006
AI-disclosure dodge); stated facts re-asked or recorded wrongly (HO-009 B loop;
HO-016 P recorded a promised referral as on file, bypassing the gate in state).
RW-005 is proposed as a driver-fidelity limitation: the scripted human-handoff
demand was never delivered and the recorded patient explicitly consented; the
raw wrong-booking flag remains recorded and unpromoted. All injected faults
verifiably fired; the weakness is disclosure, not recovery mechanics. These are
proposed judgments only; final semantic pass rates remain pending user
validation.

## 2026-11-12: voice call B stuck-choice fix after final evaluation (no paid calls)

Observed in logs/voice-tools.jsonl and logs/turns.jsonl, call 35e9b8b2 (today
10:08-10:10): find_slots returned two slots at 10:09:40 with next_action
ask_patient_to_choose; the spoken offer was the stored options line without
service or provider context. After the patient's barge-in ("Sorry. W-"),
turns 19-23 made five model calls with zero tool calls, and each reply was the
guard's canned line "Your details are confirmed. I'll check the available
appointments." Root causes, all in code, none in the model: (1) the options
text in scheduling_agent.find_slots listed only dates and sites; (2) the
pending slot choice lived only in the one-shot dialogue `pending` field, which
is cleared on every patient turn, and next_step() had no slot-choice stage, so
any tool-free turn after the offer fell to stage "offer", where BookingSpeech
replaced the model's text with that canned line — falsely implying an identity
step had just finished and claiming a check that never ran; (3)
avoid_repeated_question returned early for text without "?", so the repeated
statement was never caught. The same canned line explains the misleading
replies observed in RW-002/RW-003 of the final run.

Fixes, explicitly requested by the user and applied to the shared dialogue
code used by both arms: slot offers are rendered by a new
SchedulingDialogue.offer_options with one context sentence (service, provider,
site; per-slot only when they differ) ending "Which works for you?"; the
offered choice is durable dialogue state surfaced by a new next_step stage
"slot_choice", gated on engine offered_slot_ids so constraint changes retire
it; during a pending choice a tool-free model reply is spoken first and the
contextual choice is repeated after it; the canned line is removed — a
tool-free "offer"-stage turn now asks "Would you like me to search for
available appointments now?" instead of claiming a check; and the repeat
limiter records statements as well as questions, with a slot_choice
escalation that keeps the times. booking_gate admits the new stage so a
choice remains directly bookable.

Regression test tests/test_choice_interruption_recovery.py replays the exact
sequence offline: contextual offer, barge-in "Sorry. W-", "What are you
referring to?", "Are these appointments?", then booking the kept choice; it
asserts no "Your details are confirmed", no check-claims without a tool call,
stable offered slots and identity, and loop-breaking on repeated statements
and blank turns. One wording assertion in test_scheduling_dialogue was
updated for the contextual offer. Full offline suite: 181 tests, 179 passed,
2 paid skipped. No scenario, scorer, patient-driver or evaluated-result
change; the completed final-run results remain tied to their pinned
revisions. These edits make the current working tree diverge from the
external-infra-v1.2 pin, as any post-freeze fix must: a future evaluation
would need a new version and pin, never a repin. Voice call B still needs the
user's live retest; no paid or voice call was made here.

## 2026-11-12: single slot presentation per turn (voice retest follow-up)

Observed in the user's voice retest after the stuck-choice fix: on "Sorry,
what did you say?" the agent spoke the model's own single-slot re-offer
("I have Monday, November 16th at 8:00 AM available... Would you like to book
this?") and then the code-appended two-slot choice - two contradicting offers
in one turn. Cause: the slot_choice append branch added the canonical choice
to any non-empty model reply, including one that was itself a slot offer.

Fixes in scheduling_dialogue.py, shared by both arms: an explicit repeat
request ("what did you say", "say that again", "can/could you repeat",
"repeat that", "come again", "pardon", bare "sorry") is detected per patient
turn and gets the pending choice once, verbatim, nothing else; it also
bypasses the repeated-question limiter, since a requested repeat is never a
loop. During a pending choice, a model reply that already names an offered
slot (month+day plus its time, matched against engine offered_slot_ids) is
spoken alone - never two slot presentations in one turn; a reply without
slots is spoken first with the choice appended once, as before. One persona
sentence was added to agents/catalog_scheduler.json telling the model to
answer side questions briefly during a pending choice and never list or
re-offer slots itself, because the system repeats the choice; this changes
the saved agent revision, which the session logs record per call.

Regression cases added to tests/test_choice_interruption_recovery.py: a
repeat request with a model self-offer yields exactly the canonical choice;
a second repeat request still yields it rather than a bail-out; a side answer
mentioning an offered slot is not doubled; a side answer without slots gets
exactly one appended choice. Full offline suite: 183 tests, 181 passed, 2
paid skipped. No paid calls, no scenario/scorer/driver change, nothing
committed; the working tree continues to diverge from the external-infra-v1.2
pin as documented in the previous entry.

## 2026-11-12: repeat-request detection narrowed to the whole utterance

User flagged a false-positive risk before retesting: repeat_requested matched
"sorry"/"pardon" etc. anywhere via re.search over most phrases (only the bare
"sorry" case was already a fullmatch), the same class of bug as matching
"ENT" inside "patient". "Sorry, the first one" or "Sorry, can we do Richmond
instead?" would not have been misdetected under the exact prior patterns
tested, but the rule itself search-matched a phrase anywhere in the utterance
rather than requiring the utterance to BE a repeat request, so it was not a
safe general rule.

Fix: REPEAT_REQUEST_RE in scheduling_dialogue.py now requires a fullmatch -
an optional leading "sorry" plus exactly one recognized repeat phrase (what
did you say / can or could you repeat or say that again / repeat, optionally
with "please" / come again / pardon, optionally "me" / bare sorry), with only
trailing punctuation after. patient() now sets repeat_requested from this
fullmatch instead of the previous search-based check.

Verified directly against the regex and end to end with the real engine:
"Sorry, what did you say?", "Can you repeat that?", "Sorry?", "Pardon?",
"Pardon me?", "Come again?", "Repeat please", "Can you repeat?", "Could you
say that again?", "Say that again please." all match (true positives).
"Sorry, the first one" selects the first offered slot and proceeds to
needs_confirmation; "Sorry, I meant the second one" selects the second;
"Sorry, can we do Richmond instead?" changes state.location_id to loc_007
and clears the stale Midtown offered_slot_ids (a real change, not a silent
repeat) - none of these three set repeat_requested. "I beg your pardon, I
will take the first one" and "No, sorry, book the second slot" also do not
match.

Four regression cases added to tests/test_choice_interruption_recovery.py:
first-one and second-one selection proceed to a correct readback and are
not treated as repeats; the Richmond case is confirmed as a real location
change; and a direct true/false table exercises REPEAT_REQUEST_RE against
both the known repeat phrasings and the three reported false-positive risks
plus two extra interjection cases. Full offline suite: 187 tests, 185
passed, 2 paid skipped. No paid calls, no scenario/scorer/driver change,
nothing committed.

## 2026-11-12: semantic review finalized with adjudicated labels

User adjudicated the proposed semantic-review labels. Method, as stated by
the author: labels were proposed by two LLM reviewers, with disagreements
adjudicated by the author; the two reviewers agreed on 37 of the 40 cases
before adjudication. The author personally re-checked the 7 passing cases
and the proposed HO-016 (proposed) case against the full transcripts. Each
conversation ran once; these remain single-trial observations.

Three adjudication decisions, applied to docs/semantic-review.md (index-only)
and left unapplied to the private full sheet, which the user did not ask to
update:

- HO-003, both arms: reclassified driver limitation -> confirmed agent
  failure. The patient had pre-accepted the Mission District alternative in
  the opening message, so no further scripted reply was needed; the agent
  explained the capability gate correctly but then closed with a phone
  referral instead of proceeding with the already-accepted site.
- HO-004 (proposed): kept as driver limitation, recorded as a judgment call
  against the considered alternative "not assessable."
- HO-009 (proposed): kept as pass, with the repeated "confirm new patient"
  question kept as a caveat note, not a disqualifying defect.

Recomputed and verified programmatically against the updated table rows
(not by hand): held-out proposed pass/agent/driver 2/7/7, baseline 4/8/4,
robustness 1/6/1 (not assessable: 0 throughout). Total 7 pass, 21 confirmed
agent failures, 12 evaluator-or-driver limitations, 0 not assessable, across
40. The "Notes" section's breakdown of the 15 harness-auto-flagged
driver-limited runs was also corrected: it previously cited the wrong case
IDs for the agent-labeled subset (naming HO-005/HO-004, which were never in
that auto-flagged pool); it now correctly lists HO-002/003/007/008/010/011/013
across both arms plus HO-009 (baseline only), split 8 driver / 7 agent after
the HO-003 reclassification.

No automatic score, scenario, driver or scorer changed. No paid calls were
made; nothing was committed.

## 2026-11-12: v2.1 working-tree smoke and agent revision

User approved one usual four-case smoke on the current working tree (called
v2.1: the post-freeze dialogue fixes logged on 2026-11-12 above), maximum
$0.50, no retries. Run smoke-20261112-164821-2fe6d5 passed 4/4 with 42 model
calls and fully reported usage, total $0.2417925 (spend-guard accounting equals
the JSONL usage; no request was refused, no retry). Per case: DEV-012 PASS,
9 calls, $0.0477275; DEV-002 PASS, 13 calls, $0.0752075; DEV-008 PASS, 9 calls,
$0.0483475; DEV-009 PASS, 11 calls, $0.0705100. Previous run of the same four
cases on v2 (smoke-20261109-131238-90cbfb): 4/4, 40 calls, $0.22736500. Of the
four, only DEV-009 (three matching fixture slots) exercises the rewritten
multi-slot offer; the scripted text driver never interrupts, so the
interruption/repeat-request fixes are not exercised by this smoke.

Agent revisions (SHA-256 of backend/agents/catalog_scheduler.json bytes, the
same value the session logs record as agent_revision):
- v2, pinned for all final measurements (tag proposed-v2, commit a5b124f):
  40db1b587b5790ab2c92bc642edbc55e67f0d44ebd8d4f1267de29e1e86ebdc5
- v2.1, current working tree: 478567bcb1ad1f80851489bb7b45d8d45eab90ff96cd10340d6880eff9e159ae
The v2.1 JSON differs only by the persona sentence added on 2026-11-12; the
shared dialogue code (scheduling_dialogue.py, scheduling_agent.py) also
changed and is not covered by this JSON hash.

Scope statement: the final held-out, robustness, x1 DEV comparison and scaling
results were all measured on v2 under their pinned revisions. The v2.1 dialogue
fixes (durable slot choice, contextual multi-slot offer, removal of the
"I'll check" canned line, repeat-request handling, statement-aware loop
breaker, single slot presentation per turn) were verified only by offline
tests, this four-case smoke and the user's manual voice calls. They were not
verified by a full matrix, and no final result may be attributed to v2.1.
No paid call beyond this smoke; nothing committed.

## 2026-11-12: active time update

Total active time: 9h51 as of 2026-11-12 (author's timer), to be updated before
submission; agent compute time not counted. The challenge brief suggests 8 to
12 hours (author's reading of the brief). This supersedes the "4h44 so far"
figure in the Time spent section above, which covered work through November 8.
