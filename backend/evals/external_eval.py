"""Versioned external adapter: offline checks, pinning, private schema preflight, paid execution."""
import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from .external_contract import VERSION, ContractError, PatientDriver, compile_scenario, require
from .external_score import grade, saved_observation, tool_events
from .final_preflight import REFERENCES
from .external_io import INFRA_VERSION, EvidenceJournal, EvidenceWriteError, DurableBudgets, atomic_json

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
CONFIG = Path(__file__).with_name("external_config.json")
PIN = Path(__file__).with_name("external_pin_v1_2.json")
ASSET_MANIFEST = ROOT / "docs/results/revised-assets-manifest.json"
EVIDENCE = ROOT / "docs/results/external-offline-validation-v1.2.json"
REPORTS = ("comparison-proposed-v2-20261109-180827-8752c3.results.json", "comparison-baseline-20261109-182321-c4ee5f.results.json")


def config():
    value = json.loads(CONFIG.read_text())
    require(value["version"] == VERSION and value["model"] == "gpt-4o" and value["concurrency"] == 1
            and value["max_input_tokens"] == 128000 and value["max_completion_tokens"] == 512
            and value["sdk_retries"] == 0 and value["timeout_retries"] is False,
            "configuration_not_supported", "configuration")
    return value


def compile_dataset(data, catalog, count=None):
    from .loader import DEFAULT_CATALOG_PATH, git_blob_sha
    require(isinstance(data, dict), "object_required", "dataset")
    require(not set(data) - {"schema_version", "created_at", "dataset_role", "execution_status", "catalog", "contract", "scenarios"},
            "unsupported_dataset_field", "dataset")
    require(data.get("schema_version") in ("0.1", "external-contract-v1"), "unsupported_schema_version", "schema_version")
    require(isinstance(data.get("catalog"), dict) and data["catalog"].get("blob_sha") == git_blob_sha(DEFAULT_CATALOG_PATH),
            "catalog_pin_mismatch", "catalog.blob_sha")
    require(isinstance(data.get("contract"), dict), "contract_required", "contract")
    require(isinstance(data.get("dataset_role"), str) and bool(data["dataset_role"]), "dataset_role_required", "dataset_role")
    require(data["contract"].get("language") == "English" and data["contract"].get("timezone") == "America/Los_Angeles"
            and data["contract"].get("identity_is_synthetic") is True, "unsupported_contract_configuration", "contract")
    require(isinstance(data.get("scenarios"), list) and bool(data["scenarios"]), "scenarios_required", "scenarios")
    if count is not None:
        require(len(data["scenarios"]) == count, "scenario_count_mismatch", "scenarios")
    compiled = [compile_scenario(s, catalog) for s in data["scenarios"]]
    require(len({s["scenario"]["id"] for s in compiled}) == len(compiled), "duplicate_labels", "scenarios.id")
    # Prose/extensions stay in the review packet, including unfamiliar requirements.
    # Compatibility does not mean automatic scorability.
    for key, value in data["contract"].items():
        if key not in {"language", "timezone", "identity_is_synthetic", "evaluation_revision"}:
            require(isinstance(value, (str, list, dict, bool)), "unsupported_contract_value", "contract." + key)
            for item in compiled:
                item["review_required"].append("dataset.contract." + key)
    return compiled


def fingerprints():
    names = {"baseline_agent.py", "agent_runtime.py", "metrics_logging.py", "scheduling_agent.py", "scheduling_dialogue.py", "text_runner.py", "agents/catalog_scheduler.json", "data/catalog.json"}
    names.update(str(p.relative_to(BACKEND)) for folder in ("scheduling", "agent_builder") for p in (BACKEND / folder).glob("*.py"))
    names.update("evals/" + name for name in ("external_contract.py", "external_score.py", "external_eval.py", "external_budget.py", "external_config.json", "external_io.py", "external_restart_v1_2.json", "write_faults.py", "preflight_reviewed.py", "revise_assets.py", "review_rubric_v1_1.json", "scorer.py", "text_integration.py", "spend_guard.py", "dev_matrix.py", "loader.py", "final_preflight.py"))
    names.update({"tests/test_external_adapter.py", "tests/test_external_write_faults.py", "tests/test_external_persistence.py"})
    return {name: sha256((BACKEND / name).read_bytes()).hexdigest() for name in sorted(names)}


