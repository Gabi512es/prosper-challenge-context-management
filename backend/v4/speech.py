"""How catalog values and names are spoken. Pure functions, no state."""
import re

from scheduling_dialogue import SchedulingDialogue

DAYS = {'mon': 'Monday', 'tue': 'Tuesday', 'wed': 'Wednesday', 'thu': 'Thursday',
        'fri': 'Friday', 'sat': 'Saturday', 'sun': 'Sunday'}
MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
          'September', 'October', 'November', 'December')
HOURS = re.compile(r'^\s*([A-Za-z]{3})[a-z]*(?:\s*-\s*([A-Za-z]{3})[a-z]*)?\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$')
STREET = {'St': 'Street', 'Ave': 'Avenue', 'Blvd': 'Boulevard', 'Rd': 'Road', 'Dr': 'Drive', 'Ln': 'Lane', 'Ste': 'Suite'}


THANKS = re.compile(r"\b(thank|thanks|thank you|appreciate)\b", re.I)


def words_of(text):
    return re.findall(r"[a-z0-9']+", text.casefold())


def provider_name(provider):
    """Catalog role controls the spoken title, not a caller's honorific or an
    inconsistent display-name prefix. IDs/catalog records stay intact."""
    roles = {'NP': 'Nurse practitioner', 'PA': 'Physician assistant'}
    if provider.title in roles:
        name = provider.name.removeprefix('Dr. ').removeprefix('Dr ')
        return f'{roles[provider.title]} {name}'
    return provider.name


def spoken_list(labels):
    """'A', 'A and B', 'A, B, and C'."""
    labels = list(labels)
    if len(labels) < 3:
        return ' and '.join(labels)
    return ', '.join(labels[:-1]) + ', and ' + labels[-1]


def spoken_time(hour, minute):
    if (hour, minute) == (12, 0):
        return 'noon'
    clock = hour % 12 or 12
    return (f'{clock}' if minute == 0 else f'{clock}:{minute:02d}') + (' AM' if hour < 12 else ' PM')


def spoken_hours(value):
    """'Mon-Fri 8:00-17:00' -> 'Monday to Friday, 8 AM to 5 PM'; unknown formats unchanged."""
    spoken = []
    for segment in re.split(r'[;,]', value):
        m = HOURS.match(segment)
        if not m or m.group(1).lower() not in DAYS or (m.group(2) and m.group(2).lower() not in DAYS):
            return value
        days = DAYS[m.group(1).lower()] + (' to ' + DAYS[m.group(2).lower()] if m.group(2) else '')
        spoken.append(f'{days}, {spoken_time(int(m[3]), int(m[4]))} to {spoken_time(int(m[5]), int(m[6]))}')
    return '; '.join(spoken)


def spoken_phone(value):
    """Ten-digit numbers are read digit by digit in their three groups."""
    digits = re.sub(r'\D', '', value)
    if len(digits) != 10:
        return value
    return ', '.join(' '.join(group) for group in (digits[:3], digits[3:6], digits[6:]))


def spoken_address(value):
    return re.sub(r'\b(' + '|'.join(STREET) + r')\b\.?', lambda m: STREET[m.group(1)], value)


def spoken_name(name):
    """Catalog display punctuation is not spoken ('EKG / Electrocardiogram')."""
    return name.replace('OB/GYN', 'OB-GYN').replace(' / ', ' or ')


def spoken_service(service):
    """'MRI - Knee' -> 'a knee MRI'."""
    return SchedulingDialogue.spoken_service(spoken_name(service.name))


def ordinal(day):
    return f"{day}{'th' if 10 <= day % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')}"


def capitalized(name):
    """'alex morgan' -> 'Alex Morgan'; names already in mixed case are kept."""
    if name != name.lower() and name != name.upper():
        return name
    return ' '.join('-'.join(part[:1].upper() + part[1:].lower() for part in word.split('-'))
                    for word in name.split())
