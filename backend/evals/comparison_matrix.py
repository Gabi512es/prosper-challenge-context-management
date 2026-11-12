"""Versioned, sequential comparison measurements with partial-result checkpoints."""
import argparse
import asyncio
import hashlib
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from decimal import Decimal
import shutil

import text_runner
from baseline_agent import build_baseline_agent
from scheduling_agent import build_scheduling_agent
from .dev_matrix import PRICE_DATE, PRICE_PER_MILLION, PRICE_SOURCE, usage_for_call
from .loader import load_dev_scenarios
from .scorer import SCORER_VERSION, evaluate_run
from .spend_guard import SpendGuard
from .text_integration import run_dev_case
from .version import EVALUATOR_VERSION, evaluator_sha256

BACKEND = Path(__file__).resolve().parents[1]


async def measure_arm(arm, budget, resume=None):
    dataset = load_dev_scenarios()
    run_id = f"comparison-{arm}-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"
    path = BACKEND / "logs/evals" / f"{run_id}.results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path = path.with_name(f"{run_id}.jsonl")
    report = {
        "run_id": run_id, "arm": arm, "model": "gpt-4o", "planned_runs": 36,
        "evaluator_version": EVALUATOR_VERSION, "evaluator_sha256": evaluator_sha256(),
        "scorer_version": SCORER_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BACKEND, text=True).strip(),
        "scenario_sha256": hashlib.sha256((BACKEND / "evals/dev_scenarios.json").read_bytes()).hexdigest(),
        "catalog_blob_sha": dataset["catalog"]["blob_sha"], "metrics_path": str(metrics_path),
        "pricing": {"as_of": PRICE_DATE, "source": PRICE_SOURCE, "per_million_tokens_usd": PRICE_PER_MILLION},
        "execution": {"concurrency": 1, "sdk_retries": 0, "timeout_retries": False,
                      "max_completion_tokens": 512, "turn_limit": 9},
        "runs": [],
    }
    factory = build_scheduling_agent if arm == "proposed-v2" else build_baseline_agent
    execution_hash = hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name("spend_guard.py").read_bytes()).hexdigest()
    if resume:
        old_path = Path(resume)
        previous = json.loads(old_path.read_text())
        assert previous["arm"] == arm and previous["evaluator_version"] == EVALUATOR_VERSION
        assert previous["scenario_sha256"] == report["scenario_sha256"]
        assert previous["catalog_blob_sha"] == report["catalog_blob_sha"]
        archive = old_path.with_name(old_path.stem + ".paused.json")
        if not archive.exists():
            shutil.copyfile(old_path, archive)
        run_id, path = previous["run_id"], old_path
        metrics_path = Path(previous["metrics_path"])
        report["run_id"], report["metrics_path"] = run_id, str(metrics_path)
        report["created_at"] = previous["created_at"]
        report["runs"] = previous["runs"]
        report["resume_provenance"] = {"paused_report": str(archive), "original_evaluator_full_code_hash": previous["evaluator_sha256"],
            "reason": "Provider timeout; no failed case retried. Continue only unattempted cases with unknown cost bounded separately."}
        rows = [json.loads(line) for line in metrics_path.read_text().splitlines()]
        # Seed known cost from rows, and reserve the verified absolute ceiling
        # for admitted requests whose usage never arrived. Actual stays null.
        costs = [Decimal(str(usage_for_call([row])["cost_usd"])) for row in rows
                 if all(row.get(k) is not None for k in ("prompt_tokens", "cached_tokens", "completion_tokens"))]
        missing = previous["budget"]["requests"] - len(costs)
        assert missing >= 0
        budget.observed = costs
        budget.requests = previous["budget"]["requests"]
        budget.unknown_requests = missing
        budget.unknown_usage = bool(missing)
        budget.accounted = sum(costs, Decimal(0)) + missing * Decimal("0.32512")
        if missing and report["runs"]:
            report["runs"][-1]["unreported_model_calls"] = missing
    report["execution_sha256"] = execution_hash
    report["evaluator_hash_domain"] = "scorer.py + text_integration.py (unchanged across pause)"
    report["budget_unknown_policy"] = "Actual missing usage stays null; reserve $0.32512 per unreported request; admit only when that absolute ceiling fits."
    attempted = {(r["scenario_id"], r["repetition"]) for r in report["runs"]}
    original_runtime = text_runner.build_agent_runtime

    def no_retries(**kwargs):
        runtime = original_runtime(**kwargs)
        runtime.llm._retry_on_timeout = False
        runtime.llm._client.max_retries = 0
        return runtime

    def checkpoint():
        rows = [json.loads(line) for line in metrics_path.read_text().splitlines()] if metrics_path.exists() else []
        by_call = defaultdict(list)
        for row in rows:
            by_call[row["call_id"]].append(row)
        for run in report["runs"]:
            call_rows = by_call[run["call_id"]]
            run["usage"] = usage_for_call(call_rows) if call_rows else {
                "model_calls": 0, "prompt_tokens": None, "cached_tokens": None,
                "uncached_prompt_tokens": None, "completion_tokens": None, "cost_usd": None}
            if run.get("unreported_model_calls"):
                run["known_usage_subtotal"] = dict(run["usage"])
                run["usage"] = {k: None for k in run["usage"]}
                run["usage"]["model_calls"] = len(call_rows) + run["unreported_model_calls"]
        runs = report["runs"]
        report["summary"] = {
            "runs": len(runs), "passed": sum(r["passed"] for r in runs),
            "failed": sum(not r["passed"] for r in runs),
            "model_calls": sum(r["usage"]["model_calls"] for r in runs),
            "known_cost_usd": round(sum((r.get("known_usage_subtotal", r["usage"])["cost_usd"] or 0) for r in runs), 8),
            "runs_with_unknown_cost": sum(r["usage"]["cost_usd"] is None for r in runs),
        }
        report["budget"] = budget.summary()
        report["complete"] = len(runs) == 36 and not budget.stopped
        path.write_text(json.dumps(report, indent=2) + "\n")

    text_runner.build_agent_runtime = no_retries
    try:
        checkpoint()
        for scenario in dataset["scenarios"]:
            for repetition in range(1, 4):
                if (scenario["id"], repetition) in attempted:
                    continue
                if budget.stopped:
                    break
                unknown_before = budget.unknown_requests
                result = await run_dev_case(scenario["id"], run_id=run_id, agent_factory=factory)
                scored = evaluate_run(scenario, result)
                scored.update(repetition=repetition, agent=result.agent,
                              patient_turn_metrics=result.patient_turn_metrics, driver_events=result.driver_events)
                if budget.unknown_requests > unknown_before:
                    scored["unreported_model_calls"] = budget.unknown_requests - unknown_before
                report["runs"].append(scored)
                checkpoint()
                print(f"{arm} {scenario['id']} {repetition}: {'PASS' if scored['passed'] else 'FAIL'} "
                      f"cost_so_far=${report['summary']['known_cost_usd']:.6f}", flush=True)
            if budget.stopped:
                break
    finally:
        text_runner.build_agent_runtime = original_runtime
        checkpoint()
    print(json.dumps({"path": str(path), **report["summary"], "complete": report["complete"], "budget": report["budget"]}), flush=True)
    return report, path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=["proposed-v2", "baseline"], required=True)
    parser.add_argument("--max-cost-usd", required=True)
    parser.add_argument("--run-paid", required=True, action="store_true")
    parser.add_argument("--resume")
    args = parser.parse_args()
    with SpendGuard(args.max_cost_usd, strict_admission=True, bound_unknown=True) as budget:
        asyncio.run(measure_arm(args.arm, budget, args.resume))


if __name__ == "__main__":
    main()
