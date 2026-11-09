"""Resolution, policy, closed-world availability, and booking."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from .catalog import Catalog
from .models import ConfirmationSnapshot, SessionState, Slot
from .opening_hours import within_opening_hours


class SchedulingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class BookingError(SchedulingError):
    pass


class SchedulingEngine:
    """One scenario/session over an immutable catalog and availability fixture."""

    def __init__(
        self,
        catalog: Catalog,
        availability: list[dict],
        *,
        now: datetime | None = None,
    ):
        self.catalog = catalog
        self.state = SessionState()
        self.now = now or datetime.now(timezone.utc)
        self._slots = {slot.slot_id: slot for slot in map(Slot.from_dict, availability)}
        if len(self._slots) != len(availability):
            raise ValueError("Availability fixture contains duplicate slot IDs.")
        self._validate_slots()
        self._bookings: dict[str, dict] = {}
        self._unavailable_slot_ids: set[str] = set()

    @property
    def bookings(self) -> list[dict]:
        return list(self._bookings.values())

    def mark_slot_unavailable(self, slot_id: str) -> None:
        """Permanently remove a slot, as after a concurrent booking wins."""
        if slot_id not in self._slots:
            raise SchedulingError("unknown_slot", f"Unknown slot: {slot_id}")
        self._unavailable_slot_ids.add(slot_id)
        self.state.offered_slot_ids.discard(slot_id)
        if self.state.selected_slot_id == slot_id:
            self.state.selected_slot_id = None
            self.state.confirmation = None

    def resolve_options(self, updates: dict | None = None, *, limit: int = 5) -> dict:
        updates = updates or {}
        candidates: list[dict] = []
        errors: list[dict] = []

        self._apply_patient_updates(updates)
        self._apply_scope_updates(updates)
        self._apply_direct_ids(updates)
        self._apply_preferences(updates)

        for entity, state_field in (
            ("appointment_type", "appointment_type_id"),
            ("provider", "provider_id"),
            ("location", "location_id"),
        ):
            query_key = f"{entity}_query"
            if query_key not in updates:
                continue
            matches = self.catalog.search(
                entity,
                updates[query_key],
                specialty=updates.get(f"{entity}_specialty"),
            )
            if len(matches) == 1:
                self._set_resolved(state_field, matches[0]["id"])
            elif matches:
                self._set_resolved(state_field, None)
                candidates.extend({"entity": entity, **match} for match in matches)
            else:
                self._set_resolved(state_field, None)
                errors.append(
                    {
                        "code": f"unknown_{entity}",
                        "entity": entity,
                        "query": updates[query_key],
                    }
                )

        issues = self._policy_issues(require_identity=True)
        blocked = [
            self._with_alternatives(issue)
            for issue in issues
            if issue["kind"] == "blocked"
        ]
        missing = [issue["field"] for issue in issues if issue["kind"] == "missing"]
        unresolved_catalog_scope = any(
            field in missing
            for field in ("appointment_type_id", "provider_id", "location_id")
        )
        deferred_patient_facts = []
        if errors or candidates or blocked or unresolved_catalog_scope:
            deferred_patient_facts = [
                field for field in missing if field in {"name", "date_of_birth"}
            ]
            missing = [field for field in missing if field not in deferred_patient_facts]
        limited = candidates[:limit]
        self.state.last_candidates = limited
        self.state.more_available = max(0, len(candidates) - len(limited))

        if errors:
            status = "no_match"
        elif candidates:
            status = "clarify"
        elif blocked:
            status = "blocked"
        elif missing:
            status = "missing_facts"
        else:
            status = "ready"
        if errors:
            next_action = "explain_no_match_before_collecting_patient_details"
        elif candidates:
            next_action = "clarify_catalog_entity_before_collecting_patient_details"
        elif blocked:
            next_action = "explain_block_and_valid_alternatives"
        elif unresolved_catalog_scope:
            next_action = "resolve_catalog_scope_before_collecting_patient_details"
        elif missing:
            next_action = "collect_missing_facts"
        else:
            next_action = "find_slots"
        return {
            "status": status,
            "next_action": next_action,
            "resolved": self._resolved(),
            "search_scope": {
                "any_provider": self.state.any_provider,
                "any_location": self.state.any_location,
            },
            "candidates": limited,
            "more_available": self.state.more_available,
            "missing_facts": missing,
            "deferred_patient_facts": deferred_patient_facts,
            "blocked_options": blocked,
            "errors": errors,
            "clinic_contacts": self._clinic_contacts(),
        }

    def get_details(self, entity: str, entity_id: str) -> dict:
        try:
            return {"status": "ok", "entity": entity, "details": self.catalog.details(entity, entity_id)}
        except KeyError as error:
            raise SchedulingError("unknown_entity", str(error)) from error

    def find_slots(self, horizon_days: int, *, limit: int = 5) -> dict:
        if horizon_days <= 0:
            raise SchedulingError("invalid_horizon", "horizon_days must be positive.")
        issues = self._policy_issues(require_identity=True)
        if issues:
            self.state.offered_slot_ids.clear()
            self.state.last_horizon_end = None
            return {
                "status": "blocked",
                "horizon_days": horizon_days,
                "relaxed": [],
                "slots": [],
                "issues": issues,
                "alternatives": [] if any(i["kind"] == "missing" for i in issues) else self._slot_alternatives(horizon_days, limit),
                "clinic_contacts": self._clinic_contacts(),
            }
        horizon = self.now + timedelta(days=horizon_days)
        matches = []
        excluded_outside_hours = 0
        excluded_unavailable = 0
        for slot in self._slots.values():
            if not (
                self.now <= slot.start <= horizon
                and self._slot_matches_constraints(slot)
                and not self._slot_patient_issues(slot)
            ):
                continue
            if not self._slot_within_opening_hours(slot):
                excluded_outside_hours += 1
                continue
            if slot.slot_id in self._unavailable_slot_ids:
                excluded_unavailable += 1
                continue
            matches.append(slot)
        matches.sort(key=lambda slot: (slot.start, slot.slot_id))
        offered = matches[:limit]
        self.state.offered_slot_ids = {slot.slot_id for slot in offered}
        self.state.last_horizon_end = horizon
        return {
            "status": "ok" if matches else "no_availability",
            "horizon_days": horizon_days,
            "horizon_end": horizon.isoformat(),
            "relaxed": [],
            "slots": [self._present_slot(slot) for slot in offered],
            "alternatives": [] if matches else self._slot_alternatives(horizon_days, limit),
            "clinic_contacts": self._clinic_contacts(),
            "more_available": max(0, len(matches) - limit),
            "excluded": {
                "outside_opening_hours": excluded_outside_hours,
                "unavailable": excluded_unavailable,
            },
        }

    def select_slot(self, slot_id: str) -> dict:
        slot = self._slots.get(slot_id)
        if slot is None:
            raise SchedulingError("unknown_slot", f"Unknown slot: {slot_id}")
        if slot_id in self._unavailable_slot_ids:
            raise SchedulingError("slot_taken", "Slot is no longer available.")
        if not self._slot_within_opening_hours(slot):
            raise SchedulingError(
                "outside_opening_hours",
                "Slot falls outside the location's opening hours.",
            )
        if slot_id not in self.state.offered_slot_ids:
            raise SchedulingError("slot_not_offered", "Slot was not offered by the latest search.")
        if not self._slot_matches_constraints(slot) or self._slot_patient_issues(slot):
            raise SchedulingError("slot_incompatible", "Slot does not match current eligible state.")
        if self.state.appointment_type_id is None:
            self.state.appointment_type_id = slot.appointment_type_id
        if self.state.provider_id is None:
            self.state.provider_id = slot.provider_id
        if self.state.location_id is None:
            self.state.location_id = slot.location_id
        if self.state.selected_slot_id != slot_id:
            self.state.selected_slot_id = slot_id
            self.state.confirmation = None
        return slot.to_dict()

    def confirm_selected_slot(self) -> dict:
        facts = self.state.patient_facts
        missing = [
            field
            for field, value in (
                ("name", facts.name),
                ("date_of_birth", facts.date_of_birth),
                ("is_new_patient", facts.is_new_patient),
            )
            if value is None
        ]
        if missing:
            raise SchedulingError("missing_identity", f"Missing confirmation facts: {missing}")
        if not self.state.selected_slot_id:
            raise SchedulingError("slot_not_selected", "Select a slot before confirmation.")
        issues = self._policy_issues(require_identity=True)
        if issues:
            raise SchedulingError("not_bookable", f"Current state is not bookable: {issues}")
        self.state.confirmation = self._current_snapshot(self.state.selected_slot_id)
        return asdict(self.state.confirmation)

    def book_appointment(self, slot_id: str) -> dict:
        if slot_id in self._bookings:
            return {"status": "idempotent", "booking": self._bookings[slot_id]}
        slot = self._slots.get(slot_id)
        if slot is None:
            raise BookingError("unknown_slot", f"Unknown slot: {slot_id}")
        if slot_id in self._unavailable_slot_ids:
            raise BookingError("slot_taken", "Slot is no longer available.")
        if not self._slot_within_opening_hours(slot):
            raise BookingError(
                "outside_opening_hours",
                "Slot falls outside the location's opening hours.",
            )
        if self.state.selected_slot_id != slot_id:
            raise BookingError("slot_not_selected", "Requested slot is not currently selected.")
        if self.state.confirmation is None:
            raise BookingError("confirmation_required", "Patient confirmation is required.")
        if self.state.confirmation != self._current_snapshot(slot_id):
            raise BookingError("stale_confirmation", "Confirmation no longer matches current state.")
        issues = self._policy_issues(require_identity=True)
        if issues or not self._slot_matches_state(slot):
            raise BookingError("revalidation_failed", f"Booking revalidation failed: {issues}")
        booking = {"booking_id": f"booking-{slot_id}", **self._present_slot(slot)}
        self._bookings[slot_id] = booking
        return {"status": "booked", "booking": booking}

    def _apply_patient_updates(self, updates: dict) -> None:
        facts = self.state.patient_facts
        for key in ("name", "date_of_birth", "is_new_patient", "referral_on_file"):
            if key not in updates or getattr(facts, key) == updates[key]:
                continue
            setattr(facts, key, updates[key])
            self.state.confirmation = None
            if key in {"is_new_patient", "referral_on_file"}:
                self.state.selected_slot_id = None
                self.state.offered_slot_ids.clear()
                self.state.last_horizon_end = None

    def _apply_scope_updates(self, updates: dict) -> None:
        for flag, field, explicit_keys in (
            ("any_provider", "provider_id", {"provider_id", "provider_query"}),
            ("any_location", "location_id", {"location_id", "location_query"}),
        ):
            if explicit_keys.intersection(updates):
                if getattr(self.state, flag):
                    setattr(self.state, flag, False)
                    self._invalidate_slot_choice()
                continue
            if flag not in updates:
                continue
            value = updates[flag]
            if not isinstance(value, bool):
                raise SchedulingError("invalid_search_scope", f"{flag} must be boolean.")
            if getattr(self.state, flag) == value:
                continue
            setattr(self.state, flag, value)
            if value and getattr(self.state, field) is not None:
                setattr(self.state, field, None)
            self._invalidate_slot_choice()

    def _apply_direct_ids(self, updates: dict) -> None:
        for field, entity in (
            ("appointment_type_id", "appointment_type"),
            ("provider_id", "provider"),
            ("location_id", "location"),
        ):
            if field not in updates:
                continue
            value = updates[field]
            if value is not None:
                try:
                    self.catalog.details(entity, value)
                except KeyError as error:
                    raise SchedulingError(f"unknown_{entity}", str(error)) from error
            self._set_resolved(field, value)
        hard = updates.get("hard_constraints")
        if hard is not None:
            self.state.hard_constraints = {key for key, enabled in hard.items() if enabled}

    def _apply_preferences(self, updates: dict) -> None:
        if "preferences" in updates:
            self.state.preferences.update(updates["preferences"])

    def _set_resolved(self, field: str, value: str | None) -> None:
        if getattr(self.state, field) == value:
            return
        setattr(self.state, field, value)
        if field == "provider_id" and value is not None:
            self.state.any_provider = False
        elif field == "location_id" and value is not None:
            self.state.any_location = False
        # Keep explicitly resolved choices even when their combination is invalid.
        # Policy evaluation needs the full combination to explain the conflict and
        # return valid alternatives; silently clearing one makes tool-call order
        # affect the outcome.
        self._invalidate_slot_choice()

    def _invalidate_slot_choice(self) -> None:
        self.state.selected_slot_id = None
        self.state.confirmation = None
        self.state.offered_slot_ids.clear()
        self.state.last_horizon_end = None

    def _policy_issues(self, *, require_identity: bool = False) -> list[dict]:
        issues: list[dict] = []
        appointment_type = self._appointment_type()
        provider = self._provider()
        location = self._location()
        facts = self.state.patient_facts

        for field, value, optional in (
            ("appointment_type_id", appointment_type, False),
            ("provider_id", provider, self.state.any_provider),
            ("location_id", location, self.state.any_location),
        ):
            if value is None and not optional:
                issues.append({"kind": "missing", "field": field})
        if appointment_type and not self.catalog.providers_for_type(appointment_type.id):
            issues.append(
                {
                    "kind": "blocked",
                    "code": "unbookable_type_no_provider",
                    "appointment_type_id": appointment_type.id,
                }
            )
        if appointment_type and provider and appointment_type.id not in provider.appointment_type_ids:
            issues.append({"kind": "blocked", "code": "provider_does_not_offer_type"})
        if provider and location and location.id not in provider.location_ids:
            issues.append({"kind": "blocked", "code": "provider_not_at_location"})
        if (
            appointment_type
            and location
            and appointment_type.required_capability
            and appointment_type.required_capability not in location.capabilities
        ):
            issues.append(
                {
                    "kind": "blocked",
                    "code": "location_missing_capability",
                    "required_capability": appointment_type.required_capability,
                }
            )
        if facts.is_new_patient is None:
            issues.append({"kind": "missing", "field": "is_new_patient"})
        elif facts.is_new_patient:
            if appointment_type and not appointment_type.new_patients_allowed:
                issues.append({"kind": "blocked", "code": "new_patient_type_restricted"})
            if provider and not provider.accepting_new_patients:
                issues.append({"kind": "blocked", "code": "new_patient_provider_restricted"})
        if appointment_type and appointment_type.requires_referral:
            if facts.referral_on_file is None:
                issues.append({"kind": "missing", "field": "referral_on_file"})
            elif not facts.referral_on_file:
                issues.append({"kind": "blocked", "code": "referral_required"})
        if require_identity:
            if not facts.name:
                issues.append({"kind": "missing", "field": "name"})
            if not facts.date_of_birth:
                issues.append({"kind": "missing", "field": "date_of_birth"})
        return issues

    def _with_alternatives(self, issue: dict) -> dict:
        enriched = dict(issue)
        if issue.get("code") in {
            "location_missing_capability",
            "provider_not_at_location",
        }:
            alternatives, pending = self._valid_alternative_locations()
            if alternatives:
                enriched["alternatives"] = alternatives
                if pending:
                    # Site capability does not depend on these facts, but booking
                    # at an alternative still does; they must be collected first.
                    enriched["alternatives_pending_patient_facts"] = pending
        return enriched

    def _valid_alternative_locations(self) -> tuple[list[dict], list[str]]:
        """Return capability-valid sites plus patient facts still unknown.

        Unknown patient facts do not hide alternatives. A known patient fact
        that blocks this provider/type everywhere does, since no site helps.
        """
        appointment_type = self._appointment_type()
        provider = self._provider()
        facts = self.state.patient_facts
        if not appointment_type or not provider:
            return [], []
        if appointment_type.id not in provider.appointment_type_ids:
            return [], []
        pending = []
        if facts.is_new_patient is None:
            if not appointment_type.new_patients_allowed or not provider.accepting_new_patients:
                pending.append("is_new_patient")
        elif facts.is_new_patient:
            if not appointment_type.new_patients_allowed or not provider.accepting_new_patients:
                return [], []
        if appointment_type.requires_referral:
            if facts.referral_on_file is None:
                pending.append("referral_on_file")
            elif not facts.referral_on_file:
                return [], []
        alternatives = []
        for location_id in provider.location_ids:
            if location_id == self.state.location_id:
                continue
            location = self.catalog.locations_by_id[location_id]
            if (
                appointment_type.required_capability
                and appointment_type.required_capability not in location.capabilities
            ):
                continue
            alternatives.append(self.catalog.summary("location", location_id))
        return sorted(alternatives, key=lambda item: (item["name"], item["id"])), pending

    def _current_snapshot(self, slot_id: str) -> ConfirmationSnapshot:
        facts = self.state.patient_facts
        if None in (
            facts.name,
            facts.date_of_birth,
            facts.is_new_patient,
            self.state.appointment_type_id,
            self.state.provider_id,
            self.state.location_id,
        ):
            raise SchedulingError("incomplete_state", "Cannot snapshot incomplete state.")
        return ConfirmationSnapshot(
            name=facts.name,
            date_of_birth=facts.date_of_birth,
            is_new_patient=facts.is_new_patient,
            referral_on_file=facts.referral_on_file,
            appointment_type_id=self.state.appointment_type_id,
            provider_id=self.state.provider_id,
            location_id=self.state.location_id,
            slot_id=slot_id,
        )

    def _slot_matches_state(self, slot: Slot) -> bool:
        return (
            slot.appointment_type_id == self.state.appointment_type_id
            and slot.provider_id == self.state.provider_id
            and slot.location_id == self.state.location_id
        )

    def _slot_matches_constraints(self, slot: Slot) -> bool:
        return (
            (
                self.state.appointment_type_id is None
                or slot.appointment_type_id == self.state.appointment_type_id
            )
            and (self.state.provider_id is None or slot.provider_id == self.state.provider_id)
            and (self.state.location_id is None or slot.location_id == self.state.location_id)
        )

    def _slot_patient_issues(self, slot: Slot) -> list[dict]:
        appointment_type = self.catalog.appointment_types_by_id[slot.appointment_type_id]
        provider = self.catalog.providers_by_id[slot.provider_id]
        facts = self.state.patient_facts
        issues = []
        if facts.is_new_patient is None:
            issues.append({"kind": "missing", "field": "is_new_patient"})
        elif facts.is_new_patient:
            if not appointment_type.new_patients_allowed:
                issues.append({"kind": "blocked", "code": "new_patient_type_restricted"})
            if not provider.accepting_new_patients:
                issues.append({"kind": "blocked", "code": "new_patient_provider_restricted"})
        if appointment_type.requires_referral:
            if facts.referral_on_file is None:
                issues.append({"kind": "missing", "field": "referral_on_file"})
            elif not facts.referral_on_file:
                issues.append({"kind": "blocked", "code": "referral_required"})
        return issues

    def _slot_within_opening_hours(self, slot: Slot) -> bool:
        location = self.catalog.locations_by_id[slot.location_id]
        return within_opening_hours(location.hours, slot.start, slot.end)

    def _validate_slots(self) -> None:
        for slot in self._slots.values():
            try:
                appointment_type = self.catalog.appointment_types_by_id[slot.appointment_type_id]
                provider = self.catalog.providers_by_id[slot.provider_id]
                location = self.catalog.locations_by_id[slot.location_id]
            except KeyError as error:
                raise ValueError(f"Slot {slot.slot_id} has a dangling reference: {error}") from error
            if appointment_type.id not in provider.appointment_type_ids:
                raise ValueError(f"Slot {slot.slot_id} uses a provider/type mismatch.")
            if location.id not in provider.location_ids:
                raise ValueError(f"Slot {slot.slot_id} uses a provider/location mismatch.")
            if (
                appointment_type.required_capability
                and appointment_type.required_capability not in location.capabilities
            ):
                raise ValueError(f"Slot {slot.slot_id} uses a location without required capability.")

    def _resolved(self) -> dict:
        return {
            "appointment_type_id": self.state.appointment_type_id,
            "provider_id": self.state.provider_id,
            "location_id": self.state.location_id,
        }

    def _clinic_contacts(self) -> list[dict]:
        locations = [self._location()] if self._location() else self.catalog.locations
        service = self._appointment_type()
        if service and service.required_capability:
            locations = [loc for loc in locations if service.required_capability in loc.capabilities]
            if not locations:
                locations = [loc for loc in self.catalog.locations if service.required_capability in loc.capabilities]
        return [{"location": item.name, "phone": item.phone, "hours": item.hours} for item in locations]

    def _present_slot(self, slot: Slot) -> dict:
        return {**slot.to_dict(),
                "service": self.catalog.appointment_types_by_id[slot.appointment_type_id].name,
                "provider": self.catalog.providers_by_id[slot.provider_id].name,
                "location": self.catalog.locations_by_id[slot.location_id].name}

    def _slot_alternatives(self, horizon_days: int, limit: int) -> list[dict]:
        """Preview one-axis relaxations only; never make previews bookable."""
        horizon = self.now + timedelta(days=horizon_days)
        later = horizon + timedelta(days=14)
        alternatives = []
        for slot in self._slots.values():
            if (slot.appointment_type_id != self.state.appointment_type_id
                    or slot.slot_id in self._unavailable_slot_ids
                    or self._slot_patient_issues(slot)
                    or not self._slot_within_opening_hours(slot)
                    or not self.now <= slot.start <= later):
                continue
            differences = []
            if self.state.provider_id and slot.provider_id != self.state.provider_id:
                differences.append("provider")
            if self.state.location_id and slot.location_id != self.state.location_id:
                differences.append("location")
            if slot.start > horizon:
                differences.append("date_range")
            if len(differences) != 1:
                continue
            constraint = differences[0]
            hard = constraint in self.state.hard_constraints or f"{constraint}_id" in self.state.hard_constraints
            alternatives.append({"relaxes": constraint, "hard_constraint": hard,
                                 "requires_patient_consent": True, "slot": self._present_slot(slot)})
        alternatives.sort(key=lambda item: (item["hard_constraint"],
            {"location": 0, "provider": 1, "date_range": 2}[item["relaxes"]],
            item["slot"]["start"], item["slot"]["slot_id"]))
        return alternatives[:min(limit, 3)]

    def _appointment_type(self):
        return self.catalog.appointment_types_by_id.get(self.state.appointment_type_id)

    def _provider(self):
        return self.catalog.providers_by_id.get(self.state.provider_id)

    def _location(self):
        return self.catalog.locations_by_id.get(self.state.location_id)
