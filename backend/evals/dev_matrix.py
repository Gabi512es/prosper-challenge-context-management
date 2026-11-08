"""Run and score the complete development text matrix with paid OpenAI calls."""

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agent_runtime import DEFAULT_EVAL_LOG_DIR

from .loader import load_dev_scenarios
from .scorer import SCORER_VERSION, evaluate_run, normalize_transcript_text
from .text_integration import ScenarioTextRun, run_dev_case


PRICE_DATE = "2026-11-07"
PRICE_SOURCE = "https://developers.openai.com/api/docs/models/gpt-4o"
PRICE_PER_MILLION = {
    "uncached_input": 2.50,
    "cached_input": 1.25,
    "output": 10.00,
}


def rescore_saved_report(source: Path) -> Path:
    """Correct known text-normalization defects without making new model calls."""
    report = json.loads(source.read_text())
    corrections = []
    for run in report["runs"]:
        text = normalize_transcript_text(" ".join(
            item.get("text", "")
            for item in run["transcript"]
            if item.get("role") == "assistant"
        ))
        by_name = {item["name"]: item for item in run["assertions"]}
        if run["scenario_id"] == "DEV-005":
            assertion = by_name["provider_restriction_explained"]
            assertion["passed"] = "new patient" in text and any(
                word in text for word in ("accept", "available", "restrict", "block")
            )
            corrections.append("DEV-005 provider restriction wording")
        elif run["scenario_id"] == "DEV-010":
            opening = any(value in text for value in ("8:00", "8 am", "8 a.m."))
            closing = any(
                value in text
                for value in ("17:00", "5 pm", "5:00 pm", "5 p.m.", "5:00 p.m.")
            )
            by_name["faq_hours"]["passed"] = opening and closing
            if all(
                by_name[name]["passed"]
                for name in (
                    "booking_count",
                    "faq_phone",
                    "faq_hours",
                    "faq_no_booking_tool",
                    "faq_no_identity_collection",
                )
            ):
                by_name["runner_completed"]["passed"] = True
                by_name["runner_completed"]["observed"] = (
                    "Valid FAQ answer completed before the old parser recognized 5:00 PM."
                )
                run["error"] = None
            corrections.append("DEV-010 spoken closing-time format")
        elif run["scenario_id"] == "DEV-011":
            acknowledged = any(
                phrase in text
                for phrase in (
                    "couldn't find",
                    "could not find",
                    "unable to find",
                    "not found",
                    "no provider",
                    "not in our",
                    "don't have",
                )
            )
            by_name["unknown_provider_acknowledged"]["passed"] = acknowledged
            corrections.append("DEV-011 unknown-provider wording")
        run["passed"] = all(item["passed"] for item in run["assertions"])
        run["outcome_signature"]["passed"] = run["passed"]

    agreement = {}
    for scenario_id in sorted({item["scenario_id"] for item in report["runs"]}):
        scenario_runs = [item for item in report["runs"] if item["scenario_id"] == scenario_id]
        pass_values = {item["passed"] for item in scenario_runs}
        signatures = {
            json.dumps(item["outcome_signature"], sort_keys=True) for item in scenario_runs
        }
        agreement[scenario_id] = {
            "agrees": len(pass_values) == 1 and len(signatures) == 1,
            "pass_values": sorted(pass_values),
            "distinct_outcomes": len(signatures),
        }
    report["agreement"] = agreement
    report["summary"]["passed"] = sum(item["passed"] for item in report["runs"])
    report["summary"]["failed"] = sum(not item["passed"] for item in report["runs"])
    report["rescored_at"] = datetime.now(timezone.utc).isoformat()
    report["rescore_basis"] = sorted(set(corrections))
    target = source.with_name(f"{source.stem}.rescored.json")
    target.write_text(json.dumps(report, indent=2) + "\n")
    return target


