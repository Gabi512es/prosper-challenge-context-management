"""Explicit external evaluation contract. IDs and metadata never select behavior."""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime
import re

from .scorer import _name_is_mentioned

VERSION = "external-eval-v1.1"
OUTCOMES = {"book", "no_booking", "answer_only", "clarify_or_handoff"}
EXPECTED = {"bookings", "booking", "confirmation_required", "provider_identity_resolved_before_booking",
            "global_slot_ranking", "ambiguity_preserved", "old_slot_invalidated_after_correction",
            "confirmation_invalidated_after_correction", "unknown_entity_acknowledged", "required_facts",
            "explanation", "assertions"}
KINDS = {"policy_block", "transcript_contains", "catalog_distinction", "staff_request",
         "no_identity_collection", "no_tool", "review"}
TRIGGERS = {"first_offer", "identity_question", "identity_confirmation", "provider_question",
            "location_question", "service_question", "booking_offer", "name_spelling",
            "human_help_offer", "no_availability", "tool_error", "assistant_contains"}
FACTS = {"name", "date_of_birth", "synthetic", "is_new_patient", "referral_on_file", "provider_id",
         "intended_provider_id", "provider_name", "location_id", "intended_location_id", "initial_location_id",
         "final_location_id", "appointment_type_id", "ambiguous_type_ids", "location_is_hard_constraint",
         "provider_is_hard_constraint", "preference", "provider_preference", "location_preference"}


class ContractError(ValueError):
    def __init__(self, code, path):
        self.code, self.path = code, path
        super().__init__(f"{code} at {path}")  # No scenario values in errors.


def require(condition, code, path):
    if not condition:
        raise ContractError(code, path)


