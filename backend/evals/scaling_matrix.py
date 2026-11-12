"""Step 6b experiment overlays; frozen agent, patient driver and scorer unchanged."""
import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from dotenv import load_dotenv
import text_runner
from agent_builder import AgentBuilder
from baseline_agent import build_baseline_agent
from scheduling import load_catalog
from scheduling_agent import build_scheduling_agent, build_scheduling_tool_registry
from . import text_integration
from .catalog_scaling import BACKEND, CASES, cache_billing, measure_offline
from .baseline_check import request_parameters
from .comparison_report import aggregate
from .dev_matrix import usage_for_call
from .loader import DEFAULT_CATALOG_PATH, DEFAULT_SCENARIOS_PATH, load_dev_scenarios
from .scorer import evaluate_run
from .spend_guard import SpendGuard
from .version import EVALUATOR_VERSION, evaluator_sha256


def search_only_registry(engine):
    registry = build_scheduling_tool_registry(engine)
    original = registry["resolve_options"]
    excluded = {"appointment_type_id", "provider_id", "location_id"}

    async def resolve_queries(args, manager):
        rejected = sorted(excluded.intersection(args))
        if rejected:
            return {"status": "clarify", "code": "search_only_resolution", "technical_failure": False,
                    "rejected_fields": rejected, "next_action": "submit_free_text_catalog_queries_not_ids"}
        return await original.handler(args, manager)

    registry["resolve_options"] = replace(original, handler=resolve_queries,
        properties={k: v for k, v in original.properties.items() if k not in excluded},
        description="Apply patient facts and resolve catalog identities using free-text queries, not catalog IDs. Preserve ambiguity, evaluate policies and return alternatives.")
    return registry


def build_search_agent(engine, catalog, *, flow_path, availability_mode):
    if engine.catalog is not catalog:
        raise ValueError("Engine and exploratory agent must share the expanded catalog")
    raw = Path(flow_path).read_bytes()
    builder = AgentBuilder.from_dict(json.loads(raw), function_registry=search_only_registry(engine))
    builder.session_metadata = {"agent_id": "exploratory_search_only",
        "agent_revision": sha256(raw).hexdigest(), "availability_mode": availability_mode}
    return builder


def phase_factory(phase, directory):
    arm, factor = phase["arm"], phase["factor"]
    if arm == "baseline":
        return build_baseline_agent
    if arm == "proposed-indexed":
        return lambda engine, catalog, **kwargs: build_scheduling_agent(engine, catalog,
            flow_path=directory / f"agent-x{factor:02d}-expanded-index.json", **kwargs)
    if arm == "exploratory-search-only":
        return lambda engine, catalog, **kwargs: build_search_agent(engine, catalog,
            flow_path=directory / "agent-search-only-exploratory.json", **kwargs)
    raise ValueError(f"Unknown experiment arm: {arm}")


async def offline_wiring_check(offline, directory):
    """Serialize real expanded requests twice, without sending either."""
    from openai.resources.chat.completions import AsyncCompletions
    from pipecat.services.openai.llm import OpenAILLMService
    from scheduling import SchedulingEngine
    evidence = []
    with patch.object(AsyncCompletions, "create", new_callable=AsyncMock) as network:
        for phase in offline["plans"]["revised_6b"]["phases"]:
            catalog = load_catalog(directory / f"catalog-x{phase['factor']:02d}.json")
            prefixes, schemas = [], []
            for history in ([], [{"role": "user", "content": "I need an appointment."}]):
                builder = phase_factory(phase, directory)(SchedulingEngine(catalog, []), catalog, availability_mode="eval_fixture")
                node = builder.build_initial_node()
                llm = OpenAILLMService(api_key="offline-no-network", settings=OpenAILLMService.Settings(model="gpt-4o"))
                try:
                    params = request_parameters(llm, node, history)
                    prefix = params["messages"][:1 + len(node["task_messages"])]
                    prefixes.append(sha256(json.dumps(prefix, sort_keys=True).encode()).hexdigest())
                    schemas.append(sha256(json.dumps(params["tools"], sort_keys=True).encode()).hexdigest())
                finally:
                    await llm._client.close()
            assert len(set(prefixes)) == len(set(schemas)) == 1
            evidence.append({"arm": phase["arm"], "factor": phase["factor"],
                             "prefix_hashes": prefixes, "tool_schema_hashes": schemas})
        network.assert_not_called()
    (directory / "offline-wiring.json").write_text(json.dumps({"network_calls": 0, "checks": evidence}, indent=2) + "\n")


