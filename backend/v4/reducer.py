"""Offline v4 scheduling reducer. No model, speech, worker or runtime wiring.

A caller turn is first repaired (acts the model mislabels in known ways, flow
acts, request boundaries), then applied by the core turn reducer, which owns
references, consent, controls and the engine updates.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json
import re
from zoneinfo import ZoneInfo

from scheduling.engine import SchedulingError
from scheduling.catalog import _specialty_matches
from scheduling.models import PatientFacts, SessionState
from .acts import ActError, split_flow_acts, validate_acts
from .catalog import matching_sites
from .speech import THANKS, capitalized, provider_name, words_of

CLINIC_ZONE = ZoneInfo('America/Los_Angeles')
ENTITY = {'service': ('appointment_type', 'appointment_type_id'),
          'provider': ('provider', 'provider_id'), 'location': ('location', 'location_id')}
FACT = {'name': 'name', 'date_of_birth': 'date_of_birth',
        'new_patient': 'is_new_patient', 'referral': 'referral_on_file'}
CONTROL_PRIORITY = {'active': 0, 'paused': 1, 'cancelled': 2, 'human': 3, 'urgent': 4}
# Only an urgent escalation or a request for a person ends scheduling.
TERMINAL = {'urgent', 'human'}
# Booking consent needs an explicit acceptance in the quoted words; restating
# the read-back ("Monday, November twenty-third at four twenty") is not one.
# The interpreter's restatement act is extra evidence only.
ACCEPTANCE = re.compile(
    r"\b(yes|yeah|yea|yep|yup|ya|sure|ok|okay|alright|all right|please|go ahead|go for it|book it|book that|"
    r"book me|do it|do that|sounds good|sounds great|that works|works for me|correct|that's right|"
    r"perfect|great|fine|absolutely|definitely|confirm|confirmed|let's do|i'll take it|deal)\b", re.I)
# A request for a person names one; "get me to Richmond" asks for a site.
PERSON = re.compile(
    r"\b(person|human|someone|somebody|anyone|anybody|staff|representative|rep|agent|operator|receptionist|"
    r"front desk|manager|people|transfer|real)\b", re.I)
# A referral that is promised, being sent or expected is not on file. "It should be on
# file" says the caller believes it is there: that counts as on file.
FUTURE_REFERRAL = re.compile(
    r"\b(tomorrow|will|won't|going to|gonna|sending|send it|sent over|later|next (week|month)|soon|not yet|"
    r"hasn't|haven't|has not|have not|waiting|pending|on (its|the) way|getting)\b", re.I)
NEW_PATIENT = re.compile(r"\b(i'?m|i am)( actually| still)? (a )?new patient\b|\bmy first (time|visit)\b|"
                         r"\bfirst time (there|here|visiting)\b|\bnever been (there|here|seen)\b", re.I)
EXISTING_PATIENT = re.compile(r"\b(i'?m|i am)( actually)? (an )?(existing|returning|current) patient\b|"
                              r"\b(i'?ve|i have) been (there|here|seen there|seen here) before\b", re.I)
NEW_PATIENT_VISIT = re.compile(r"\bnew patient visit\b", re.I)
PROXIMITY = re.compile(r"\b(nearest|closest|near me|nearby|close to me|close by|near my)\b", re.I)
# Words that ask for an appointment without naming a service.
GENERIC_SERVICE = {'appointment', 'appointments', 'visit', 'something', 'booking', 'book', 'schedule', 'slot',
                   'a', 'an', 'the', 'some', 'kind', 'of', 'to', 'make'}
# Acts that may follow up after a booking or a cancel ("thanks", "no, that's all").
CLOSING_ACTS = {'deny', 'acknowledge', 'affirm', 'cancel'}
REQUEST_ACTS = {'set_field', 'correct', 'select_option', 'information_question', 'repeat_request',
                'cancel', 'affirm', 'deny'}
# Fields that make a booking request (not a patient fact alone).
BOOKING_FIELDS = {'service', 'provider', 'location', 'provider_specialty', 'appointment_date', 'date_shift',
                  'any_provider', 'any_location', 'hard_constraint', 'location_preference'}
# Connector words skipped when spoken words spell a catalog abbreviation ("ear, nose and throat" = ENT).
CONNECTORS = {'and', 'the', 'of'}


def _spells_abbreviation(words, specialty):
    """A catalog abbreviation ("ENT") matches consecutive spoken words whose
    initials spell it ("ear, nose and throat"). Generic: no per-specialty table."""
    letters = re.sub(r'[^A-Za-z]', '', specialty)
    if not (2 <= len(letters) <= 6 and specialty.replace('/', '').isupper()):
        return False
    initials = ''.join(w[0] for w in words_of(words) if w not in CONNECTORS)
    return letters.casefold() in initials


@dataclass(frozen=True)
class Presentation:
    id: str
    entity: str
    option_ids: tuple[str, ...]
    generation: int
    delivered: bool = False


@dataclass(frozen=True)
class Proposal:
    id: str
    kind: str
    snapshot: tuple
    message_id: str
    slot_id: str | None = None
    delivered: bool = False
    status: str = 'open'


@dataclass(frozen=True)
class Question:
    id: str
    kind: str
    field: str | None = None
    delivered: bool = False
    proposal_id: str | None = None


@dataclass(frozen=True)
class Arrival:
    proposals: frozenset[str]
    presentations: frozenset[str]
    questions: frozenset[str]


@dataclass
class TurnRepair:
    """What the repair of one turn's acts has decided so far."""
    caller_text: str
    open_booking: object
    identity_question: bool
    referral_question: bool
    future_referral: bool
    stated: set
    act_count: int
    changed: bool = False
    consent: str | None = None


@dataclass(frozen=True)
class TurnResult:
    status: str
    state_version: int
    effects: tuple[dict, ...] = ()
    errors: tuple[str, ...] = ()
    readback_required: bool = False
    resolution: dict | None = None
    duplicate: bool = False


