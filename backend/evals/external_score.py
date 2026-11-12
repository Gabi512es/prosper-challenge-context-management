"""Tri-state, field-driven grading. No scenario-ID dispatch or inferred prose rubric."""
import json
import re

from .scorer import (general_conversation_checks, normalize_transcript_text, _name_is_mentioned,
                     _catalog_limit_explained, unknown_provider_explained)


def tool_events(context):
    names = {}
    for message in context:
        for call in message.get("tool_calls", []):
            names[call["id"]] = call["function"]
        if message.get("role") not in {"developer", "tool"}:
            continue
        try:
            envelope = json.loads(message["content"])
            if envelope.get("type") != "async_tool" or envelope.get("status") != "finished":
                continue
            result = envelope["result"]
            result = json.loads(result) if isinstance(result, str) else result
            yield {"function": names[envelope["tool_call_id"]], "result": result}
        except (ValueError, KeyError, TypeError):
            continue


def saved_observation(run):
    """Only observed saved fields; never replay tools or fill state from gold facts."""
    events = list(tool_events(run.get("context_messages", [])))
    state = {}; policies = None
    for event in events:
        result = event["result"]
        if not isinstance(result, dict):
            continue
        state.update(result.get("resolved", {}))
        if "blocked_options" in result:
            policies = [i["code"] for i in result["blocked_options"]]
    # Old scorer observations are final-state measurements, not expected values.
    fields = {"ambiguity_preserved": "appointment_type_id", "final_location_retained": "location_id", "old_slot_invalidated": "selected_slot_id",
              "confirmation_invalidated": "confirmation", "unknown_provider_not_invented": "provider_id"}
    for assertion in run.get("assertions", []):
        name = assertion["name"]
        if name in fields and "observed" in assertion:
            value = assertion["observed"]
            state[fields[name]] = None if value == "None" else value
        if name == "confirmation_recorded" and "observed" in assertion:
            state["confirmation"] = None if assertion["observed"] in (None, "None") else True
    bookings = [e["result"]["booking"] for e in events if isinstance(e["result"], dict)
                and e["result"].get("status") == "booked"]
    if not bookings and "bookings" in run.get("outcome_signature", {}):
        bookings = run["outcome_signature"]["bookings"]
    error = run.get("error")
    infra = bool(error and (error.startswith(("TimeoutError", "APITimeoutError", "ConnectionError"))
                           or "text pipeline failed" in error.casefold()))
    return {"transcript": run.get("transcript", []), "state": state, "bookings": bookings,
            "policy_codes": policies, "tool_events": events, "driver_events": run.get("driver_events", []),
            "tool_attempts": [c["function"]["name"] for m in run.get("context_messages", []) for c in m.get("tool_calls", [])],
            "infrastructure_failure": infra, "runner_error": bool(error),
            "evaluation_limited": bool(error) and not infra,
            "evidence_source": "saved trace; absent final-state fields remain unknown"}


