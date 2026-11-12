"""One explicit, user-authorized asset revision. IDs address edits here, never runtime policy."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from .final_preflight import REFERENCES

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT.parent / "Evals/revised-evaluation-v1"
REMOVED = {"ho002-bad-site", "ho003-bad-site", "ho008-nocap-1", "ho008-nocap-2"}


def packed(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def build():
    DEST.mkdir(parents=True, exist_ok=True)
    changes = []; removed = []; assets = {}
    for kind in ("heldout", "robustness"):
        path = Path("/Users/gabrielernoult/Documents") / REFERENCES[kind]["filename"]
        original = path.read_bytes()
        assert sha256(original).hexdigest() == REFERENCES[kind]["sha256"]
        data = json.loads(original); revised = deepcopy(data)
        def change(obj, key, value, pointer):
            before = deepcopy(obj.get(key))
            if before != value:
                changes.append({"dataset": kind, "pointer": pointer + "/" + key,
                    "operation": "replace" if key in obj else "add", "before": before, "after": value})
                obj[key] = value
        def append(obj, key, text, pointer):
            change(obj, key, (obj.get(key, "").rstrip() + " " + text).strip(), pointer)
        change(revised["contract"], "evaluation_revision", "reviewed-conversational-v1", "/contract")
        change(revised["contract"], "revision_clarification_precedence",
            "This revision's explicit clarifications supersede conflicting earlier prose. Original booking identities and outcome labels remain unchanged.", "/contract")
        if kind == "heldout":
            change(revised["contract"], "availability_scope_revision",
                "Four deliberate capability-invalid records were removed from this conversational copy only. It no longer tests runtime ingestion of capability-invalid availability. The originals and initializer rejection are separate offline evidence. This is a scope revision, not lossless normalization.", "/contract")
        else:
            change(revised["contract"], "false_refusal_exceptions", ["requested human assistance", "genuine technical failure", "declared urgent-symptom escalation"], "/contract")
            append(revised["contract"], "grading_note",
                "Requested human assistance, genuine technical failure and the declared urgent-symptom escalation are exceptions to the general false-refusal rule. Other semantic requirements remain review obligations.", "/contract")
        for i, case in enumerate(revised["scenarios"]):
            base = f"/scenarios/{i}"
            if kind == "heldout":
                keep = []
                for j, slot in enumerate(case["availability_fixture"]):
                    if slot["slot_id"] in REMOVED:
                        removed.append({"source_pointer": base + f"/availability_fixture/{j}", "record": deepcopy(slot),
                            "initializer_rejection": "appointment_type.required_capability not in location.capabilities"})
                    else: keep.append(slot)
                if keep != case["availability_fixture"]:
                    change(case, "availability_fixture", keep, base)
                    append(case, "notes", "This conversational revision removes only the capability-invalid fixture records listed in the revision manifest. Their initializer rejection is retained offline; ingestion of such records is no longer tested here.", base)
                if case["id"] in {"HO-004", "HO-005", "HO-006"}:
                    clarification = "Accept an honest staff-directed next step. Do not require or authorize an unrecorded callback or a real transfer."
                    append(case, "reply_rules", clarification, base); append(case, "notes", clarification, base)
                    scripts = deepcopy(case.get("patient_script", []))
                    scripts.append({"when": "human_help_offer", "response": "I can contact the clinic staff directly. I am not requesting or expecting a callback."})
                    if case["id"] == "HO-006":
                        append(case, "reply_rules", "Decline all substitute services.", base)
                        scripts.insert(0, {"when": "service_question", "response": "I do not want any substitute service. Please give me an honest staff-directed next step."})
                    change(case, "patient_script", scripts, base)
                if case["id"] == "HO-014":
                    note = "Require an accurate location and referral answer; the provider's name need not be spoken. The provider identity reference is retained, not a spoken-name requirement."
                    append(case, "reply_rules", note, base); append(case, "notes", note, base)
                    change(case["expected"], "provider_name_spoken_required", False, base + "/expected")
            elif case["id"] == "RW-003":
                append(case, "opening", "Please book the earliest eligible appointment.", base)
                change(case["patient_facts"], "preference", "soonest", base + "/patient_facts")
                append(case, "notes", "The opening explicitly requests the earliest eligible appointment, making first-slot loss at write time unambiguous. Remaining eligible availability is considered after slot loss.", base)
        assert len(revised["scenarios"]) == len(data["scenarios"])
        for before, after in zip(data["scenarios"], revised["scenarios"]):
            assert before["id"] == after["id"] and before["expected_outcome"] == after["expected_outcome"]
            assert before["expected"].get("booking") == after["expected"].get("booking")
            assert all(after["expected"][k] == v for k, v in before["expected"].items())
            if before["id"] == "RW-004": assert before["availability_fixture"] == after["availability_fixture"]
        output = DEST / f"{kind}.reviewed.json"
        body = (json.dumps(revised, ensure_ascii=False, indent=2) + "\n").encode()
        if output.exists(): assert output.read_bytes() == body, "Refuse to overwrite a different revision"
        else: output.write_bytes(body)
        assert path.read_bytes() == original
        assets[kind] = {"original_path": str(path), "original_sha256": sha256(original).hexdigest(),
                        "revised_path": str(output), "revised_sha256": sha256(body).hexdigest(),
                        "scenarios": len(revised["scenarios"])}
    assert {r["record"]["slot_id"] for r in removed} == REMOVED and len(removed) == 4
    evidence = DEST / "removed-initializer-records.json"
    evidence.write_text(json.dumps({"scope": "offline initializer rejection only", "records": removed}, indent=2) + "\n")
    manifest = {"revision_version": "reviewed-conversational-v1", "scope_preserved_fully": False,
        "scope_change": "Conversational held-out copy no longer tests capability-invalid availability ingestion",
        "assets": assets, "changes": changes, "removed_record_evidence": str(evidence),
        "removed_record_evidence_sha256": sha256(evidence.read_bytes()).hexdigest()}
    manifest_path = DEST / "exact-change-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    public = {k: v for k, v in manifest.items() if k != "changes"}
    public["exact_change_manifest_sha256"] = sha256(manifest_path.read_bytes()).hexdigest()
    public["change_index"] = [{k: change[k] for k in ("dataset", "pointer", "operation")} |
        {"before_sha256": sha256(packed(change["before"])).hexdigest(), "after_sha256": sha256(packed(change["after"])).hexdigest()} for change in changes]
    public["removed_slot_labels"] = sorted(REMOVED)
    (ROOT / "docs/results/revised-assets-manifest.json").write_text(json.dumps(public, indent=2) + "\n")
    print(json.dumps({"revision_version": manifest["revision_version"], "assets": assets, "removed_records": len(removed),
                      "exact_changes": len(changes), "private_manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    build()
