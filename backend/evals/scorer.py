"""Canonical deterministic scorer shared by every evaluation arm."""

import re
from typing import Any
from .version import EVALUATOR_VERSION


SCORER_VERSION = EVALUATOR_VERSION


def evaluate_run(scenario: dict, run: Any) -> dict:
    """Evaluate only scenario-declared outcomes against observable state/transcript."""
    assertions: list[dict] = []

    def check(name: str, passed: bool, observed=None) -> None:
        assertions.append({"name": name, "passed": bool(passed), "observed": observed})

    check("runner_completed", not run.error, run.error)
    bookings = run.engine.bookings
    expected = scenario["expected"]
    expected_outcome = scenario["expected_outcome"]
    text = normalize_transcript_text(
        " ".join(
            item.get("text", "")
            for item in run.transcript
            if item.get("role") == "assistant"
        )
    )
    tool_names = [
        tool
        for item in run.transcript
        if item.get("role") == "assistant"
        for tool in item.get("tools", [])
    ]
    current = run.engine.resolve_options()
    blocked_codes = {item["code"] for item in current["blocked_options"]}
    general = general_conversation_checks(run.transcript, run.engine.catalog)
    for name, passed in general.items():
        check(name, passed)

    check(
        "booking_count",
        len(bookings) == (1 if expected_outcome == "book" else 0),
        len(bookings),
    )
    if "booking" in expected:
        booking = bookings[0] if len(bookings) == 1 else {}
        expected_booking = expected["booking"]
        observed = {key: booking.get(key) for key in expected_booking}
        check("booking_fields", observed == expected_booking, observed)
    if expected.get("confirmation_required"):
        check(
            "confirmation_recorded",
            run.engine.state.confirmation is not None,
            repr(run.engine.state.confirmation),
        )

    scenario_id = scenario["id"]
    if scenario_id == "DEV-002":
        check(
            "provider_identity_resolved",
            bool(bookings) and bookings[0].get("provider_id") == "prov_003",
            bookings[0].get("provider_id") if bookings else None,
        )
    elif scenario_id == "DEV-003":
        check(
            "capability_block",
            "location_missing_capability" in blocked_codes,
            sorted(blocked_codes),
        )
        check(
            "capability_explained",
            "imaging" in text and "mission bay" in text and "downtown" in text,
            text,
        )
    elif scenario_id == "DEV-004":
        check(
            "type_new_patient_block",
            "new_patient_type_restricted" in blocked_codes,
            sorted(blocked_codes),
        )
        check("type_restriction_explained", "new patient" in text, text)
    elif scenario_id == "DEV-005":
        check(
            "provider_new_patient_block",
            "new_patient_provider_restricted" in blocked_codes,
            sorted(blocked_codes),
        )
        check(
            "provider_restriction_explained",
            "new patient" in text
            and any(word in text for word in ("accept", "available", "restrict", "block")),
            text,
        )
    elif scenario_id == "DEV-006":
        check("referral_block", "referral_required" in blocked_codes, sorted(blocked_codes))
        check("referral_explained", "referral" in text, text)
    elif scenario_id == "DEV-007":
        check(
            "ambiguity_preserved",
            run.engine.state.appointment_type_id is None,
            run.engine.state.appointment_type_id,
        )
        check(
            "staff_confirmation_requested",
            any(word in text for word in ("staff", "human", "representative")),
            text,
        )
        ambiguous_names = [
            run.engine.catalog.appointment_types_by_id[item_id].name.casefold()
            for item_id in scenario["patient_facts"]["ambiguous_type_ids"]
        ]
        check(
            "undocumented_distinction_explained",
            all(name in text for name in ambiguous_names)
            and _catalog_limit_explained(text),
            text,
        )
    elif scenario_id == "DEV-008":
        check(
            "final_location_retained",
            run.engine.state.location_id == scenario["patient_facts"]["final_location_id"],
            run.engine.state.location_id,
        )
        check("old_slot_invalidated", run.engine.state.selected_slot_id is None, run.engine.state.selected_slot_id)
        check(
            "confirmation_invalidated",
            run.engine.state.confirmation is None,
            repr(run.engine.state.confirmation),
        )
        check(
            "corrected_location_block",
            "location_missing_capability" in blocked_codes,
            sorted(blocked_codes),
        )
        location = run.engine.catalog.locations_by_id[
            scenario["patient_facts"]["final_location_id"]
        ]
        appointment_type = run.engine.catalog.appointment_types_by_id[
            scenario["patient_facts"]["appointment_type_id"]
        ]
        check(
            "corrected_location_explained",
            _name_is_mentioned(location.name, text)
            and appointment_type.required_capability.casefold() in text
            and _absence_is_explained(text),
            text,
        )
    elif scenario_id == "DEV-009":
        check(
            "globally_earliest_slot",
            bool(bookings) and bookings[0].get("slot_id") == "dev009-early",
            bookings[0].get("slot_id") if bookings else None,
        )
    elif scenario_id == "DEV-010":
        digits = "".join(character for character in text if character.isdigit())
        phone_ok = "4155554657" in digits
        opening = any(value in text for value in ("8:00", "8 am", "8 a.m."))
        closing = any(
            value in text for value in ("17:00", "5 pm", "5:00 pm", "5 p.m.", "5:00 p.m.")
        )
        hours_ok = opening and closing
        check("faq_phone", phone_ok, digits)
        check("faq_hours", hours_ok, text)
        check("faq_no_booking_tool", "book_appointment" not in tool_names, tool_names)
        identity_request = any(
            phrase in text
            for phrase in ("your name", "full name", "date of birth", "birth date", "dob", "birthday")
        )
        check("faq_no_identity_collection", not identity_request, text)
        location = run.engine.catalog.locations_by_id[
            expected["required_facts"]["location_id"]
        ]
        check(
            "location_details_explained",
            _name_is_mentioned(location.name, text) and phone_ok and hours_ok,
            text,
        )
    elif scenario_id == "DEV-011":
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
        check("unknown_provider_acknowledged", acknowledged, text)
        check(
            "unknown_provider_not_invented",
            run.engine.state.provider_id is None,
            run.engine.state.provider_id,
        )
        requested_name = _requested_provider_name(scenario["opening"])
        check(
            "unknown_provider_explained",
            requested_name is not None and unknown_provider_explained(scenario, run.transcript),
            text,
        )

    passed = all(item["passed"] for item in assertions)
    return {
        "scenario_id": scenario_id,
        "call_id": run.call_id,
        "passed": passed,
        "assertions": assertions,
        "outcome_signature": {
            "passed": passed,
            "bookings": [
                {
                    key: booking.get(key)
                    for key in ("slot_id", "provider_id", "location_id", "appointment_type_id")
                }
                for booking in bookings
            ],
            "node": run.transcript[-1].get("node") if run.transcript else None,
        },
        "error": run.error,
        "transcript": run.transcript,
        "context_messages": run.context_messages,
    }


