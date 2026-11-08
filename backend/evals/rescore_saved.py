"""Rescore a saved matrix report with the current canonical scorer. No model calls.

Usage, from backend/:
    .venv/bin/python -m evals.rescore_saved <results.json> <output.json>

Transcript-based assertions are recomputed by the current scorer code.
State-based assertions (bookings, blocked codes, session fields) are recomputed
from the observed values the original run saved, because the engine object is
not persisted. Validation: applied to proposed-v2-rescored.json it reproduces
32/36 with no assertion changes.
"""
import json
import sys
from types import SimpleNamespace

from evals import scorer
from evals.loader import DEFAULT_CATALOG_PATH, load_dev_scenarios
from scheduling import load_catalog

if len(sys.argv) != 3:
    raise SystemExit(__doc__)
src, out = sys.argv[1], sys.argv[2]
report = json.load(open(src))
scen = {s["id"]: s for s in load_dev_scenarios()["scenarios"]}
catalog = load_catalog(DEFAULT_CATALOG_PATH)

class FakeEngine:
    """Reconstructs only what evaluate_run reads, from saved observations."""
    def __init__(self, run):
        obs = {a["name"]: a["observed"] for a in run["assertions"]}
        self.catalog = catalog
        self.bookings = run["outcome_signature"]["bookings"]
        codes = []
        for k in ("capability_block","type_new_patient_block","provider_new_patient_block","referral_block","corrected_location_block"):
            if k in obs and isinstance(obs[k], list): codes += obs[k]
        self._codes = codes
        conf = obs.get("confirmation_recorded", obs.get("confirmation_invalidated"))
        st = SimpleNamespace(
            confirmation=None if conf in (None, "None") else conf,
            appointment_type_id=obs.get("ambiguity_preserved"),
            location_id=obs.get("final_location_retained"),
            selected_slot_id=obs.get("old_slot_invalidated"),
            provider_id=obs.get("unknown_provider_not_invented"))
        self.state = st
        self.missing = [k for k in ("booking_count",) if k not in obs]
    def resolve_options(self):
        return {"blocked_options": [{"code": c} for c in self._codes]}

runs, changes = [], []
for run in report["runs"]:
    s = scen[run["scenario_id"]]
    fake = SimpleNamespace(error=run["error"], engine=FakeEngine(run), transcript=run["transcript"],
                           context_messages=[], call_id=run["call_id"])
    new = scorer.evaluate_run(s, fake)
    old_by = {a["name"]: a["passed"] for a in run["assertions"]}
    for a in new["assertions"]:
        if a["name"] in old_by and old_by[a["name"]] != a["passed"]:
            changes.append((run["scenario_id"], run["repetition"], a["name"], old_by[a["name"]], a["passed"]))
    runs.append({"scenario_id": run["scenario_id"], "repetition": run["repetition"], "call_id": run["call_id"],
                 "passed_original": run["passed"], "passed_rescored": new["passed"],
                 "failed_rescored": [a["name"] for a in new["assertions"] if not a["passed"]]})
summary = {"source": src, "scorer_version": scorer.SCORER_VERSION, "model_calls_made": 0,
           "original_passed": sum(r["passed_original"] for r in runs),
           "rescored_passed": sum(r["passed_rescored"] for r in runs), "runs": len(runs),
           "assertion_changes_on_shared_checks": changes}
json.dump({"summary": summary, "runs": runs}, open(out, "w"), indent=2)
print(json.dumps(summary, indent=1))
for r in runs:
    if not r["passed_rescored"]: print(r["scenario_id"], r["repetition"], r["failed_rescored"])