async def run_scaling(offline, directory, budget):
    dataset = load_dev_scenarios()  # Always checks the ORIGINAL source catalog pin.
    scenarios = {s["id"]: s for s in dataset["scenarios"]}
    experiment_id = f"scaling-v3-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"
    path = BACKEND / "logs/evals" / f"{experiment_id}.results.json"
    report = {"experiment_id": experiment_id, "evaluator_version": EVALUATOR_VERSION,
        "evaluator_sha256": evaluator_sha256(), "plan": offline["plans"]["revised_6b"],
        "offline_report": str(directory / "offline-measurements.json"),
        "scenario_sha256": sha256(DEFAULT_SCENARIOS_PATH.read_bytes()).hexdigest(),
        "source_catalog_blob_sha": dataset["catalog"]["blob_sha"],
        "source_agent_sha256": sha256((BACKEND / "agents/catalog_scheduler.json").read_bytes()).hexdigest(),
        "execution_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "execution": {"sdk_retries": 0, "timeout_retries": False, "concurrency": 1,
                      "turn_timeout_seconds": 45, "max_completion_tokens": 512},
        "phases": [], "complete": False}
    original_runtime = text_runner.build_agent_runtime

    def no_retries(**kwargs):
        runtime = original_runtime(**kwargs)
        runtime.llm._retry_on_timeout = False
        runtime.llm._client.max_retries = 0
        return runtime

    def checkpoint():
        report["budget"] = budget.summary()
        for phase in report["phases"]:
            metrics = Path(phase["metrics_path"])
            rows = [json.loads(line) for line in metrics.read_text().splitlines()] if metrics.exists() else []
            for run in phase["runs"]:
                call_rows = [r for r in rows if r["call_id"] == run["call_id"]]
                run["usage"] = usage_for_call(call_rows) if call_rows else {
                    "model_calls": 0, "prompt_tokens": None, "cached_tokens": None,
                    "uncached_prompt_tokens": None, "completion_tokens": None, "cost_usd": None}
                if run.get("unreported_model_calls"):
                    run["known_usage_subtotal"] = dict(run["usage"])
                    run["usage"] = {k: None for k in run["usage"]}
                    run["usage"]["model_calls"] = len(call_rows) + run["unreported_model_calls"]
                run["cache_billing"] = cache_billing(run["usage"])
            phase["summary"] = aggregate(phase["runs"], {})
            phase["complete"] = len(phase["runs"]) == phase["planned_runs"]
        path.write_text(json.dumps(report, indent=2) + "\n")

    with patch.object(text_runner, "build_agent_runtime", no_retries):
        try:
            checkpoint()
            for planned in report["plan"]["phases"]:
                if budget.stopped:
                    break
                factor = planned["factor"]
                catalog_path = directory / f"catalog-x{factor:02d}.json"
                catalog = load_catalog(catalog_path)
                run_id = f"{experiment_id}-{planned['arm']}-x{factor:02d}"
                phase = {"arm": planned["arm"], "factor": factor, "run_id": run_id,
                         "exploratory": planned["arm"] == "exploratory-search-only",
                         "catalog_path": str(catalog_path), "catalog_sha256": sha256(catalog_path.read_bytes()).hexdigest(),
                         "metrics_path": str(BACKEND / "logs/evals" / f"{run_id}.jsonl"),
                         "planned_runs": planned["conversations"], "runs": []}
                report["phases"].append(phase)
                factory = phase_factory(planned, directory)
                for sid in CASES:
                    for repetition in range(1, planned["repetitions"] + 1):
                        if budget.stopped:
                            break
                        requests_before = budget.requests
                        # Scoped evaluation-only data injection: the same unchanged
                        # v5 patient driver/core/session runs over this derived catalog.
                        # load_dev_scenarios still checks the original blob independently.
                        with patch.object(text_integration, "load_catalog", return_value=catalog):
                            result = await text_integration.run_dev_case(sid, run_id=run_id, agent_factory=factory)
                        scored = evaluate_run(scenarios[sid], result)
                        scored.update(repetition=repetition, agent=result.agent,
                            patient_turn_metrics=result.patient_turn_metrics, driver_events=result.driver_events)
                        scored["admitted_model_calls"] = budget.requests - requests_before
                        metrics = Path(phase["metrics_path"])
                        rows = [json.loads(line) for line in metrics.read_text().splitlines()] if metrics.exists() else []
                        seen = sum(r["call_id"] == result.call_id for r in rows)
                        missing = max(0, scored["admitted_model_calls"] - seen)
                        if missing:
                            scored["unreported_model_calls"] = missing
                        phase["runs"].append(scored)
                        checkpoint()
                        print(f"{planned['arm']} x{factor} {sid}/{repetition}: "
                              f"{'PASS' if scored['passed'] else 'FAIL'} reported=${budget.summary()['reported_cost_usd']}", flush=True)
                    if budget.stopped:
                        break
            report["complete"] = (len(report["phases"]) == len(report["plan"]["phases"])
                and all(p["complete"] for p in report["phases"]) and not budget.stopped)
        finally:
            checkpoint()
    print(json.dumps({"report": str(path), "complete": report["complete"], "budget": budget.summary()}), flush=True)
    return report, path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-paid", action="store_true", required=True)
    args = parser.parse_args()
    offline, offline_path = measure_offline()
    if offline["plans"]["revised_6b"]["projected_usd_observed_cache"] >= 6:
        raise SystemExit("Expected cost is not below $6: user approval required; no request sent")
    asyncio.run(offline_wiring_check(offline, offline_path.parent))
    load_dotenv(BACKEND / ".env", override=False)
    with SpendGuard("8.00", strict_admission=True, bound_unknown=True) as budget:
        asyncio.run(run_scaling(offline, offline_path.parent, budget))


if __name__ == "__main__":
    main()
