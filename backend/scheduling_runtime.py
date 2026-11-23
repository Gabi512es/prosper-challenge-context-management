"""Shared factory for loading a selected JSON scheduling agent."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from agent_builder import AgentBuilder
from agent_store import AgentStore
from v4.agent_config import is_v4_file
from scheduling import SchedulingEngine, load_catalog
from scheduling_agent import build_scheduling_agent
from scheduling.demo import generate_demo_availability


BACKEND_DIR = Path(__file__).parent
DEFAULT_CATALOG_PATH = BACKEND_DIR / "data" / "catalog.json"
DEFAULT_DEMO_AVAILABILITY_PATH = BACKEND_DIR / "data" / "demo_availability.json"


def load_selected_scheduling_agent(
    *,
    flow_path: Path | None = None,
    availability_path: Path | None = None,
    now: datetime | None = None,
) -> tuple[AgentBuilder, SchedulingEngine]:
    """Create fresh session state and tools for one saved JSON graph."""
    catalog = load_catalog(DEFAULT_CATALOG_PATH)
    selected_path = flow_path or AgentStore().active_path()
    if is_v4_file(selected_path):
        raise ValueError(f"'{selected_path.stem}' is a v4 agent: run it with v4_bot.py or v4_text.py, "
                         "not the Flows runtime.")
    configured_availability = os.getenv("AVAILABILITY_PATH")
    slot_path = availability_path or (
        Path(configured_availability)
        if configured_availability
        else DEFAULT_DEMO_AVAILABILITY_PATH
    )
    session_now = now or datetime.now(timezone.utc)
    from_file = bool(availability_path or configured_availability)
    availability = (json.loads(slot_path.read_text()) if from_file
                    else generate_demo_availability(catalog, session_now))
    engine = SchedulingEngine(
        catalog,
        availability,
        now=session_now,
    )
    return (
        build_scheduling_agent(
            engine,
            catalog,
            flow_path=selected_path,
            availability_mode=f"file:{slot_path.name}" if from_file else "demo_generated",
        ),
        engine,
    )