def verify_pin():
    from importlib.metadata import version
    pinned = json.loads(PIN.read_text())
    require(pinned["version"] == VERSION and pinned["infrastructure_version"] == INFRA_VERSION and pinned["files"] == fingerprints(), "adapter_pin_mismatch", "pin")
    require(sha256(EVIDENCE.read_bytes()).hexdigest() == pinned["offline_evidence_sha256"], "offline_evidence_pin_mismatch", "pin")
    require(all(version(k) == v for k, v in pinned["packages"].items()), "dependency_version_mismatch", "pin")
    require(sha256(ASSET_MANIFEST.read_bytes()).hexdigest() == pinned["asset_manifest_sha256"], "asset_manifest_pin_mismatch", "pin")
    return pinned


def load_external(path, kind, catalog):
    """Only called after pinned offline checks. Never prints case data."""
    require(Path(path).resolve().is_relative_to(ROOT) is False, "external_path_required", "path")
    verify_pin()
    asset = json.loads(ASSET_MANIFEST.read_text())["assets"][kind]
    raw = Path(path).read_bytes()
    require(Path(path).resolve() == Path(asset["revised_path"]).resolve(), "revised_path_mismatch", "source")
    require(sha256(raw).hexdigest() == asset["revised_sha256"], "revised_hash_mismatch", "source")
    require(sha256(Path(asset["original_path"]).read_bytes()).hexdigest() == asset["original_sha256"], "original_hash_mismatch", "source")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ContractError("malformed_json", "source") from None
    from copy import deepcopy
    from .write_faults import normalize_faults
    normalized = deepcopy(data)
    for source in normalized["scenarios"]:
        if "faults" in source:
            source["faults"] = normalize_faults(source["faults"])
    # Only fault aliases/stage declarations differ; fixtures and all expectations stay exact.
    output = Path(path).with_name(kind + ".boundary-v1.1.json")
    body = (json.dumps(normalized, ensure_ascii=False, indent=2) + "\n").encode()
    if output.exists():
        require(output.read_bytes() == body, "normalized_revision_collision", "source")
    else:
        output.write_bytes(body)
    compiled = compile_dataset(normalized, catalog, REFERENCES[kind]["recorded_scenarios"])
    return compiled, {**asset, "normalized_path": str(output), "normalized_sha256": sha256(body).hexdigest(),
                      "normalization": "fault aliases and explicit write stage only; availability unchanged"}


def replay(catalog, compiled):
    by_label = {c["scenario"]["id"]: c for c in compiled}  # Join saved records only; no behavior dispatch.
    rows = []
    for name in REPORTS:
        path = BACKEND / "logs/evals" / name
        original = json.loads(path.read_text())
        for run in original["runs"]:
            result = grade(by_label[run["scenario_id"]], saved_observation(run), catalog)
            old = {a["name"]: a["passed"] for a in run["assertions"]}
            new = {a["name"]: a["passed"] for a in result["assertions"]}
            rows.append({"source_run_id": original["run_id"], "source_sha256": sha256(path.read_bytes()).hexdigest(),
                "scenario_id": run["scenario_id"], "repetition": run["repetition"], "old_passed": run["passed"],
                "new_status": result["status"], "new_passed": result["passed"],
                "common_assertion_disagreements": {k: {"old": old[k], "new": new[k]} for k in old.keys() & new.keys() if old[k] != new[k]},
                "legacy_checks_not_reproduced_automatically": sorted(old.keys() - new.keys()),
                "new_automatic_failures": [a["name"] for a in result["assertions"] if a["passed"] is False],
                "required_review": result["required_review"],
                "explanation": "New version: prose rules/forbidden/explanation require review; absent saved state stays unknown. No missing trace is reconstructed. Remaining common differences require explicit review."})
    return rows


