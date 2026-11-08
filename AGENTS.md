# AGENTS.md: Prosper AI challenge (context management)

Read this first. It is the working context for any coding agent in this repo. Technical only, safe to commit.

## 1. The task

Brief: Prosper builds voice AI for healthcare phone calls. Challenge has two phases, budget about 16 hours total.

- Phase 1: a UI to create and edit voice agents (graph of nodes and edges) and place a test call.
- Phase 2 (the heart of it): a context-management approach so a scheduling agent reliably and cheaply navigates a large catalog of locations, doctors and appointment types under booking policies.

The agent must: create appointments, offer slots, match the request to the right appointment type, location and provider (disambiguating similar options, honoring provider, location and soonest preferences), and answer questions about locations, doctors and appointment types.

Judged on: originality and rigor of the context approach (cost AND accuracy), system design and scalability, explicit trade-offs, pragmatic scoping (what NOT to build is a signal), a live end-to-end demo.

Deliverables: this repo + `solution.md` at the root (overview and key decisions, with measured results).

## 2. What exists in the starter (observed)

- Stack: Pipecat (pipecat-ai >=1.4,<2), Pipecat Flows (>=1.3,<2). Browser mic -> ElevenLabs STT -> OpenAI LLM -> ElevenLabs TTS. Python 3.11+. `make install`, `make run`, open http://localhost:7860/client (prebuilt Pipecat test-call client, no frontend needed for the call itself).
- `backend/bot.py`: pipeline. Loads `AGENT_FLOW` (hardcoded path to `example_flow.json`) through `AgentBuilder`. `PipelineParams(enable_metrics=True, enable_usage_metrics=True)` is already on (verify what usage data actually surfaces).
- `backend/agent_builder/schema.py`: `AgentConfig` (name, initial_node, nodes, persona, voice_id, model default gpt-4o), `Node` (name, task_messages, role_message, edges, pre_actions, post_actions, end), `Edge` (function, description, target, properties, required).
- `backend/agent_builder/builder.py`: validates, then compiles lazily node by node. The ONLY functions a node exposes are its edges. An edge handler does `flow_manager.state.update(args)` and returns `({"status": "success", **args}, next_node)`. So today every tool call is a transition.
- `backend/example_flow.json`: 4-node toy scheduler with hardcoded slots (Tuesday 10 AM, Thursday 2 PM). A sample of the format, not the target agent.
- No persistence, no editing API, no availability data, no tests, no eval harness.

Consequences to design for:
1. Data lookup tools that stay in the same node do not exist. The schema and builder must be extended with non-transition node functions (handler returns a result and no next node), referenced by name in JSON and mapped to Python handlers in a registry.
2. Per-node context strategy (append / reset / reset with summary) is not exposed. Check what Flows 1.3+ supports before promising resets.
3. `bot.py` hardcodes one agent. Phase 1 needs agent selection and save/load.

## 3. The catalog (measured, `backend/data/catalog.json`)

Size: 45,661 chars, roughly 11-14K tokens (estimate; measure with the real tokenizer). 8 locations, 50 providers, 82 appointment types, 6 policy sentences. No availability data: mock it.

Rules (also in `policies`): provider only at their `location_ids`; provider only for their `appointment_type_ids`; types with `required_capability` only at locations having it; `requires_referral` needs a referral on file; new patients only for `new_patients_allowed` types and providers with `accepting_new_patients`; a provider with several locations needs the location disambiguated before booking.

Facts that shape the design:
- Referential integrity is clean: no dangling location or appointment type ids, every provider has locations and types.
- 34 of 50 providers practice at multiple locations. Location is almost always an open question when a provider is named.
- 31 provider x gated-type pairs where some of the provider's sites lack the required capability (the capability gate really bites). No pair is unbookable everywhere.
- 8 appointment types have NO provider (appt_045, 046, 047, 048, 049, 070, 071, 077). They exist in the catalog but are not bookable. The agent must say so, not invent a provider.
- Duplicate provider full names: Maria Garcia (prov_002, prov_003), Linda Ramirez (prov_005, prov_014), Michael Sato (prov_026, prov_032). Surname collisions: Nguyen 8, Chen 7, Sato 6, Patel 5. A name is never a key.
- Provider specialty does not constrain bookable types (215 provider-type pairs cross specialties). Use `appointment_type_ids`, never infer from specialty.
- 36 types require a referral, 31 do not allow new patients, 11 providers are not accepting new patients. Some types (e.g. Follow-up Visit) are existing-patient only.
- Near-duplicate types: New Patient Consultation vs New Patient Visit; Annual Physical (Family Medicine) vs Annual Wellness Visit (Internal Medicine); Physical Therapy Evaluation vs Session; MRI Brain/Spine/Knee family; Skin Cancer Screening vs Full Body Skin Exam.
- Lexical fuzzy matching is a trap: "Neurology Consultation" vs "Urology Consultation" scores 0.95 string similarity, and it is also a likely speech-to-text confusion, as are Colonoscopy/Endoscopy. Resolution must preserve ambiguity and confirm, not pick the top fuzzy hit.
- Important honesty point: the full catalog is only about 13K tokens, which is cheap, especially cached. The cost story at this size is weak on its own. The scalability claim must be shown with a synthetic expansion test (x10, x50) and the accuracy claim with close-option scenarios. Do not claim savings before measuring, and report if the baseline is competitive.

