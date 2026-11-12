"""Offline aggregation only; never calls a model or changes scored results."""
import argparse
import json
import math
from collections import Counter
from pathlib import Path


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    lo, hi = math.floor(index), math.ceil(index)
    return round(values[lo] + (values[hi] - values[lo]) * (index - lo), 3)


def tool_results(run):
    names = {}
    for message in run["context_messages"]:
        for call in message.get("tool_calls", []):
            names[call["id"]] = call["function"]
        if message.get("role") != "developer":
            continue
        try:
            envelope = json.loads(message["content"])
            if envelope.get("type") != "async_tool" or envelope.get("status") != "finished":
                continue
            result = envelope["result"]
            result = json.loads(result) if isinstance(result, str) else result
            yield names[envelope["tool_call_id"]], result
        except (ValueError, KeyError, TypeError):
            continue


def run_metrics(run):
    assertions = {a["name"]: a["passed"] for a in run["assertions"]}
    bookings = run["outcome_signature"]["bookings"]
    successful = len(bookings) if (assertions.get("booking_fields") and assertions.get("confirmation_recorded")) else 0
    invalid, book_statuses = 0, Counter()
    for function, result in tool_results(run):
        if function["name"] != "book_appointment":
            continue
        status = result.get("status")
        book_statuses[str(status)] += 1
        # Preparing the offer and asking for missing facts/consent are protocol,
        # not attempts to write a booking that failed validation.
        invalid += status in {"validation_required", "error", "blocked", "slot_taken"}
    times = [t["elapsed_ms"] for t in run["patient_turn_metrics"] if t["patient_turn"] > 0 and t["completed"]]
    return {
        "successful_bookings": successful, "invalid_booking_attempts": invalid,
        "booking_result_statuses": dict(book_statuses),
        "unnecessary_questions_logged": sum(e["type"] == "unnecessary_question" for e in run["driver_events"]),
        "completed_patient_turns": len(times), "latency_ms": times,
        "incomplete_patient_turns": sum(t["patient_turn"] > 0 and not t["completed"] for t in run["patient_turn_metrics"]),
    }


def aggregate(runs, annotations):
    measurements = [run_metrics(r) for r in runs]
    usages = [r["usage"] for r in runs]
    subtotals = [r.get("known_usage_subtotal", r["usage"]) for r in runs]
    known = all(u.get("cost_usd") is not None for u in usages)
    cost = round(sum(u["cost_usd"] for u in usages), 8) if known else None
    known_cost = round(sum(u["cost_usd"] for u in subtotals if u.get("cost_usd") is not None), 8)
    unknown_calls = sum(r.get("unreported_model_calls", 0) for r in runs)
    exposure = round(known_cost + unknown_calls * .32512, 8)
    successes = sum(m["successful_bookings"] for m in measurements)
    times = [x for m in measurements for x in m["latency_ms"]]
    severity = Counter()
    extras = 0
    for run in runs:
        key = f"{run['scenario_id']}/{run['repetition']}"
        note = annotations.get(key, {})
        if not run["passed"]:
            severity[note.get("severity", "unreviewed")] += 1
        extras += note.get("additional_unnecessary_questions", 0)
    return {
        "runs": len(runs), "passed": sum(r["passed"] for r in runs),
        "failed": sum(not r["passed"] for r in runs),
        "pass_rate": sum(r["passed"] for r in runs) / len(runs) if runs else None,
        "severity": dict(severity),
        "model_calls": sum(u["model_calls"] for u in usages),
        **{k: sum(u[k] for u in usages) if all(u.get(k) is not None for u in usages) else None
           for k in ("prompt_tokens", "cached_tokens", "uncached_prompt_tokens", "completion_tokens")},
        "known_token_subtotals": {k: sum(u[k] for u in subtotals if u.get(k) is not None)
                                  for k in ("prompt_tokens", "cached_tokens", "uncached_prompt_tokens", "completion_tokens")},
        "known_cost_usd": known_cost, "unreported_model_calls": unknown_calls,
        "maximum_cost_exposure_usd": exposure,
        "cost_usd": cost, "successful_bookings": successes,
        "cost_per_successful_booking_usd": round(cost / successes, 8) if successes and cost is not None else None,
        "known_cost_per_successful_booking_usd": round(known_cost / successes, 8) if successes else None,
        "maximum_cost_per_successful_booking_usd": round(exposure / successes, 8) if successes else None,
        "invalid_booking_attempts": sum(m["invalid_booking_attempts"] for m in measurements),
        "unnecessary_questions_logged": sum(m["unnecessary_questions_logged"] for m in measurements),
        "additional_unnecessary_questions_reviewed": extras,
        "unnecessary_questions": sum(m["unnecessary_questions_logged"] for m in measurements) + extras,
        "completed_patient_turns": len(times),
        "incomplete_patient_turns": sum(m["incomplete_patient_turns"] for m in measurements),
        "patient_turn_latency_ms_p50": percentile(times, .5),
        "patient_turn_latency_ms_p95": percentile(times, .95),
        "calls_per_repetition": [r["usage"]["model_calls"] for r in runs],
        "min_run_cost_usd": min(u["cost_usd"] for u in usages) if known and usages else None,
        "max_run_cost_usd": max(u["cost_usd"] for u in usages) if known and usages else None,
    }


def build_comparison(paths, annotations):
    reports = [json.loads(Path(path).read_text()) for path in paths]
    for field in ("evaluator_version", "evaluator_sha256", "execution_sha256", "scorer_version", "scenario_sha256", "catalog_blob_sha", "model", "execution"):
        assert reports[0][field] == reports[1][field], f"Mismatched {field}"
    assert reports[0]["execution"]["sdk_retries"] == 0
    assert reports[0]["execution"]["timeout_retries"] is False
    result = {"evaluator_version": reports[0]["evaluator_version"], "evaluator_sha256": reports[0]["evaluator_sha256"], "arms": {}}
    for report in reports:
        arm = report["arm"]
        notes = annotations.get(arm, {})
        result["arms"][arm] = {
            "run_id": report["run_id"], "complete": report["complete"], "budget": report["budget"],
            "overall": aggregate(report["runs"], notes),
            "scenarios": {sid: aggregate([r for r in report["runs"] if r["scenario_id"] == sid], notes)
                          for sid in sorted({r["scenario_id"] for r in report["runs"]})},
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("proposed")
    parser.add_argument("baseline")
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_comparison([args.proposed, args.baseline], json.loads(Path(args.annotations).read_text()))
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({arm: data["overall"] for arm, data in result["arms"].items()}, indent=2))