def validate_dev():
    from scheduling import load_catalog
    from .loader import load_dev_scenarios, DEFAULT_CATALOG_PATH
    from openai.resources.chat.completions import AsyncCompletions
    catalog = load_catalog(DEFAULT_CATALOG_PATH)
    compiled = compile_dataset(load_dev_scenarios(), catalog)
    tested_files = fingerprints()
    with patch.object(AsyncCompletions, "create", side_effect=AssertionError("Offline validation attempted an API call")) as network:
        suite = unittest.defaultTestLoader.loadTestsFromNames(["tests.test_external_adapter", "tests.test_external_write_faults", "tests.test_external_persistence"])
        def test_names(group):
            for test in group:
                if isinstance(test, unittest.TestSuite):
                    yield from test_names(test)
                else:
                    yield test.id()
        names = list(test_names(suite))
        capture = io.StringIO()
        tests = unittest.TextTestRunner(stream=capture, verbosity=1).run(suite)
        saved = replay(catalog, compiled)
        network.assert_not_called()
    require(tests.wasSuccessful(), "offline_validation_failed", "tests")
    require(tested_files == fingerprints(), "sources_changed_during_validation", "tests")
    evidence = {"version": VERSION, "infrastructure_version": INFRA_VERSION, "api_calls": 0, "external_contents_accessed": False,
        "tested_fingerprints": tested_files, "test_names": names,
        "tests_run": tests.testsRun, "test_failures": len(tests.failures), "test_errors": len(tests.errors),
        "dev_scenarios_compiled": len(compiled), "replay": saved,
        "replay_summary": {"runs": len(saved), "old_passes": sum(r["old_passed"] for r in saved),
            "new_passes": sum(r["new_passed"] for r in saved),
            "review_required": sum(r["new_status"] == "review_required" for r in saved),
            "failed": sum(r["new_status"] == "failed" for r in saved),
            "infrastructure_failure": sum(r["new_status"] == "infrastructure_failure" for r in saved)}}
    EVIDENCE.write_text(json.dumps(evidence, indent=2) + "\n")
    return {k: v for k, v in evidence.items() if k != "replay"}


def pin():
    from importlib.metadata import version
    import subprocess
    from scheduling import load_catalog, SchedulingEngine
    from scheduling_agent import build_scheduling_agent
    from baseline_agent import build_baseline_agent
    from .loader import DEFAULT_CATALOG_PATH, git_blob_sha
    from .version import evaluator_sha256
    evidence = json.loads(EVIDENCE.read_text())
    require(evidence["version"] == VERSION and evidence["test_errors"] == evidence["test_failures"] == 0
            and evidence["api_calls"] == 0 and evidence["external_contents_accessed"] is False, "successful_offline_evidence_required", "pin")
    require(evidence["tested_fingerprints"] == fingerprints(), "untested_source_change", "pin")
    config()
    catalog = load_catalog(DEFAULT_CATALOG_PATH)
    identities = {name: factory(SchedulingEngine(catalog, []), catalog, availability_mode="eval_fixture").session_metadata
                  for name, factory in (("proposed", build_scheduling_agent), ("baseline", build_baseline_agent))}
    require(identities["proposed"]["agent_revision"] == "40db1b587b5790ab2c92bc642edbc55e67f0d44ebd8d4f1267de29e1e86ebdc5"
            and identities["baseline"]["agent_revision"] == "68d02acb9a89a72c279c3410001e2b184438abce7f7c714ce39a0e87ddf4f623"
            and evaluator_sha256() == "97117348b6d00263d60c0561381841e3fc50e843873a53b60e827a8c7415a996",
            "frozen_identity_mismatch", "pin")
    value = {"version": VERSION, "infrastructure_version": INFRA_VERSION, "files": fingerprints(), "offline_evidence_sha256": sha256(EVIDENCE.read_bytes()).hexdigest(),
             "configuration_sha256": sha256(CONFIG.read_bytes()).hexdigest(), "paid_authorized": False,
             "asset_manifest_sha256": sha256(ASSET_MANIFEST.read_bytes()).hexdigest(),
             "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
             "catalog_blob_sha": git_blob_sha(DEFAULT_CATALOG_PATH), "agent_identities": identities,
             "legacy_evaluator_behavior_sha256": evaluator_sha256(),
             "packages": {k: version(k) for k in ("pipecat-ai", "pipecat-ai-flows", "openai", "tiktoken")}}
    PIN.write_text(json.dumps(value, indent=2) + "\n")
    return {"version": VERSION, "pin_sha256": sha256(PIN.read_bytes()).hexdigest(), "files": len(value["files"]), "paid_authorized": False}


