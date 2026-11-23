"""Session and fixture models for the scheduling core."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PatientFacts:
    name: str | None = None
    date_of_birth: str | None = None
    is_new_patient: bool | None = None
    referral_on_file: bool | None = None


@dataclass(frozen=True)
class ConfirmationSnapshot:
    name: str
    date_of_birth: str
    is_new_patient: bool
    referral_on_file: bool | None
    appointment_type_id: str
    provider_id: str
    location_id: str
    slot_id: str


@dataclass
class SessionState:
    patient_facts: PatientFacts = field(default_factory=PatientFacts)
    appointment_type_id: str | None = None
    provider_id: str | None = None
    location_id: str | None = None
    any_provider: bool = False
    any_location: bool = False
    hard_constraints: set[str] = field(default_factory=set)
    preferences: dict = field(default_factory=dict)
    last_candidates: list[dict] = field(default_factory=list)
    more_available: int = 0
    offered_slot_ids: set[str] = field(default_factory=set)
    last_horizon_end: datetime | None = None
    selected_slot_id: str | None = None
    confirmation: ConfirmationSnapshot | None = None


@dataclass(frozen=True)
class Slot:
    slot_id: str
    provider_id: str
    location_id: str
    appointment_type_id: str
    start: datetime
    end: datetime

    @classmethod
    def from_dict(cls, value: dict) -> "Slot":
        return cls(
            slot_id=value["slot_id"],
            provider_id=value["provider_id"],
            location_id=value["location_id"],
            appointment_type_id=value["appointment_type_id"],
            start=datetime.fromisoformat(value["start"]),
            end=datetime.fromisoformat(value["end"]),
        )

    def to_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "provider_id": self.provider_id,
            "location_id": self.location_id,
            "appointment_type_id": self.appointment_type_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }
