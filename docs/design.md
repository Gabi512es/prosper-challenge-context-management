# Design v1: catalog-backed scheduling core

## Boundary

The LLM interprets patient language and presents results. Plain Python owns
identity resolution, catalog joins, policy decisions, availability, state
invalidation, and booking. The core has no Pipecat or OpenAI imports. The
development scenario fixture is a closed availability universe; unlisted slots
do not exist. The catalog is read-only, including its eight appointment types
with no provider.

Flows stays on `APPEND`. The proposed cached appointment-type index is compact
JSON with `id+name`: 1,026 `o200k_base` tokens for 82 types. Adding specialty is
1,559 tokens and is rejected for now because specialty does not determine
provider/type compatibility. Tools return authoritative specialty when useful.

## Session state

- `patient_facts`: name, date of birth, new-patient status, referral-on-file;
  unknown is distinct from false.
- `constraints`: explicit hard provider/location/type constraints.
- `preferences`: soft ranking preferences such as soonest.
- `resolved`: appointment-type, provider, and location IDs, each nullable.
- `last_candidates`: the last bounded candidate set plus omitted count.
- `selected_slot_id`: nullable.
- `confirmation`: immutable snapshot of patient, type, provider, location, and
  slot IDs at the moment the patient confirms.
- `booking`: at most one completed booking per slot; repeated calls are
  idempotent.

## Invalidation

- Type change clears an incompatible provider or location, then clears slot
  and confirmation.
- Location change clears a provider only if that provider does not practice
  there, then always clears slot and confirmation.
- Provider change clears slot and confirmation. An incompatible retained
  location is reported, never silently replaced.
- Patient eligibility changes clear slot and confirmation.
- Slot change clears confirmation.
- Any correction is applied before the next policy or availability check.

Known facts are retained and are not re-asked. Hard constraints are never
relaxed without explicit patient agreement.

## Tool contracts

### `resolve_options(updates)`

Applies structured updates with invalidation, resolves exact IDs or textual
queries without collapsing ambiguity, joins type/provider/location relations,
and evaluates current policies. Returns resolved IDs, bounded candidates,
`more_available`, missing facts, and blocked options with stable reason codes.
No match, ambiguity, missing facts, and policy refusal are distinct outcomes.

### `get_details(entity, id)`

Returns the authoritative catalog record for one appointment type, provider,
or location. Unknown entity kinds or IDs are structured errors. It never
infers facts absent from the catalog.

### `find_slots(horizon_days)`

Requires a fully resolved and policy-eligible combination. Searches every slot
in the scenario fixture within the stated horizon, ranks globally by declared
preferences and then time, and truncates only after ranking. Returns the
horizon and any relaxation; v1 performs no silent relaxation.

### `book_appointment(slot_id)`

Looks up the slot in the closed fixture, revalidates all booking preconditions
against current state, and creates at most one booking. A repeated identical
request returns the existing booking. A stale or altered request fails with a
structured reason.

## Booking preconditions

1. Name, date of birth, new-patient status, and any required referral status
   are known.
2. Appointment type, provider, and location are resolved to IDs.
3. The provider offers the type and practices at the location.
4. Required location capability, referral, type new-patient rule, and provider
   new-patient rule all pass.
5. The slot exists in the scenario fixture, is within the requested horizon,
   exactly matches the resolved IDs, and its full interval is within the
   location's catalog opening hours.
6. The slot is selected and the confirmation snapshot exactly matches current
   state. Corrections invalidate that snapshot.

## Text-only fault injection

An optional scenario `faults` list is installed by `TextAgentSession` around
the real graph tool handlers. The returned error object is passed to the model
as the normal tool result; the runner never turns it into success or hides it.
Unknown tool names and malformed fault definitions fail before the session.

- `{"mode":"error","tool":"find_slots"}` returns a structured error on every
  call. Optional `code` and `message` fields customize the result.
- `{"mode":"slot_taken","tool":"book_appointment","slot_id":"...",
  "attempts":2}` forcibly fails the first two matching writes. The first write
  permanently removes the slot, so later searches exclude it and later writes
  continue to fail through normal core revalidation. `"slot taken"` is accepted
  as an equivalent mode spelling.

Fault injection is evaluation infrastructure only and is not installed in the
voice runtime. A request for a human leaves automated scheduling through a
terminal handoff node. Because this prototype has no live transfer integration,
the final response must say so rather than claim a connection was completed.

First proof cases are DEV-012 (valid gated booking), DEV-004 (type-level
new-patient refusal), and DEV-008 (location correction invalidates the old
slot). These are development tests, not held-out evidence.