def live_observation(engine, transcript, context, driver, runner_error=False, infra=False, limited=False):
    return {"state": asdict(engine.state), "bookings": engine.bookings, "transcript": transcript,
        "tool_events": list(tool_events(context)), "driver_events": list(driver.events),
        "tool_attempts": [c["function"]["name"] for m in context for c in m.get("tool_calls", [])],
        "policy_codes": [i["code"] for i in engine._policy_issues(require_identity=True) if i["kind"] == "blocked"],
        "runner_error": runner_error, "infrastructure_failure": infra, "evaluation_limited": limited}


async def run_one(compiled, catalog, arm, run_id, cfg, evidence=None, metrics_log=None):
    from time import perf_counter
    from scheduling import SchedulingEngine
    from scheduling_agent import build_scheduling_agent
    from baseline_agent import build_baseline_agent
    from text_runner import TextAgentSession
    source = compiled["scenario"]
    engine = SchedulingEngine(catalog, source["availability_fixture"], now=datetime.fromisoformat(cfg["now"]))
    factory = build_scheduling_agent if arm == "proposed" else build_baseline_agent
    builder = factory(engine, catalog, availability_mode=cfg["availability_mode"])
    from .write_faults import WriteFaultController
    faults = WriteFaultController(engine, source.get("faults", []))
    builder.set_function_handler_wrapper(
        (lambda name, handler: evidence.wrap_tool(name, faults.wrap(name, handler))) if evidence else faults.wrap)
    # Only catalog+fixtures go to the engine/builder. Gold and private fact cards do not.
    session = TextAgentSession(builder=builder, run_id=run_id, faults=[], metrics_log=metrics_log,
        on_slot_taken=engine.mark_slot_unavailable, turn_timeout=cfg["patient_turn_timeout_seconds"])
    session._runtime.llm._retry_on_timeout = False
    session._runtime.llm._client.max_retries = 0
    if evidence:
        evidence.context.update(call_id=session.call_id, **builder.session_metadata)
        evidence.emit("conversation_started", metrics_path=str(session.metrics_log))
    driver = PatientDriver.from_compiled(compiled)
    transcript = []; times = []; infra = False; limited = False; runner_error = False
    async def measured(operation, patient_turn):
        start = perf_counter(); done = False
        if evidence: evidence.emit("turn_started", patient_turn=patient_turn)
        try:
            result = await operation; done = True
            if evidence:
                evidence.emit("assistant_message", patient_turn=patient_turn, text=result.assistant_text, node=result.node,
                              ended=result.ended, tool_names=list(result.tool_calls), context_messages=session.context_messages)
            return result
        finally:
            timing = {"patient_turn": patient_turn, "completed": done, "elapsed_ms": round((perf_counter()-start)*1000, 3)}
            times.append(timing)
            if evidence: evidence.emit("turn_finished", **timing)
    try:
        startup = await measured(session.start(), 0)
        transcript.append({"role": "assistant", "text": startup.assistant_text})
        patient_text = source["opening"]
        for turn in range(1, cfg["max_patient_turns"] + 1):
            if evidence: evidence.emit("patient_message", patient_turn=turn, text=patient_text)
            result = await measured(session.send(patient_text), turn)
            transcript.extend([{"role": "patient", "text": patient_text}, {"role": "assistant", "text": result.assistant_text,
                               "tools": list(result.tool_calls), "node": result.node}])
            observation = live_observation(engine, transcript, session.context_messages, driver)
            observation["fault_evidence"] = faults.evidence()
            scored = grade(compiled, observation, catalog)
            if result.ended or engine.bookings:
                break  # Required transcript review is still pending, never promoted to pass.
            offered = [engine._present_slot(engine._slots[x]) for x in sorted(engine.state.offered_slot_ids)]
            driver.availability = [s for s in source["availability_fixture"] if s["slot_id"] not in engine._unavailable_slot_ids]
            offered = [s for s in offered if s["slot_id"] not in engine._unavailable_slot_ids]
            patient_text = driver.reply(result.assistant_text, catalog, offered, engine.state.last_candidates)
            if patient_text is None:
                limited = not all(a["passed"] is True for a in scored["assertions"])
                break
        else:
            limited = True
    except EvidenceWriteError:
        raise  # Logging failure is fatal infrastructure, never an agent outcome.
    except (TimeoutError, ConnectionError):
        infra = runner_error = True
    except Exception as error:
        runner_error = True
        # Pipeline ErrorFrames can wrap provider failures in RuntimeError.
        infra = type(error).__name__ in {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError"}
        infra |= any(x in str(error).casefold() for x in ("llm completion timeout", "connection error", "rate limit", "apiconnectionerror", "apitimeouterror"))
        limited = not infra
    finally:
        try:
            await session.close()
        finally:
            if evidence:
                evidence.emit("conversation_snapshot", context_messages=session.context_messages,
                    observation=live_observation(engine, transcript, session.context_messages, driver, runner_error, infra, limited),
                    patient_turn_metrics=times, fault_evidence=faults.evidence(), fault_events=faults.events)
    observation = live_observation(engine, transcript, session.context_messages, driver, runner_error, infra, limited)
    observation["fault_evidence"] = faults.evidence()
    observation["fault_events"] = faults.events
    return {**grade(compiled, observation, catalog), "call_id": session.call_id, "run_id": run_id,
            "agent": builder.session_metadata, "transcript": transcript, "patient_turn_metrics": times,
            "driver_events": driver.events, "observation": observation}


def restart_plan(sets, path):
    plan_path = Path(__file__).with_name("external_restart_v1_2.json")
    require(Path(path).resolve() == plan_path.resolve(), "pinned_restart_plan_required", "restart")
    value = json.loads(plan_path.read_text())
    history_path = ROOT / value["historical_inventory"]
    require(sha256(history_path.read_bytes()).hexdigest() == value["historical_inventory_sha256"], "restart_history_changed", "restart")
    summary_path = ROOT / "docs/results/final-evaluation/summary.json"
    require(sha256(summary_path.read_bytes()).hexdigest() == value["original_attempts_summary_sha256"], "restart_cost_history_changed", "restart")
    history = json.loads(history_path.read_text())
    expected = {(r["batch"],r["arm"],r["scenario_id"]):r for r in history}
    sources = {(kind,c["scenario"]["id"]):c for kind,cases in sets.items() for c in cases}
    jobs = []
    for row in value["conversations"]:
        key = (row["batch"],row["arm"],row["scenario_id"])
        old = expected[key]
        require(row["prior_status"] == old["status"], "restart_status_changed", "restart")
        if row["replacement_for"]:
            require(old["attempted"] and old["status"] == "infrastructure_failure"
                    and row["replacement_for"]["run_id"] == old["run_id"]
                    and row["replacement_for"]["call_id"] == old["call_id"], "invalid_replacement", "restart")
        else:
            require(not old["attempted"] and old["status"] == "not_run", "invalid_new_attempt", "restart")
        jobs.append((row["batch"],row["arm"],sources[(row["batch"],row["scenario_id"])],1,row["replacement_for"]))
    require(len(jobs)==40 and len({(a,b,c["scenario"]["id"]) for a,b,c,_,_ in jobs})==40
            and all(row["replacement_for"] for row in value["conversations"][:2])
            and not any(row["replacement_for"] for row in value["conversations"][2:]), "restart_scope_changed", "restart")
    return jobs


def checkpoint(path, report, metrics, budget):
    from .dev_matrix import usage_for_call
    rows = [json.loads(x) for x in metrics.read_text().splitlines()] if metrics.exists() else []
    journal_path = report.get("evidence_path")
    events = [json.loads(x) for x in Path(journal_path).read_text().splitlines()] if journal_path else None
    for run in report["runs"]:
        own = [x for x in rows if x["call_id"] == run["call_id"]]
        run["usage"] = usage_for_call(own) if own else None
        sdk_complete = True
        if events is not None:
            admitted = {e["request_id"] for e in events if e.get("call_id") == run["call_id"] and e["event"] == "request_reserved"}
            reported = {e["request_id"] for e in events if e.get("call_id") == run["call_id"] and e["event"] == "request_usage" and e["usage_status"] == "reported"}
            sdk_complete = len(admitted) == run["admitted_requests"] and admitted == reported
            run["request_coverage"] = {"admitted": len(admitted), "complete_usage": len(reported), "certified": sdk_complete}
        if not sdk_complete or len(own) != run["admitted_requests"] or run["usage"] is None or run["usage"]["cost_usd"] is None:
            run["known_usage_subtotal"] = run["usage"] if sdk_complete else None
            run["usage"] = None
    report["budget"] = budget.summary()
    atomic_json(path, report)


async def run_batch(catalog, sets, cfg, args):
    run_id = "external-infra-v1.2-" + args.batch + "-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6]
    path = BACKEND / "logs/evals" / f"{run_id}.results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    metrics = path.with_name(run_id + ".jsonl")
    evidence = EvidenceJournal(path.with_name(run_id + ".events.jsonl"), run_id)
    report = {"version": VERSION, "infrastructure_version": INFRA_VERSION, "configuration": cfg,
              "configuration_sha256": sha256(CONFIG.read_bytes()).hexdigest(),
              "adapter_pin_sha256": sha256(PIN.read_bytes()).hexdigest(), "approval_reference": args.approval_ref,
              "run_id": run_id, "runs": [], "complete": False, "metrics_path": str(metrics),
              "evidence_path": str(evidence.path), "batch": args.batch, "dataset_hashes": args.dataset_hashes}
    if args.batch == "restart":
        plan = restart_plan(sets, args.restart_plan)
        limits = {"heldout": args.heldout_max_cost_usd, "robustness": args.robustness_max_cost_usd}
        report["restart_plan_sha256"] = sha256(Path(args.restart_plan).read_bytes()).hexdigest()
    else:
        plan = ([("heldout", arm, c, 1, None) for arm in ("proposed", "baseline") for c in sets["heldout"]]
                if args.batch == "heldout" else [("robustness", "proposed", c, 1, None) for c in sets["robustness"]])
        limits = {args.batch: args.max_cost_usd}
    with DurableBudgets(limits, cfg, evidence) as budget:
        evidence.emit("batch_started", planned_conversations=len(plan), budget=budget.summary(), identities=report)
        try:
            for kind, arm, compiled, repetition, replacement in plan:
                if budget.stopped: break
                budget.use(kind)
                attempt = {"dataset": kind, "arm": arm, "scenario_id": compiled["scenario"]["id"],
                           "repetition": repetition, "attempt_id": uuid4().hex, "replacement_for": replacement}
                evidence.context = dict(attempt)
                report["pending_attempt"] = attempt
                evidence.emit("attempt_planned", budget=budget.summary())
                checkpoint(path, report, metrics, budget)
                if budget.accounted + budget.ceiling > budget.limit:
                    budget.stopped = True; budget.stop_reason = "Full per-request exposure does not fit; next attempt not admitted"
                    report["pending_attempt"]["status"] = "not_admitted_budget"
                    evidence.emit("attempt_not_admitted", budget=budget.summary())
                    break
                before = budget.requests
                result = await run_one(compiled, catalog, arm, run_id, cfg, evidence=evidence, metrics_log=metrics)
                result.update(attempt, admitted_requests=budget.requests-before)
                if budget.stopped:
                    result.update(status="incomplete_budget", passed=False, agent_assessment="not_assessable")
                # Commit the conversation independently BEFORE aggregate serialization/export.
                evidence.emit("conversation_result", result=result, budget=budget.summary())
                result_path = path.with_name(run_id + "." + attempt["attempt_id"] + ".conversation.json")
                atomic_json(result_path, result)
                result["conversation_result_path"] = str(result_path)
                report["runs"].append(result); report.pop("pending_attempt", None)
                checkpoint(path, report, metrics, budget)
            report["complete"] = len(report["runs"]) == len(plan) and not budget.stopped
            checkpoint(path, report, metrics, budget)
            evidence.emit("batch_finished", complete=report["complete"], budget=budget.summary())
        except BaseException as error:
            evidence.emit("batch_aborted", error_type=type(error).__name__, budget=budget.summary(),
                          results_committed=len(report["runs"]))
            raise  # No resume, no automatic retry, and no further request after export failure.
    return {"report": str(path), "evidence": str(evidence.path), "complete": report["complete"],
            "budget": report["budget"], "attempts": len(report["runs"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate-dev", "pin", "preflight", "prepare-restart", "run-paid"))
    parser.add_argument("--heldout-path")
    parser.add_argument("--robustness-path")
    parser.add_argument("--max-cost-usd")
    parser.add_argument("--approval-ref")
    parser.add_argument("--batch", choices=("heldout", "robustness", "restart"))
    parser.add_argument("--restart-plan")
    parser.add_argument("--heldout-max-cost-usd")
    parser.add_argument("--robustness-max-cost-usd")
    args = parser.parse_args()
    try:
        if args.command == "validate-dev":
            result = validate_dev()
        elif args.command == "pin":
            result = pin()
        else:
            from scheduling import load_catalog
            from .loader import DEFAULT_CATALOG_PATH
            cfg = config(); catalog = load_catalog(DEFAULT_CATALOG_PATH)
            if args.command == "run-paid":
                require(bool(args.approval_ref), "explicit_approval_reference_required", "approval")
                require(bool(args.batch), "explicit_batch_required", "batch")
                if args.batch == "restart":
                    require(bool(args.restart_plan and args.heldout_max_cost_usd and args.robustness_max_cost_usd), "restart_plan_and_separate_caps_required", "approval")
                else:
                    require(bool(args.max_cost_usd), "explicit_cost_cap_required", "approval")
            require(bool(args.heldout_path and args.robustness_path), "explicit_paths_required", "paths")
            sets = {}; hashes = {}
            for kind, path in (("heldout", args.heldout_path), ("robustness", args.robustness_path)):
                try:
                    sets[kind], hashes[kind] = load_external(path, kind, catalog)
                except ContractError as error:
                    error.external_set = kind
                    raise
            if args.command == "preflight":
                from .preflight_reviewed import inspect_offline
                result = inspect_offline(catalog, sets, hashes)
                result.update(version=VERSION, infrastructure_version=INFRA_VERSION, pin_verified=True, api_calls=0, scenario_contents_printed=False,
                              adapter_pin_sha256=sha256(PIN.read_bytes()).hexdigest())
                (ROOT / "docs/results/external-preflight-v1.2.json").write_text(json.dumps(result, indent=2) + "\n")
            elif args.command == "prepare-restart":
                require(bool(args.restart_plan), "pinned_restart_plan_required", "restart")
                jobs = restart_plan(sets, args.restart_plan)
                result = {"version": VERSION, "infrastructure_version": INFRA_VERSION,
                    "api_calls": 0, "paid_authorized": False, "dataset_hashes": hashes,
                    "adapter_pin_sha256": sha256(PIN.read_bytes()).hexdigest(),
                    "restart_plan_sha256": sha256(Path(args.restart_plan).read_bytes()).hexdigest(),
                    "conversations": len(jobs), "replacements_first": sum(bool(j[4]) for j in jobs),
                    "previously_unrun": sum(not j[4] for j in jobs),
                    "batch_counts": {k: sum(j[0] == k for j in jobs) for k in sets}}
                atomic_json(ROOT / "docs/results/external-restart-preflight-v1.2.json", result)
            else:
                args.dataset_hashes = hashes
                result = asyncio.run(run_batch(catalog, sets, cfg, args))
        print(json.dumps(result, indent=2))
        return 0
    except ContractError as error:
        result = {"status": "unsupported", "code": error.code, "field": error.path, "api_calls": 0,
                  "external_set": getattr(error, "external_set", None),
                  "scenario_contents_printed": False, "no_scenario_change": True}
        if args.command == "preflight":
            (ROOT / "docs/results/external-preflight-v1.2.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
