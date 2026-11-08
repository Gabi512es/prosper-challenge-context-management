"""Parse the catalog's compact weekly opening-hours strings."""

import re
from datetime import datetime, time
from functools import lru_cache


DAY_INDEX = {
    "Mon": 0,
    "Tue": 1,
    "Wed": 2,
    "Thu": 3,
    "Fri": 4,
    "Sat": 5,
    "Sun": 6,
}
HOURS_PATTERN = re.compile(
    r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
    r"(?:-(Mon|Tue|Wed|Thu|Fri|Sat|Sun))?\s+"
    r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$"
)


@lru_cache(maxsize=None)
def parse_opening_hours(value: str) -> tuple[frozenset[int], time, time]:
    """Return allowed weekdays and same-day opening/closing times."""
    match = HOURS_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Unsupported opening-hours format: {value!r}")
    first_day, last_day, open_hour, open_minute, close_hour, close_minute = (
        match.groups()
    )
    first = DAY_INDEX[first_day]
    last = DAY_INDEX[last_day or first_day]
    if first <= last:
        days = frozenset(range(first, last + 1))
    else:
        days = frozenset((*range(first, 7), *range(0, last + 1)))
    opening = _time(open_hour, open_minute, value)
    closing = _time(close_hour, close_minute, value)
    if closing <= opening:
        raise ValueError(f"Opening hours must close after they open: {value!r}")
    return days, opening, closing


def within_opening_hours(value: str, start: datetime, end: datetime) -> bool:
    """Whether an entire slot fits within one catalog opening interval."""
    days, opening, closing = parse_opening_hours(value)
    return (
        start < end
        and start.date() == end.date()
        and start.weekday() in days
        and opening <= start.timetz().replace(tzinfo=None)
        and end.timetz().replace(tzinfo=None) <= closing
    )


def _time(hour: str, minute: str, source: str) -> time:
    try:
        return time(int(hour), int(minute))
    except ValueError as error:
        raise ValueError(f"Invalid opening-hours time in {source!r}") from error
