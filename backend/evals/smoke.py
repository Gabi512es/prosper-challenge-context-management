"""Run a small paid scenario subset through the canonical scorer."""

import argparse
import asyncio
import json
from datetime import datetime
from uuid import uuid4

from agent_runtime import DEFAULT_EVAL_LOG_DIR

from .loader import load_dev_scenarios
from .scorer import SCORER_VERSION, evaluate_run
from .text_integration import run_dev_case


async def run(scenario_ids: list[str]) -> None:
    scenarios = {item["id"]: item for item in load_dev_scenarios()["scenarios"]}
    unknown = set(scenario_ids) - set(scenarios)
    if unknown:
        raise ValueError(f"Unknown development scenarios: {sorted(unknown)}")
    run_id = f"smoke-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    results = []
    for scenario_id in scenario_ids:
        run_result = await run_dev_case(scenario_id, run_id=run_id)
        scored = evaluate_run(scenarios[scenario_id], run_result)
        results.append(scored)
        print(f"{scenario_id}: {'PASS' if scored['passed'] else 'FAIL'}", flush=True)
    output = DEFAULT_EVAL_LOG_DIR / f"{run_id}.smoke.json"
    output.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "scorer_version": SCORER_VERSION,
                "results": results,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"results={output}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario_ids", nargs="+")
    args = parser.parse_args()
    asyncio.run(run(args.scenario_ids))


if __name__ == "__main__":
    main()