def grade(compiled, observation, catalog):
    source = compiled["scenario"]; expected = source["expected"]
    checks = []; review = list(compiled["review_required"])
    state = observation.get("state", {})
    transcript = observation.get("transcript", [])
    text = normalize_transcript_text(" ".join(x.get("text", "") for x in transcript if x.get("role") == "assistant"))
    bookings = observation.get("bookings")

    def check(name, value, observed=None):
        checks.append({"name": name, "automatic": True, "passed": value, "observed": observed})
        if value is None:
            review.append("missing_evidence:" + name)

    def state_check(name, field, predicate):
        check(name, predicate(state[field]) if field in state else None, state.get(field))

    check("runner_completed", not observation.get("runner_error", False))
    for name, passed in general_conversation_checks(transcript, catalog).items():
        check(name, passed)
    count = expected.get("bookings", 1 if source["expected_outcome"] == "book" else 0)
    check("booking_count", len(bookings) == count if bookings is not None else None, len(bookings) if bookings is not None else None)
    if "booking" in expected:
        actual = bookings[0] if bookings and len(bookings) == 1 else {}
        observed = {k: actual.get(k) for k in expected["booking"]}
        check("booking_fields", observed == expected["booking"], observed)
    if expected.get("confirmation_required"):
        state_check("confirmation_recorded", "confirmation", lambda x: x is not None and x is not False)
    if expected.get("provider_identity_resolved_before_booking"):
        provider = expected.get("booking", {}).get("provider_id")
        resolved = False; written = False
        for event in observation.get("tool_events", []):
            r = event["result"]
            if isinstance(r, dict):
                resolved |= bool(provider and r.get("resolved", {}).get("provider_id") == provider)
                if r.get("status") == "booked":
                    written = True
                    check("provider_identity_resolved_before_booking", resolved and r["booking"].get("provider_id") == provider)
                    break
        if not written:
            check("provider_identity_resolved_before_booking", False if not bookings else None)
    if expected.get("global_slot_ranking"):
        slot_id = expected.get("booking", {}).get("slot_id")
        check("globally_earliest_slot", (bool(bookings) and bookings[0].get("slot_id") == slot_id) if slot_id else None)
    if expected.get("ambiguity_preserved"):
        state_check("ambiguity_preserved", "appointment_type_id", lambda x: x is None)
    for key, name, state_field in (
        ("old_slot_invalidated_after_correction", "old_slot_invalidated", "selected_slot_id"),
        ("confirmation_invalidated_after_correction", "confirmation_invalidated", "confirmation")):
        if expected.get(key):
            final = source["patient_facts"].get("final_location_id")
            if not final:
                # The legacy location-correction assertion cannot automatically grade
                # a different correction dimension. Preserve it for explicit review.
                check("correction_observed:" + state_field, None)
                check(name, None)
                check("correction_target:" + state_field, None)
                continue
            corrected = any(e.get("type") == "location_correction" for e in observation.get("driver_events", []))
            if final:
                corrected |= any(m.get("role") == "patient" and "actually" in m.get("text", "").casefold()
                    and _name_is_mentioned(catalog.locations_by_id[final].name, m["text"].casefold()) for m in transcript)
            check("correction_observed:" + state_field, corrected)
            state_check(name, state_field, lambda x: x is None)
            if final:
                state_check("final_location_retained:" + state_field, "location_id", lambda x: x == final)
            else:
                check("correction_target:" + state_field, None)
    if expected.get("unknown_entity_acknowledged"):
        phrases = ("couldn't find", "could not find", "unable to find", "not found", "no provider", "not in our", "don't have")
        check("unknown_provider_acknowledged", any(x in text for x in phrases))
        state_check("unknown_provider_not_invented", "provider_id", lambda x: x is None)
        check("unknown_provider_explained", unknown_provider_explained(source, transcript))
    facts = expected.get("required_facts", {})
    if facts.get("location_id"):
        location = catalog.locations_by_id[facts["location_id"]]
        check("location_details_explained", _name_is_mentioned(location.name, text))
        if "phone" in facts:
            check("faq_phone", re.sub(r"\D", "", facts["phone"]) in re.sub(r"\D", "", text))
        if "hours" in facts:
            from scheduling.opening_hours import parse_opening_hours
            try:
                _, opening, closing = parse_opening_hours(facts["hours"])
                def mentioned(clock):
                    hour = clock.hour % 12 or 12; period = "am" if clock.hour < 12 else "pm"
                    simple = text.replace(".", "")
                    return f"{clock.hour}:{clock.minute:02d}" in text or bool(re.search(rf"\b{hour}(?::{clock.minute:02d})?\s*{period}\b", simple))
                check("faq_hours", mentioned(opening) and mentioned(closing))
            except ValueError:
                check("faq_hours", None)
    tool_names = [e["function"]["name"] for e in observation.get("tool_events", [])] + observation.get("tool_attempts", [])
    tool_names += [name for m in transcript for name in m.get("tools", [])]
    identity_request = any(x in text for x in ("your name", "full name", "date of birth", "birth date", "dob", "birthday"))
    if source["expected_outcome"] == "answer_only":
        check("faq_no_booking_tool", "book_appointment" not in tool_names)
        check("faq_no_identity_collection", not identity_request)
    for i, rule in enumerate(expected.get("assertions", [])):
        kind = rule["kind"]; name = f"declared:{i}:{kind}"
        if kind == "policy_block":
            codes = observation.get("policy_codes")
            check(name, rule["code"] in codes if codes is not None else None, codes)
        elif kind == "transcript_contains":
            check(name, normalize_transcript_text(rule["text"]) in text)
        elif kind == "catalog_distinction":
            check(name, all(catalog.appointment_types_by_id[x].name.casefold() in text for x in rule["ids"]) and _catalog_limit_explained(text))
        elif kind == "staff_request":
            check(name, any(x in text for x in ("staff", "human", "representative")))
        elif kind == "no_identity_collection":
            check(name, not identity_request)
        elif kind == "no_tool":
            check(name, rule["tool"] not in tool_names)
        # review explicitly tracked by compile_scenario, never counted as an automatic pass.
    for i, fault in enumerate(source.get("faults", [])):
        evidence = next((e for e in observation.get("fault_evidence", []) if e["fault_index"] == i), {})
        check(f"fault:{i}:triggered", evidence.get("triggered", False))
        if fault.get("tool") == "book_appointment":
            check(f"fault:{i}:write_after_consent", evidence.get("write_after_consent", False))
    failed = [c["name"] for c in checks if c["passed"] is False]
    labels = []
    if observation.get("infrastructure_failure"):
        status = "infrastructure_failure"; labels.append("infrastructure_failure")
    elif failed:
        status = "failed"
    elif review or observation.get("evaluation_limited"):
        status = "review_required"
    else:
        status = "passed"
    if bookings and ("booking_fields" in failed or "booking_count" in failed):
        labels.append("wrong_booking")
    if not bookings and any(k in state and state[k] is not None and state[k] != v for k, v in expected.get("booking", {}).items()
                            if k in {"provider_id", "location_id", "appointment_type_id"}):
        labels.append("incorrect_internal_selection")
    if any(x.get("type") == "unnecessary_question" for x in observation.get("driver_events", [])):
        labels.append("unnecessary_clarification")
    # Missing booking != false refusal; wrong internal ID != spoken false claim.
    # These semantic consequences require transcript review and are never auto-inferred.
    return {"scenario_id": source["id"], "status": status, "passed": status == "passed",
            "assertions": checks, "required_review": sorted(set(review)),
            "consequences_automatic": labels, "evaluation_limited": observation.get("evaluation_limited", False),
            "transcript_review_taxonomy": ["false_statement_to_patient", "false_refusal", "unnecessary_clarification"],
            "agent_assessment": "not_assessable" if observation.get("infrastructure_failure") or observation.get("evaluation_limited") else
                ("automatic_failure" if failed else "review_pending" if review else "automatic_pass")}