def compile_scenario(source, catalog):
    """Validate every grading/rule field; prose becomes mandatory review, not a pass."""
    require(isinstance(source, dict), "object_required", "scenario")
    allowed = {"id", "split", "category", "opening", "patient_facts", "reply_rules", "patient_script",
               "expected_outcome", "expected", "forbidden", "source_refs", "notes", "availability_fixture",
               "review_status", "faults", "source_basis"}
    require(not set(source) - allowed, "unsupported_scenario_field", "scenario")
    for key in ("id", "opening", "patient_facts", "expected_outcome", "expected", "availability_fixture"):
        require(key in source, "missing_field", key)
    require(isinstance(source["id"], str) and bool(source["id"]), "string_required", "id")
    require(isinstance(source["opening"], str) and bool(source["opening"].strip()), "string_required", "opening")
    require(isinstance(source["patient_facts"], dict), "object_required", "patient_facts")
    facts = source["patient_facts"]
    for key in ("is_new_patient", "referral_on_file", "synthetic", "location_is_hard_constraint", "provider_is_hard_constraint"):
        if key in facts:
            require(type(facts[key]) is bool, "boolean_required", "patient_facts." + key)
    for key in ("name", "provider_name"):
        if key in facts:
            require(isinstance(facts[key], str) and bool(facts[key].strip()), "string_required", "patient_facts." + key)
    if "date_of_birth" in facts:
        try:
            date.fromisoformat(facts["date_of_birth"])
        except (TypeError, ValueError):
            raise ContractError("iso_date_required", "patient_facts.date_of_birth") from None
    for key, records in (("appointment_type_id", catalog.appointment_types_by_id), ("provider_id", catalog.providers_by_id),
                         ("intended_provider_id", catalog.providers_by_id), ("location_id", catalog.locations_by_id),
                         ("intended_location_id", catalog.locations_by_id), ("initial_location_id", catalog.locations_by_id),
                         ("requested_location_id", catalog.locations_by_id),
                         ("final_location_id", catalog.locations_by_id)):
        if key in facts:
            require(isinstance(facts[key], str) and facts[key] in records, "unknown_catalog_fact", "patient_facts." + key)
    if "ambiguous_type_ids" in facts:
        require(isinstance(facts["ambiguous_type_ids"], list) and len(facts["ambiguous_type_ids"]) >= 2
                and all(isinstance(x, str) and x in catalog.appointment_types_by_id for x in facts["ambiguous_type_ids"]),
                "invalid_ambiguity_set", "patient_facts.ambiguous_type_ids")
    if "preference" in facts:
        require(facts["preference"] == "soonest", "unsupported_preference", "patient_facts.preference")
    require(isinstance(source["expected_outcome"], str) and source["expected_outcome"] in OUTCOMES, "unsupported_outcome", "expected_outcome")
    expected = source["expected"]
    require(isinstance(expected, dict), "object_required", "expected")
    if "bookings" in expected:
        require(type(expected["bookings"]) is int and expected["bookings"] >= 0, "nonnegative_integer_required", "expected.bookings")
        require((expected["bookings"] > 0) == (source["expected_outcome"] == "book"), "conflicting_outcome", "expected.bookings")
    if source["expected_outcome"] == "book":
        require(isinstance(expected.get("booking"), dict) and bool(expected["booking"]), "booking_fields_required", "expected.booking")
    if "booking" in expected:
        require(isinstance(expected["booking"], dict) and not set(expected["booking"]) -
                {"slot_id", "provider_id", "location_id", "appointment_type_id"}
                and all(isinstance(v, str) for v in expected["booking"].values()), "invalid_booking_assertion", "expected.booking")
    for key in EXPECTED - {"bookings", "booking", "required_facts", "explanation", "assertions"}:
        if key in expected:
            require(type(expected[key]) is bool, "boolean_required", "expected." + key)
    if "required_facts" in expected:
        require(isinstance(expected["required_facts"], dict) and bool(expected["required_facts"]),
                "unsupported_factual_assertion", "expected.required_facts")
        if set(expected["required_facts"]) & {"location_id", "phone", "hours"}:
            require(isinstance(expected["required_facts"].get("location_id"), str) and expected["required_facts"]["location_id"] in catalog.locations_by_id,
                    "location_required", "expected.required_facts.location_id")
    if source["expected_outcome"] == "answer_only":
        require(bool(expected.get("required_facts") or expected.get("assertions")), "answer_assertions_required", "expected")
    require(isinstance(expected.get("assertions", []), list), "array_required", "expected.assertions")
    for rule in expected.get("assertions", []):
        require(isinstance(rule, dict) and isinstance(rule.get("kind"), str) and rule["kind"] in KINDS, "unsupported_assertion", "expected.assertions")
        needed = {"policy_block": "code", "transcript_contains": "text", "catalog_distinction": "ids",
                  "no_tool": "tool", "review": "text"}.get(rule["kind"])
        if needed:
            require(bool(rule.get(needed)), "missing_assertion_argument", "expected.assertions")
        require(set(rule) == ({"kind", needed} if needed else {"kind"}), "unsupported_assertion_argument", "expected.assertions")
        if needed and needed != "ids":
            require(isinstance(rule[needed], str), "string_required", "expected.assertions")
        if rule["kind"] == "catalog_distinction":
            require(isinstance(rule["ids"], list) and len(rule["ids"]) >= 2 and all(isinstance(x, str) and x in catalog.appointment_types_by_id for x in rule["ids"]),
                    "invalid_catalog_assertion", "expected.assertions")
    require(isinstance(source.get("forbidden", []), list) and all(isinstance(x, str) and x.strip() for x in source.get("forbidden", [])),
            "prose_list_required", "forbidden")
    for key in ("reply_rules", "notes"):
        require(isinstance(source.get(key, ""), str), "string_required", key)
    if "explanation" in expected:
        require(isinstance(expected["explanation"], str) and bool(expected["explanation"].strip()), "string_required", "expected.explanation")
    require(isinstance(source.get("patient_script", []), list), "array_required", "patient_script")
    for rule in source.get("patient_script", []):
        require(isinstance(rule, dict) and not set(rule) - {"when", "response", "match", "max_uses"}
                and isinstance(rule.get("when"), str) and rule["when"] in TRIGGERS, "unsupported_patient_rule", "patient_script")
        require(isinstance(rule.get("response"), str) and bool(rule["response"].strip()), "response_required", "patient_script")
        require(type(rule.get("max_uses", 1)) is int and 1 <= rule.get("max_uses", 1) <= 3, "invalid_repeat_limit", "patient_script")
        if rule["when"] == "assistant_contains":
            require(isinstance(rule.get("match"), str) and bool(rule["match"]), "match_required", "patient_script")
    require(isinstance(source["availability_fixture"], list), "array_required", "availability_fixture")
    for slot in source["availability_fixture"]:
        require(isinstance(slot, dict) and set(slot) == {"slot_id", "provider_id", "location_id", "appointment_type_id", "start", "end"}
                and all(isinstance(v, str) for v in slot.values()), "malformed_slot", "availability_fixture")
        try:
            start, end = datetime.fromisoformat(slot["start"]), datetime.fromisoformat(slot["end"])
            require(start.tzinfo is not None and end.tzinfo is not None and start < end, "aware_ordered_times_required", "availability_fixture")
        except ValueError:
            raise ContractError("malformed_slot_time", "availability_fixture") from None
    require(("initial_location_id" in facts or "requested_location_id" in facts) == ("final_location_id" in facts), "correction_pair_required", "patient_facts")
    # Existing engine validates fixture references, relations, capability and timestamps (not duration).
    from scheduling import SchedulingEngine
    try:
        SchedulingEngine(catalog, source["availability_fixture"])
    except (KeyError, TypeError, ValueError):
        raise ContractError("malformed_availability", "availability_fixture") from None
    from .write_faults import normalize_faults
    require(isinstance(source.get("faults", []), list), "array_required", "faults")
    try:
        normalize_faults(source.get("faults", []))
    except (TypeError, ValueError, KeyError):
        raise ContractError("malformed_faults", "faults") from None
    review = ["patient_facts." + key for key in ("provider_preference", "location_preference") if facts.get(key) is not None]
    review.extend("patient_facts." + k for k in sorted(set(facts) - FACTS))
    review.extend("expected." + k for k in sorted(set(expected) - EXPECTED))
    review.extend("expected.required_facts." + k for k in sorted(set(expected.get("required_facts", {})) - {"location_id", "hours", "phone"}))
    if source.get("source_basis"): review.append("source_basis")
    if expected.get("explanation"):
        review.append("expected.explanation")
    review.extend(f"forbidden[{i}]" for i in range(len(source.get("forbidden", []))))
    if source.get("reply_rules"):
        review.append("reply_rules_execution")
    if source.get("notes"):
        review.append("notes")
    review.extend(f"expected.assertions[{i}]" for i, r in enumerate(expected.get("assertions", [])) if r["kind"] == "review")
    return {"scenario": deepcopy(source), "review_required": review}


@dataclass
class PatientDriver:
    """Private patient facts, never grading expectations. No agent-state writes."""
    opening: str
    facts: dict
    script: list = field(default_factory=list)
    availability: list = field(default_factory=list)
    identity_given: bool = False
    corrected: bool = False
    provider_given: bool = False
    ambiguity_given: bool = False
    spelling_given: bool = False
    repeats: dict = field(default_factory=dict)
    events: list = field(default_factory=list)

    @classmethod
    def from_compiled(cls, compiled):
        source = compiled["scenario"]
        facts = deepcopy(source["patient_facts"])
        if "requested_location_id" in facts and "initial_location_id" not in facts:
            facts["initial_location_id"] = facts["requested_location_id"]  # Private driver alias only; retain source.
        return cls(source["opening"], facts, deepcopy(source.get("patient_script", [])), deepcopy(source["availability_fixture"]))

    def _repeat(self, key, reply, limit=1):
        used = self.repeats.get(key, 0)
        if used >= limit:
            return None
        self.repeats[key] = used + 1
        if used:
            self.events.append({"type": "unnecessary_question", "field": key})
        return reply

    def reply(self, text, catalog, offered=(), candidates=()):
        # Expectations, outcome labels, IDs and prose reply_rules are not present in this object.
        low = text.casefold(); facts = self.facts
        identity_q = any(x in low for x in ("your name", "full name", "patient name", "date of birth", "birth date", "dob", "birthday"))
        identity_confirm = self.identity_given and any(x in low for x in ("confirm", "correct", "right")) and any(x in low for x in ("birth", "born", "dob"))
        provider_q = bool(re.search(r"which|did you mean|spell", low)) and any(x in low for x in ("provider", "doctor", "clinician", "mean", "surname"))
        location_q = "?" in text and any(x in low for x in ("which location", "which site", "where", "location would", "site would"))
        service_q = any(x in low for x in ("appointment service", "what service", "which service", "confirm the service", "confirm the appointment type", "choose between"))
        booking_q = bool(offered) and any(x in low for x in ("shall i book", "would you like", "confirm", "book it", "which slot"))
        triggers = {"first_offer": bool(offered) and not self.corrected, "booking_offer": booking_q,
                    "identity_question": identity_q, "identity_confirmation": identity_confirm,
                    "provider_question": provider_q, "location_question": location_q, "service_question": service_q,
                    "name_spelling": "spell" in low, "human_help_offer": "?" in text and any(x in low for x in ("human", "staff", "representative")),
                    "no_availability": any(x in low for x in ("no slots", "no matching", "no availability")),
                    "tool_error": any(x in low for x in ("error", "failed", "unavailable", "shut down"))}
        for i, rule in enumerate(self.script):
            match = (rule["match"].casefold() in low) if rule["when"] == "assistant_contains" else triggers[rule["when"]]
            if match:
                reply = self._repeat(f"script:{i}", rule["response"], rule.get("max_uses", 1))
                if reply:
                    self.events.append({"type": "script_response", "rule_index": i})
                    return reply
        if any(slot_matches_facts(s, facts) and accurate_offer(text, s, catalog) for s in offered) and facts.get("final_location_id") and not self.corrected:
            self.corrected = True
            self.events.append({"type": "location_correction"})
            final = catalog.locations_by_id[facts["final_location_id"]].name
            suffix = " only" if facts.get("location_is_hard_constraint") else ""
            return f"Actually, please change the location to {final}{suffix}."
        if facts.get("ambiguous_type_ids") and not self.ambiguity_given and ("?" in text or service_q):
            self.ambiguity_given = True
            names = [catalog.appointment_types_by_id[x].name for x in facts["ambiguous_type_ids"]]
            return "I cannot choose between " + " and ".join(names) + ". Please have a staff member confirm the intended service."
        if "spell" in low and facts.get("provider_name") and not self.spelling_given:
            self.spelling_given = True
            suffix = " I only want that doctor." if facts.get("provider_is_hard_constraint") else ""
            return f"It is spelled {facts['provider_name']}." + suffix
        provider = facts.get("intended_provider_id", facts.get("provider_id"))
        if provider_q and provider and not self.provider_given:
            self.provider_given = True
            p = catalog.providers_by_id[provider]
            return f"I mean {p.name}, {p.specialty}, {p.title}."
        location = facts.get("final_location_id") if self.corrected else facts.get("intended_location_id", facts.get("location_id", facts.get("initial_location_id")))
        if location_q and location:
            return self._repeat("location", f"I want {catalog.locations_by_id[location].name}.")
        if identity_confirm and all(facts.get(k) for k in ("name", "date_of_birth")):
            dob = date.fromisoformat(facts["date_of_birth"])
            accurate = _name_is_mentioned(facts["name"], low) and (facts["date_of_birth"] in low or
                (dob.strftime("%B").casefold() in low and bool(re.search(rf"\b{dob.day}(?:st|nd|rd|th)?\b", low)) and str(dob.year) in low))
            return "Yes, my name and date of birth are correct." if accurate else f"No. My name is {facts['name']} and my date of birth is {facts['date_of_birth']}."
        if identity_q and all(facts.get(k) for k in ("name", "date_of_birth")):
            self.identity_given = True
            reply = self._repeat("identity", f"My name is {facts['name']} and my date of birth is {facts['date_of_birth']}.", 2)
            if reply:
                if "new patient" in low and "is_new_patient" in facts:
                    reply += " I am a new patient." if facts["is_new_patient"] else " I am an existing patient."
                    self.repeats["status"] = 1
                if "referral" in low and "referral_on_file" in facts:
                    reply += " I have a referral on file." if facts["referral_on_file"] else " I do not have a referral on file."
                    self.repeats["referral"] = 1
            return reply
        for key, pattern, field_name, positive, negative in (
            ("status", r"(?:confirm|are you|whether|tell me|let me know).{0,45}(?:new patient|new or existing)", "is_new_patient", "I am a new patient.", "I am an existing patient."),
            ("referral", r"(?:confirm|do you|whether|have you|is there|tell me|let me know).{0,45}referral", "referral_on_file", "I have a referral on file.", "I do not have a referral on file.")):
            if field_name in facts and re.search(pattern, low):
                already = bool(re.search(r"\b(?:new|existing) patient\b|new to the clinic", self.opening, re.I)) if key == "status" else "referral" in self.opening.casefold()
                if already and not self.repeats.get(key):
                    self.events.append({"type": "unnecessary_question", "field": key})
                return self._repeat(key, positive if facts[field_name] else negative, 1 if already else 2)
        if service_q and facts.get("appointment_type_id"):
            return self._repeat("service", "I'm asking for " + catalog.appointment_types_by_id[facts["appointment_type_id"]].name + ".")
        if booking_q:
            if facts.get("preference") == "soonest":
                # A private patient-side oracle checks consent, never the live engine.
                from scheduling import SchedulingEngine
                oracle = SchedulingEngine(catalog, self.availability, now=datetime.fromisoformat("2026-11-07T00:00:00-08:00"))
                updates = {k: facts[k] for k in ("name", "date_of_birth", "is_new_patient", "referral_on_file", "appointment_type_id") if k in facts}
                provider = facts.get("intended_provider_id", facts.get("provider_id"))
                location = facts.get("intended_location_id", facts.get("location_id"))
                updates.update({"provider_id": provider} if provider else {"any_provider": True})
                updates.update({"location_id": location} if location else {"any_location": True})
                oracle.resolve_options(updates)
                eligible = oracle.find_slots(30).get("slots", [])
                if not eligible:
                    self.events.append({"type": "patient_review_required", "reason": "cannot_determine_earliest_eligible_slot"})
                    return None
                earliest = min(datetime.fromisoformat(s["start"]) for s in eligible)
                offered = [s for s in offered if datetime.fromisoformat(s["start"]) == earliest]
                if not offered:
                    return self._repeat("earlier_slot", "Is there an earlier eligible appointment?")
            if "which slot" in low:
                for slot in sorted(offered, key=lambda s: s["start"]):
                    site = catalog.locations_by_id[slot["location_id"]].name
                    start = datetime.fromisoformat(slot["start"])
                    if slot_matches_facts(slot, facts, self.corrected) and _name_is_mentioned(site, low) and start.strftime("%A").casefold() in low:
                        return f"The {start.strftime('%A %B %d at %I:%M %p')} at {site}, please. Please read back the full appointment before booking."
            for slot in offered:
                if slot_matches_facts(slot, facts, self.corrected) and accurate_offer(text, slot, catalog):
                    return "Yes. I confirm that exact provider, location, service, date, and time. Please book it."
            return self._repeat("inaccurate_offer", "That does not match my request. Please check the service, provider, location, date and time.")
        return None


