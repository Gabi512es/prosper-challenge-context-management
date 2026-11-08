"""Read-only catalog models, indexes, and integrity validation."""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .opening_hours import parse_opening_hours


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    address: str
    city: str
    phone: str
    hours: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    title: str
    specialty: str
    location_ids: tuple[str, ...]
    accepting_new_patients: bool
    languages: tuple[str, ...]
    appointment_type_ids: tuple[str, ...]


@dataclass(frozen=True)
class AppointmentType:
    id: str
    name: str
    specialty: str
    duration_min: int
    requires_referral: bool
    new_patients_allowed: bool
    required_capability: str | None = None


@dataclass(frozen=True)
class Catalog:
    policies: tuple[str, ...]
    locations: tuple[Location, ...]
    providers: tuple[Provider, ...]
    appointment_types: tuple[AppointmentType, ...]

    def __post_init__(self):
        object.__setattr__(self, "locations_by_id", _unique(self.locations, "location"))
        object.__setattr__(self, "providers_by_id", _unique(self.providers, "provider"))
        object.__setattr__(
            self,
            "appointment_types_by_id",
            _unique(self.appointment_types, "appointment type"),
        )
        self._validate_references()

    def _validate_references(self) -> None:
        location_ids = set(self.locations_by_id)
        type_ids = set(self.appointment_types_by_id)
        for location in self.locations:
            parse_opening_hours(location.hours)
        for provider in self.providers:
            if not provider.location_ids or not provider.appointment_type_ids:
                raise ValueError(f"Provider {provider.id} has an empty relationship list.")
            unknown_locations = set(provider.location_ids) - location_ids
            unknown_types = set(provider.appointment_type_ids) - type_ids
            if unknown_locations or unknown_types:
                raise ValueError(
                    f"Provider {provider.id} has dangling references: "
                    f"locations={sorted(unknown_locations)}, types={sorted(unknown_types)}"
                )

    def providers_for_type(self, appointment_type_id: str) -> list[Provider]:
        return [
            provider
            for provider in self.providers
            if appointment_type_id in provider.appointment_type_ids
        ]

    def search(
        self,
        entity: str,
        query: str,
        *,
        specialty: str | None = None,
    ) -> list[dict]:
        collection = self._collection(entity)
        normalized_query = _normalize(query, strip_provider_title=entity == "provider")
        if specialty:
            collection = tuple(
                item
                for item in collection
                if hasattr(item, "specialty")
                and _specialty_matches(specialty, item.specialty)
            )
        exact = [
            item
            for item in collection
            if _normalize(item.name, strip_provider_title=entity == "provider")
            == normalized_query
        ]
        same_words = [
            item
            for item in collection
            if set(
                _normalize(item.name, strip_provider_title=entity == "provider").split()
            )
            == set(normalized_query.split())
        ]
        matches = exact or same_words or [
            item
            for item in collection
            if normalized_query
            and normalized_query
            in _normalize(item.name, strip_provider_title=entity == "provider")
        ]
        return [self.summary(entity, item.id) for item in matches]

    def details(self, entity: str, entity_id: str) -> dict:
        item = self._by_id(entity).get(entity_id)
        if item is None:
            raise KeyError(f"Unknown {entity} id: {entity_id}")
        value = asdict(item)
        for key, field_value in value.items():
            if isinstance(field_value, tuple):
                value[key] = list(field_value)
        return value

    def summary(self, entity: str, entity_id: str) -> dict:
        item = self._by_id(entity).get(entity_id)
        if item is None:
            raise KeyError(f"Unknown {entity} id: {entity_id}")
        result = {"id": item.id, "name": item.name}
        if hasattr(item, "specialty"):
            result["specialty"] = item.specialty
        if entity == "provider":
            result["title"] = item.title
            result["location_ids"] = list(item.location_ids)
        return result

    def _collection(self, entity: str):
        if entity == "location":
            return self.locations
        if entity == "provider":
            return self.providers
        if entity == "appointment_type":
            return self.appointment_types
        raise KeyError(f"Unknown entity kind: {entity}")

    def _by_id(self, entity: str):
        if entity == "location":
            return self.locations_by_id
        if entity == "provider":
            return self.providers_by_id
        if entity == "appointment_type":
            return self.appointment_types_by_id
        raise KeyError(f"Unknown entity kind: {entity}")


