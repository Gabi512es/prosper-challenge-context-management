"""Load the scheduling JSON graph and bind its pure-Python tool registry."""

import hashlib
import json
from pathlib import Path

from pipecat_flows import FlowsFunctionSchema

from agent_builder import AgentBuilder
from scheduling import SchedulingEngine
from scheduling.catalog import Catalog
from scheduling.engine import SchedulingError
from scheduling_dialogue import SchedulingDialogue


BACKEND_DIR = Path(__file__).parent
DEFAULT_SCHEDULING_AGENT_PATH = BACKEND_DIR / "agents" / "catalog_scheduler.json"
SCHEDULING_TOOL_NAMES = (
    "resolve_options",
    "get_details",
    "find_slots",
    "book_appointment",
)


class SchedulingToolRegistry(dict):
    """Carries mandatory dialogue policy to every builder using these tools."""
    def __init__(self, tools, dialogue):
        super().__init__(tools)
        self.dialogue = dialogue


def build_scheduling_agent(
    engine: SchedulingEngine,
    catalog: Catalog,
    *,
    flow_path: Path = DEFAULT_SCHEDULING_AGENT_PATH,
    availability_mode: str,
) -> AgentBuilder:
    """Load an editable JSON graph and bind session-local scheduling tools.

    The JSON bytes are read once, so the logged revision is exactly the graph
    that was compiled even if the editor saves a new version concurrently.
    """
    if engine.catalog is not catalog:
        raise ValueError("The scheduling engine and agent registry must share one catalog.")
    raw = Path(flow_path).read_bytes()
    builder = AgentBuilder.from_dict(
        json.loads(raw),
        function_registry=build_scheduling_tool_registry(engine),
    )
    builder.session_metadata = {
        "agent_id": Path(flow_path).stem,
        "agent_revision": hashlib.sha256(raw).hexdigest(),
        "availability_mode": availability_mode,
    }
    builder.dialogue = engine.dialogue
    return builder


