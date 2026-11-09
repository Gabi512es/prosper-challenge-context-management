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
            updates = dict(args)
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
            if engine.dialogue.specialty:
                updates["provider_specialty"] = engine.dialogue.specialty
            if "patient_name" in updates:
                updates["name"] = updates.pop("patient_name")
            result = engine.resolve_options(updates)
            message = engine.dialogue.capability_message(result)
            if message:
                engine.dialogue.pending = ("message", message)
            return result
        except SchedulingError as error:
            return {"status": "error", "code": error.code, "message": str(error)}

    async def get_details(args: dict, flow_manager):
        try:
            return engine.get_details(args["entity"], args["id"])
        except SchedulingError as error:
            return {"status": "error", "code": error.code, "message": str(error)}

    async def find_slots(args: dict, flow_manager):
        try:
            if engine.dialogue.location_conflict:
                return {"status": "clarify", "code": "location_conflict"}
            result = engine.find_slots(args.get("horizon_days", 7))
            if result.get("slots"):
                engine.dialogue.pending = ("offer", result["slots"][0])
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
            if engine.dialogue.location_conflict:
                return {"status": "clarify", "code": "location_conflict"}
            result = engine.book_appointment(args["slot_id"])
            if result["status"] == "booked":
                engine.dialogue.pending = ("booked", result["booking"])
            return result
        except SchedulingError as error:
            return {"status": "error", "code": error.code, "message": str(error)}

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
                "hard_constraints": {"type": "object", "properties": {
                    "provider": {"type": "boolean"}, "location": {"type": "boolean"},
                    "date_range": {"type": "boolean"}}},
                "appointment_type_id": {"type": "string"},
                "appointment_type_query": {"type": "string"},
                "provider_id": {"type": "string"},
                "provider_query": {"type": "string"},
                "provider_specialty": {"type": "string"},
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
                "Book an offered slot after explicit patient confirmation. Revalidates the "
                "current state and is idempotent."
            ),
            properties={"slot_id": {"type": "string"}},
            required=["slot_id"],
            handler=book_appointment,
        ),
    }, engine.dialogue)