def _unique(items, label: str) -> dict:
    result = {}
    for item in items:
        if item.id in result:
            raise ValueError(f"Duplicate {label} id: {item.id}")
        result[item.id] = item
    return result


def _normalize(value: str, *, strip_provider_title: bool = False) -> str:
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    if strip_provider_title:
        tokens = [token for token in tokens if token not in {"dr", "doctor"}]
    return " ".join(tokens)


def _specialty_matches(query: str, catalog_value: str) -> bool:
    """Match common practitioner nouns to catalog specialty labels generically."""
    normalized_query = _normalize(query)
    query_tokens = set(normalized_query.split())
    for variant in _specialty_variants(catalog_value):
        variant_tokens = set(variant.split())
        if normalized_query == variant or (variant_tokens and variant_tokens <= query_tokens):
            return True
    return False


def _specialty_variants(value: str) -> set[str]:
    normalized = _normalize(value)
    words = normalized.split()
    if not words:
        return set()
    variants = {normalized}
    derived = practitioner_nouns(value)
    prefix_words = words[:-1]
    for word in derived:
        variants.add(word)
        if len(word.split()) == 1:
            variants.add(" ".join((*prefix_words, word)))
    return variants


_IRREGULAR_PRACTITIONER_NOUNS = {
    "allergy immunology": {"allergist", "immunologist"},
    "dental": {"dentist"},
    "ent": {"ent doctor", "otolaryngologist"},
    "general": {"general practitioner", "general doctor"},
    "internal medicine": {"internist"},
    "lab": {"lab technician", "phlebotomist"},
    "ob gyn": {"ob gyn doctor", "obgyn", "obstetrician", "gynecologist"},
    "physical therapy": {"physical therapist", "physiotherapist"},
}


def practitioner_nouns(specialty: str) -> set[str]:
    """Generate searchable practitioner nouns for one catalog specialty."""
    normalized = _normalize(specialty)
    words = normalized.split()
    if not words:
        return set()
    nouns = set(_IRREGULAR_PRACTITIONER_NOUNS.get(normalized, set()))
    for word in words:
        nouns.update(_practitioner_forms(word))
    if words[-1] == "medicine" and len(words) > 1:
        prefix = " ".join(words[:-1])
        nouns.update(
            {
                f"{prefix} doctor",
                f"{prefix} physician",
                f"{prefix} practitioner",
            }
        )
    return nouns


def _practitioner_forms(specialty_word: str) -> set[str]:
    """Return ordinary practitioner nouns derived from a specialty label."""
    derived: set[str] = set()
    if specialty_word.endswith("ology"):
        derived.add(f"{specialty_word[:-5]}ologist")
    if specialty_word.endswith("iatrics"):
        stem = specialty_word[:-7]
        derived.update({f"{stem}iatric", f"{stem}iatrician"})
    elif specialty_word.endswith("ics"):
        derived.update({specialty_word[:-1], f"{specialty_word[:-3]}ist"})
    if specialty_word.endswith("iatry"):
        derived.add(f"{specialty_word[:-5]}iatrist")
    return derived


def load_catalog(path: Path) -> Catalog:
    data = json.loads(path.read_text())
    return Catalog(
        policies=tuple(data["policies"]),
        locations=tuple(
            Location(
                id=item["id"],
                name=item["name"],
                address=item["address"],
                city=item["city"],
                phone=item["phone"],
                hours=item["hours"],
                capabilities=tuple(item["capabilities"]),
            )
            for item in data["locations"]
        ),
        providers=tuple(
            Provider(
                id=item["id"],
                name=item["name"],
                title=item["title"],
                specialty=item["specialty"],
                location_ids=tuple(item["location_ids"]),
                accepting_new_patients=item["accepting_new_patients"],
                languages=tuple(item["languages"]),
                appointment_type_ids=tuple(item["appointment_type_ids"]),
            )
            for item in data["providers"]
        ),
        appointment_types=tuple(
            AppointmentType(
                id=item["id"],
                name=item["name"],
                specialty=item["specialty"],
                duration_min=item["duration_min"],
                requires_referral=item["requires_referral"],
                new_patients_allowed=item["new_patients_allowed"],
                required_capability=item.get("required_capability"),
            )
            for item in data["appointment_types"]
        ),
    )
