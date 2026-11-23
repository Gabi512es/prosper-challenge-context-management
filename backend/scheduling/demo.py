"""Synthetic demo availability, separate from closed-world evaluation fixtures."""

import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .opening_hours import parse_opening_hours, within_opening_hours


def generate_demo_availability(catalog, now: datetime, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    local = now.astimezone(ZoneInfo("America/Los_Angeles"))
    slots = []
    # Allocate non-overlapping provider time across every valid combination.
    for provider in catalog.providers:
        cursor = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        for location_id in sorted(provider.location_ids):
            location = catalog.locations_by_id[location_id]
            days, opening, _ = parse_opening_hours(location.hours)
            for type_id in sorted(provider.appointment_type_ids):
                service = catalog.appointment_types_by_id[type_id]
                if service.required_capability and service.required_capability not in location.capabilities:
                    continue
                start = max(cursor, cursor.replace(hour=opening.hour, minute=opening.minute)) + timedelta(minutes=15 * rng.randrange(0, 2))
                while start.weekday() not in days or not within_opening_hours(location.hours, start, start + timedelta(minutes=service.duration_min)):
                    start = (start + timedelta(days=1)).replace(hour=opening.hour, minute=opening.minute)
                if start >= local + timedelta(days=14):
                    raise ValueError("Demo combinations exceed the two-week allocation window")
                end = start + timedelta(minutes=service.duration_min)
                slots.append(dict(slot_id=f"demo-{provider.id}-{location_id}-{type_id}", provider_id=provider.id,
                    location_id=location_id, appointment_type_id=type_id, start=start.isoformat(), end=end.isoformat()))
                cursor = end
    repeated = []
    for slot in slots:
        start = datetime.fromisoformat(slot["start"]) + timedelta(days=7)
        end = datetime.fromisoformat(slot["end"]) + timedelta(days=7)
        if end <= local + timedelta(days=14):
            repeated.append({**slot, "slot_id": slot["slot_id"] + "-week2",
                             "start": start.isoformat(), "end": end.isoformat()})
    return slots + repeated