## 4. Architecture (design v0.2, see docs/design.md)

Principle: the LLM interprets and converses; code resolves identities, evaluates policy, searches slots, decides what is bookable. Structured session state, not the transcript, is the source of truth.

Session state: patient_facts (name, dob, is_new_patient, has_referral; each yes/no/not_asked), constraints (hard, e.g. "only Dr X"), preferences (soft), resolved ids (appointment_type, provider, location, each nullable), last candidates + count of the rest, selected_slot, confirmation snapshot. Invalidate dependents only: type change -> provider/location if incompatible, slot, confirmation; location -> provider if not there, slot, confirmation; provider -> slot, confirmation; slot -> confirmation. Never re-ask known facts.

Tools (extend the builder; keep coarse to save LLM round trips):
- `resolve_options(updates?)`: apply updates with invalidation, search from any entry point (service, doctor, site, availability), join relations, evaluate known policies in one backend pass. Returns candidates (presentation limit N, plus `more_available` count), distinguishing facts, facets to narrow, missing facts, blocked options with reasons.
- `get_details(entity, id)`: authoritative info for factual questions.
- `find_slots(horizon_days)`: search ALL compatible combinations in the horizon, rank by preferences, then truncate. Report the horizon and whether anything was relaxed (never silently).
- `book_appointment(slot_id)`: revalidate against current state and confirmation, idempotent, structured errors.
Open: separate `update_request` vs updates inside `resolve_options`.

Rules: no forced specialty-first path; a caller can enter by doctor or site. Explicit constraints are never relaxed without asking. Unknown means a required fact is missing; an optional missing field does not block. Aliases keep provenance, ambiguous alias maps to several candidates. Handoff is simulated, say so.

Context hypotheses to measure, not assume: compact appointment type list in a cached prefix (82 names is about 1K tokens) vs tools only; append vs reset-with-summary between nodes. Providers and locations are resolved by tools, not pasted.

Core logic lives in plain Python (state, catalog loader, resolution, policy, slots, booking) with no Pipecat imports, so the voice agent (Flows handlers) and the text eval runner call the same code.

## 5. Evaluation

- Unit tests: resolution, policies, slot search, invalidation, booking guard, direct invalid tool calls, duplicate bookings.
- Text runner: same agent logic, no STT/TTS. 24 scenarios, 8 dev and 16 held-out; freeze held-out and expected outcomes before the final run; never add aliases or rules from held-out.
- Coverage: straightforward; lay paraphrase; similar types needing clarification; referral with/without; new-patient restriction; capability-gated; multi-location provider; duplicate provider name; unbookable type (no provider); preference vs soonest; correction after a slot was proposed; factual question; no eligible option; out of catalog.
- Expected outcome per scenario: book (acceptable ids), clarify (topic), refuse (reason) or answer (required facts), plus forbidden actions. Patient is scripted (fact card, conditional replies, 2-3 phrasings, closed-label mapper logged). LLM simulator optional.
- Arms: (A) baseline, full catalog and policies in context, same model, same find_slots/book tools, same final guard, caching allowed; (B) proposed. This compares whole architectures, not components.
- Metrics: recall of acceptable option, outcome correctness, false refusals, preference adherence, invalid booking attempts vs invalid bookings created (separate), confidently wrong (any wrong selection or claim stated as certain, booking or not; separate from accuracy), turns/model calls/tool calls, tokens and cached tokens, cost per attempted scenario and per successful booking (failures included, dated prices, LLM separate from STT/TTS), latency (LLM, tools, end of speech to first audio on a few live calls). Check spoken-answer facts and review a sample of transcripts by hand; state what is manual.
- Volume: dev iterations run 8 dev scenarios once; final 16 x 2 arms x 3 runs = 96 conversations, adjusted after measuring cost.
- Synthetic expansion test: add unrelated records, check resolution time and returned context stay flat. Behavior test, not accuracy proof.
- Log one JSONL line per turn: call id, node, model, prompt/cached/completion tokens, latency, tool calls, tool latency. Missing usage is unknown, never zero.

## 6. Plan and gates (16h, one hour is contingency)

1. Run starter, browser call, text runner, usage logging (2h). GATE h2: browser call works.
2. Design v1 from findings (0.5h).
3. Loader, state, resolution, policies, slots, booking + unit tests (4h).
4. Scheduling flow through the text runner (2h). GATE h8.5: resolution and booking verified in text, else freeze editor features.
5. Graph editor: create, load, save, edit nodes/edges/prompts, start test call; edits must change runtime behavior (2.5h). Existing graph library (React Flow), keep the supplied schema.
6. Eval runs, failure analysis, fixes, frozen held-out (2h).
7. solution.md, demo rehearsal from a clean start, backup recording (2h).

Not built: catalog CRUD, auth, multi-tenancy, real calendar, reschedule/cancel, rules framework, exhaustive close-pair generation, extra experimental arms, fine-tuning, VAD tuning, polish.

## 7. Working rules for the agent

- Keep a decision log in `docs/decisions.md`: date, options, choice, reason, the measurement behind it.
- Measure before claiming. Raw numbers come from logs, never from estimates.
- Smallest change that proves the behavior. Do not add architecture layers to answer each remark.
- Never commit `.env`, keys, or anything outside the task. No secrets in logs.
- Voice replies: short, speakable, no lists or emojis.
- Distinguish observed facts from hypotheses in every doc.