def normalize_transcript_text(value: str) -> str:
    """Normalize typography without weakening scenario-declared content checks."""
    return value.casefold().replace("\u2018", "'").replace("\u2019", "'")


def unknown_provider_explained(scenario, transcript):
    """Accept a named or unambiguous contextual no-match, never no availability."""
    requested = _requested_provider_name(scenario["opening"])
    if not requested:
        return False
    patient_texts = [scenario["opening"], *(m.get("text", "") for m in transcript if m.get("role") == "patient")]
    references = {_requested_provider_name(t).casefold() for t in patient_texts if _requested_provider_name(t)}
    unique_reference = len(references) == 1 and all(len(re.findall(r"\bdr\.?\s+", t, re.I)) <= 1 for t in patient_texts)
    absent = ("couldn't find", "could not find", "unable to find", "cannot find", "can't find",
              "not found", "no provider", "not in our", "don't have")
    for message in transcript:
        if message.get("role") != "assistant":
            continue
        text = normalize_transcript_text(message.get("text", "")).replace("dr.", "dr")
        for clause in re.split(r"[.!?]", text):
            if not any(phrase in clause for phrase in absent):
                continue
            if re.search(r"\b(?:slots?|appointments?|availability)\b", clause):
                continue
            if _name_is_mentioned(requested, clause):
                return True
            contextual = re.search(r"\b(?:that provider|that doctor|that clinician|(?:provider|doctor|clinician) with that name)\b", clause)
            if unique_reference and contextual and not re.search(r"\bdr\s+", clause):
                return True
    return False


def general_conversation_checks(transcript, catalog) -> dict:
    offers_ok = callbacks_ok = next_step_ok = True
    for item in transcript:
        if item.get("role") != "assistant":
            continue
        text = normalize_transcript_text(item.get("text", ""))
        timed_offer = bool(re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)\b", text)) and any(
            word in text for word in ("appointment", "slot", "available", "book"))
        if timed_offer:
            offers_ok &= any(_name_is_mentioned(location.name, text) for location in catalog.locations)
        # This prototype records no callbacks in either arm.
        callbacks_ok &= not bool(re.search(
            r"(?:staff|someone|we|they|representative|it).{0,35}(?:will|'ll).{0,25}(?:follow up|reach out|call you|contact you|notify)|(?:a callback|a call back) (?:is |has been )?(?:scheduled|recorded|arranged)", text))
        no_match = any(phrase in text for phrase in ("no slots", "no available", "no appointments", "no matching", "no availability"))
        if no_match:
            next_step_ok &= bool(re.search(r"\?|\b(?:call|phone|try|alternative|another|later|different)\b", text))
    return {"slot_offers_include_location": offers_ok,
            "no_unrecorded_callback_promise": callbacks_ok,
            "no_match_has_next_step": next_step_ok}


def _catalog_limit_explained(text: str) -> bool:
    return "catalog" in text and any(
        phrase in text
        for phrase in (
            "does not document",
            "doesn't document",
            "not documented",
            "does not distinguish",
            "doesn't distinguish",
            "cannot distinguish",
            "can't distinguish",
            "does not specify",
            "doesn't specify",
        )
    )


def _absence_is_explained(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "lacks",
            "doesn't have",
            "does not have",
            "doesn't support",
            "does not support",
            "not available at",
            "without the required",
            "unable to provide",
            "does not offer",
            "doesn't offer",
            "cannot perform",
            "can't perform",
        )
    )


def _name_is_mentioned(name: str, text: str) -> bool:
    ignored = {"clinic", "center", "health", "medical", "dr", "doctor"}
    tokens = {
        token for token in re.findall(r"[a-z0-9]+", name.casefold()) if token not in ignored
    }
    return bool(tokens) and tokens <= set(re.findall(r"[a-z0-9]+", text))


def _requested_provider_name(opening: str) -> str | None:
    match = re.search(r"\bdr\.?\s+([^.!?]+)", opening, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None
