import json
import tempfile
import unittest
from pathlib import Path

from agent_store import AgentStore, AgentStoreError


BACKEND_DIR = Path(__file__).parents[1]


class AgentStoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.store = AgentStore(root / "agents", root / "active.txt")

    def tearDown(self):
        self.temporary.cleanup()

    def test_create_duplicate_activate_save_and_delete(self):
        created = self.store.create("first_agent", name="First")
        duplicate = self.store.duplicate("first_agent", "second_agent")
        self.store.activate("second_agent")

        self.assertEqual(created["initial_node"], "start")
        self.assertEqual(duplicate["name"], "First Copy")
        self.assertEqual(self.store.active_id(), "second_agent")
        self.assertEqual({item["id"] for item in self.store.list()}, {"first_agent", "second_agent"})

        duplicate["nodes"][0]["task_messages"][0]["content"] = "A changed greeting."
        self.store.save("second_agent", duplicate)
        self.assertEqual(
            self.store.load("second_agent")["nodes"][0]["task_messages"][0]["content"],
            "A changed greeting.",
        )

        self.store.delete("second_agent")
        self.assertEqual(self.store.active_id(), "first_agent")

    def test_saved_scheduling_agent_validates_with_registered_tools(self):
        data = json.loads((BACKEND_DIR / "agents" / "catalog_scheduler.json").read_text())

        saved = self.store.save("scheduler", data)

        self.assertEqual(saved["name"], "Catalog Scheduler proposed-v2")

    def test_schema_and_builder_validation_errors_are_returned(self):
        invalid = self.store.create("invalid_target")
        invalid["nodes"][0]["edges"] = [
            {
                "function": "leave",
                "description": "Invalid target",
                "target": "missing",
                "properties": {},
                "required": [],
            }
        ]

        with self.assertRaisesRegex(AgentStoreError, "unknown node 'missing'"):
            self.store.save("invalid_target", invalid)

    def test_agent_ids_cannot_escape_the_store(self):
        with self.assertRaises(AgentStoreError):
            self.store.create("../outside")


class AgentLayoutTest(unittest.TestCase):
    """Editor node positions are stored beside the agent, never inside it."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = AgentStore(self.root / "agents", self.root / "active.txt")
        self.store.create("layout_agent")

    def tearDown(self):
        self.temporary.cleanup()

    def test_layout_round_trips_in_a_separate_file(self):
        positions = {"start": {"x": 120, "y": 45.5}}
        self.store.save_layout("layout_agent", positions)
        self.assertEqual(self.store.load_layout("layout_agent"), {"start": {"x": 120.0, "y": 45.5}})
        self.assertTrue((self.root / "agents" / "layouts" / "layout_agent.layout.json").exists())

    def test_saving_a_layout_never_changes_the_agent_json_or_its_hash(self):
        import hashlib
        agent_file = self.root / "agents" / "layout_agent.json"
        before = hashlib.sha256(agent_file.read_bytes()).hexdigest()
        self.store.save_layout("layout_agent", {"start": {"x": 1, "y": 2}})
        self.assertEqual(hashlib.sha256(agent_file.read_bytes()).hexdigest(), before)
        self.assertNotIn("positions", self.store.load("layout_agent"))

    def test_layout_files_are_not_listed_as_agents(self):
        self.store.save_layout("layout_agent", {"start": {"x": 1, "y": 2}})
        self.assertEqual([item["id"] for item in self.store.list()], ["layout_agent"])

    def test_missing_or_corrupt_layout_loads_as_empty(self):
        self.assertEqual(self.store.load_layout("layout_agent"), {})
        path = self.store.layout_path("layout_agent")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        self.assertEqual(self.store.load_layout("layout_agent"), {})

    def test_invalid_positions_are_rejected(self):
        for bad in ({"start": {"x": "a", "y": 1}}, {"start": [1, 2]}, [], {"start": {"x": True, "y": 1}}):
            with self.assertRaises(AgentStoreError):
                self.store.save_layout("layout_agent", bad)

    def test_layout_for_unknown_agent_is_rejected_and_ids_are_validated(self):
        with self.assertRaises(AgentStoreError):
            self.store.save_layout("missing_agent", {})
        with self.assertRaises(AgentStoreError):
            self.store.layout_path("../outside")

    def test_duplicate_copies_and_delete_removes_the_layout(self):
        self.store.save_layout("layout_agent", {"start": {"x": 5, "y": 6}})
        self.store.duplicate("layout_agent", "layout_copy")
        self.assertEqual(self.store.load_layout("layout_copy"), {"start": {"x": 5.0, "y": 6.0}})
        self.store.delete("layout_agent")
        self.assertFalse(self.store.layout_path("layout_agent").exists())
