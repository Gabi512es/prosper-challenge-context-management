"""Read-only structural diagnostic, not a converter or evaluator. Never prints case values."""
import argparse
from collections import Counter
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re

from evals.external_contract import ContractError, FACTS, EXPECTED, compile_scenario
from evals.external_eval import compile_dataset, verify_pin
from evals.final_preflight import REFERENCES
from scheduling import SchedulingEngine, load_catalog

VERSION = "fixture-compatibility-audit-v1"
CONTRACT_FIELDS = {"integration", "language", "default_patient_behavior", "identity_is_synthetic", "referral_on_file", "confirmation", "availability", "timezone", "slot_horizon", "synchronization", "holdout", "grading"}
SCENARIO_FIELDS = {"id", "split", "category", "opening", "patient_facts", "reply_rules", "patient_script", "expected_outcome", "expected", "forbidden", "source_refs", "notes", "availability_fixture", "review_status", "faults"}


def safe_name(key):
    return key if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,80}", key) else "<non_identifier_field>"


def audit(path, kind, catalog):
    original = path.read_bytes(); digest = sha256(original).hexdigest()
    assert digest == REFERENCES[kind]["sha256"]
    data = json.loads(original); cases = data["scenarios"]
    assert len(cases) == REFERENCES[kind]["recorded_scenarios"]
    assert len({c["id"] for c in cases}) == len(cases)
    shapes = Counter(); body_errors = Counter(); full_errors = Counter(); unknown = Counter(); reviews = Counter()
    diagnostics = []; total = invalid = body_ok = full_ok = fixture_cases_ok = aware = review_cases = 0
    def inventory(values, allowed, prefix):
        for key, value in values.items():
            if key not in allowed:
                unknown[(prefix + safe_name(key), type(value).__name__)] += 1
    inventory(data["contract"], CONTRACT_FIELDS, "contract.")
    for i, case in enumerate(cases):
        try:
            compile_dataset({**data, "scenarios": [case]}, catalog); full_ok += 1
        except ContractError as error:
            full_errors[(error.code, error.path)] += 1
        try:
            compile_scenario(case, catalog); body_ok += 1
        except ContractError as error:
            body_errors[(error.code, error.path)] += 1
        try:
            SchedulingEngine(catalog, case["availability_fixture"]); fixture_cases_ok += 1
        except (KeyError, ValueError, TypeError):
            pass
        inventory(case, SCENARIO_FIELDS, "scenarios[].")
        inventory(case.get("patient_facts", {}), FACTS, "scenarios[].patient_facts.")
        expected = case.get("expected", {})
        inventory(expected, EXPECTED, "scenarios[].expected.")
        inventory(expected.get("required_facts", {}), {"location_id", "hours", "phone"}, "scenarios[].expected.required_facts.")
        required = []
        if expected.get("explanation"): required.append("prose explanation")
        required += ["prose forbidden criterion"] * len(case.get("forbidden", []))
        if case.get("reply_rules"): required.append("prose patient rules")
        if case.get("notes"): required.append("notes")
        required += ["dataset contract prose"] * sum(k in data["contract"] for k in
            ("default_patient_behavior", "confirmation", "availability", "grading", "referral_on_file", "slot_horizon"))
        required += ["explicit manual assertion"] * sum(r.get("kind") == "review" for r in expected.get("assertions", []))
        reviews.update(required); review_cases += bool(required)
        for j, slot in enumerate(case["availability_fixture"]):
            total += 1
            shapes[tuple(sorted((k, type(v).__name__) for k, v in slot.items()))] += 1
            try:
                start, end = datetime.fromisoformat(slot["start"]), datetime.fromisoformat(slot["end"])
                aware += bool(start.tzinfo is not None and end.tzinfo is not None and start < end)
            except (KeyError, ValueError, TypeError): pass
            try:
                SchedulingEngine(catalog, [slot])
            except (KeyError, ValueError, TypeError):
                invalid += 1
                appt = catalog.appointment_types_by_id.get(slot["appointment_type_id"])
                provider = catalog.providers_by_id.get(slot["provider_id"])
                location = catalog.locations_by_id.get(slot["location_id"])
                cap = bool(appt and provider and location and appt.id in provider.appointment_type_ids
                    and location.id in provider.location_ids and appt.required_capability
                    and appt.required_capability not in location.capabilities)
                diagnostics.append({"field_path": f"scenarios[{i}].availability_fixture[{j}]" + (".location_id" if cap else ""),
                    "validator": "SchedulingEngine._validate_slots",
                    "condition": "appointment_type.required_capability in location.capabilities" if cap else "other engine fixture validation",
                    "condition_result": False, "classification": "substantive data validity" if cap else "unresolved; do not repair",
                    "expected_structure": "six string fields; referenced location must have the appointment type's required capability",
                    "supplied_structure": "six string fields; existing location lacks the required capability" if cap else "not exposed"})
    assert path.read_bytes() == original
    counts = lambda values: [{"code": c, "field_path": p, "case_count": n} for (c, p), n in sorted(values.items())]
    return {"source_path": str(path), "recorded_sha256": REFERENCES[kind]["sha256"], "actual_sha256": digest, "hash_matches": True,
        "scenario_count": len(cases), "fixture_record_count": total,
        "fixture_structures": [{"fields_and_types": dict(shape), "record_count": n} for shape, n in shapes.items()],
        "engine_valid_fixture_records": total-invalid, "engine_invalid_fixture_records": invalid,
        "complete_engine_fixture_cases_accepted": fixture_cases_ok, "complete_engine_fixture_cases_rejected": len(cases)-fixture_cases_ok,
        "scenario_schema_compatible": full_ok, "scenario_schema_incompatible": len(cases)-full_ok,
        "schema_error_counts": counts(full_errors), "scenario_body_compatible": body_ok,
        "scenario_body_incompatible": len(cases)-body_ok, "scenario_body_first_error_counts": counts(body_errors),
        "timezone_aware_ordered_intervals": aware, "interval_count": total, "diagnostics": diagnostics,
        "unsupported_field_structures": [{"field_path": p, "supplied_type": t, "occurrences": n} for (p, t), n in sorted(unknown.items())],
        "manual_review": {"cases_with_required_prose_review": review_cases, "criterion_counts": dict(reviews),
                          "assertions_executed": False, "review_completed": False},
        "validation_scope": "Every complete scenario body and fixture array checked independently; error buckets are first failure per scope, not assertion outcomes."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heldout-path", type=Path, required=True)
    parser.add_argument("--robustness-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); pin = verify_pin()
    root = Path(__file__).resolve().parents[2]
    catalog = load_catalog(root / "backend/data/catalog.json")
    result = {"audit_version": VERSION, "diagnostic_script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "adapter_version": pin["version"], "adapter_pin_sha256": sha256((root / "backend/evals/external_pin.json").read_bytes()).hexdigest(),
        "api_calls": 0, "source_files_changed": False, "source_contents_printed": False,
        "conversion": {"implemented": False, "conversion_version": None, "normalized_input_sha256": None,
                       "reason": "substantive capability inconsistency; no lossless representational mapping"},
        "datasets": {"heldout": audit(args.heldout_path, "heldout", catalog),
                     "robustness": audit(args.robustness_path, "robustness", catalog)}}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"audit_version": VERSION, "api_calls": 0, "datasets": {k: {f: v[f] for f in
        ("scenario_count", "fixture_record_count", "engine_invalid_fixture_records", "scenario_schema_compatible", "scenario_schema_incompatible")}
        for k, v in result["datasets"].items()}}, indent=2))


if __name__ == "__main__":
    main()