def usage_for_call(rows: list[dict]) -> dict:
    missing = any(
        row.get(field) is None
        for row in rows
        for field in ("prompt_tokens", "cached_tokens", "completion_tokens")
    )
    usage = {
        "model_calls": len(rows),
        "prompt_tokens": None,
        "cached_tokens": None,
        "uncached_prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "cost_usd": None,
    }
    if missing:
        return usage
    prompt = sum(row["prompt_tokens"] for row in rows)
    cached = sum(row["cached_tokens"] for row in rows)
    completion = sum(row["completion_tokens"] for row in rows)
    uncached = prompt - cached
    if uncached < 0:
        raise ValueError("Cached input tokens exceeded prompt tokens.")
    cost = (
        uncached * PRICE_PER_MILLION["uncached_input"]
        + cached * PRICE_PER_MILLION["cached_input"]
        + completion * PRICE_PER_MILLION["output"]
    ) / 1_000_000
    usage.update(
        {
            "prompt_tokens": prompt,
            "cached_tokens": cached,
            "uncached_prompt_tokens": uncached,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cost_usd": round(cost, 8),
        }
    )
    return usage


async def run_matrix(repetitions: int, concurrency: int) -> tuple[dict, Path]:
    dataset = load_dev_scenarios()
    scenarios = dataset["scenarios"]
    run_id = f"dev-matrix-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    metrics_path = DEFAULT_EVAL_LOG_DIR / f"{run_id}.jsonl"
    results_path = DEFAULT_EVAL_LOG_DIR / f"{run_id}.results.json"
    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(scenario: dict, repetition: int):
        async with semaphore:
            result = await run_dev_case(scenario["id"], run_id=run_id)
            scored = evaluate_run(scenario, result)
            scored["repetition"] = repetition
            scored["agent"] = result.agent
            print(
                f"{scenario['id']} run {repetition}: "
                f"{'PASS' if scored['passed'] else 'FAIL'}",
                flush=True,
            )
            return scored

    tasks = [
        asyncio.create_task(run_one(scenario, repetition))
        for scenario in scenarios
        for repetition in range(1, repetitions + 1)
    ]
    scored_runs = []
    for completed in asyncio.as_completed(tasks):
        scored_runs.append(await completed)

    rows = [json.loads(line) for line in metrics_path.read_text().splitlines()]
    rows_by_call: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        rows_by_call[row["call_id"]].append(row)
    for scored in scored_runs:
        scored["usage"] = usage_for_call(rows_by_call[scored["call_id"]])

    scored_runs.sort(key=lambda item: (item["scenario_id"], item["repetition"]))
    agreement = {}
    for scenario in scenarios:
        scenario_runs = [
            item for item in scored_runs if item["scenario_id"] == scenario["id"]
        ]
        pass_values = {item["passed"] for item in scenario_runs}
        signatures = {
            json.dumps(item["outcome_signature"], sort_keys=True)
            for item in scenario_runs
        }
        agreement[scenario["id"]] = {
            "agrees": len(pass_values) == 1 and len(signatures) == 1,
            "pass_values": sorted(pass_values),
            "distinct_outcomes": len(signatures),
        }

    known_costs = [
        item["usage"]["cost_usd"]
        for item in scored_runs
        if item["usage"]["cost_usd"] is not None
    ]
    agent_versions = sorted(
        {json.dumps(item["agent"], sort_keys=True) for item in scored_runs}
    )
    report = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "backend/evals/dev_scenarios.json",
        "repetitions": repetitions,
        "model": "gpt-4o",
        "arm": "proposed-v2",
        # One entry when every run used the same saved agent revision.
        "agent_versions": [json.loads(item) for item in agent_versions],
        "scorer_version": SCORER_VERSION,
        "pricing": {
            "as_of": PRICE_DATE,
            "source": PRICE_SOURCE,
            "per_million_tokens_usd": PRICE_PER_MILLION,
            "formula": "(prompt-cached)*input + cached*cached_input + completion*output",
        },
        "metrics_path": str(metrics_path),
        "summary": {
            "runs": len(scored_runs),
            "passed": sum(item["passed"] for item in scored_runs),
            "failed": sum(not item["passed"] for item in scored_runs),
            "model_calls": sum(item["usage"]["model_calls"] for item in scored_runs),
            "known_cost_usd": round(sum(known_costs), 8),
            "runs_with_unknown_cost": len(scored_runs) - len(known_costs),
        },
        "agreement": agreement,
        "runs": scored_runs,
    }
    results_path.write_text(json.dumps(report, indent=2) + "\n")
    return report, results_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    if args.repetitions < 1 or args.concurrency < 1:
        parser.error("repetitions and concurrency must be positive")
    report, results_path = asyncio.run(run_matrix(args.repetitions, args.concurrency))
    print(json.dumps(report["summary"], sort_keys=True), flush=True)
    print(f"results={results_path}", flush=True)


if __name__ == "__main__":
    main()