def slot_matches_facts(slot, facts, corrected=False):
    constraints = {"appointment_type_id": facts.get("appointment_type_id"),
        "provider_id": facts.get("intended_provider_id", facts.get("provider_id")),
        "location_id": facts.get("final_location_id") if corrected else facts.get("intended_location_id", facts.get("location_id", facts.get("initial_location_id")))}
    return bool(constraints["appointment_type_id"]) and all(v is None or slot.get(k) == v for k, v in constraints.items())


def accurate_offer(text, slot, catalog):
    low = text.casefold(); start = datetime.fromisoformat(slot["start"])
    names = (catalog.appointment_types_by_id[slot["appointment_type_id"]].name,
             catalog.providers_by_id[slot["provider_id"]].name, catalog.locations_by_id[slot["location_id"]].name)
    hour = start.hour % 12 or 12; minute = start.minute; period = "am" if start.hour < 12 else "pm"
    clock = re.search(rf"\b0?{hour}(?::0?{minute})?\s*{period}\b", re.sub(r"[.]", "", low)) if minute == 0 else re.search(rf"\b0?{hour}:{minute:02d}\s*{period}\b", re.sub(r"[.]", "", low))
    return all(_name_is_mentioned(name, low) for name in names) and bool(clock) and start.strftime("%A").casefold() in low and start.strftime("%B").casefold() in low and bool(re.search(rf"\b{start.day}(?:st|nd|rd|th)?\b", low))
