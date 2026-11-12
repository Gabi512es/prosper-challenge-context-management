"""Metadata-only final-evaluation preparation. No scenario parsing or API calls.

Only explicit external paths may be hashed; no discovery and no execute mode.
The existing DEV-specific evaluator cannot yet claim external-contract coverage.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
REFERENCES = {
    "heldout": {"filename": "prosper_heldout_scenarios.json", "recorded_scenarios": 16,
                "sha256": "d41abdad3defe405a48becc55a97d4d153c3c3b27a4eff5f5518db8a2dedd1b6"},
    "robustness": {"filename": "prosper_robustness_scenarios.json", "recorded_scenarios": 8,
                  "sha256": "c5de085b51996c51afaa9dbc3b40c392452d0eec28760b422ced2a6f74aa6c19"},
}
REPORTS = {
    "proposed": "comparison-proposed-v2-20261109-180827-8752c3.results.json",
    "baseline": "comparison-baseline-20261109-182321-c4ee5f.results.json",
}


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def external_status(kind, explicit_path):
    result = {**REFERENCES[kind], "reference_source": "docs/decisions.md:447-450",
              "content_parsed": False, "content_copied": False}
    if not explicit_path:
        return {**result, "path": None, "actual_sha256": None, "status": "not_verified_exact_path_unavailable"}
    path = Path(explicit_path).expanduser().resolve()
    result["path"] = str(path)
    if path.is_relative_to(ROOT):
        return {**result, "actual_sha256": None, "status": "blocked_path_must_be_external"}
    try:
        actual = digest(path)  # Bytes only: never json.loads/read_text on external sources.
    except OSError as error:
        return {**result, "actual_sha256": None, "status": "unavailable", "error_type": type(error).__name__}
    return {**result, "actual_sha256": actual, "status": "verified" if actual == result["sha256"] else "hash_mismatch"}


def prepare(heldout_path=None, robustness_path=None):
    reports = {k: json.loads((BACKEND / "logs/evals" / v).read_text()) for k, v in REPORTS.items()}
    common = reports["proposed"]
    files = ("agents/catalog_scheduler.json", "data/catalog.json", "baseline_agent.py", "agent_runtime.py",
             "scheduling_agent.py", "scheduling_dialogue.py", "agent_builder/builder.py", "text_runner.py",
             "evals/scorer.py", "evals/text_integration.py", "evals/version.py", "evals/spend_guard.py",
             "evals/comparison_matrix.py", "evals/final_preflight.py")
    fingerprints = {name: digest(BACKEND / name) for name in files}
    behavior = hashlib.sha256()
    for name in ("scorer.py", "text_integration.py"):
        behavior.update(name.encode() + b"\0" + (BACKEND / "evals" / name).read_bytes())
    catalog_bytes = (BACKEND / "data/catalog.json").read_bytes()
    catalog_blob = hashlib.sha1(f"blob {len(catalog_bytes)}\0".encode() + catalog_bytes).hexdigest()
    frozen_paths = ["backend/agents/catalog_scheduler.json", "backend/scheduling", "backend/scheduling_agent.py",
                    "backend/scheduling_dialogue.py", "backend/agent_builder", "backend/agent_runtime.py", "backend/text_runner.py",
                    "backend/data/catalog.json"]
    changes = subprocess.check_output(["git", "diff", "HEAD", "--name-only", "--", *frozen_paths], cwd=ROOT, text=True).splitlines()
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    profiles = {}
    for arm, report in reports.items():
        # Exclude the ENTIRE incomplete-usage conversation, rather than treat its
        # missing request as free. These are mix-dependent estimates, not results.
        complete = [r["usage"] for r in report["runs"] if r["usage"].get("cost_usd") is not None]
        n = len(complete)
        profiles[arm] = {"source_run_id": report["run_id"], "complete_usage_conversations": n,
            "excluded_incomplete_usage_conversations": len(report["runs"]) - n,
            "mean_usd": sum(u["cost_usd"] for u in complete) / n,
            "all_cold_mean_usd_same_calls": sum((u["prompt_tokens"] * 2.5 + u["completion_tokens"] * 10) / 1e6 for u in complete) / n}
    phases = []
    for dataset, arm, count, repetitions in (("heldout", "proposed", 16, 2), ("heldout", "baseline", 16, 2),
                                            ("robustness", "proposed", 8, 1)):
        n = count * repetitions
        phases.append({"dataset": dataset, "arm": arm, "scenarios": count, "repetitions": repetitions,
            "conversations": n, "expected_usd": round(n * profiles[arm]["mean_usd"], 6),
            "conservative_allowance_usd": round(n * profiles[arm]["all_cold_mean_usd_same_calls"] * 1.5, 6)})
    versions = {
        "current_git_commit": git("rev-parse", "HEAD"), "proposed_v2_tag_commit": git("rev-parse", "proposed-v2"),
        "historical_comparison_git_commits": {k: r["git_commit"] for k, r in reports.items()},
        "source_agent_revision_sha256": fingerprints["agents/catalog_scheduler.json"],
        "evaluated_agent_revisions": {k: r["runs"][0]["agent"]["agent_revision"] for k, r in reports.items()},
        "catalog_git_blob_sha1": catalog_blob, "catalog_file_sha256": fingerprints["data/catalog.json"],
        "rendered_baseline_catalog_sha256": reports["baseline"]["runs"][0]["agent"]["catalog_prefix_sha256"],
        "evaluator_version": common["evaluator_version"], "evaluator_behavior_sha256": behavior.hexdigest(),
        "historical_execution_sha256": common["execution_sha256"], "current_frozen_path_changes": changes,
        "fingerprints_sha256": fingerprints,
    }
    statuses = {"heldout": external_status("heldout", heldout_path), "robustness": external_status("robustness", robustness_path)}
    return {"plan_version": "final-preparation-v1", "paid_authorized": False, "api_calls": 0,
        "scenario_contents_read": False, "external_sources": statuses, "versions": versions,
        "integrity_matches_historical": {
            "proposed_agent": versions["source_agent_revision_sha256"] == versions["evaluated_agent_revisions"]["proposed"],
            "evaluator": versions["evaluator_behavior_sha256"] == common["evaluator_sha256"],
            "catalog_blob": catalog_blob == common["catalog_blob_sha"], "frozen_paths": not changes},
        "configuration": {"model": "gpt-4o", "provider_snapshot": "not recorded/pinned",
            "temperature": "not explicitly set", "parallel_tool_calls": False, "context_strategy": "APPEND",
            "availability_mode": "eval_fixture", "synthetic_catalog_expansion": False,
            "planned_concurrency": 1, "planned_sdk_retries": 0, "planned_timeout_retries": False,
            "planned_max_completion_tokens": 512, "planned_patient_turn_timeout_seconds": 45,
            "existing_driver_clock": "2026-11-07T00:00:00-08:00", "clock_contract": "external fixture clock compatibility not yet verified"},
        "budget_projection": {"prices": common["pricing"], "profiles": profiles, "phases": phases,
            "conversations": 72, "expected_usd": round(sum(p["expected_usd"] for p in phases), 6),
            "all_cold_plus_50_percent_call_allowance_usd": round(sum(p["conservative_allowance_usd"] for p in phases), 6),
            "rounded_spending_allowance_usd": 9, "proposed_hard_global_cap_usd": 10,
            "unknown_request_exposure_bound_usd": .32512,
            "limitations": "Unseen case mix, driver compatibility and recovery lengths unknown. Not a quote or measured final spend."},
        "execution_status": "BLOCKED: current loader/driver/scorer are DEV-specific. No valid external paid command exists yet.",
        "required_decisions": ["Supply exact external paths; verify hashes using bytes only.",
            "Approve an external-contract driver/assertion adapter separately, or supply a compatible evaluator. No DEV-ID remapping.",
            "Approve the final paid batch/cap explicitly after preflight; prior scaling go is exhausted."],
        "voice_call_B": "pending manual verification; not a text-evaluation gate"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heldout-path")
    parser.add_argument("--robustness-path")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.heldout_path, args.robustness_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"manifest": str(args.output), "external_sources": report["external_sources"],
                      "budget_projection": report["budget_projection"], "execution_status": report["execution_status"]}, indent=2))
    return 2  # Intentionally not an executable/approved final-run entrypoint.


if __name__ == "__main__":
    raise SystemExit(main())
