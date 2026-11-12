"""No-network acceptance checks for the full-catalog comparison arm."""
import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pipecat.frames.frames import LLMFullResponseEndFrame
from pipecat.processors.frame_processor import FrameDirection

from baseline_agent import build_baseline_agent, id_only_registry, render_catalog
from evals.baseline_check import check_prefix
from scheduling import SchedulingEngine, load_catalog
from scheduling_agent import build_scheduling_agent
from scheduling_dialogue import BookingSpeech

BACKEND = Path(__file__).resolve().parents[1]


class BaselineTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.catalog = load_catalog(BACKEND / "data/catalog.json")

    def engine(self):
        return SchedulingEngine(self.catalog, [], now=datetime.fromisoformat("2026-11-07T00:00:00-08:00"))

    def test_rendering_round_trips_every_source_field_and_policy(self):
        raw = json.loads((BACKEND / "data/catalog.json").read_text())
        text = render_catalog(self.catalog)
        policies = text.split("## Policies\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual([line.split(". ", 1)[1] for line in policies.splitlines()], raw["policies"])
        for section, key in (("Locations", "locations"), ("Providers", "providers"),
                             ("Appointment types", "appointment_types")):
            table = text.split(f"## {section}\n", 1)[1].split("\n\n", 1)[0].strip().splitlines()
            columns = table[0].split(" | ")
            recovered = []
            for original, row in zip(raw[key], table[2:], strict=True):
                self.assertTrue(set(original) <= set(columns))
                # The source omits optional required_capability on ungated
                # types; the loader represents that absence as None.
                self.assertTrue(set(columns) - set(original) <= {"required_capability"})
                expected = {field: original.get(field) for field in columns}
                cells = row.split(" | ")
                self.assertEqual(len(cells), len(columns))
                record = {}
                for field, cell in zip(columns, cells):
                    cell = cell.replace("\\n", "\n").replace("\\|", "|").replace("\\\\", "\\")
                    value = expected[field]
                    if value is None:
                        self.assertEqual(cell, "(none)"); cell = None
                    elif isinstance(value, bool):
                        self.assertIn(cell, {"yes", "no"}); cell = cell == "yes"
                    elif isinstance(value, int):
                        cell = int(cell)
                    elif isinstance(value, list):
                        cell = [] if cell == "(empty)" else cell.split(", ")
                    record[field] = cell
                recovered.append(record)
            self.assertEqual(recovered, [{field: row.get(field) for field in columns} for row in raw[key]])

    async def test_installed_request_serializer_has_a_stable_prefix_without_http(self):
        report = await check_prefix()
        self.assertEqual(report["network_calls"], 0)
        self.assertEqual(len(set(report["request_prefix_hashes"])), 1)
        self.assertEqual(len(set(report["tool_schema_hashes"])), 1)

    async def test_id_only_mode_rejects_hidden_queries_and_preserves_runtime_id_validation(self):
        engine = self.engine()
        registry = id_only_registry(engine)
        resolver = registry["resolve_options"]
        self.assertFalse(any(k.endswith("_query") or k == "provider_specialty" for k in resolver.properties))
        with patch.object(type(self.catalog), "search", side_effect=AssertionError("No free-text search")):
            bad = await resolver.handler({"provider_query": "some name"}, None)
            self.assertEqual(bad["code"], "id_only_resolution")
            unknown = await resolver.handler({"provider_id": "not-a-catalog-id"}, None)
            self.assertTrue(unknown["filter_issues"])
            self.assertIsNone(engine.state.provider_id)
            provider = self.catalog.providers[0]
            await resolver.handler({"provider_id": provider.id}, None)
            self.assertEqual(engine.state.provider_id, provider.id)

    async def test_shared_guards_and_block_results_match_proposed(self):
        proposed = build_scheduling_agent(self.engine(), self.catalog, availability_mode="eval_fixture")
        baseline = build_baseline_agent(self.engine(), self.catalog, availability_mode="eval_fixture")
        for name in ("find_slots", "book_appointment", "get_details"):
            self.assertIs(proposed._function_registry[name].handler.__code__,
                          baseline._function_registry[name].handler.__code__)
            self.assertEqual(proposed._function_registry[name].properties, baseline._function_registry[name].properties)
        for builder in (proposed, baseline):
            self.assertIs(builder.dialogue, builder._function_registry.dialogue)
            self.assertIs(builder.transition_guard.__func__, builder.dialogue.authorize_transition.__func__)
            blocked = await builder._function_registry["book_appointment"].handler({"slot_id": "invented"}, None)
            self.assertNotEqual(blocked["status"], "booked")
        # A capability-gated type/provider pair at an incompatible site exercises
        # the shared policy explanations and alternate-location recovery.
        item = next(t for t in self.catalog.appointment_types if t.required_capability and any(
            t.id in p.appointment_type_ids and any(t.required_capability not in self.catalog.locations_by_id[l].capabilities
                                                   for l in p.location_ids) for p in self.catalog.providers))
        provider = next(p for p in self.catalog.providers if item.id in p.appointment_type_ids and any(
            item.required_capability not in self.catalog.locations_by_id[l].capabilities for l in p.location_ids))
        site = next(l for l in provider.location_ids if item.required_capability not in self.catalog.locations_by_id[l].capabilities)
        args = dict(appointment_type_id=item.id, provider_id=provider.id, location_id=site,
                    is_new_patient=False, referral_on_file=True)
        results = [await b._function_registry["resolve_options"].handler(args, None) for b in (proposed, baseline)]
        self.assertEqual(results[0], results[1])
        self.assertTrue(any(x["code"] == "location_missing_capability" for x in results[0]["blocked_options"]))

    def test_build_leaves_source_agent_unchanged_and_all_nodes_use_reference(self):
        path = BACKEND / "agents/catalog_scheduler.json"
        original = path.read_bytes()
        builder = build_baseline_agent(self.engine(), self.catalog, availability_mode="eval_fixture")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(builder.config.model, json.loads(original)["model"])
        for node in builder.config.nodes:
            compiled = builder._make_node(node)
            self.assertTrue(compiled["role_message"].startswith(render_catalog(self.catalog)))
            self.assertFalse(any("Appointment type index:" in m["content"] for m in compiled["task_messages"]))

    async def test_both_arms_complete_identity_offer_consent_and_one_booking_offline(self):
        provider, service, site = next(
            (p, self.catalog.appointment_types_by_id[t], self.catalog.locations_by_id[l])
            for p in self.catalog.providers for t in p.appointment_type_ids for l in p.location_ids
            if not self.catalog.appointment_types_by_id[t].required_capability
            or self.catalog.appointment_types_by_id[t].required_capability in self.catalog.locations_by_id[l].capabilities)
        start = datetime.fromisoformat("2026-11-09T10:00:00-08:00")
        fixture = [dict(slot_id="offline-slot", provider_id=provider.id, location_id=site.id,
                        appointment_type_id=service.id, start=start.isoformat(),
                        end=(start + timedelta(minutes=service.duration_min)).isoformat())]
        for build in (build_scheduling_agent, build_baseline_agent):
            engine = SchedulingEngine(self.catalog, fixture, now=datetime.fromisoformat("2026-11-07T00:00:00-08:00"))
            builder = build(engine, self.catalog, availability_mode="unit_fixture")
            functions = builder._function_registry
            await functions["resolve_options"].handler(dict(
                appointment_type_id=service.id, provider_id=provider.id, location_id=site.id,
                patient_name="Alex Morgan", date_of_birth="1990-04-12", is_new_patient=False,
                referral_on_file=True), None)
            speaker = BookingSpeech(builder.dialogue)
            speaker.push_frame = AsyncMock()
            await speaker.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
            self.assertIn("Alex Morgan, born April 12, 1990", speaker.push_frame.call_args_list[0].args[0].text)
            builder.dialogue.patient("yes")
            result = await functions["find_slots"].handler({"horizon_days": 7}, None)
            self.assertEqual(result["booking_phase"]["status"], "needs_confirmation")
            self.assertEqual(engine.bookings, [])
            await speaker.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
            builder.dialogue.patient("yes")
            result = await functions["book_appointment"].handler({"slot_id": "offline-slot"}, None)
            self.assertEqual(result["status"], "booked")
            self.assertEqual(len(engine.bookings), 1)
            self.assertEqual(engine.bookings[0]["location_id"], site.id)


if __name__ == "__main__":
    unittest.main()
