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
