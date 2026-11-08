"""Load the scheduling JSON graph and bind its pure-Python tool registry."""

from pathlib import Path

from pipecat_flows import FlowsFunctionSchema

from agent_builder import AgentBuilder
from scheduling import SchedulingEngine
from scheduling.catalog import Catalog
from scheduling.engine import SchedulingError


BACKEND_DIR = Path(__file__).parent
DEFAULT_SCHEDULING_AGENT_PATH = BACKEND_DIR / "agents" / "catalog_scheduler.json"
SCHEDULING_TOOL_NAMES = (
    "resolve_options",
    "get_details",
    "find_slots",
    "book_appointment",
)


def build_scheduling_agent(
    engine: SchedulingEngine,
    catalog: Catalog,
    *,
    flow_path: Path = DEFAULT_SCHEDULING_AGENT_PATH,
) -> AgentBuilder:
    """Load an editable JSON graph and bind session-local scheduling tools."""
    if engine.catalog is not catalog:
        raise ValueError("The scheduling engine and agent registry must share one catalog.")
    return AgentBuilder.from_json(
        flow_path,
        function_registry=build_scheduling_tool_registry(engine),
    )


def build_scheduling_tool_registry(
    engine: SchedulingEngine,
) -> dict[str, FlowsFunctionSchema]:
    async def resolve_options(args: dict, flow_manager):
        try:
            updates = dict(args)
            if "patient_name" in updates:
                updates["name"] = updates.pop("patient_name")
            return engine.resolve_options(updates)
        except SchedulingError as error:
            return {"status": "error", "code": error.code, "message": str(error)}

    async def get_details(args: dict, flow_manager):
        try:
            return engine.get_details(args["entity"], args["id"])
        except SchedulingError as error:
            return {"status": "error", "code": error.code, "message": str(error)}

    async def find_slots(args: dict, flow_manager):
        try:
            return engine.find_slots(args.get("horizon_days", 7))
        except SchedulingError as error:
            return {"status": "error", "code": error.code, "message": str(error)}

    async def book_appointment(args: dict, flow_manager):
        try:
            engine.select_slot(args["slot_id"])
            engine.confirm_selected_slot()
            return engine.book_appointment(args["slot_id"])
        except SchedulingError as error:
            return {"status": "error", "code": error.code, "message": str(error)}

    return {
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
    }
