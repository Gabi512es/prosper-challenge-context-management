"""Offline checks of experiment-only catalog/config injection; never call OpenAI."""
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from evals.catalog_scaling import BACKEND, INDEX_MARKER, search_only_agent
from evals.loader import load_dev_scenarios
from evals.scaling_matrix import search_only_registry
from evals.version import evaluator_sha256
from scheduling import SchedulingEngine, load_catalog
from scheduling_agent import build_scheduling_tool_registry


class SearchOnlyExperimentTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_only_preserves_guards_and_resolves_actual_service_facts(self):
        data = load_dev_scenarios()
        scenario = next(s for s in data["scenarios"] if s["id"] == "DEV-012")
        catalog = load_catalog(BACKEND / "data/catalog.json")
        engines = [SchedulingEngine(catalog, scenario["availability_fixture"]) for _ in range(2)]
        original = build_scheduling_tool_registry(engines[0])
        search = search_only_registry(engines[1])
        for name in ("find_slots", "book_appointment", "get_details"):
            self.assertEqual(original[name].properties, search[name].properties)
            self.assertEqual(original[name].description, search[name].description)
        for field in ("appointment_type_id", "provider_id", "location_id"):
            self.assertNotIn(field, search["resolve_options"].properties)
        for field in ("appointment_type_query", "provider_query", "location_query"):
            self.assertIn(field, search["resolve_options"].properties)
        rejected = await search["resolve_options"].handler({"appointment_type_id": "not-an-id"}, None)
        self.assertEqual(rejected["code"], "search_only_resolution")
        self.assertIsNone(engines[1].state.appointment_type_id)
        facts = scenario["patient_facts"]
        queries = {"appointment_type_query": catalog.appointment_types_by_id[facts["appointment_type_id"]].name,
                   "provider_query": catalog.providers_by_id[facts["provider_id"]].name,
                   "provider_specialty": catalog.providers_by_id[facts["provider_id"]].specialty,
                   "location_query": catalog.locations_by_id[facts["location_id"]].name,
                   "is_new_patient": facts["is_new_patient"], "referral_on_file": facts["referral_on_file"]}
        results = [await registry["resolve_options"].handler(queries, None) for registry in (original, search)]
        self.assertEqual(*results)
        self.assertEqual(results[1]["resolved"], {k: facts[k] for k in ("appointment_type_id", "provider_id", "location_id")})
        self.assertIs(search.dialogue, engines[1].dialogue)

    async def test_search_config_only_changes_index_and_its_access_sentence(self):
        path = BACKEND / "agents/catalog_scheduler.json"
        before = path.read_bytes()
        original = json.loads(before)
        search = search_only_agent(original)
        self.assertEqual(search["persona"], original["persona"])
        differences = []
        for i, node in enumerate(search["nodes"]):
            for j, message in enumerate(node["task_messages"]):
                old = original["nodes"][i]["task_messages"][j]["content"]
                if message["content"] != old:
                    differences.append((i, j))
                    self.assertIn(INDEX_MARKER, old)
                    self.assertNotIn(INDEX_MARKER, message["content"])
                    self.assertNotIn("appt_", message["content"])
                    message["content"] = old
        self.assertEqual(len(differences), 1)
        self.assertEqual(search, original)
        self.assertEqual(before, path.read_bytes())

    async def test_catalog_injection_does_not_change_evaluator_or_original_pin(self):
        from evals import text_integration
        signature = evaluator_sha256()
        catalog = load_catalog(BACKEND / "data/catalog.json")
        # An offline sentinel session checks constructor wiring without an LLM.
        class OfflineSession:
            call_id = "offline-scaling"
            run_id = "offline-scaling"
            context_messages = []
            def __init__(self, **kwargs):
                self.builder = kwargs["builder"]
            async def start(self):
                raise RuntimeError("offline sentinel")
            async def close(self):
                pass
        from scheduling_agent import build_scheduling_agent
        with patch.object(text_integration, "load_catalog", return_value=catalog) as loader, patch.object(text_integration, "TextAgentSession", OfflineSession):
            result = await text_integration.run_dev_case("DEV-012", run_id="offline-scaling", agent_factory=build_scheduling_agent)
        self.assertIs(result.engine.catalog, catalog)
        loader.assert_called_once_with(text_integration.DEFAULT_CATALOG_PATH)
        self.assertIn("offline sentinel", result.error)
        self.assertEqual(signature, evaluator_sha256())
        load_dev_scenarios()