class SchedulingReducer:
    """One session's typed facts/proposals. M2 will own input scheduling and speech.

    Call receive() when input arrives, reduce() in order, and commit_booking()
    only after the caller queue/endpoint is closed. reduce never books.
    """
    def __init__(self, engine, *, requested_specialty=None):
        self.engine = engine
        self.state_version = self.generation = self._serial = 0
        self.requested_specialty = self._specialty(requested_specialty) if requested_specialty else None
        self.appointment_date = None
        self.partial_dob = {}
        self.identity_confirmed = None
        self.fields = {}
        self.provenance = {}
        self.presentations = {}
        self.proposals = {}
        self.messages = {}
        self.question = None
        self._question_ids = set()
        self.control = 'active'
        self.readback_required = False
        self.consent_ledger = []
        self.pending_inputs = {}
        self.processed = {}
        # True from a pending-request cancel until the caller supplies new booking facts.
        self.request_cancelled = False
        # The facts of a declined or cancelled request, until the caller resumes it or the call ends.
        self.set_aside = None
        self.set_aside_by = None  # 'decline' (a block's alternatives refused) or 'cancel' (the caller stopped).
        # The alternative the last block offered, by field: {'service': id, 'provider': id, 'location': id}
        # (None where several were offered). Set by the composer; a yes to the block accepts it.
        self.block_offer = {}
        self.block_offer_options = {}  # Every option the last block offered, by field (lists of IDs).
        self.referral_unknown = False  # The caller could not say whether a referral is on file.
        self.block_turns = 0  # Caller turns in a row answering a block.
        self.referral_answers = {}  # Service ID -> referral on file (True/False), as answered.
        self.last_turn_fields = set()
        self.last_turn_changed = False
        self.restated = set()
        # Earliest slot start to offer, from a relative date ("the week after").
        self.not_before = None
        self.last_shift = self._planned_shift = None  # The last relative date: (kind, offered IDs, latest start, window before).
        # Bookings recorded before the current request began.
        self.bookings_before_request = 0
        # The caller asked for "an appointment" without naming the service.
        self.generic_service_request = False
        # A one-word name was given and the last name was asked for once.
        self.surname_requested = False
        # "The nearest clinic": list the eligible sites once instead of a site name.
        self.proximity_request = False
        # "What kind of appointment?" was asked: a vague answer gets suggestions, not "could not find".
        self.kind_asked = False
        # (field, value) of the name spelled letter by letter in the previous turn.
        self.spelled = None

    def _id(self, prefix):
        self._serial += 1
        return f'{prefix}-{self._serial}'

    def request_finished(self):
        """True when the current request ended in a recorded booking."""
        return len(self.engine.bookings) > self.bookings_before_request

    def partial_name(self):
        name = self.engine.state.patient_facts.name
        return name if name and len(name.split()) == 1 else None

    def nothing_pending(self):
        """After a booking, or after a cancel with no new request."""
        return (self.control == 'active' and (self.request_finished() or self.request_cancelled)
                and not any(p.kind == 'booking' and p.status in {'open', 'accepted'} for p in self.proposals.values()))

    def open_booking(self):
        """The delivered, current, not yet accepted booking read-back, if any."""
        return next((p for p in reversed(list(self.proposals.values()))
                     if p.kind == 'booking' and p.status == 'open' and p.delivered and self._current_proposal(p)), None)

    def named_site(self, text):
        """The one catalog site whose distinctive words are all in the text ("Richmond")."""
        sites = matching_sites(self.engine.catalog.locations, text)
        return sites[0].name if len(sites) == 1 else None

    def identity(self):
        f = self.engine.state.patient_facts
        return f.name, f.date_of_birth

    def _specialty(self, words):
        specialties = {p.specialty for p in self.engine.catalog.providers}
        matches = ({s for s in specialties if _specialty_matches(words, s)}
                   or {s for s in specialties if _spells_abbreviation(words, s)}
                   or self._specialty_from_catalog_words(words, specialties))
        if len(matches) != 1:
            raise ActError('unknown_or_ambiguous_specialty', 'Choose a catalog specialty')
        return matches.pop()

    def _specialty_from_catalog_words(self, words, specialties):
        """Generic fallbacks from catalog text, no alias table: a spoken word that
        starts a specialty word ("gastro" -> Gastroenterology), else a word that,
        among service names, belongs to one specialty only ("gi" -> GI Consultation,
        Gastroenterology). Each must point at exactly one specialty."""
        spoken = [w for w in words_of(words) if w not in CONNECTORS]
        prefix = {s for s in specialties for w in spoken if len(w) >= 4
                  and any(part.startswith(w) for part in words_of(s))}
        if len(prefix) == 1:
            return prefix
        owners = {}
        for t in self.engine.catalog.appointment_types:
            for part in words_of(t.name):
                owners.setdefault(part, set()).add(t.specialty)
        named = {s for w in spoken for s in owners.get(w, ()) if len(owners[w]) == 1}
        return named if len(named) == 1 else set()

    def receive(self, event_id):
        """Queue metadata only; does not invalidate an already running turn."""
        if event_id in self.processed or event_id in self.pending_inputs:
            return False
        self.pending_inputs[event_id] = Arrival(
            frozenset(k for k, p in self.proposals.items() if p.delivered and p.status in {'open', 'accepted'}),
            frozenset(k for k, p in self.presentations.items() if p.delivered and p.generation == self.generation),
            frozenset([self.question.id] if self.question and self.question.delivered else []))
        return True

    def set_question(self, kind, *, field=None, question_id=None, delivered=False, proposal_id=None):
        if proposal_id is not None:
            p = self.proposals.get(proposal_id)
            if (not p or kind != p.kind + '_consent' or field is not None
                    or p.status != 'open' or not self._current_proposal(p)):
                raise ActError('invalid_consent_question', 'A consent question must bind its current read-back')
        ident = question_id or self._id('question')
        if ident in self._question_ids:
            raise ActError('reused_reference', 'Question IDs cannot change meaning')
        self._question_ids.add(ident)
        self.question = Question(ident, kind, field, delivered, proposal_id)
        self.state_version += 1
        return self.question

    def deliver_question(self, question_id):
        if not self.question or self.question.id != question_id:
            raise ActError('stale_question', 'Cannot deliver a retired question')
        self.question = replace(self.question, delivered=True)

    def present(self, entity, option_ids, *, presentation_id=None, delivered=False, message_id=None):
        ids = tuple(option_ids)
        if entity not in {*ENTITY, 'slot'} or not ids or len(set(ids)) != len(ids):
            raise ActError('invalid_presentation', 'Presentation needs ordered unique option IDs')
        for option_id in ids:
            if entity == 'slot':
                if option_id not in self.engine.state.offered_slot_ids:
                    raise ActError('slot_not_offered', 'Only current availability results may be presented')
            else:
                self.engine.catalog.details(ENTITY[entity][0], option_id)
        pid = presentation_id or self._id('presentation')
        if pid in self.presentations:
            raise ActError('reused_reference', 'Presentation IDs are immutable')
        if (message_id or pid) in self.messages:
            raise ActError('reused_reference', 'Message IDs cannot change meaning')
        p = Presentation(pid, entity, ids, self.generation, delivered)
        self.presentations[pid] = p
        self.messages[message_id or pid] = ('presentation', pid)
        self.state_version += 1
        return p

    def deliver_presentation(self, pid):
        p = self.presentations[pid]
        if p.generation != self.generation:
            raise ActError('stale_presentation', 'Cannot deliver a retired presentation')
        self.presentations[pid] = replace(p, delivered=True)

    def _booking_snapshot(self, slot_id):
        slot = self.engine._slots[slot_id]
        s = self.engine.state
        return (self.engine._current_snapshot(slot_id), slot.start, slot.end,
                self.requested_specialty, self.appointment_date, s.any_provider, s.any_location,
                tuple(sorted(s.hard_constraints)), json.dumps(s.preferences, sort_keys=True))

    def _proposal(self, kind, snapshot, *, slot_id=None, proposal_id=None, message_id=None):
        pid = proposal_id or self._id('proposal')
        if pid in self.proposals:
            raise ActError('reused_reference', 'Never rebind consent to another proposal')
        if (message_id or pid) in self.messages:
            raise ActError('reused_reference', 'Message IDs cannot change meaning')
        p = Proposal(pid, kind, snapshot, message_id or pid, slot_id)
        self.proposals[pid] = p
        self.messages[p.message_id] = ('proposal', pid)
        self.state_version += 1
        return p

    def propose_identity(self, *, proposal_id=None, message_id=None):
        if not all(self.identity()) or self.partial_dob:
            raise ActError('missing_identity', 'A complete identity is needed for its read-back')
        return self._proposal('identity', self.identity(), proposal_id=proposal_id, message_id=message_id)

    def deliver_proposal(self, pid):
        p = self.proposals[pid]
        if p.status != 'open' or not self._current_proposal(p):
            raise ActError('stale_proposal', 'Cannot deliver a retired read-back')
        self.proposals[pid] = replace(p, delivered=True)

    def _current_proposal(self, p):
        if p.kind == 'identity':
            return p.snapshot == self.identity() and not self.partial_dob
        return p.slot_id == self.engine.state.selected_slot_id and p.snapshot == self._booking_snapshot(p.slot_id)

    def _revoke_booking(self, reason):
        for pid, p in list(self.proposals.items()):
            if p.kind == 'booking' and p.status in {'open', 'accepted'}:
                self.proposals[pid] = replace(p, status='revoked')
                self.consent_ledger.append({'proposal_id': pid, 'action': 'revoke', 'reason': reason})
                self.readback_required = True
        self.engine.state.confirmation = None

    def _invalidate(self, reason, *, identity=False):
        self._revoke_booking(reason)
        if identity:
            self.identity_confirmed = None
            for pid, p in list(self.proposals.items()):
                if p.kind == 'identity' and p.status in {'open', 'accepted'}:
                    self.proposals[pid] = replace(p, status='revoked')
        self.engine._invalidate_slot_choice()
        self.generation += 1
        self.question = None

    def interrupt_proposal(self, pid):
        p = self.proposals[pid]
        if not p.delivered and p.status == 'open':
            self.proposals[pid] = replace(p, status='revoked')
            if p.kind == 'booking':
                self._revoke_booking('interrupted_readback')
                self.readback_required = True

    def _selected(self, act, arrival):
        p = self.presentations.get(act['presentation_id'])
        if not p or p.generation != self.generation or p.id not in arrival.presentations:
            raise ActError('stale_presentation', 'Choose from a delivered current presentation')
        selector = act['selector']
        if selector['by'] == 'ordinal':
            index = selector['ordinal'] - 1
            if index >= len(p.option_ids):
                raise ActError('option_not_presented', 'Ordinal is outside the presented list')
            chosen = p.option_ids[index]
            if p.entity in ENTITY and act.get('quote'):
                named = [row['id'] for row in self.engine.catalog.search(ENTITY[p.entity][0], act['quote'])
                         if not row.get('requires_confirmation') and row['id'] in p.option_ids]
                if len(named) == 1 and named[0] != chosen:
                    raise ActError('selection_quote_conflict', 'The selected option contradicts the named catalog option')
            return p.entity, chosen
        if selector['option_id'] not in p.option_ids:
            raise ActError('option_not_presented', 'Named option was not presented')
        return p.entity, selector['option_id']

    def _references(self, acts, arrival):
        selections, consent_targets = [], {}
        for index, act in enumerate(acts):
            if act['kind'] == 'select_option':
                selections.append(self._selected(act, arrival))
            elif act['kind'] in {'affirm', 'deny'}:
                target = act['target']
                if target['type'] == 'proposal':
                    pid = target['id']
                else:
                    if not self.question or target['id'] != self.question.id or target['id'] not in arrival.questions:
                        raise ActError('stale_question', 'Answer needs a current delivered question')
                    pid = self.question.proposal_id
                if pid is not None:
                    p = self.proposals.get(pid)
                    if not p or p.status not in {'open', 'accepted'} or p.id not in arrival.proposals or not self._current_proposal(p):
                        raise ActError('stale_proposal', 'Consent needs its own fully delivered current proposal')
                    # Resolve the immutable question binding BEFORE deltas retire it.
                    consent_targets[index] = pid
            elif act['kind'] == 'repeat_request':
                reference = self.messages.get(act['message_id'])
                if not reference:
                    raise ActError('unknown_message', 'There is no such message to repeat')
                kind, ident = reference
                if kind == 'presentation' and self.presentations[ident].generation != self.generation:
                    raise ActError('stale_message', 'That choice is no longer current')
                if kind == 'proposal' and not self._current_proposal(self.proposals[ident]):
                    raise ActError('stale_message', 'That read-back is no longer current')
            elif act['kind'] == 'information_question' and act['reference_id'] is not None:
                ident = act['reference_id']
                valid = ident in self.messages or ident in self.proposals or ident in self.presentations
                reference = self.messages.get(ident)
                if reference:
                    kind, ident = reference
                else:
                    kind = 'proposal' if ident in self.proposals else 'presentation'
                if valid and kind == 'proposal' and not self._current_proposal(self.proposals[ident]):
                    raise ActError('stale_information_reference', 'That proposal no longer describes the request')
                if valid and kind == 'presentation' and self.presentations[ident].generation != self.generation:
                    raise ActError('stale_information_reference', 'That presentation is retired')
                if not valid:
                    entity = {'service': 'appointment_type'}.get(act['entity'], act['entity'])
                    try:
                        self.engine.catalog.details(entity, ident)
                    except KeyError:
                        raise ActError('unknown_information_reference', 'Information reference is unknown')
        if len({entity for entity, _ in selections}) != len(selections):
            raise ActError('conflicting_selections', 'Choose one option for each field')
        return selections, consent_targets

    def _current_field(self, field):
        if field in FACT:
            return getattr(self.engine.state.patient_facts, FACT[field])
        if field in ENTITY:
            entity, state_field = ENTITY[field]
            ident = getattr(self.engine.state, state_field)
            return self.engine.catalog.details(entity, ident)['name'] if ident else self.fields.get(field)
        if field == 'provider_specialty':
            return self.requested_specialty
        if field == 'appointment_date':
            return self.appointment_date
        return getattr(self.engine.state, field, None)

    def _deltas(self, acts, selections):
        """A generic request ("schedule an appointment") names no service."""
        kept = [a for a in acts if not (
            a['kind'] in {'set_field', 'correct'} and a['delta']['field'] == 'service'
            and isinstance(a['delta']['value'], str) and set(words_of(a['delta']['value'])) <= GENERIC_SERVICE)]
        if len(kept) != len(acts):
            self.generic_service_request = True
        elif any(a['kind'] in {'set_field', 'correct'} and a['delta']['field'] == 'service' for a in kept):
            self.generic_service_request = False  # A real service word answers "what kind".
        return self._plan_deltas(kept, selections)

    def _plan_deltas(self, acts, selections):
        """Plan the complete turn before checking a selection against specialty."""
        changes, corrections = {}, set()
        for act in acts:
            if act['kind'] not in {'set_field', 'correct'}:
                continue
            d = act['delta']; key, value = d['field'], d['value']
            if key == 'hard_constraint':
                hard = changes.setdefault(key, {})
                if value['field'] in hard and hard[value['field']] != value['enabled']:
                    raise ActError('conflicting_deltas', 'Conflicting constraint updates need clarification')
                hard[value['field']] = value['enabled']
                continue
            if key in changes and act['kind'] != 'correct' and changes[key] != value:
                raise ActError('conflicting_deltas', 'Conflicting field updates need clarification')
            if act['kind'] == 'correct':
                corrections.add(key)
            changes[key] = value
        for act in acts:
            if act['kind'] in {'affirm', 'deny'} and act['target']['type'] == 'question':
                if self.question.proposal_id is not None:
                    continue  # Consent answers are not boolean patient facts.
                key = self.question.field
                if key not in {'new_patient', 'referral', 'any_provider', 'any_location'}:
                    if self.question.kind.endswith('_consent'):
                        # Consent stays strict: a yes needs the proposal it answers.
                        raise ActError('not_a_boolean_question', 'That question does not accept yes/no as a field value')
                    if act['kind'] == 'affirm' and self.question.kind == 'blocked' and self.block_offer:
                        # Yes to the alternative a block offered: that alternative, by ID, for
                        # every field the turn does not set itself (its corrections stand).
                        for field, ident in self.block_offer.items():
                            if ident and field not in changes:
                                changes[field] = ('id', ident)
                                corrections.add(field)
                    continue  # Otherwise a yes/no to a non-yes/no question changes no fact; the turn stands.
                value = act['kind'] == 'affirm'
                if key in changes and changes[key] != value:
                    raise ActError('conflicting_deltas', 'Question answer conflicts with field update')
                changes[key] = value
        self._adopt_offer(changes, corrections)
        if 'provider_specialty' in changes and changes['provider_specialty'] is not None:
            changes['provider_specialty'] = self._specialty(changes['provider_specialty'])
        for field, value in list(changes.items()):
            if isinstance(value, str):
                if not value.strip():
                    raise ActError('empty_field', 'A field value cannot be empty')
                changes[field] = value = value.strip()
            if field == 'date_shift':
                changes[field] = value = self._shifted_start(value)
            if field == 'appointment_date' and value is not None:
                try:
                    parsed = date.fromisoformat(value)
                    if parsed.isoformat() != value:
                        raise ValueError()
                except ValueError:
                    raise ActError('invalid_appointment_date', 'Use a complete local calendar date')
                changes[field] = value = parsed
            current = self._current_field(field)
            if field not in corrections and field not in {'date_of_birth', 'hard_constraint', 'location_preference', 'any_provider', 'any_location', 'date_shift'} and current is not None and current != value:
                # Same resolved entity repeated by its catalog name is harmless.
                if not (isinstance(current, str) and isinstance(value, str) and current.casefold() == value.casefold()):
                    if field == 'name':
                        raise ActError('correction_required', 'A known name changes only through correct')
                    # A new value for a known booking fact is a correction (the model's intent is
                    # clear); dependents are invalidated as for correct. Identity keeps its rules.
                    corrections.add(field)
            if field == 'date_of_birth' and value is not None:
                parts = dict(zip(('year', 'month', 'day'), map(int, current.split('-')))) if current else dict(self.partial_dob)
                for part, supplied in value.items():
                    if supplied is not None:
                        if field not in corrections and part in parts and parts[part] != supplied:
                            raise ActError('correction_required', 'Changing an existing DOB component needs correct')
                        parts[part] = supplied
                try:
                    date(parts.get('year', 2000), parts.get('month', 1), parts.get('day', 1))
                    if 'year' in parts and parts['year'] > self.engine.now.astimezone(CLINIC_ZONE).year:
                        raise ValueError()
                except ValueError:
                    raise ActError('invalid_date_of_birth', 'DOB components are not a possible past date')
                if len(parts) == 3 and date(**parts) > self.engine.now.astimezone(CLINIC_ZONE).date():
                    raise ActError('invalid_date_of_birth', 'DOB is in the future')
                changes[field] = parts
            if field not in corrections and field not in {'hard_constraint', 'location_preference'}:
                same = changes[field] == current
                if isinstance(changes[field], str) and isinstance(current, str):
                    same = changes[field].casefold() == current.casefold()
                if field == 'date_of_birth' and current and isinstance(changes[field], dict):
                    same = len(changes[field]) == 3 and date(**changes[field]).isoformat() == current
                if same:
                    del changes[field]
        if any(e == 'slot' for e, _ in selections) and {'name', 'date_of_birth'} & changes.keys():
            raise ActError('identity_and_slot_selection', 'Resolve the identity correction before selecting a slot')
        if self.question and self.question.kind == 'slot_choice' and any(
                a['kind'] == 'set_field' and a['delta']['field'] in {'name', 'date_of_birth'} for a in acts):
            raise ActError('identity_from_slot_choice', 'A slot choice cannot populate identity')
        specialty = changes.get('provider_specialty', self.requested_specialty)
        for entity, ident in selections:
            if entity == 'slot':
                continue
            if entity == 'provider' and specialty and self.engine.catalog.providers_by_id[ident].specialty != specialty:
                raise ActError('specialty_conflict', 'The chosen provider does not match requested specialty')
            if entity in changes and self._names_option(entity, changes[entity], ident):
                # The chosen option named again ("yes, that's fine, I meant Mission Bay"): one choice.
                del changes[entity]
                corrections.discard(entity)
            if entity in changes:
                raise ActError('conflicting_selection_delta', 'Field and selection both update the same entity')
            chosen = next(a for a in acts if a['kind'] == 'select_option'
                          and self.presentations[a['presentation_id']].entity == entity)
            if chosen['selector']['by'] == 'name':
                presented = self.presentations[chosen['presentation_id']]
                matches = self.engine.catalog.search(ENTITY[entity][0], chosen['selector']['words'],
                    specialty=specialty if entity == 'provider' else None)
                ids = {m['id'] for m in matches if m['id'] in presented.option_ids and not m.get('requires_confirmation')}
                if ids != {ident}:
                    raise ActError('ambiguous_named_option', 'Named option does not uniquely match the presented choice')
            changes[entity] = ('id', ident)
            corrections.add(entity)  # A valid explicit new choice replaces the old choice.
        if selections and any(e == 'slot' for e, _ in selections) and changes:
            raise ActError('stale_slot_with_changes', 'Apply changed facts before choosing a fresh slot')
        return changes, corrections

    def _names_option(self, entity, value, ident):
        """The field value names this catalog option (by ID, or words that find it)."""
        if isinstance(value, tuple):
            return value[1] == ident
        if not isinstance(value, str):
            return False
        found = [row['id'] for row in self.engine.catalog.search(ENTITY[entity][0], value)]
        if entity == 'location':
            found += [site.id for site in matching_sites(self.engine.catalog.locations, value)]
        return set(found) == {ident}

    def _apply_changes(self, changes, event_id):
        result = self._apply_fact_changes(changes, event_id)
        result = self._reresolve_named_provider() or result
        return self._retry_unresolved_requests() or result

    def _reresolve_named_provider(self):
        """"Dr. Maria Garcia in Family Medicine instead": the same spoken name under a
        new specialty re-resolves the provider, and a site the new provider does not
        serve is cleared unless the caller fixed it. None when nothing changed."""
        provider = self.engine._provider()
        if not (provider and self.requested_specialty and provider.specialty != self.requested_specialty
                and isinstance(self.fields.get('provider'), str)):
            return None
        result = self.engine.resolve_options({'provider_query': self.fields['provider'],
                                              'provider_specialty': self.requested_specialty})
        provider = self.engine._provider()
        site = self.engine.state.location_id
        if (provider and site and site not in provider.location_ids
                and not {'location', 'location_id'} & self.engine.state.hard_constraints):
            result = self.engine.resolve_options({'location_id': None})
        return result

    def _retry_unresolved_requests(self):
        """Retry unresolved caller facts against the current constraints, rather than
        forgetting them on an unrelated later change. None when there are none."""
        queries = {}
        for field_name, (entity, state_field) in ENTITY.items():
            words = self.fields.get(field_name)
            if (not getattr(self.engine.state, state_field) and isinstance(words, str)
                    and not getattr(self.engine.state, 'any_' + field_name, False)):
                queries[entity + '_query'] = words
        if not queries:
            return None
        if self.requested_specialty:
            queries['provider_specialty'] = self.requested_specialty
        return self.engine.resolve_options(queries)

    def _apply_fact_changes(self, changes, event_id):
        updates, scope, specialty = {}, {}, changes.get('provider_specialty', self.requested_specialty)
        partial = dict(self.partial_dob)
        for key, value in changes.items():
            if key in ENTITY:
                entity, state_field = ENTITY[key]
                if value is None or isinstance(value, tuple):
                    updates[state_field] = value[1] if value else None
                elif value != self._current_field(key):
                    updates[entity + '_query'] = value
                    if key == 'provider' and specialty:
                        updates['provider_specialty'] = specialty
            elif key in FACT:
                if key == 'date_of_birth':
                    partial = value or {}
                    value = date(**partial).isoformat() if len(partial) == 3 else None
                    if value is not None:
                        partial = {}
                updates[FACT[key]] = value
            elif key in {'any_provider', 'any_location'}:
                scope[key] = value
            elif key == 'hard_constraint':
                hard = set(self.engine.state.hard_constraints)
                for field, enabled in value.items():
                    (hard.add if enabled else hard.discard)(field)
                updates['hard_constraints'] = {f: True for f in hard}
        if changes.get('any_provider') and 'provider' in changes and changes['provider'] is not None:
            raise ActError('contradictory_scope', 'Named provider and any provider cannot both be selected')
        if changes.get('any_location') and 'location' in changes and changes['location'] is not None:
            raise ActError('contradictory_scope', 'Named site and any site cannot both be selected')
        before = deepcopy(self.engine.state)
        if (changes.get('any_provider') is True and changes.get('location') is None and 'location' not in changes
                and not self.engine.state.location_id and self.fields.get('location') is None):
            # Anyone, with no site named: the earliest times at every valid site; the
            # read-back names the site.
            scope.setdefault('any_location', True)
        for flag, entity in (('any_provider', 'provider'), ('any_location', 'location')):
            # Only a named choice contradicts its own explicitly widened scope.
            scope.setdefault(flag, getattr(before, flag) and changes.get(entity) is None)
        try:
            resolution = self.engine.resolve_options(updates) if updates else None
            provider = self.engine._provider()
            if 'provider_specialty' in changes and 'provider' not in changes and provider and specialty and provider.specialty != specialty:
                resolution = self.engine.resolve_options({'provider_id': None})
                provider = None
            if 'provider' in changes and 'location' not in changes and provider and self.engine.state.location_id not in provider.location_ids:
                if not {'location', 'location_id'} & self.engine.state.hard_constraints:
                    resolution = self.engine.resolve_options({'location_id': None})
            if any(getattr(self.engine.state, flag) != value for flag, value in scope.items()):
                # The unchanged core resets both flags on parent changes. Restore
                # noncontradicted scope, then refresh policy and lookup evidence
                # without replaying direct-ID/fact updates that could reset it.
                self.engine._apply_scope_updates(scope)
                resolution = self.engine.resolve_options({key: value for key, value in updates.items()
                    if key.endswith('_query') or key.endswith('_specialty')})
        except SchedulingError:
            self.engine.state = before
            raise
        # A referral answer belongs to its service, for the rest of the call: the same
        # service requested again (after a cancel or a goodbye) never asks it again.
        state = self.engine.state
        if 'referral' in changes and state.appointment_type_id and changes['referral'] is not None:
            self.referral_answers[state.appointment_type_id] = changes['referral']
        elif (state.appointment_type_id in self.referral_answers
              and state.patient_facts.referral_on_file is None):
            resolution = self.engine.resolve_options(
                {'referral_on_file': self.referral_answers[state.appointment_type_id]})
        # Semantic fields stay outside the unchanged engine's data model.
        self.requested_specialty = specialty
        self.partial_dob = partial
        if 'appointment_date' in changes:
            self.appointment_date = changes['appointment_date']
        if 'date_shift' in changes:
            self.not_before, self.appointment_date = changes['date_shift'], None
            self.last_shift = self._planned_shift  # (kind, IDs offered before it, latest of them)
        self.last_turn_fields = set(changes)
        for key, value in changes.items():
            self.fields[key] = value
            self.provenance[key] = event_id
        if changes:
            identity_changed = self.identity() != (before.patient_facts.name, before.patient_facts.date_of_birth)
            self._invalidate('field_change', identity=identity_changed or bool(self.partial_dob))
        return resolution

    def _reduce_turn(self, event_id, caller_text, raw, *, state_version=None):
        """The core turn: references, deltas, consent and controls, in arrival order."""
        fingerprint = sha256(json.dumps([caller_text, raw], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if event_id in self.processed:
            previous, result = self.processed[event_id]
            if previous != fingerprint:
                self._revoke_booking('duplicate_event_conflict')
                raise ActError('duplicate_event_conflict', 'Event ID was reused with different content')
            return replace(deepcopy(result), state_version=self.state_version, effects=(),
                           resolution=None, readback_required=False, duplicate=True)
        self.receive(event_id)
        if event_id != next(iter(self.pending_inputs)):
            self._revoke_booking('out_of_order_input')
            raise ActError('out_of_order_input', 'Reduce received inputs in arrival order')
        arrival = self.pending_inputs[event_id]
        effects, resolution = [], None
        try:
            if state_version is not None and state_version != self.state_version:
                raise ActError('stale_state_version', 'Apply the turn to its captured session state')
            acts = validate_acts(raw, caller_text).acts
            selections, consent_targets = self._references(acts, arrival)
            changes, corrections = self._deltas(acts, selections)
            resolution = self._apply_changes(changes, event_id)
            suppress = bool(changes or corrections) or any(a['kind'] in {
                'deny', 'pause', 'information_question', 'repeat_request', 'cancel', 'human_request',
                'unclear', 'unsupported', 'urgent_escalation'} for a in acts)
            if suppress:
                self._revoke_booking('changed_or_nonconsent_turn')
            controls = [self.control]
            for act in acts:
                if act['kind'] in {'pause', 'human_request', 'urgent_escalation'}:
                    controls.append({'pause': 'paused', 'human_request': 'human',
                                     'urgent_escalation': 'urgent'}[act['kind']])
                elif act['kind'] == 'cancel' and act['scope'] != 'recorded_booking' and not self.request_finished():
                    controls.append('cancelled')
            self.control = max(controls, key=CONTROL_PRIORITY.__getitem__)
            for index, act in enumerate(acts):
                kind = act['kind']
                if kind in {'set_field', 'correct', 'select_option'}:
                    if kind in {'set_field', 'correct'} and act['delta']['field'] == 'location_preference':
                        effects.append({'kind': 'location_preference', 'value': act['delta']['value'],
                                        'scope_change_authorized': False})
                    continue
                if index in consent_targets:
                    pid = consent_targets[index]; p = self.proposals[pid]
                    # An identity yes stands with a question or with a change that is not the
                    # identity ("yeah, that's right, just the date the week after"); booking
                    # consent stays strict (any other act voids it).
                    kept = (p.kind == 'identity' and not ({'name', 'date_of_birth'} & (set(changes) | corrections))
                            and all(a['kind'] in {'affirm', 'information_question', 'repeat_request', 'acknowledge',
                                                  'set_field', 'correct'} for a in acts))
                    outcome = ('discarded' if suppress and kind == 'affirm' and not kept
                               else 'accepted' if kind == 'affirm' else 'revoked')
                    if outcome != 'discarded' and p.status != 'revoked':
                        self.proposals[pid] = replace(p, status=outcome)
                    if p.kind == 'identity' and outcome == 'accepted' and p.snapshot == self.identity():
                        self.identity_confirmed = self.identity()
                    elif p.kind == 'identity' and outcome == 'revoked':
                        self.identity_confirmed = None
                    self.consent_ledger.append({'event_id': event_id, 'proposal_id': pid, 'action': kind,
                                               'outcome': outcome, 'target': deepcopy(act['target'])})
                elif kind == 'pause':
                    if self.control == 'paused':
                        effects.append({'kind': 'pause'})
                elif kind in {'human_request', 'urgent_escalation'}:
                    self._invalidate(kind)
                    if self.control == ('human' if kind == 'human_request' else 'urgent'):
                        effects.append(deepcopy(act))
                elif kind == 'cancel':
                    if act['scope'] == 'recorded_booking' or self.request_finished():
                        effects.append({'kind': 'unsupported', 'topic': 'recorded_booking_change'})
                    else:
                        self._invalidate('cancel')
                        if self.control == 'cancelled':
                            effects.append({'kind': 'cancel'})
                elif kind in {'information_question', 'repeat_request', 'acknowledge', 'unclear', 'unsupported'}:
                    effects.append(deepcopy(act))
            selection_with_information = (not changes and not corrections
                and any(a['kind'] == 'information_question' for a in acts)
                and all(a['kind'] in {'select_option', 'information_question', 'acknowledge', 'affirm'} for a in acts))
            if self.control == 'active' and (not suppress or selection_with_information):
                for entity, ident in selections:
                    if entity == 'slot':
                        p = self.prepare_booking(ident)
                        effects.append({'kind': 'booking_readback', 'proposal_id': p.id})
            if changes or any(a['kind'] not in {'acknowledge'} for a in acts):
                self.state_version += 1
            result = TurnResult('accepted', self.state_version, tuple(effects), readback_required=self.readback_required, resolution=resolution)
        except (ActError, SchedulingError) as error:
            self._revoke_booking('invalid_interpretation')
            result = TurnResult('rejected', self.state_version, errors=(error.code,), readback_required=self.readback_required)
        self.pending_inputs.pop(event_id, None)
        self.processed[event_id] = fingerprint, deepcopy(result)
        return result

    def _referral_unknown(self, raw, flow):
        """The referral question asked, and a turn that does not answer it ("I don't know",
        "I just want to book"): the referral is treated as not on file (it can only block a
        booking, never allow one) and the reply explains what a referral is. Decided from the
        acts (unclear, acknowledge, move on), not from words."""
        q = self.question
        kinds = {a.get('kind') for a in [*(raw.get('acts') or []), *(flow or [])] if isinstance(a, dict)}
        if not (q and q.field == 'referral' and q.proposal_id is None
                and kinds <= {'unclear', 'acknowledge', 'request_next_step'}
                and kinds & {'unclear', 'request_next_step'}):
            return raw, flow
        self.referral_unknown = True
        return {'acts': [{'kind': 'set_field', 'delta': {'field': 'referral', 'value': False}, 'quote': None}]}, None

    def _adopt_offer(self, changes, corrections):
        """Choosing one of the options a block offered ("I'll go with the nurse practitioner
        Maria Garcia") takes the offered alternative with it: the chosen option by ID, and
        the offered service when only one was offered and the turn names none."""
        options = self.block_offer_options
        if not (self.question and self.question.kind == 'blocked' and options):
            return
        chosen = False
        for field in ('provider', 'location'):
            value, offered = changes.get(field), options.get(field) or []
            if isinstance(value, str) and offered:
                found = [row['id'] for row in self.engine.catalog.search(ENTITY[field][0], value) if row['id'] in offered]
                if len(found) == 1:
                    changes[field] = ('id', found[0])
                    corrections.add(field)
                    chosen = True
        services = options.get('service') or []
        if chosen and len(services) == 1 and 'service' not in changes:
            changes['service'] = ('id', services[0])
            corrections.add('service')

    def _shifted_start(self, shift):
        """The earliest start to offer for a relative date the model labelled:
        'later' is after the latest time offered or proposed; 'week_later' is a week
        after the earliest one (from today when nothing was offered yet)."""
        ids = set(self.engine.state.offered_slot_ids)
        ids |= {p.slot_id for p in self.proposals.values() if p.kind == 'booking' and p.slot_id and p.status in {'open', 'accepted'}}
        starts = sorted(self.engine._slots[i].start for i in ids if i in self.engine._slots)
        self._planned_shift = (shift, frozenset(ids), starts[-1] if starts else None, self.not_before)
        if shift == 'earlier':
            return self.engine.now  # Never later: the search starts from now.
        if shift == 'later':
            return starts[-1] + timedelta(minutes=1) if starts else self.engine.now
        base = starts[0].astimezone(CLINIC_ZONE).date() if starts else self.engine.now.astimezone(CLINIC_ZONE).date()
        return datetime.combine(base + timedelta(days=7), time(0), tzinfo=CLINIC_ZONE)

    def drop_date_shift(self):
        """Nothing after the shifted start: back to the window before the shift."""
        self.not_before = self.last_shift[3]

    def _slot_allowed(self, slot):
        return ((self.not_before is None or slot.start >= self.not_before)
                and (self.appointment_date is None or slot.start.astimezone(CLINIC_ZONE).date() == self.appointment_date)
                and (self.requested_specialty is None or self.engine.catalog.providers_by_id[slot.provider_id].specialty == self.requested_specialty))

    def find_slots(self, horizon_days=30, *, limit=3):
        if limit < 1:
            raise ActError('invalid_limit', 'Presentation limit must be positive')
        self._invalidate('new_search')
        result = self.engine.find_slots(horizon_days, limit=max(1, len(self.engine._slots)))
        if result['status'] == 'blocked':
            return result
        if self.identity_confirmed != self.identity() or not all(self.identity()) or self.partial_dob:
            self.engine.state.offered_slot_ids.clear()
            return {'status': 'needs_identity_confirmation', 'slots': []}
        matches = [s for s in result['slots'] if self._slot_allowed(self.engine._slots[s['slot_id']])]
        shown = matches[:limit]
        self.engine.state.offered_slot_ids = {s['slot_id'] for s in shown}
        result.update(slots=shown, more_available=max(0, len(matches) - limit),
                      status='ok' if matches else 'no_availability')
        result['alternatives'] = [a for a in result['alternatives'] if self._slot_allowed(self.engine._slots[a['slot']['slot_id']])]
        return result

    def prepare_booking(self, slot_id, *, proposal_id=None, message_id=None):
        if self.control not in {'active', 'paused'}:
            raise ActError('scheduling_stopped', 'Scheduling is not active')
        if self.identity_confirmed != self.identity() or not all(self.identity()) or self.partial_dob:
            raise ActError('identity_confirmation_required', 'Confirm identity before the booking proposal')
        if not any(p.entity == 'slot' and p.delivered and p.generation == self.generation and slot_id in p.option_ids for p in self.presentations.values()):
            raise ActError('slot_not_presented', 'Choose an actually presented slot')
        if not self._slot_allowed(self.engine._slots[slot_id]):
            raise ActError('date_or_specialty_mismatch', 'Slot violates the current date or specialty')
        self.engine.select_slot(slot_id)
        self._revoke_booking('new_readback')
        self.control = 'active'
        self.readback_required = False
        return self._proposal('booking', self._booking_snapshot(slot_id), slot_id=slot_id,
                              proposal_id=proposal_id, message_id=message_id)

    def commit_booking(self, pid, *, endpoint_closed=False):
        """Only this explicit dispatch method writes; M2 must supply queue discipline."""
        p = self.proposals.get(pid)
        if p and p.kind == 'booking' and p.status == 'consumed':
            return self.engine.book_appointment(p.slot_id)  # Core idempotency, never a new write.
        code = None
        if self.pending_inputs or not endpoint_closed:
            code = 'unprocessed_input'
        elif self.control != 'active':
            code = 'scheduling_stopped'
        elif not p or p.kind != 'booking' or p.status != 'accepted' or not p.delivered:
            code = 'consent_required'
        elif self.identity_confirmed != self.identity() or not self._current_proposal(p):
            code = 'stale_proposal'
        elif not self._slot_allowed(self.engine._slots[p.slot_id]):
            code = 'date_or_specialty_mismatch'
        if code:
            return {'status': 'not_booked', 'code': code, 'technical_failure': False}
        try:
            self.engine.confirm_selected_slot()
            result = self.engine.book_appointment(p.slot_id)
        except SchedulingError as error:
            self._revoke_booking(error.code)
            return {'status': 'not_booked', 'code': error.code, 'technical_failure': False}
        self.proposals[pid] = replace(p, status='consumed')
        return result

    # -- One caller turn: repair, then the core turn ---------------------------

    def facts(self):
        """The facts a booking depends on (the loop breaker's measure of progress)."""
        s = self.engine.state
        return deepcopy((s.patient_facts, s.appointment_type_id, s.provider_id, s.location_id, s.any_provider,
                         s.any_location, sorted(s.hard_constraints), self.requested_specialty, self.appointment_date,
                         self.not_before, self.identity_confirmed))

    def reduce(self, event_id, caller_text, raw, *, state_version=None):
        acts, saved = [], None
        self.last_turn_fields = set()  # Fields this turn recorded (the reply can acknowledge them).
        self.restated = set()  # Known facts said again (no change, but heard).
        before = self.facts()
        result = self._reduce(event_id, caller_text, raw, state_version=state_version)
        self.last_turn_changed = self.facts() != before
        self.last_turn_fields |= self.restated
        return result

    def _reduce(self, event_id, caller_text, raw, *, state_version=None):
        acts, saved = [], None
        if event_id not in self.processed and state_version in (None, self.state_version):
            early, raw, acts = self._prepare_turn(event_id, caller_text, raw)
            if early is not None:
                return early
            self._resume_after_pause(acts)
            saved = self._start_next_request(acts)
        result = self._reduce_turn(event_id, caller_text, raw, state_version=state_version)
        self._settle_request(saved, acts, result)
        return result

    def _prepare_turn(self, event_id, caller_text, raw):
        """(a result decided here, or None; the raw acts for the core turn; the acts)."""
        flow, raw = split_flow_acts(raw, caller_text)
        self._resume_after_handoff([*raw.get('acts', []), *(flow or [])], caller_text)
        raw, flow = self._referral_unknown(raw, flow)
        if flow is not None and not raw['acts']:
            self._resume_set_aside(flow)
        if (flow is not None and not raw['acts']
                and not self._provider_left_open(flow, bool(self.engine.state.appointment_type_id))):
            return self._recorded_turn(event_id, caller_text, {'acts': flow}, self._flow_effect(flow)), raw, []
        try:
            acts = validate_acts(raw, caller_text).acts
        except ActError:
            acts = []
        # Resume a set-aside request before repairs read the request's state.
        self._resume_set_aside([*acts, *(flow or [])])
        declined = self._decline_followup(event_id, caller_text, raw, acts)
        if declined is not None:
            return declined, raw, acts
        declined = self._block_declined(event_id, caller_text, raw, acts)
        if declined is not None:
            return declined, raw, acts
        choice = self.open_choice()
        if choice and acts and all(
                (a['kind'] == 'affirm' and a['target'] == {'type': 'question', 'id': self.question.id})
                or (a['kind'] == 'unclear' and a['subject'] == 'consent') for a in acts):
            # "Yes, book it" while two or more options are open: which one, briefly.
            return self._recorded_turn(event_id, caller_text, raw, {'kind': 'choice_needed', 'presentation_id': choice.id}), raw, acts
        for rewrite in (self._single_option_choice, self._capitalize_names,
                        lambda current: self._join_name_part(current, caller_text),
                        lambda current: self._heard_choice(current, caller_text),
                        lambda current: self._stale_site_choice(current, caller_text)):
            rewritten = rewrite(acts)
            if rewritten is not None:
                raw, acts = rewritten
        repaired = self._repair_acts(acts, caller_text, flow or [])
        if repaired is not None:
            acts, consent = repaired
            if not acts:
                # Only a restatement of the read-back (it stays open, unaccepted),
                # or only a request to move on (the flow answers with its next step).
                effect = {'kind': 'consent_unclear', 'proposal_id': consent} if consent else {'kind': 'proceed'}
                return self._recorded_turn(event_id, caller_text, raw, effect), raw, acts
            raw = {'acts': list(acts)}
        declined = self._readback_declined(event_id, caller_text, raw, acts)
        if declined is not None:
            return declined, raw, acts
        # After a booking, a cancel of the recorded booking is a change request (answered
        # honestly), not a closing; the act's scope says which (the model interprets).
        change = self.request_finished() and any(a['kind'] == 'cancel' and a['scope'] == 'recorded_booking'
                                                 for a in acts)
        closing = CLOSING_ACTS - ({'cancel'} if change else set())
        if acts and self.nothing_pending() and all(a['kind'] in closing for a in acts):
            # Nothing is pending, so yes/no/thanks answers "anything else?"
            # rather than a retired question or proposal.
            more = any(a['kind'] == 'affirm' for a in acts) and not any(a['kind'] == 'deny' for a in acts)
            return self._closing_turn(event_id, caller_text, raw, 'more' if more else 'closing'), raw, acts
        if (acts and self.control == 'human' and all(a['kind'] in {'deny', 'acknowledge'} for a in acts)
                and (any(a['kind'] == 'deny' for a in acts) or THANKS.search(caller_text))):
            # After a request for a person, no or thanks ends the call politely
            # ("let's just continue" is acknowledged, not a goodbye).
            return self._closing_turn(event_id, caller_text, raw, 'closing'), raw, acts
        return None, raw, acts

    def _resume_set_aside(self, acts):
        """After a declined or cancelled request, a caller who keeps talking about
        booking resumes it with what is already known, instead of starting over.
        Only booking content resumes it (a fact, a choice, a request to move on), and
        only when the turn names no other service."""
        # After a cancel the caller stopped on purpose: only booking content resumes. After
        # a declined block, any turn that is not a closing (no, thanks) resumes.
        content = ({'set_field', 'correct', 'select_option', 'request_next_step'} if self.set_aside_by == 'cancel'
                   else {kind for kind in (a['kind'] for a in acts) if kind not in CLOSING_ACTS})
        if (self.set_aside is None or not self.request_cancelled or self.control != 'active'
                or not any(a['kind'] in content for a in acts)
                or any(a['kind'] in {'cancel', 'human_request', 'urgent_escalation'} for a in acts)):
            return
        service = self.set_aside[0].appointment_type_id
        named = [a['delta']['value'] for a in acts if a['kind'] in {'set_field', 'correct'}
                 and a['delta']['field'] == 'service' and isinstance(a['delta']['value'], str)
                 and not set(words_of(a['delta']['value'])) <= GENERIC_SERVICE]  # "an appointment" names none.
        if named and service:
            found = self.engine.catalog.search('appointment_type', named[0])
            if not found or found[0]['id'] != service:
                self.set_aside = None  # Another service: a new request, nothing to resume.
                return
        self._restore_request(self.set_aside)
        self.set_aside, self.request_cancelled = None, False
        # Times chosen before the request was set aside are no longer on offer: search again.
        self._revoke_booking('resumed_request')
        self.engine._invalidate_slot_choice()
        self.engine.state.offered_slot_ids = set()

    def _resume_after_pause(self, acts):
        """Pause holds a question, not a terminal control: a meaningful turn resumes.
        Any consent is still checked or revoked by the core turn."""
        meaningful = {'set_field', 'correct', 'select_option', 'affirm', 'deny', 'information_question', 'repeat_request'}
        if (self.control == 'paused' and not any(a['kind'] == 'pause' for a in acts)
                and any(a['kind'] in meaningful for a in acts)):
            self.control = 'active'

    def _readback_declined(self, event_id, caller_text, raw, acts):
        """A no to the booking read-back: nothing is booked and the time is let go. With
        thanks ("no, I'll call back later, thanks") it also closes the request (set aside,
        resumable); otherwise ask whether to try another time or finish. None: not that."""
        booking = self.open_booking()
        if not (booking and acts and all(a['kind'] in {'deny', 'acknowledge'} for a in acts)
                and any(a['kind'] == 'deny' and self._consent_target(a) == booking.id for a in acts)):
            return None
        self.consent_ledger.append({'event_id': event_id, 'proposal_id': booking.id, 'action': 'deny',
                                    'outcome': 'revoked', 'target': {'type': 'proposal', 'id': booking.id}})
        self._invalidate('readback_declined')
        thanks = bool(THANKS.search(caller_text))
        if thanks:
            self._set_aside_declined()
        return self._recorded_turn(event_id, caller_text, raw, {'kind': 'readback_declined', 'thanks': thanks},
                                   clear_question=True)

    def _set_aside_declined(self):
        self.set_aside, self.set_aside_by = self._request_snapshot(), 'decline'
        self._fresh_request()
        self.request_cancelled = True

    def _decline_followup(self, event_id, caller_text, raw, acts):
        """No or thanks to 'another time, or is that all?' closes a declined request.
        A time preference falls through to the normal delta path; nothing here consents."""
        q = self.question
        if not (q and q.kind == 'declined_booking' and acts
                and all(a['kind'] in {'deny', 'acknowledge'} for a in acts)
                and (any(a['kind'] == 'deny' for a in acts) or THANKS.search(caller_text))):
            return None
        self._set_aside_declined()
        return self._recorded_turn(event_id, caller_text, raw,
                                   {'kind': 'readback_declined', 'thanks': True}, clear_question=True)

    def _resume_after_handoff(self, acts, caller_text):
        """After a request for a person and the honest "I cannot transfer", a new booking
        request ("can I book a flu shot then?") or a plain okay ("ok fine", "let's just
        continue") resumes scheduling. A no or thanks still ends the call politely; a
        patient fact alone does not resume; another request for a person keeps the handoff."""
        acts = [a for a in acts if isinstance(a, dict)]
        booking = any(a.get('kind') in {'select_option', 'request_next_step'}
                      or (a.get('kind') in {'set_field', 'correct'}
                          and (a.get('delta') or {}).get('field') in BOOKING_FIELDS) for a in acts)
        okay = (bool(acts) and all(a.get('kind') in {'acknowledge', 'affirm'} for a in acts)
                and not THANKS.search(caller_text))
        booking = booking or okay
        if (self.control == 'human' and booking
                and not any(a.get('kind') in {'human_request', 'urgent_escalation'} for a in acts)):
            self.control = 'active'

    def _block_declined(self, event_id, caller_text, raw, acts):
        """'No' or 'okay, thanks' to a block's alternatives: nothing is booked, the
        request ends (its facts are kept aside) and the call can close. None: not that."""
        q = self.question
        self.block_turns = self.block_turns + 1 if q and q.kind == 'blocked' else 0
        times_declined = (q and q.kind == 'slot_choice' and any(a['kind'] == 'deny' for a in acts)
                          and THANKS.search(caller_text))  # "No, that's okay, thanks" to the times offered.
        if not (acts and q and (q.kind in {'blocked', 'no_availability'} or times_declined)
                and all(a['kind'] in {'deny', 'acknowledge'} for a in acts)):
            return None  # Frustration is unclear or a request, not deny/acknowledge: the block stays.
        if q.kind == 'blocked' and not any(a['kind'] == 'deny' for a in acts) and self.block_turns < 2:
            # The first "okay" (or "so I can't book it at all?") after a block gets a plain
            # answer and the alternatives, never a goodbye; a no, or a second okay, ends it.
            return None
        self.set_aside, self.set_aside_by = self._request_snapshot(), 'decline'
        self._fresh_request()
        self.request_cancelled = True
        thanks = bool(THANKS.search(caller_text))
        return self._recorded_turn(event_id, caller_text, raw, {'kind': 'block_declined', 'thanks': thanks},
                                   clear_question=True)

    def _start_next_request(self, acts):
        """A cancel, or new booking facts after a booking, start a fresh request
        before the turn's own deltas ("forget it, a flu shot instead"). Returns
        the snapshot to restore if the turn is not accepted, else None."""
        cancel = any(a['kind'] == 'cancel' and a['scope'] == 'pending_request' for a in acts)
        new_facts = any(a['kind'] in {'set_field', 'correct'}
                        and a['delta']['field'] not in {'name', 'date_of_birth', 'new_patient'} for a in acts)
        if ((self.control not in TERMINAL and not self.request_finished() and cancel)
                or (self.request_finished() and self.control == 'active' and new_facts)):
            saved = self._request_snapshot()
            self._fresh_request()
            return saved
        return None

    def _settle_request(self, saved, acts, result):
        if saved is not None and not any(a['kind'] == 'cancel' for a in acts):
            if result.status != 'accepted':
                self._restore_request(saved)
        elif saved is not None:
            if self.control == 'cancelled':
                # Cancel retires the pending request, not the call; its facts are set aside.
                self.control = 'active'
                self.request_cancelled = True
                self.set_aside, self.set_aside_by = saved, 'cancel'
            else:
                self._restore_request(saved)
        if result.status == 'accepted' and not result.duplicate and any(
                a['kind'] in {'set_field', 'correct', 'select_option'} for a in acts):
            self.request_cancelled = False

    def _closing_turn(self, event_id, caller_text, raw, kind):
        """Records a yes/no/thanks turn when nothing is pending."""
        thanks = bool(THANKS.search(caller_text))
        return self._recorded_turn(event_id, caller_text, raw, {'kind': kind, 'thanks': thanks}, clear_question=True)

    def _recorded_turn(self, event_id, caller_text, raw, effect, *, clear_question=False):
        """Records a turn decided before the core turn, with its arrival, ordering
        and idempotency bookkeeping. No proposal changes status."""
        self.receive(event_id)
        if next(iter(self.pending_inputs)) != event_id:
            return self._reduce_turn(event_id, caller_text, raw)  # The core turn rejects out-of-order input.
        fingerprint = sha256(json.dumps([caller_text, raw], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        self.pending_inputs.pop(event_id)
        if clear_question:
            self.question = None
        self.state_version += 1
        result = TurnResult('accepted', self.state_version, (effect,))
        self.processed[event_id] = fingerprint, deepcopy(result)
        return result

    def _flow_effect(self, flow):
        """A turn of flow acts only: a restatement of the open read-back keeps it
        open and unaccepted; anything else moves the flow on."""
        booking = self.open_booking()
        if booking and any(a['kind'] == 'restatement' and self._consent_target(a) == booking.id for a in flow):
            return {'kind': 'consent_unclear', 'proposal_id': booking.id}
        choice = self.open_choice()
        if choice and any(a['kind'] == 'request_next_step' for a in flow):
            return {'kind': 'choice_needed', 'presentation_id': choice.id}
        return {'kind': 'proceed'}

    def open_choice(self):
        """The delivered, current list the pending question asks to choose from,
        when it offers two or more options; else None."""
        q = self.question
        if not q or not q.kind.endswith('_choice') or not q.delivered:
            return None
        entity = q.kind.removesuffix('_choice')
        lists = [p for p in self.presentations.values()
                 if p.entity == entity and p.generation == self.generation and p.delivered]
        return lists[-1] if lists and len(lists[-1].option_ids) > 1 else None

    # -- Act rewrites that keep the caller's meaning -------------------------

    def _single_option_choice(self, acts):
        """'Yes' to a question offering exactly one delivered option (a sole
        site, a single suggestion) selects that option."""
        q = self.question
        if not q or not q.kind.endswith('_choice') or not any(
                a['kind'] == 'affirm' and a['target'] == {'type': 'question', 'id': q.id} for a in acts):
            return None
        entity = q.kind.removesuffix('_choice')
        options = [p for p in self.presentations.values()
                   if p.entity == entity and p.generation == self.generation and p.delivered]
        if not options or len(options[-1].option_ids) != 1:
            return None
        chosen = [dict(kind='select_option', presentation_id=options[-1].id, quote=a['quote'],
                       selector={'by': 'ordinal', 'ordinal': 1})
                  if a['kind'] == 'affirm' and a['target'] == {'type': 'question', 'id': q.id} else a for a in acts]
        return {'acts': chosen}, tuple(chosen)

    @staticmethod
    def _capitalize_names(acts):
        """Names are stored and read back capitalized ("alex morgan" -> "Alex Morgan")."""
        fixed = [dict(a, delta={'field': 'name', 'value': capitalized(a['delta']['value'])})
                 if a['kind'] in {'set_field', 'correct'} and a['delta']['field'] == 'name'
                 and isinstance(a['delta']['value'], str) and capitalized(a['delta']['value']) != a['delta']['value']
                 else a for a in acts]
        return ({'acts': fixed}, tuple(fixed)) if fixed != list(acts) else None

    def _join_name_part(self, acts, caller_text):
        """After a one-word name, a name part completes it ("Alex", then
        "Morgan" -> "Alex Morgan"). Only an explicit correction replaces it:
        a correct act whose turn says more than the bare name part."""
        first = self.partial_name()
        if not first:
            return None
        joined = []
        for a in acts:
            if a['kind'] in {'set_field', 'correct'} and a['delta']['field'] == 'name' and isinstance(a['delta']['value'], str):
                value = a['delta']['value'].strip()
                parts = words_of(value)
                bare_turn = parts == words_of(caller_text)
                if len(parts) == 1 and parts[0] != first.casefold() and (a['kind'] == 'set_field' or bare_turn):
                    a = dict(a, kind='correct', delta={'field': 'name', 'value': f'{first} {value}'})
                elif a['kind'] == 'set_field' and len(parts) > 1 and parts[0] == first.casefold():
                    a = dict(a, kind='correct')  # The full name, completing the first name.
            joined.append(a)
        return ({'acts': joined}, tuple(joined)) if joined != list(acts) else None

    def _heard_choice(self, acts, caller_text):
        """The model selected an option from the current list, but the list was cut
        off while it was spoken, so the selection cannot stand as is. Code checks
        it: the caller's words must name something only the selected option has
        in its spoken label ("the nurse practitioner" among two Maria Garcias).
        Then the choice is restated as a field the list does not need ("the second
        one" names nothing, so it is left to the normal stale-list handling)."""
        out, changed = [], False
        for a in acts:
            p = self.presentations.get(a.get('presentation_id')) if a['kind'] == 'select_option' else None
            if not p or p.delivered or p.generation != self.generation or p.entity not in {'provider', 'location', 'service'}:
                out.append(a)
                continue
            selector = a['selector']
            index = selector['ordinal'] - 1 if selector['by'] == 'ordinal' else (
                p.option_ids.index(selector['option_id']) if selector['option_id'] in p.option_ids else -1)
            fixed = (self._heard_option(p, index, a.get('quote') or caller_text)
                     if 0 <= index < len(p.option_ids) else None)
            if fixed:
                out.append(dict(fixed, quote=a['quote']))
                changed = True
            else:
                out.append(a)
        return ({'acts': out}, tuple(out)) if changed else None

    def _heard_option(self, p, index, words):
        """A delta naming option `index` of an undelivered list, when the caller's
        words distinguish it from the other listed options. None otherwise."""
        catalog = self.engine.catalog
        if p.entity == 'provider':
            records = [catalog.providers_by_id[i] for i in p.option_ids]
            labels = [set(words_of(provider_name(x) + ' ' + x.specialty)) for x in records]
        elif p.entity == 'location':
            records = [catalog.locations_by_id[i] for i in p.option_ids]
            labels = [set(words_of(x.name)) for x in records]
        else:
            records = [catalog.appointment_types_by_id[i] for i in p.option_ids]
            labels = [set(words_of(x.name)) for x in records]
        said = set(words_of(words))
        others = set().union(*(label for i, label in enumerate(labels) if i != index))
        if not said & (labels[index] - others) or said & (others - labels[index]):
            return None
        chosen = records[index]
        if p.entity == 'location':
            return {'kind': 'correct', 'delta': {'field': 'location', 'value': chosen.name}}
        if p.entity == 'service':
            return {'kind': 'correct', 'delta': {'field': 'service', 'value': chosen.name}}
        if [x.specialty for x in records].count(chosen.specialty) == 1 and isinstance(self.fields.get('provider'), str):
            # The spoken name is kept; its specialty resolves which one.
            return {'kind': 'set_field', 'delta': {'field': 'provider_specialty', 'value': chosen.specialty}}
        return None

    def _stale_site_choice(self, acts, caller_text):
        """A choice from a list that is no longer current (or was never heard),
        whose words name exactly one site, names that site: "Midtown." said while
        another question is pending still answers where."""
        current = {p.id for p in self.presentations.values() if p.generation == self.generation and p.delivered}
        fixed, changed = [], False
        for a in acts:
            if a['kind'] == 'select_option' and a['presentation_id'] not in current:
                site = self.named_site(a.get('quote') or caller_text)
                if site:
                    a, changed = {'kind': 'correct', 'delta': {'field': 'location', 'value': site},
                                  'quote': a['quote']}, True
            fixed.append(a)
        return ({'acts': fixed}, tuple(fixed)) if changed else None

    # -- Act repairs ---------------------------------------------------------

    def _repair_acts(self, acts, caller_text, flow=()):
        """Returns (acts, consent proposal ID) when the turn's acts need repair, else None.
        An empty act list means the turn only restated the read-back (consent set) or
        only asked to move on (consent None)."""
        q = self.question
        open_booking = self.open_booking()
        turn = TurnRepair(
            caller_text=caller_text, open_booking=open_booking, act_count=len(acts),
            identity_question=bool(q and (q.kind == 'identity' or q.field in {'name', 'date_of_birth'})),
            referral_question=bool(q and q.field == 'referral' and q.proposal_id is None),
            future_referral=bool(FUTURE_REFERRAL.search(caller_text)),
            stated={a['delta']['field'] for a in acts if a['kind'] in {'set_field', 'correct'}})
        restated = bool(open_booking) and any(
            a['kind'] == 'restatement' and self._consent_target(a) == open_booking.id for a in flow)
        out = [repaired for repaired in (self._repair_act(a, turn) for a in acts) if repaired is not None]
        out += self._stated_patient_facts(turn)
        out = self._any_provider(out, turn, flow)
        out = self._without_noise(out, turn, flow)
        if restated and not out:
            turn.changed, turn.consent = True, open_booking.id
        if not turn.changed and not flow:
            return None
        if turn.consent and all(a['kind'] == 'acknowledge' for a in out):
            out = []
        return tuple(out), turn.consent

    def _repair_act(self, act, turn):
        """The act as the turn means it, or None when it carries nothing to apply."""
        kind = act['kind']
        if kind == 'affirm':
            return self._repair_affirm(act, turn)
        if kind == 'deny' and self.question and self.question.kind == 'blocked' and act['target'].get('id') == self.question.id:
            turn.changed = True  # "I'm not changing the request" answers no yes/no field.
            return None
        if kind == 'unclear' and act['subject'] == 'consent' and turn.open_booking and turn.act_count == 1:
            turn.changed, turn.consent = True, turn.open_booking.id
            return None
        if kind == 'human_request' and not PERSON.search(turn.caller_text):
            return self._site_change_request(act, turn)
        if kind == 'unsupported' and act['topic'] == 'same_call_continuation' and self.control == 'active':
            turn.changed = True  # Only meaningful after a human handoff.
            return None
        if kind in {'set_field', 'correct'}:
            return self._repair_fact(act, turn)
        return act

    def _repair_affirm(self, act, turn):
        """Booking consent needs an acceptance in the quoted words; a promised
        referral answers the referral question with no."""
        text = act.get('quote') or turn.caller_text
        if turn.open_booking and self._consent_target(act) == turn.open_booking.id and not ACCEPTANCE.search(text):
            turn.changed, turn.consent = True, turn.open_booking.id
            return None
        if (turn.referral_question and act['target'] == {'type': 'question', 'id': self.question.id}
                and 'new_patient' in turn.stated and 'referral' not in turn.stated):
            turn.changed = True  # "Yes, I'm a new patient" answers new-patient status, not the referral.
            return None
        if (turn.referral_question and act['target'] == {'type': 'question', 'id': self.question.id}
                and turn.future_referral):
            turn.changed = True
            return dict(act, kind='deny')
        return act

    def _site_change_request(self, act, turn):
        """"Get me to Richmond" without a person named is a site change; "is there
        another way?" without a person named is not a request for one."""
        site = self.named_site(act.get('quote') or turn.caller_text) or self.named_site(turn.caller_text)
        if not site:
            turn.changed = True
            return {'kind': 'unclear', 'subject': 'meaning', 'quote': act['quote']}
        turn.changed = True
        return {'kind': 'correct', 'delta': {'field': 'location', 'value': site}, 'quote': act['quote']}

    def _repair_fact(self, act, turn):
        kind, (field, value) = act['kind'], (act['delta']['field'], act['delta']['value'])
        state = self.engine.state
        if field == 'provider_specialty' and isinstance(value, str) and turn.act_count > 1:
            try:
                self._specialty(value)
            except ActError:
                turn.changed = True  # An unknown qualifier never discards the turn's other facts.
                return None
        if field == 'referral' and value is True and turn.future_referral:
            turn.changed = True
            return dict(act, delta={'field': 'referral', 'value': False})
        if field == 'service' and isinstance(value, str):
            fuller = self._fuller_service(value, turn.caller_text)
            if fuller:
                turn.changed = True
                act = dict(act, delta={'field': 'service', 'value': fuller})
                value = fuller
        if field == 'location' and isinstance(value, str) and PROXIMITY.search(value):
            turn.changed, self.proximity_request = True, True
            return None
        if field == 'location_preference' and value == 'place' and not state.location_id:
            self.proximity_request = True
            return act
        if field == 'appointment_date' and turn.open_booking and kind == 'set_field' and str(
                self.engine._slots[turn.open_booking.slot_id].start.astimezone(CLINIC_ZONE).date()) == value:
            turn.changed, turn.consent = True, turn.open_booking.id  # The read-back's own date, restated.
            return None
        if (field == 'name' and kind == 'set_field' and isinstance(value, str) and not turn.identity_question
                and not self._introduced(value, turn.caller_text) and self._provider_named(value)):
            return self._provider_not_patient(act, turn)
        if field == 'name' and isinstance(value, str) and not self._identity_context(turn) \
                and not self._introduced(value, turn.caller_text) and 'date_of_birth' not in turn.stated:
            return self._name_outside_identity(act, turn)
        self.spelled = None
        if field in {'name', 'date_of_birth'} and kind == 'set_field' and self._same_identity(act):
            turn.changed = True
            return {'kind': 'acknowledge', 'quote': act['quote']}
        current = getattr(state, ENTITY[field][1]) if field in ENTITY else None
        if current and kind in {'set_field', 'correct'} and isinstance(value, str):
            found = {row['id'] for row in self.engine.catalog.search(ENTITY[field][0], value)}
            # The known choice said again, maybe less precisely ("the consultation"): no change.
            # A correction counts as a restatement only when its words name the current choice
            # alone and no specialty changes with it.
            if current in found and (kind == 'set_field' or (found == {current} and 'provider_specialty' not in turn.stated)
                                     or self._less_specific(field, value, current, turn)):
                turn.changed = True
                self.restated.add(field)
                return None
        if (field in ENTITY and kind == 'set_field' and isinstance(value, str)
                and not getattr(state, ENTITY[field][1]) and isinstance(self.fields.get(field), str)
                and self.fields[field].casefold() != value.casefold()):
            turn.changed = True
            return dict(act, kind='correct')  # The caller's next word for an unresolved request.
        return act

    def _fuller_service(self, value, caller_text):
        """The catalog service whose full name matches most of the caller's words: when the
        model kept only part of what was said ("dental exam" from "new patient dental exam"),
        a longer catalog name whose other words were all said too. None: no such name."""
        said, words = words_of(caller_text), set(words_of(value))
        if not words:
            return None
        names = []
        for service in self.engine.catalog.appointment_types:
            name_words = words_of(service.name)
            if not words < set(name_words):
                continue
            # Restore a full catalog name actually spoken together. A separate
            # demographic statement ("I'm new ... a dental exam") is not a
            # qualifier on the service name.
            if any(set(said[i:i + len(name_words)]) == set(name_words)
                   for i in range(len(said) - len(name_words) + 1)):
                names.append((len(name_words), service.name))
        if not names:
            return None
        best = max(size for size, _ in names)
        longest = [name for size, name in names if size == best]
        return longest[0] if len(longest) == 1 else None

    def _less_specific(self, field, value, current, turn):
        """A correction that names the current provider less precisely ("Dr. Smith" for
        Dr. Daniel Smith) keeps that provider; the same full name stays a correction
        (two providers share it)."""
        if field != 'provider' or 'provider_specialty' in turn.stated:
            return False
        said = set(words_of(value)) - {'dr', 'doctor'}
        name = set(words_of(self.engine.catalog.providers_by_id[current].name)) - {'dr', 'doctor'}
        return bool(said) and said < name

    def _identity_context(self, turn):
        """The patient's name is being collected: the identity question or its
        read-back is pending, or part of the identity is already given."""
        q = self.question
        return (turn.identity_question or bool(q and q.kind.startswith('identity'))
                or any(self.identity()) or bool(self.partial_dob))

    def _name_outside_identity(self, act, turn):
        """A name outside the identity question is not the patient's: it answers
        the question asked (a provider, site or service name); one-word parts given
        in consecutive turns ("h-a-n-n-a", then "n-g-u-y-e-n") are joined, like the
        patient's split name. Otherwise it is dropped."""
        turn.changed = True
        q = self.question
        field = 'provider' if q and q.kind == 'provider_choice' else q.field if q else None
        if field not in {'provider', 'location', 'service'}:
            if isinstance(self.fields.get('provider'), str) and not self.engine.state.provider_id:
                field = 'provider'  # The unresolved provider is what the caller is naming.
            else:
                return None
        value, now = act['delta']['value'], len(self.processed)
        previous = self.spelled
        if (previous and previous[0] == field and previous[2] == now - 1
                and len(value.split()) == 1 and len(previous[1].split()) == 1):
            value = f'{previous[1]} {value}'
        self.spelled = (field, value, now)
        if field in turn.stated:
            return None
        turn.stated.add(field)
        return {'kind': 'correct', 'delta': {'field': field, 'value': value}, 'quote': act['quote']}

    def _provider_left_open(self, acts, service_known):
        """A request to move on ("as soon as possible", "just look for appointments")
        with the service known and no provider named or resolved leaves the provider
        open. The model's request_next_step act decides, not the words."""
        state = self.engine.state
        return (any(a['kind'] == 'request_next_step' for a in acts) and service_known
                and not state.provider_id and not state.any_provider and self.fields.get('provider') is None)

    def _any_provider(self, out, turn, flow):
        """Moving on with the provider left open: any provider who offers the service."""
        service = bool(self.engine.state.appointment_type_id) or 'service' in turn.stated
        if (not self._provider_left_open([*flow, *out], service)
                or turn.stated & {'provider', 'provider_specialty', 'any_provider'}
                or any(a['kind'] in {'human_request', 'select_option'} for a in out)):
            return out
        turn.changed = True
        turn.stated.add('any_provider')
        quote = next((a.get('quote') for a in [*flow, *out] if a['kind'] == 'request_next_step'), None)
        return out + [{'kind': 'set_field', 'delta': {'field': 'any_provider', 'value': True}, 'quote': quote}]

    def _provider_not_patient(self, act, turn):
        """A provider's name is never the patient's name."""
        turn.changed = True
        if 'provider' in turn.stated or self.engine.state.provider_id:
            return None
        turn.stated.add('provider')
        return dict(act, delta={'field': 'provider', 'value': act['delta']['value']})

    def _stated_patient_facts(self, turn):
        """An explicit new-patient statement always counts; "make it a new patient
        visit" names the service."""
        added = []
        facts = self.engine.state.patient_facts
        for pattern, status in ((NEW_PATIENT, True), (EXISTING_PATIENT, False)):
            match = pattern.search(turn.caller_text)
            if match and 'new_patient' not in turn.stated and facts.is_new_patient is not status:
                turn.changed = True
                added.append({'kind': 'correct', 'delta': {'field': 'new_patient', 'value': status},
                              'quote': match.group(0)})
                turn.stated.add('new_patient')
        match = NEW_PATIENT_VISIT.search(turn.caller_text)
        service = self.engine._appointment_type()
        if match and 'service' not in turn.stated and not (service and service.name == 'New Patient Visit'):
            turn.changed = True
            added.append({'kind': 'correct', 'delta': {'field': 'service', 'value': 'New Patient Visit'},
                          'quote': match.group(0)})
        return added

    @staticmethod
    def _without_noise(out, turn, flow):
        """Wait plus a request is the request; asking to move on is neither
        unclear nor unsupported nor a thanks."""
        if any(a['kind'] == 'pause' for a in out) and any(a['kind'] in REQUEST_ACTS for a in out):
            turn.changed = True
            out = [a for a in out if a['kind'] != 'pause']
        if any(a['kind'] == 'request_next_step' for a in flow):
            kept = [a for a in out if a['kind'] not in {'unclear', 'unsupported', 'acknowledge'}]
            turn.changed, out = turn.changed or kept != out, kept
        return out

    def _consent_target(self, act):
        target = act['target']
        if target['type'] == 'proposal':
            return target['id'] if target['id'] in self.proposals else None
        if self.question and self.question.id == target['id']:
            return self.question.proposal_id
        return None

    def _provider_named(self, value):
        """True when a name value is a catalog provider's name ("Maria Garcia", "Dr. Garcia")."""
        spoken = [w for w in words_of(value) if w not in {'dr', 'doctor'}]
        if not spoken:
            return False
        return any(spoken == [w for w in words_of(p.name) if w != 'dr'] or
                   (len(spoken) == 1 and spoken[0] == words_of(p.name)[-1])
                   for p in self.engine.catalog.providers)

    @staticmethod
    def _introduced(value, caller_text):
        """The caller introduced themself by this name ("my name is ...", "this is ...")."""
        return bool(re.search(r"\b(my name is|my name's|name is|this is|call me|i'?m|i am|it'?s)\s+" + re.escape(value),
                              caller_text, re.I))

    def _same_identity(self, act):
        """A name or full date of birth that repeats the current confirmed value."""
        field, value = act['delta']['field'], act['delta']['value']
        facts = self.engine.state.patient_facts
        if field == 'name' and isinstance(value, str) and facts.name:
            return value.casefold().split() == facts.name.casefold().split()
        if field == 'date_of_birth' and isinstance(value, dict) and facts.date_of_birth and None not in value.values():
            return f"{value['year']:04d}-{value['month']:02d}-{value['day']:02d}" == facts.date_of_birth
        return False

    # -- Request boundaries --------------------------------------------------

    def _request_snapshot(self):
        return deepcopy((self.engine.state, self.fields, self.provenance, self.requested_specialty,
                         self.appointment_date, self.partial_dob, self.identity_confirmed,
                         self.bookings_before_request, self.not_before))

    def _restore_request(self, saved):
        (self.engine.state, self.fields, self.provenance, self.requested_specialty,
         self.appointment_date, self.partial_dob, self.identity_confirmed,
         self.bookings_before_request, self.not_before) = saved

    def _fresh_request(self):
        """Keep the caller's facts (a confirmed identity, new-patient status);
        every booking choice starts over."""
        name, dob = self.identity()
        keep = all((name, dob)) and not self.partial_dob and self.identity_confirmed == (name, dob)
        new_patient = self.engine.state.patient_facts.is_new_patient
        self.engine.state = SessionState(patient_facts=PatientFacts(
            name if keep else None, dob if keep else None, is_new_patient=new_patient))
        caller_fields = ({'name', 'date_of_birth'} if keep else set()) | {'new_patient'}
        self.fields = {k: v for k, v in self.fields.items() if k in caller_fields}
        self.provenance = {k: v for k, v in self.provenance.items() if k in caller_fields}
        self.bookings_before_request = len(self.engine.bookings)
        self.generic_service_request = False
        self.kind_asked = self.proximity_request = False
        self.requested_specialty = self.appointment_date = self.not_before = None
        self.partial_dob = {}
        if not keep:
            self.identity_confirmed = None
