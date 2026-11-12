"""Explicit paid entrypoint for the baseline, reusing the unchanged patient/scorer."""
import argparse
import asyncio
import json

import text_runner
from baseline_agent import build_baseline_agent
from . import text_integration
from .dev_matrix import run_matrix
from .spend_guard import SpendGuard


async def run_baseline(repetitions=3):
    original = text_integration.build_scheduling_agent
    original_runtime = text_runner.build_agent_runtime

    def no_retries(**kwargs):
        runtime = original_runtime(**kwargs)
        runtime.llm._retry_on_timeout = False
        runtime.llm._client.max_retries = 0
        return runtime

    # Patch factory references only for this standalone baseline run; no frozen
    # source or shared state implementation changes. All sessions use baseline.
    text_integration.build_scheduling_agent = build_baseline_agent
    text_runner.build_agent_runtime = no_retries
    try:
        report, path = await run_matrix(repetitions, 1)
        report["arm"] = "full_catalog_baseline"
        path.write_text(json.dumps(report, indent=2) + "\n")
        return report, path
    finally:
        text_integration.build_scheduling_agent = original
        text_runner.build_agent_runtime = original_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-paid", action="store_true", required=True)
    parser.add_argument("--max-cost-usd", type=float, required=True)
    args = parser.parse_args()
    with SpendGuard(args.max_cost_usd) as budget:
        try:
            report, path = asyncio.run(run_baseline())
            print(json.dumps(report["summary"]))
            print(f"results={path}")
        finally:
            print(json.dumps(budget.summary()))


if __name__ == "__main__":
    main()