def build_scheduling_tool_registry(
    engine: SchedulingEngine,
) -> dict[str, FlowsFunctionSchema]:
    if not hasattr(engine, "dialogue"):
        engine.dialogue = SchedulingDialogue(engine)
    async def resolve_options(args: dict, flow_manager):
        try:
            updates, rejected_filters = engine.validate_filters(args)
            preference = updates.pop("location_preference", None)
            if preference is not None and preference not in {"time", "place", "unclear"}:
                return engine.dialogue.set_location_preference(preference)
            if engine.dialogue.global_soonest:
                for key in ("provider_id", "provider_query", "provider_specialty", "location_id", "location_query"):
                    updates.pop(key, None)
                updates.update(any_provider=True, any_location=True)
            if engine.dialogue.location:
                requested = updates.get("location_id")
                if updates.get("location_query"):
                    matches = engine.catalog.search("location", updates["location_query"])
                    requested = matches[0]["id"] if len(matches) == 1 else None
                if requested and requested != engine.dialogue.location:
                    name = engine.catalog.locations_by_id[engine.dialogue.location].name
                    engine.dialogue.location_conflict = f"I heard {name}, but the requested location differs. Which location would you like?"
                    return {"status": "clarify", "code": "location_conflict", "message": engine.dialogue.location_conflict}
                updates["location_id"] = engine.dialogue.location
                updates.pop("location_query", None)
            if engine.dialogue.specialty and not engine.dialogue.global_soonest:
                updates["provider_specialty"] = engine.dialogue.specialty
            if "patient_name" in updates:
                updates["name"] = updates.pop("patient_name")
            result = engine.resolve_options(updates)
            if engine.state.location_id:
                engine.dialogue.location = engine.state.location_id
                engine.dialogue.location_intent_question = None
                engine.dialogue.location_intent_stage = None
            if preference is not None:
                engine.dialogue.set_location_preference(preference)
                result = engine.resolve_options()
                if engine.dialogue.location_intent_question:
                    result.update(status="clarify", next_action="clarify_location_preference",
                                  message=engine.dialogue.location_intent_question)
            result["filter_issues"] = rejected_filters + result["filter_issues"]
            provider_candidates = [c for c in result["candidates"] if c["entity"] == "provider"]
            if provider_candidates:
                names = list(dict.fromkeys(c["name"] for c in provider_candidates))
                if any(c.get("requires_confirmation") for c in provider_candidates):
                    engine.dialogue.pending = ("message", "Did you mean " + " or ".join(names) + "?")
                else:
                    options = [f"{c['name']}, {c['specialty']} ({c['title']})" for c in provider_candidates]
                    engine.dialogue.pending = ("message", "Which provider did you mean: " + "; ".join(options) + "?")
            elif any(err["entity"] == "provider" for err in result["errors"]):
                engine.dialogue.pending = ("message", "I couldn't find a provider with that name. Could you repeat or spell the first name and surname?")
            elif "location_id" in result["missing_facts"] and result["eligible_locations"]:
                engine.dialogue.pending = ("message", engine.dialogue.site_choices())
            if result["filter_issues"]:
                fields = ", ".join(issue["filter"].replace("_", " ") for issue in result["filter_issues"])
                prefix = f"The {fields} filter didn't match and was not applied. "
                if engine.dialogue.pending and engine.dialogue.pending[0] == "message":
                    engine.dialogue.pending = ("message", prefix + engine.dialogue.pending[1])
                else:
                    engine.dialogue.pending = ("message", prefix + "Which catalog option did you mean?")
            message = engine.dialogue.capability_message(result)
            if message:
                engine.dialogue.pending = ("message", message)
            engine.dialogue.last_resolution = result
            result["dialogue_step"] = engine.dialogue.next_step()
            if result["dialogue_step"]["stage"] == "identity_confirmation":
                result["identity_confirmation"] = engine.dialogue.require_identity()
            return result
        except SchedulingError as error:
            return {"status": "error", "code": error.code, "message": str(error)}

    async def get_details(args: dict, flow_manager):
        try:
            engine.dialogue.catalog_answer = True
            return engine.get_details(args["entity"], args["id"])
        except SchedulingError as error:
            return {"status": "error", "code": error.code, "message": str(error)}

    async def find_slots(args: dict, flow_manager):
        try:
            identity_step = engine.dialogue.booking_gate()
            if identity_step:
                return identity_step
            if engine.dialogue.location_conflict:
                return {"status": "clarify", "code": "location_conflict"}
            result = engine.find_slots(args.get("horizon_days", 7))
            if len(result.get("slots", [])) == 1:
                result["booking_phase"] = await book_appointment({"slot_id": result["slots"][0]["slot_id"]}, flow_manager)
            elif result.get("slots"):
                from datetime import datetime
                choices = [f"{datetime.fromisoformat(s['start']).strftime('%A %B %d at %I:%M %p')} at {s['location']}" for s in result["slots"][:3]]
                engine.dialogue.pending = ("options", "; ".join(choices) + ". Which slot would you like?")
                result["next_action"] = "ask_patient_to_choose_then_call_book_appointment"
            else:
                message = engine.dialogue.capability_message(result)
                missing = [i["field"] for i in result.get("issues", []) if i["kind"] == "missing"]
                if missing:
                    message = message or "Before I can offer bookable slots, please confirm: " + ", ".join(missing).replace("_", " ") + "."
                if not message and result.get("alternatives"):
                    sites = list(dict.fromkeys(a["slot"]["location"] for a in result["alternatives"]))
                    message = "No slots match the current request. Other locations to consider are " + " or ".join(sites[:2]) + ". Would you like to change your constraints and search again?"
                engine.dialogue.pending = ("message", message or "No matching slots are available. Would you like to change your search constraints?")
            return result
        except SchedulingError as error:
            return {"status": "error", "code": error.code, "message": str(error)}

    async def book_appointment(args: dict, flow_manager):
        try:
            identity_step = engine.dialogue.booking_gate()
            if identity_step:
                return identity_step
            if engine.dialogue.location_conflict:
                return {"status": "clarify", "code": "location_conflict"}
            slot_id = args["slot_id"]
            if not any(b["slot_id"] == slot_id for b in engine.bookings) and (
                engine.state.confirmation is None or engine.state.selected_slot_id != slot_id):
                return engine.dialogue.prepare_booking(slot_id)
            result = engine.book_appointment(slot_id)
            if result["status"] == "booked":
                engine.dialogue.pending = ("booked", result["booking"])
            return result
        except SchedulingError as error:
            engine.dialogue.pending = ("message", "The slot needs revalidation. Please choose a slot from a fresh availability search.")
            return {"status": "validation_required", "technical_failure": False,
                    "code": error.code, "message": str(error), "next_action": "find_slots_then_prepare_booking"}

    return SchedulingToolRegistry({
        "resolve_options": FlowsFunctionSchema(
            name="resolve_options",
            description=(
                "Apply patient/request facts, resolve catalog identities without guessing, "
                "invalidate stale choices, and return policy or ambiguity results."
            ),
            properties={
                "patient_name": {
                    "type": "string",
                    "description": (
                        "Patient's full name; never an appointment, provider, or location name."
                    ),
                },
                "date_of_birth": {"type": "string", "description": "YYYY-MM-DD"},
                "is_new_patient": {"type": "boolean"},
                "referral_on_file": {"type": "boolean"},
                "location_preference": {"type": "string", "enum": ["time", "place", "unclear"],
                    "description": "Interpret the patient's location preference: time = earliest eligible slot across sites/providers; place = geographic proximity (including 'near me', 'to where I live', 'nearest clinic geographically'); unclear = closest with no time/place meaning. Set this field for a preference reply, including answers to clarification. Code cannot calculate distances."},
                "hard_constraints": {"type": "object", "properties": {
                    "provider": {"type": "boolean"}, "location": {"type": "boolean"},
                    "date_range": {"type": "boolean"}}},
                "appointment_type_id": {"type": "string"},
                "appointment_type_query": {"type": "string"},
                "provider_id": {"type": "string"},
                "provider_query": {"type": "string"},
                "provider_specialty": {"type": "string",
                    "description": "Only use a catalog specialty explicitly supplied by the patient. Omit if unknown; never infer from the requested service."},
                "any_provider": {
                    "type": "boolean",
                    "description": "True only when the patient accepts any clinician.",
                },
                "location_id": {"type": "string"},
                "location_query": {"type": "string"},
                "any_location": {
                    "type": "boolean",
                    "description": "True only when the patient accepts any location or site.",
                },
            },
            required=[],
            handler=resolve_options,
        ),
        "get_details": FlowsFunctionSchema(
            name="get_details",
            description="Return authoritative details for one resolved catalog entity.",
            properties={
                "entity": {
                    "type": "string",
                    "enum": ["appointment_type", "provider", "location"],
                },
                "id": {"type": "string"},
            },
            required=["entity", "id"],
            handler=get_details,
        ),
        "find_slots": FlowsFunctionSchema(
            name="find_slots",
            description=(
                "Search the complete closed-world availability fixture for eligible slots, "
                "ranking globally before truncation."
            ),
            properties={
                "horizon_days": {"type": "integer", "minimum": 1, "maximum": 30}
            },
            required=["horizon_days"],
            handler=find_slots,
        ),
        "book_appointment": FlowsFunctionSchema(
            name="book_appointment",
            description=(
                "Two-phase booking. Call with the chosen slot id to validate and prepare an exact read-back. "
                "Say the returned readback and wait for the patient. Call again with the same slot after yes to book. "
                "needs_confirmation and validation_required are normal protocol steps, never technical failures."
            ),
            properties={"slot_id": {"type": "string"}},
            required=["slot_id"],
            handler=book_appointment,
        ),
    }, engine.dialogue)
