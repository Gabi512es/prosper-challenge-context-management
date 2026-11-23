"""Offline validation of the dialogue-act contract. No model or runtime I/O.

The M0 acts are validated strictly as one Output. The two flow acts added in
v1.6+ (request_next_step, restatement) are split off first and checked one by
one: a malformed flow act is dropped, never guessed at, and never voids the
turn's other acts."""
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ActError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class DateParts(Closed):
    year: int | None
    month: int | None
    day: int | None

    @model_validator(mode='after')
    def supported_parts(self):
        if all(x is None for x in (self.year, self.month, self.day)):
            raise ValueError('DOB must supply at least one component')
        for value, upper in ((self.year, 9999), (self.month, 12), (self.day, 31)):
            if value is not None and not 1 <= value <= upper:
                raise ValueError('Invalid date component')
        return self


class TextDelta(Closed):
    field: Literal['service', 'provider', 'provider_specialty', 'location', 'name']
    value: Annotated[str, Field(min_length=1)]


class BirthDelta(Closed):
    field: Literal['date_of_birth']
    value: DateParts


class BoolDelta(Closed):
    field: Literal['new_patient', 'referral', 'any_provider', 'any_location']
    value: bool


class AppointmentDateDelta(Closed):
    field: Literal['appointment_date']
    value: str


class ProximityDelta(Closed):
    field: Literal['location_preference']
    value: Literal['time', 'place', 'unclear']


class HardValue(Closed):
    field: Literal['provider', 'provider_specialty', 'location', 'appointment_date']
    enabled: bool


class HardDelta(Closed):
    field: Literal['hard_constraint']
    value: HardValue


class RetractDelta(Closed):
    field: Literal['service', 'provider', 'provider_specialty', 'location', 'name',
                   'date_of_birth', 'new_patient', 'referral', 'appointment_date']
    value: None


class DateShiftDelta(Closed):
    """A relative date (v1.10): 'later' than the times offered, or a week later;
    'earlier' (v1.12): the earliest times ("sooner", "the soonest")."""
    field: Literal['date_shift']
    value: Literal['later', 'week_later', 'earlier']


Delta = TextDelta | BirthDelta | BoolDelta | AppointmentDateDelta | ProximityDelta | HardDelta | DateShiftDelta


class Ordinal(Closed):
    by: Literal['ordinal']
    ordinal: Annotated[int, Field(ge=1)]


class NamedOption(Closed):
    by: Literal['name']
    words: Annotated[str, Field(min_length=1)]
    option_id: str


class Target(Closed):
    type: Literal['proposal', 'question']
    id: str


class Act(Closed):
    quote: Annotated[str | None, Field(max_length=160)]


class SelectOption(Act):
    kind: Literal['select_option']
    presentation_id: str
    selector: Ordinal | NamedOption


class SetField(Act):
    kind: Literal['set_field']
    delta: Delta


class Correct(Act):
    kind: Literal['correct']
    delta: Delta | RetractDelta


class Affirm(Act):
    kind: Literal['affirm']
    target: Target


class Deny(Act):
    kind: Literal['deny']
    target: Target


class Information(Act):
    kind: Literal['information_question']
    entity: Literal['location', 'provider', 'service', 'appointment', 'assistant']
    name: str | None
    reference_id: str | None
    attribute: Literal['hours', 'phone', 'address', 'services', 'locations', 'specialty',
                       'referral', 'new_patient_policy', 'date', 'time', 'identity', 'block_reason']


class Repeat(Act):
    kind: Literal['repeat_request']
    message_id: str
    part: Literal['all', 'date', 'time', 'location', 'provider', 'identity']


class Cancel(Act):
    kind: Literal['cancel']
    scope: Literal['pending_request', 'recorded_booking']


class Human(Act):
    kind: Literal['human_request']
    action: Literal['request']


class Unclear(Act):
    kind: Literal['unclear']
    subject: Literal['meaning', 'reference', 'date_role', 'date_value', 'scope',
                     'consent', 'noise', 'unsupported']


class Urgent(Act):
    kind: Literal['urgent_escalation']


class Acknowledge(Act):
    kind: Literal['acknowledge']


class Pause(Act):
    kind: Literal['pause']


class Unsupported(Act):
    kind: Literal['unsupported']
    topic: Literal['clock_time', 'geographic_ranking', 'timezone_conversion',
                   'recorded_booking_change', 'live_transfer', 'callback',
                   'same_call_continuation', 'other']


class Output(Closed):
    acts: Annotated[list[SelectOption | SetField | Correct | Affirm | Deny | Information |
                         Repeat | Cancel | Human | Unclear | Urgent | Acknowledge |
                         Pause | Unsupported], Field(min_length=1, max_length=16)]


@dataclass(frozen=True)
class ValidatedActs:
    acts: tuple[dict, ...]
    quote_starts: tuple[tuple[int, ...], ...]


def validate_acts(raw: dict, caller_text: str) -> ValidatedActs:
    try:
        output = Output.model_validate(raw)
    except ValidationError as error:
        raise ActError('invalid_act_shape', 'Output does not match the act contract') from error
    positions = []
    for act in output.acts:
        quote = act.quote
        starts = tuple(i for i in range(len(caller_text)) if quote and caller_text.startswith(quote, i))
        if quote is not None and (not quote or not starts):
            raise ActError('quote_not_found', 'Supplied quote is not in the caller turn')
        positions.append(starts)
    return ValidatedActs(tuple(a.model_dump() for a in output.acts), tuple(positions))


FLOW_ACTS = {'request_next_step', 'restatement'}


def _valid_flow_act(act, caller_text):
    quote = act.get('quote')
    if quote is not None and (not isinstance(quote, str) or quote not in caller_text):
        return False
    if act['kind'] == 'request_next_step':
        return set(act) == {'kind', 'quote'}
    target = act.get('target')
    return (set(act) == {'kind', 'quote', 'target'} and isinstance(target, dict)
            and target.get('type') in {'proposal', 'question'} and isinstance(target.get('id'), str))


def split_flow_acts(raw, caller_text):
    """(valid flow acts, or None when the turn has none; the raw M0 acts)."""
    items = raw.get('acts') if isinstance(raw, dict) else None
    is_flow = lambda act: isinstance(act, dict) and act.get('kind') in FLOW_ACTS
    if not isinstance(items, list) or not any(is_flow(act) for act in items):
        return None, raw
    flow = [dict(act) for act in items if is_flow(act) and _valid_flow_act(act, caller_text)]
    return flow, {'acts': [act for act in items if not is_flow(act)]}
