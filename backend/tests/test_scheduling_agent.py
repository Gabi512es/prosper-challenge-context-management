import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from scheduling import SchedulingEngine, load_catalog
from scheduling_agent import build_scheduling_agent


BACKEND_DIR = Path(__file__).parents[1]


class SchedulingAgentAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_resolver_exposes_unconstrained_search_scope(self):
        catalog = load_catalog(BACKEND_DIR / "data" / "catalog.json")
        engine = SchedulingEngine(
            catalog,
            [],
            now=datetime.fromisoformat("2026-11-07T00:00:00-08:00"),
        )
        builder = build_scheduling_agent(engine, catalog)
        node = builder.build_initial_node()
        resolver = next(
            function for function in node["functions"] if function.name == "resolve_options"
        )

        self.assertIn("any_provider", resolver.properties)
        self.assertIn("any_location", resolver.properties)

    async def test_registered_resolver_stays_in_same_node_and_calls_core(self):
        catalog = load_catalog(BACKEND_DIR / "data" / "catalog.json")
        engine = SchedulingEngine(
            catalog,
            [],
            now=datetime.fromisoformat("2026-11-07T00:00:00-08:00"),
        )
        builder = build_scheduling_agent(engine, catalog)
        node = builder.build_initial_node()
        functions = {function.name: function for function in node["functions"]}

        result = await functions["resolve_options"].handler(
            {
                "patient_name": "Alex Morgan",
                "date_of_birth": "1990-04-12",
                "appointment_type_id": "appt_065",
                "provider_query": "Linda Ramirez",
                "provider_specialty": "Radiology",
                "location_query": "Downtown",
                "is_new_patient": True,
                "referral_on_file": True,
            },
            SimpleNamespace(state={}),
        )

        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "new_patient_type_restricted",
            {item["code"] for item in result["blocked_options"]},
        )
        self.assertEqual(builder.current_node, "scheduling")
        self.assertEqual(engine.state.patient_facts.name, "Alex Morgan")
        self.assertEqual(engine.state.patient_facts.date_of_birth, "1990-04-12")

    async def test_human_request_transitions_out_of_automated_scheduling(self):
        catalog = load_catalog(BACKEND_DIR / "data" / "catalog.json")
        engine = SchedulingEngine(
            catalog,
            [],
            now=datetime.fromisoformat("2026-11-07T00:00:00-08:00"),
        )
        builder = build_scheduling_agent(engine, catalog)
        node = builder.build_initial_node()
        functions = {function.name: function for function in node["functions"]}
        manager = SimpleNamespace(state={})

        result, next_node = await functions["request_human_transfer"].handler(
            {
                "human_transfer_requested": True,
                "reason": "Patient asked for a person.",
            },
            manager,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(next_node["name"], "human_handoff")
        self.assertNotIn("post_actions", next_node)
        self.assertEqual(builder.current_node, "human_handoff")
        self.assertTrue(builder.current_node_is_terminal)
        self.assertTrue(manager.state["human_transfer_requested"])
        self.assertEqual(manager.state["reason"], "Patient asked for a person.")

    async def test_saved_task_edit_is_loaded_for_the_next_session(self):
        catalog = load_catalog(BACKEND_DIR / "data" / "catalog.json")
        engine = SchedulingEngine(
            catalog,
            [],
            now=datetime.fromisoformat("2026-11-07T00:00:00-08:00"),
        )
        data = json.loads(
            (BACKEND_DIR / "agents" / "catalog_scheduler.json").read_text()
        )
        changed = "This greeting came from the saved graph editor JSON."
        data["nodes"][0]["task_messages"][0]["content"] = changed

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "edited.json"
            path.write_text(json.dumps(data))
            builder = build_scheduling_agent(engine, catalog, flow_path=path)

        self.assertEqual(
            builder.build_initial_node()["task_messages"][0]["content"],
            changed,
        )
