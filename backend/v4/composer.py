"""The one deterministic reply per turn: statements first, then exactly one question.

Information answers precede the next question; nothing the reducer decided is
ever recited as an internal error. Catalog values are spoken, never read raw.
"""
from dataclasses import replace
from datetime import datetime
import re

from scheduling_dialogue import SchedulingDialogue
from .catalog import matching_sites
from .reducer import CLINIC_ZONE, TERMINAL
from .speech import (MONTHS, THANKS, ordinal, provider_name, spoken_address, spoken_hours, spoken_list, spoken_name,
                     spoken_phone, spoken_service)

APOLOGY, STILL = 'Sorry, I did not get that.', 'Sorry, I still did not get that.'
GREETING = 'Hi, I’m an AI scheduling assistant. How can I help you today?'
EMERGENCY = 'Please call emergency services right now. I cannot provide medical advice.'
NO_TRANSFER = 'I cannot transfer this call or arrange a callback.'
EMERGENCY_AGAIN = 'Please hang up and call 911 now.'
CONSENT_QUESTION = 'Shall I book it?'
REFERRAL_QUESTION = 'Do you already have the referral on file?'
READBACK_DECLINED = 'No problem, nothing is booked.'
DECLINED_QUESTION = READBACK_DECLINED + ' Would you like another time, or is that all for today?'
DECLINED_GOODBYE = READBACK_DECLINED + ' Thank you for calling, goodbye.'
GOODBYES = ("You're welcome. Have a great day.", 'Thank you for calling. Have a great day.',
            'Thank you for calling. Goodbye.', 'Goodbye.')
CAPABILITIES = ("I can book appointments and answer questions about our clinics, providers and services, "
                'such as hours, locations, phone numbers and referral rules.')
PRIMARY_CARE = {'Family Medicine', 'Internal Medicine', 'General', 'General Practice'}
BOOKED_CHANGE = "I can't cancel or change a booked appointment on this call; it stays booked."
REPEAT_LEADS = ('To repeat:', 'Let me say that again:')
SPOKEN_ATTRIBUTES = {'hours', 'phone', 'address', 'services', 'locations', 'specialty'}
STATEMENTS = {'cancel', 'unsupported', 'acknowledge'}
ENTITY_FIELD = {'location': 'location_id', 'provider': 'provider_id', 'appointment_type': 'appointment_type_id'}


def handoff_sentence(lead, contact):
    """A request for a person: the editable lead, then the fixed facts (no transfer, the clinic phone)."""
    return ' '.join(part for part in (lead, NO_TRANSFER) if part) + contact


def emergency_sentence(lead):
    """Emergency: the fixed safety sentence first, then the editable wording."""
    return ' '.join(part for part in (EMERGENCY, lead) if part)


class Composer:
    def __init__(self, reducer, *, greeting=GREETING, handoff_lead='', emergency_lead=''):
        self.r = reducer
        # Editable wording (agent file). The safety sentences around it stay fixed here.
        self.greeting, self.handoff_lead, self.emergency_lead = greeting, handoff_lead, emergency_lead
        self.resolution = None
        self.message_text = {}  # message or presentation ID -> what a repeat request replays
        self.readbacks = {}  # proposal ID -> its full read-back, what a repeat request replays
        self.last_text = None
        self.last_canonical = None  # (last reply, the same reply without a repeat lead such as "To repeat:")
        self.unknown = None  # (entity, consecutive asks) for a name not in the catalog.
        self.interrupted_text = None  # Set by the session when a question reply is cut off.
        self._interrupted = None
        self.phone_given = False  # A clinic phone is offered for a block at most once per call.
        self.last_block = None  # The block (code, service, provider, site) of the previous reply.
        self.last_block_options = False  # The last block offered alternatives.
        self.block_shown = {}  # Times each block was shown.
        self.offered = ([], [], [])  # The last block's alternatives: (services, providers, sites).
        self._alternative_times = False  # This reply gives the alternatives' first times.
        # Loop breaker: turns in a row without progress, what was already offered, and
        # whether the call must end after this reply.
        # The greeting asks which service.
        self.stalled, self._offers_seen, self._last_signature = 0, set(), (('service', 'service'), None)
        self.end_call = False
        self.end_reason = None  # 'loop_breaker' or 'emergency' when this reply ends the call.
        self.emergency_given = False  # The full emergency message was said once.
        self.loop_breaker = True  # Off only in replays whose recorded callers answered other replies.
        self.last_info_answered = False
        self._block_unclear = False  # The turn that led to this block reply was not understood.
        self._plain_again = {}  # Blocks whose plain rule was said a second time.
        self.last_body = None  # The last reply without its leads.
        self._recent_bodies = []  # The last few replies without their leads.
        self._block_now = self._block_prev = False
        self._block_variant = False
        self.near_presentation = None  # The one full "nearest" site list of this request.
        self._offered = False  # This reply offers the providers at a known site or specialty.
        self.ai_said = False  # "I'm an AI scheduling assistant, not a person." is said once per call.
        self._reason_given = False  # This reply answers "why" with the block's reason.
        self._handoffs = 0  # Replies in a row that answer a request for a person.

    # -- Spoken facts ----------------------------------------------------------

    provider_name = staticmethod(provider_name)

    @staticmethod
    def when(slot):
        start = datetime.fromisoformat(slot['start']).astimezone(CLINIC_ZONE)
        return start.strftime('%A %B %d at %I:%M %p').replace(' 0', ' ')

    def spoken_slot(self, slot_id):
        slot = self.r.engine._present_slot(self.r.engine._slots[slot_id])
        slot['provider'] = self.provider_name(self.r.engine.catalog.providers_by_id[slot['provider_id']])
        return slot

    def slot_text(self, slot_id, *, booked=False):
        # Reuse the existing critical renderer, without constructing its parser/controller.
        renderer = type('Renderer', (), {'spoken_service': staticmethod(SchedulingDialogue.spoken_service)})()
        return SchedulingDialogue.render(renderer, self.spoken_slot(slot_id), booked=booked)

    def identity_text(self):
        return SchedulingDialogue.identity_message(self.r)

    def contact(self):
        contacts = self.r.engine._clinic_contacts()
        if contacts:
            self.phone_given = True
            return f" You can call {contacts[0]['location']} at {spoken_phone(contacts[0]['phone'])}."
        site = self.main_site()
        self.phone_given = True
        return f' You can call {site.name} at {spoken_phone(site.phone)}.'

    def main_site(self):
        """The clinic to call when no site follows from the request: the requested site,
        else the catalog's first site (the main site)."""
        return self.r.engine._location() or self.r.engine.catalog.locations[0]

    def handoff_text(self):
        """The editable lead, then the fixed facts: no transfer, and the clinic phone."""
        return handoff_sentence(self.handoff_lead, self.contact())

    def limit_text(self):
        booked = 'Your appointment is booked.' if self.r.engine.bookings else 'No appointment was booked.'
        return 'I have reached the request limit for this call, so I cannot continue. ' + booked + self.contact()

    def no_availability_text(self):
        when = ''
        if self.r.appointment_date:
            day = self.r.appointment_date
            when = f' on {day.strftime("%A")}, {MONTHS[day.month - 1]} {day.day}'
        return (f'I have no appointments{when} for this request.' + self.contact()
                + ' Would you like to change the date or location?')

    def unsupported_text(self, topic):
        if topic == 'recorded_booking_change' and not self.r.engine.bookings:
            # With a request in progress the caller is talking about that request
            # ("so I can't book it at all?"): the reply about it answers, not this.
            if self.r.engine.state.appointment_type_id or (self.r.question and self.r.question.kind == 'blocked'):
                return ''
            return 'No appointment has been booked, so there is nothing to change.'
        if topic == 'recorded_booking_change':
            return BOOKED_CHANGE + self.contact()
        r = self.r
        if topic in {'live_transfer', 'callback'}:
            return NO_TRANSFER + self.contact()
        honest = {'clock_time': 'I cannot tell the current time on this call.',
                  'geographic_ranking': 'I cannot tell which clinic is closest to you, but I can give you '
                                        'any clinic\'s address.',
                  'timezone_conversion': "I can only give times in the clinic's local time."}
        if topic in honest:
            return honest[topic]
        if r.engine.state.appointment_type_id or (r.question and r.question.kind == 'blocked'):
            return ''  # A request is in progress: the reply about it answers.
        return ('I cannot do that on this call; I can book appointments and answer questions about our '
                'clinics, providers and services.')

    # -- Information answers ---------------------------------------------------

    def alternative_times(self):
        """The first times of the alternatives a block offered ("when can I see one of the
        other doctors?"), from availability; '' when nothing was offered or nothing is free."""
        engine = self.r.engine
        services, providers, sites = self.offered
        service_ids = {s.id for s in services} or ({engine.state.appointment_type_id} - {None})
        provider_ids = {p.id for p in providers}
        site_ids = {l.id for l in sites}
        if not service_ids:
            return ''
        slots = sorted((s for s in engine._slots.values() if s.appointment_type_id in service_ids
                        and (not provider_ids or s.provider_id in provider_ids)
                        and (not site_ids or s.location_id in site_ids) and s.start >= engine.now),
                       key=lambda s: s.start)
        first, seen = [], set()
        for slot in slots:
            if slot.provider_id not in seen:
                seen.add(slot.provider_id); first.append(slot)
            if len(first) == 2:
                break
        if not first:
            return ''
        rows = [self.spoken_slot(s.slot_id) for s in first]
        labels = [f"{self.when(row)} with {row['provider']} at {row['location']}" for row in rows]
        self._alternative_times = True
        return (f"For {spoken_service(engine.catalog.appointment_types_by_id[first[0].appointment_type_id])}, "
                f"the first times are {' or '.join(labels)}.")

    def info(self, effect):
        """Named lookups use the booking matcher and never end in a dead-end
        question: one match is answered, several are each named with their
        answer, none lists the valid clinics. Read-only: no state changes."""
        entity = effect['entity']
        if (entity in {'provider', 'appointment'} and not effect.get('name') and not effect.get('reference_id')
                and self.r.question and self.r.question.kind == 'blocked' and any(self.offered)):
            # After a block, "when can I see one of the other doctors?": the alternatives' times, once.
            return '' if self._alternative_times else self.alternative_times()
        if entity not in {'location', 'provider', 'service'} or effect.get('reference_id') or not effect.get('name'):
            return self._referenced_info(effect)
        kind = 'appointment_type' if entity == 'service' else entity
        catalog = self.r.engine.catalog
        matches = list({m['id']: m for m in catalog.search(kind, effect['name'])}.values())
        current = getattr(self.r.engine.state, ENTITY_FIELD[kind])
        if len(matches) > 1 and current in {m['id'] for m in matches}:
            # "Dr. Smith" with Dr. Daniel Smith in the request: the request's own provider.
            matches = [m for m in matches if m['id'] == current]
        label = {'location': 'clinic', 'provider': 'provider', 'appointment_type': 'service'}[kind]
        if len(matches) == 1 and not matches[0].get('requires_confirmation'):
            return self.details_text(kind, matches[0]['id'], effect['attribute'])
        answers = [self.details_text(kind, m['id'], effect['attribute']) for m in matches[:3]]
        if matches and any(m.get('requires_confirmation') for m in matches):
            return 'I could not find an exact match for that name. The closest catalog matches: ' + ' '.join(answers)
        if matches:
            return f'More than one {label} matches that name. ' + ' '.join(answers)
        if kind == 'location':
            return ('I could not find a clinic by that name. Our clinics are '
                    + spoken_list(location.name for location in catalog.locations) + '.')
        return f'I could not find a {label} by that name in the catalog.'

    def _referenced_info(self, effect):
        """About the assistant, the selected appointment, or a referenced entity."""
        r = self.r; entity = effect['entity']; ident = None
        if entity == 'assistant':
            if effect.get('attribute') == 'services':  # "What can you do?"; identity is "are you a person?"
                return CAPABILITIES
            if effect.get('attribute') == 'referral':  # "How do I check my referral?"
                return ('I cannot see referral records on this call; your doctor\'s office or the clinic can '
                        'confirm whether it is on file.')
            if self.ai_said:
                return ''  # Said once per call; the reply about the request answers the rest.
            self.ai_said = True
            return "I'm an AI scheduling assistant, not a person."
        if (entity == 'provider' and not effect.get('name') and not effect.get('reference_id')
                and r.engine._appointment_type() and not r.engine.state.provider_id):
            if not r.engine.state.any_provider:
                return ''  # "Who is available?": the next question names them.
            service, site = r.engine._appointment_type(), r.engine._location()
            rows = self._offering(service, site=site)
            if r.requested_specialty:
                rows = [p for p in rows if p.specialty == r.requested_specialty] or rows
            names = spoken_list(self.provider_name(p) + ' in ' + p.specialty for p in rows[:3])
            offered = spoken_service(service)
            return (f'{offered[0].upper() + offered[1:]} is offered by {names}'
                    + (', among others' if len(rows) > 3 else '') + '. I can look for the first available time with any of them.'
                    if rows else '')
        if entity == 'appointment':
            return self._appointment_info(effect.get('reference_id'))
        kind = 'appointment_type' if entity == 'service' else entity
        reference = effect.get('reference_id')
        if reference:
            _, value = r.messages.get(reference, (None, reference))
            presentation = r.presentations.get(value)
            if presentation and presentation.entity == entity and len(presentation.option_ids) == 1:
                ident = presentation.option_ids[0]
            proposal = r.proposals.get(value)
            if proposal and proposal.slot_id:
                slot = r.engine._slots[proposal.slot_id]
                ident = getattr(slot, {'location': 'location_id', 'provider': 'provider_id', 'service': 'appointment_type_id'}[entity])
        if not ident and not effect.get('name') and entity == 'location' and effect['attribute'] in {'phone', 'hours', 'address'}:
            # "How do I contact the clinic?": the site of this request, or the provider's sites.
            provider = r.engine._provider()
            sites = ([r.engine._location()] if r.engine._location()
                     else [r.engine.catalog.locations_by_id[i] for i in provider.location_ids] if provider else [])
            if sites:
                return ' '.join(self.details_text('location', site.id, effect['attribute']) for site in sites[:2])
        if not ident and not effect.get('name'):
            # No name given: the request's own service, provider or site, when known.
            current = {'service': r.engine._appointment_type(), 'provider': r.engine._provider(),
                       'location': r.engine._location()}.get(entity)
            if current and effect['attribute'] in {'date', 'time'}:
                return ''  # "Can you look for slots?": the times offered answer it.
            ident = current.id if current else None
        if not ident:
            if not effect.get('name'):
                return 'Which location, provider or service would you like information about?'
            matches = r.engine.catalog.search(kind, effect['name'])
            if len(matches) != 1 or matches[0].get('requires_confirmation'):
                names = list(dict.fromkeys(self.provider_name(r.engine.catalog.providers_by_id[item['id']])
                                           if kind == 'provider' else item['name'] for item in matches))
                return ('For that information, did you mean ' + ' or '.join(names[:3]) + '?'
                        if names else "I couldn't find that catalog entry. Could you repeat its name?")
            ident = matches[0]['id']
        return self.details_text(kind, ident, effect['attribute'])

    def _appointment_info(self, reference):
        r = self.r
        p = r.proposals.get(r.messages.get(reference, (None, reference))[1]) if reference else None
        if p is None:
            p = next((p for p in reversed(list(r.proposals.values())) if p.kind == 'booking' and r._current_proposal(p)), None)
        if p:
            slot = self.spoken_slot(p.slot_id)
            return f"That appointment is for {slot['service']} with {slot['provider']} at {slot['location']}, {self.when(slot)}."
        if (r.open_choice() and r.open_choice().entity == 'slot') or r.engine.state.appointment_type_id:
            return ''  # "When is it?" with a request in progress: the times offered next answer it.
        return 'No appointment has been selected yet.'

    def details_text(self, kind, ident, attr):
        """Catalog values are rendered as speech, never read literally."""
        details = self.r.engine.get_details(kind, ident)['details']
        if attr not in SPOKEN_ATTRIBUTES:
            return self._policy_detail(kind, ident, details, attr)
        name = (self.provider_name(self.r.engine.catalog.providers_by_id[ident])
                if kind == 'provider' else spoken_name(details['name']))
        if attr == 'locations':
            sites = [self.r.engine.catalog.locations_by_id[i].name for i in details.get('location_ids', [])]
            return f'{name} practices at {spoken_list(sites)}.' if sites else f'No practice sites are listed for {name}.'
        if attr == 'specialty':
            value = details.get('specialty')
            return f"{name}'s specialty is {value}." if value else f'No specialty is listed for {name}.'
        if attr == 'services':
            return self._services_text(kind, ident, details, name)
        value = details.get(attr)
        if not value:
            return f'The catalog has no {"phone number" if attr == "phone" else attr} for {name}.'
        if attr == 'hours':
            return f'{name} is open {spoken_hours(value)}.'
        if attr == 'phone':
            return f'The phone number for {name} is {spoken_phone(value)}.'
        city = details.get('city')
        return f'{name} is at {spoken_address(value)}' + (f', {city}' if city else '') + '.'

    def service_summary(self, service):
        """What the catalog says about a service ("what does that involve?"). The
        catalog has no description, so only its facts: length, specialty and rules."""
        spoken = spoken_service(service)
        rules = ['it needs a referral on file' if service.requires_referral else 'no referral is needed',
                 'it is open to new patients' if service.new_patients_allowed else 'it is only for existing patients']
        return (f'{spoken[0].upper() + spoken[1:]} is a {service.duration_min}-minute {service.specialty} visit; '
                f'{rules[0]}, and {rules[1]}. The catalog has no further description.')

    def _policy_detail(self, kind, ident, details, attr):
        name = details['name']
        if kind == 'provider':
            name = self.provider_name(self.r.engine.catalog.providers_by_id[ident])
        if attr == 'referral':
            return f"{name} " + ('requires a referral on file.' if details.get('requires_referral') else 'does not require a referral.')
        if attr == 'new_patient_policy':
            value = details.get('new_patients_allowed', details.get('accepting_new_patients'))
            if value is None:
                return f'No new-patient policy is listed for {name}.'
            return f"{name} " + ('accepts new patients.' if value else 'does not accept new patients.')
        catalog = self.r.engine.catalog
        if attr == 'identity':
            # "Can I get the name again?": who or what it is, from the catalog.
            if kind == 'provider':
                provider = catalog.providers_by_id[ident]
                sites = spoken_list(catalog.locations_by_id[i].name for i in provider.location_ids)
                article = 'an' if provider.specialty[:1].lower() in 'aeiou' else 'a'
                return f'{name} is {article} {provider.specialty} provider who sees patients at {sites}.'
            if kind == 'location':
                return f"{name} is at {spoken_address(details['address'])}."
            if kind == 'appointment_type':
                return self.service_summary(catalog.appointment_types_by_id[ident])
        asked = {'date': 'dates', 'time': 'times', 'hours': 'hours'}.get(attr, attr.replace('_', ' '))
        offer = ('their sites, specialty and services' if kind == 'provider'
                 else 'its hours, address, phone number and services' if kind == 'location'
                 else 'its length, referral rule and who offers it')
        return f'The catalog has no {asked} for {name}; I can tell you {offer}.'

    def _services_text(self, kind, ident, details, name):
        catalog = self.r.engine.catalog
        if kind == 'appointment_type':
            return self.service_summary(catalog.appointment_types_by_id[ident])
        ids = details.get('appointment_type_ids', [])
        if kind == 'location':
            ids = sorted({i for p in catalog.providers if ident in p.location_ids
                          for i in p.appointment_type_ids if not catalog.appointment_types_by_id[i].required_capability
                          or catalog.appointment_types_by_id[i].required_capability in details['capabilities']})
        if not ids:
            return f'The catalog lists no services for {name}.'
        names = [spoken_name(catalog.appointment_types_by_id[i].name) for i in ids]
        if len(names) > 8:
            # A spoken list stays short: the count and the first few.
            return f'{name} offers {len(names)} services, including {spoken_list(names[:5])}.'
        return f'{name} lists these services: ' + spoken_list(names) + '.'

    # -- Questions -------------------------------------------------------------

    def _question(self, text, kind, field=None, *, presentation=None, proposal=None):
        q = self.r.set_question(kind, field=field, proposal_id=proposal.id if proposal else None)
        return text, (proposal.id,) if proposal else (), (presentation.id,) if presentation else (), q.id

    def _readback(self, proposal):
        text = self.identity_text() if proposal.kind == 'identity' else self.slot_text(proposal.slot_id)
        self.message_text[proposal.message_id] = text
        self.readbacks[proposal.id] = text
        return self._question(text, proposal.kind + '_consent', proposal=proposal)

    def _options(self, entity, rows):
        """One choice among up to three catalog options or slots."""
        site = self.r.engine._location()
        if entity == 'provider' and site:
            # Offer only providers who practice at the requested site, when any do.
            here = [row for row in rows if site.id in self.r.engine.catalog.providers_by_id[row['id']].location_ids]
            rows = here or rows
        rows = rows[:3]
        p = self.r.present(entity, [row['slot_id'] if entity == 'slot' else row['id'] for row in rows])
        text = self._choice_text(entity, rows)
        self.message_text[p.id] = text  # The canonical choice text is what a repeat request replays.
        return self._question(text, entity + '_choice', presentation=p)

    def short_labels(self, presentation, *, with_time=False):
        """Short spoken labels of a list's options: only what tells them apart
        ("the 23rd or the 30th"; times when the day is the same; a provider or site
        only when it differs)."""
        catalog = self.r.engine.catalog
        if presentation.entity == 'slot':
            rows = [self.spoken_slot(i) for i in presentation.option_ids]
            starts = [datetime.fromisoformat(row['start']).astimezone(CLINIC_ZONE) for row in rows]
            days = {t.date() for t in starts}
            times = {t.strftime('%H:%M') for t in starts}
            labels = []
            for row, t in zip(rows, starts):
                day = f"{t.strftime('%A')} the {ordinal(t.day)}"
                clock = t.strftime('%I:%M %p').lstrip('0')
                label = (day if len(times) == 1 and not with_time else clock if len(days) == 1
                         else f'{day} at {clock}' if len(times) > 1 else day)
                if len({r['provider_id'] for r in rows}) > 1:
                    label += ' with ' + row['provider']
                if len({r['location_id'] for r in rows}) > 1:
                    label += ' at ' + row['location']
                labels.append(label)
            return labels
        if presentation.entity == 'provider':
            providers = [catalog.providers_by_id[i] for i in presentation.option_ids]
            names = [self.provider_name(p) for p in providers]
            same = len({p.name for p in providers}) < len(providers)  # Same name: the specialty tells them apart.
            return [n + (' in ' + p.specialty if same else '') for n, p in zip(names, providers)]
        if presentation.entity == 'location':
            return [catalog.locations_by_id[i].name for i in presentation.option_ids]
        return [spoken_name(catalog.appointment_types_by_id[i].name) for i in presentation.option_ids]

    def short_choice(self, presentation, lead='', *, with_time=False):
        """The same choice asked again in one short question; the list stays current.
        with_time: "what time was that?" always hears the time, said once when shared."""
        labels = self.short_labels(presentation, with_time=with_time)
        text = (lead + ' ' if lead else '') + ', '.join(labels[:-1]) + (' or ' if len(labels) > 1 else '') + labels[-1]
        if with_time and presentation.entity == 'slot':
            starts = {datetime.fromisoformat(self.spoken_slot(i)['start']).astimezone(CLINIC_ZONE).strftime('%I:%M %p').lstrip('0')
                      for i in presentation.option_ids}
            if len(starts) == 1:
                text += (', both at ' if len(labels) == 2 else ', all at ') + starts.pop()
        text += '?'
        q = self.r.set_question(presentation.entity + '_choice')
        return text[0].upper() + text[1:], (), (presentation.id,), q.id

    def _choice_text(self, entity, rows):
        if entity == 'slot':
            return self._slot_choice_text(rows)
        if entity == 'provider':
            return self._provider_choice_text(rows)
        if entity == 'service':
            return self._service_choice_text(rows)
        return self._location_choice_text(rows)

    def _slot_choice_text(self, rows):
        providers = {row['provider_id'] for row in rows}
        sites = {row['location_id'] for row in rows}
        by_id = self.r.engine.catalog.providers_by_id
        context = 'For your ' + spoken_name(rows[0]['service'])
        if len(providers) == 1:
            context += ' with ' + self.provider_name(by_id[rows[0]['provider_id']])
        if len(sites) == 1:
            context += ' at ' + rows[0]['location']
        labels = []
        for row in rows:
            label = self.when(row)
            if len(providers) > 1:
                label += ' with ' + self.provider_name(by_id[row['provider_id']])
            if len(sites) > 1:
                label += ' at ' + row['location']
            labels.append(label)
        return context + ', I have ' + ' or '.join(labels) + '. Which works for you?'

    def _provider_choice_text(self, rows):
        labels = [self.provider_name(self.r.engine.catalog.providers_by_id[row['id']]) + ' in ' + row['specialty']
                  for row in rows]
        if len(rows) == 1:
            lead = ('I could not find an exact match. The closest catalog match is '
                    if rows[0].get('requires_confirmation') else 'I found ')
            return lead + labels[0] + '. Is that who you meant?'
        lead = ('I could not find an exact match. The closest catalog matches are '
                if any(row.get('requires_confirmation') for row in rows) else 'I found ')
        return lead + spoken_list(labels) + '. Which provider did you mean?'

    def _service_choice_text(self, rows):
        names = spoken_list(spoken_name(row['name']) for row in rows)
        if any(row.get('requires_confirmation') for row in rows):
            lead = '' if self.r.kind_asked else 'I could not find a service by that name. '
            text = lead + 'The closest ' + ('service is ' if len(rows) == 1 else 'services are ') + names + '. '
        else:
            text = 'I found ' + names + '. '
        return text + ('Is that the one you meant?' if len(rows) == 1 else 'Which one would you like?')

    def _location_choice_text(self, rows):
        provider, service = self.r.engine._provider(), self.r.engine._appointment_type()
        if len(rows) == 1 and provider:
            # A sole site is stated, not offered as a one-item choice.
            return (('For your ' + spoken_name(service.name) + ', ' if service else '')
                    + self.provider_name(provider) + ' practices only at ' + rows[0]['name']
                    + '. Shall I look for appointments there?')
        names = [row['name'] for row in rows]
        listing = names[0] if len(names) == 1 else ' and '.join(names) if len(names) == 2 else spoken_list(names)
        intro = (f'{self.provider_name(provider)} sees patients at ' if provider and all(row['id'] in provider.location_ids for row in rows)
                 else 'The listed location is ' if len(rows) == 1 else 'The listed locations are ')
        text = intro + listing + '. Which location works best for you?'
        if service and not text.startswith(('Dr', 'Nurse', 'Physician')):
            text = text[0].lower() + text[1:]  # "For your Flu Shot, the listed locations are ..."
        return 'For your ' + spoken_name(service.name) + ', ' + text if service else text

    def _next(self, resolution):
        """The one next question of the booking flow."""
        errors = resolution.get('errors', [])
        if errors:
            entity = errors[0]['entity']
            field = entity if entity in {'location', 'provider'} else 'service'
            if field in self.r.last_turn_fields or self.unknown is None:
                return self._unknown_name(resolution, entity)
            # Said already when the name was given: the question alone, not "could not find" again.
            return self._question({'location': 'Which clinic would you like?',
                                   'provider': 'Which provider would you like to see, or shall I look for anyone available?',
                                   'service': 'What service would you like to book?'}[field], field, field)
        self.unknown = None
        if self.r.generic_service_request and not self.r.engine.state.appointment_type_id:
            self.r.kind_asked = True
            return self._question('What kind of appointment would you like?', 'service', 'service')
        for step in (self._held_booking, lambda: self._candidates(resolution), self._site_without_provider,
                     lambda: self._patient_facts(resolution),
                     self._nearest_sites, lambda: self._provider_offer(resolution)):
            parts = step()
            if parts is not None:
                return parts
        return self._next_missing_fact(resolution)

    def _candidates(self, resolution):
        """Several catalog matches for what the caller said: that choice first."""
        return self._next_missing_fact(resolution) if resolution.get('candidates') else None

    def _patient_facts(self, resolution):
        """Once the service is known: new-patient status, then a needed referral,
        before any provider, site or read-back (they decide what can be booked)."""
        r = self.r; s = r.engine.state; service = r.engine._appointment_type()
        if not service or resolution.get('blocked_options') or resolution.get('errors'):
            return None
        f = s.patient_facts
        if f.is_new_patient is None:
            return self._question('Are you a new patient?', 'boolean', 'new_patient')
        if service.requires_referral and f.referral_on_file is None:
            return self._question(REFERRAL_QUESTION, 'boolean', 'referral')
        return None

    def _services_for_request(self, rows):
        """Service matches limited to what the known provider offers, or to the
        requested specialty, searched over the whole catalog (the engine lists the
        first few matches only). Unchanged when nothing known narrows them."""
        r = self.r; catalog = r.engine.catalog
        provider, words = r.engine._provider(), r.fields.get('service')
        if not isinstance(words, str) or not (provider or r.requested_specialty):
            return rows
        found = catalog.search('appointment_type', words)
        keep = [row for row in found if (provider and row['id'] in provider.appointment_type_ids)
                or (not provider and catalog.appointment_types_by_id[row['id']].specialty == r.requested_specialty)]
        if provider:
            related = catalog.routine_options_for_provider(words, provider)
            keep = list({row['id']: row for row in [*related, *keep]}.values())
            keep.sort(key=lambda row: catalog.appointment_types_by_id[row['id']].specialty != provider.specialty)
            if related:
                # A short generic menu spans specialties instead of treating
                # the first clinical service as the caller's chosen service.
                shown, specialties = [], set()
                for row in keep:
                    specialty = catalog.appointment_types_by_id[row['id']].specialty
                    if specialty not in specialties:
                        specialties.add(specialty)
                        shown.append(row)
                keep = shown
        return keep or rows

    def _next_missing_fact(self, resolution):
        r = self.r; s = r.engine.state
        candidates = resolution.get('candidates', [])
        if candidates:
            kind = candidates[0]['entity']; entity = 'service' if kind == 'appointment_type' else kind
            rows = [row for row in candidates if row['entity'] == kind]
            if entity == 'service':
                rows = self._services_for_request(rows)
            if entity == 'provider' and r.requested_specialty:
                rows = [row for row in rows if row['specialty'] == r.requested_specialty]
            if rows:
                return self._options(entity, rows)
            return self._question('No candidate matches your requested specialty. Which provider did you mean?', 'provider_choice')
        if not s.appointment_type_id:
            return self._question('What service would you like to book?', 'service', 'service')
        if not s.provider_id and not s.any_provider:
            return self._question('Which provider would you like to see, or shall I look for anyone available?',
                                  'provider', 'provider')
        if not s.location_id and not s.any_location:
            rows = resolution.get('eligible_locations', [])
            if rows:
                return self._options('location', rows)
            return self._question('Which clinic location would you like?', 'location', 'location')
        f = s.patient_facts
        if f.is_new_patient is None:
            return self._question('Are you a new patient?', 'boolean', 'new_patient')
        if r.engine._appointment_type().requires_referral and f.referral_on_file is None:
            return self._question(REFERRAL_QUESTION, 'boolean', 'referral')
        return self._next_identity_or_slot()

    def _next_identity_or_slot(self):
        r = self.r; s = r.engine.state
        if self.identity_missing():
            text, field = self.identity_question()
            return self._question(text, 'identity', field)
        if r.identity_confirmed != r.identity():
            for pid, p in list(r.proposals.items()):
                if p.kind == 'identity' and p.status in {'open', 'accepted'}:
                    r.proposals[pid] = replace(p, status='revoked')
            return self._readback(r.propose_identity())
        if s.selected_slot_id:
            return self._readback(r.prepare_booking(s.selected_slot_id))
        slots = r.find_slots(limit=3)
        lead = ''
        shift = r.last_shift if 'date_shift' in r.last_turn_fields else None
        if shift and not slots.get('slots') and r.not_before is not None:
            # Nothing after the relative date: say so, and offer the earliest times again.
            kind, latest = shift[0], shift[2]
            r.drop_date_shift()
            slots = r.find_slots(limit=3)
            if slots.get('slots'):
                lead = (f'I have nothing later than {self.when({"start": latest.isoformat()})}. ' if kind == 'later' and latest
                        else 'I have nothing after that. ')
        elif shift and shift[0] == 'earlier' and slots.get('slots') and slots['slots'][0]['slot_id'] in shift[1]:
            lead = 'Those are the earliest times I have. '
        if slots.get('slots'):
            text, *rest = self._options('slot', slots['slots'])
            return (lead + text, *rest)
        return self._question(self.no_availability_text(), 'no_availability')

    def _unknown_name(self, resolution, entity):
        """A name not in the catalog: the valid choices, never a dead end."""
        count = self.unknown[1] + 1 if self.unknown and self.unknown[0] == entity else 1
        self.unknown = (entity, count)
        if entity == 'location':
            rows = resolution.get('eligible_locations') or []
            if rows:
                text, *ids = self._options('location', rows)
                return ('I could not find a clinic by that name. ' + text, *ids)
            names = spoken_list(location.name for location in self.r.engine.catalog.locations)
            return self._question(f'I could not find a clinic by that name. Our clinics are {names}. '
                                  'Which one would you like?', 'location', 'location')
        if entity == 'provider':
            if count == 1:
                return self._question('I could not find a provider by that name. Could you spell the first name '
                                      'and surname, or say any available provider?', 'provider', 'provider')
            return self._question('I still could not find a provider by that name.' + self.contact()
                                  + ' Would you like a different provider, or any available provider?',
                                  'provider', 'provider')
        return self._question('I could not find a service by that name. What service would you like to book?',
                              'service', 'service')

    def _held_booking(self):
        """A turn that changed nothing (thanks, okay) keeps the current booking
        read-back: an open one is asked about again, never replaced by a new
        proposal; an accepted one waits for its write. None: normal flow."""
        slot = self.r.engine.state.selected_slot_id
        p = next((p for p in reversed(list(self.r.proposals.values()))
                  if p.kind == 'booking' and p.slot_id == slot and p.status in {'open', 'accepted'}
                  and p.delivered and self.r._current_proposal(p)), None) if slot else None
        if p is None:
            return None
        if p.status == 'accepted':
            return '', (), (), None
        return self._question(CONSENT_QUESTION, 'booking_consent', proposal=p)

    def _site_without_provider(self):
        """A site that could host the service but where no provider offers it: a block
        with the reason and the sites that can, not "no appointments" later."""
        r = self.r; state = r.engine.state; service, site = r.engine._appointment_type(), r.engine._location()
        if not (service and site) or state.provider_id or not self._capable(service, site):
            return None
        if any(service.id in p.appointment_type_ids and site.id in p.location_ids for p in r.engine.catalog.providers):
            return None
        issue = {'code': 'no_provider_at_location'}
        return self._question(self.blocked_text(self._block_message(issue), issue), 'blocked')

    def _offering(self, service, *, site=None):
        """Providers who offer the service (at the site), accepting the caller if new."""
        new = self.r.engine.state.patient_facts.is_new_patient
        return [p for p in self.r.engine.catalog.providers if service.id in p.appointment_type_ids
                and (site is None or site.id in p.location_ids) and (new is not True or p.accepting_new_patients)]

    @staticmethod
    def _capable(service, location):
        return not service.required_capability or service.required_capability in location.capabilities

    def _provider_offer(self, resolution):
        """Provider still open but the specialty or site is known: name the actual
        providers there and offer anyone available, instead of a bare question."""
        r = self.r; state = r.engine.state; service = r.engine._appointment_type()
        site, specialty = r.engine._location(), r.requested_specialty
        if (not service or state.provider_id or state.any_provider
                or resolution.get('candidates') or resolution.get('errors') or resolution.get('blocked_options')):
            return None
        offering = self._offering(service, site=site)
        rows = [p for p in offering if not specialty or p.specialty == specialty]
        lead = ''
        if specialty and not rows and site:
            lead = f'No {specialty} provider offers {spoken_service(service)} at {site.name}. '
            rows = offering
        if not rows and not offering and state.patient_facts.is_new_patient is True:
            # Nobody who offers the service takes new patients: say so, with the alternative.
            spoken = spoken_service(service)
            alternative = self._new_patient_alternative(None, service)
            self.last_block_options = bool(alternative)
            return self._question(f'No provider who offers {spoken} is accepting new patients. ' + alternative
                                  + (' Would you like that, or something else?' if alternative
                                     else ' Is there anything else I can help with?'), 'blocked')
        if not rows:
            return None
        shown = rows[:3]
        presentation = r.present('provider', [p.id for p in shown])
        labels = spoken_list(self.provider_name(p) + ' in ' + p.specialty for p in shown)
        where = f'At {site.name}, ' if site else f'In {specialty}, ' if specialty else ''
        offered = spoken_service(service)
        text = (lead + where + (offered if where else offered[0].upper() + offered[1:]) + f' is offered by {labels}'
                + (', among others' if len(rows) > len(shown) else '')
                + '. Which would you like, or shall I look for anyone available?')
        self.message_text[presentation.id] = text
        self._offered = True
        return self._question(text, 'provider_choice', presentation=presentation)

    def _nearest_sites(self):
        """'The nearest clinic': the eligible sites, listed once, without claiming geography."""
        r = self.r; state = r.engine.state; service = r.engine._appointment_type()
        if not r.proximity_request or not service or state.location_id or state.any_location:
            return None
        listed = r.presentations.get(self.near_presentation or '')
        if listed and listed.generation == r.generation and listed.delivered:
            # Listed once already: ask again without reading the list again.
            return self._question('Which of those clinics works best for you?', 'location_choice', presentation=listed)
        provider = r.engine._provider()
        providers = [provider] if provider else self._offering(service)
        sites = [l for l in r.engine.catalog.locations
                 if self._capable(service, l) and any(l.id in p.location_ids for p in providers)]
        if not sites:
            return None
        presentation = r.present('location', [l.id for l in sites])
        self.near_presentation = presentation.id
        text = (f"I can't tell which clinic is nearest to you. For your {spoken_name(service.name)}, you can come to "
                f"{spoken_list(l.name for l in sites)}. Which one works best for you?")
        self.message_text[presentation.id] = text
        return self._question(text, 'location_choice', presentation=presentation)

    def identity_missing(self):
        # A one-word name gets one request for the last name before the read-back.
        return (not all(self.r.identity()) or bool(self.r.partial_dob)
                or bool(self.r.partial_name() and not self.r.surname_requested))

    @staticmethod
    def _dob_question(known, *, short=False):
        """The question for the missing date-of-birth parts only."""
        month = MONTHS[known['month'] - 1] if 'month' in known else None
        day = ordinal(known['day']) if 'day' in known else None
        year = known.get('year')
        missing = frozenset(part for part in ('year', 'month', 'day') if part not in known)
        if missing == {'day'}:
            return f'Which day in {month}?' if short else f'Which day in {month} {year}?'
        return {frozenset({'year'}): f'{month} {known.get("day")} of which year?',
                frozenset({'month'}): f'Which month in {year}, on the {day}?',
                frozenset({'month', 'day'}): f'Which month and day in {year}?',
                frozenset({'day', 'year'}): f'Which day in {month}, and which year?',
                frozenset({'month', 'year'}): f'Which month and year, on the {day}?'}[missing]

    def identity_question(self):
        """Acknowledge what was given and ask, in one question, for exactly what is missing."""
        r = self.r; f = r.engine.state.patient_facts; known = r.partial_dob
        if not f.name and not f.date_of_birth and not known:
            return 'What is your full name and date of birth?', 'name'
        name = 'your full name' if not f.name else 'your last name' if r.partial_name() and not r.surname_requested else None
        if name == 'your last name':
            r.surname_requested = True
        if f.date_of_birth and not known:
            return f'And {name}?', 'name'
        if not known:
            return (f'And {name}, and your date of birth?', 'name') if name else ('And your date of birth?', 'date_of_birth')
        dob = self._dob_question(known, short=bool(name))
        if not name:
            return dob, 'date_of_birth'
        return f'And {name}, and {dob[0].lower() + dob[1:] if dob.startswith("Which") else dob}', 'name'

    # -- Blocks ----------------------------------------------------------------

    def _block_message(self, issue):
        """Why the request cannot be booked, in one sentence."""
        r = self.r
        service, provider, site = r.engine._appointment_type(), r.engine._provider(), r.engine._location()
        provider_name = self.provider_name(provider) if provider else 'This provider'
        spoken = spoken_service(service) if service else 'this service'
        Spoken = spoken[0].upper() + spoken[1:]
        messages = {
            'location_missing_capability': f"{site.name if site else 'This location'} cannot provide {spoken} because it lacks {issue.get('required_capability', 'the required capability')}.",
            'provider_not_at_location': f"{provider_name} does not practice at {site.name if site else 'this location'}.",
            'provider_does_not_offer_type': f"{provider_name} does not offer {spoken}.",
            'unbookable_type_no_provider': f"No provider in the catalog offers {spoken}.",
            'no_provider_at_location': f"No provider at {site.name if site else 'that clinic'} offers {spoken}.",
            'new_patient_type_restricted': f'{Spoken} is only for existing patients, so I cannot book it for a new patient.',
            'new_patient_provider_restricted': f'{provider_name} is not accepting new patients.',
            'referral_required': f'{Spoken} needs a referral on file, so I cannot book it without one.'}
        return messages.get(issue['code'], 'This request does not meet the booking rules.')

    def blocked_text(self, text, issue, info=()):
        """A block states why and the valid alternatives (another provider, site or
        service that satisfies the rule), with a clinic phone at most once per call.
        The same block again gets a short reminder, never "change the request"."""
        state = self.r.engine.state
        options = self._block_options(issue)
        key = (issue.get('code'), state.appointment_type_id, state.provider_id, state.location_id)
        self.last_block_options = bool(options) and self._choosable
        last = [part for part in options.replace('Dr. ', 'Dr ').split('. ') if part][-1:] or ['']
        several = ' and ' in last[0] or ' or ' in last[0]  # The alternatives name more than one choice.
        ask = ((' Which would you like, or something else?' if several else ' Would you like that, or something else?')
               if self.last_block_options else ' Is there anything else I can help with?')
        # Each push-back moves one step: full reply, plain rule with the alternatives, then
        # the phone. A turn that was not understood ("I think", "what does that mean?")
        # gets the plain rule and does not move the step.
        before = self.block_shown.get(key, 0)
        if self._block_unclear and before == 2 and not self._plain_again.get(key):
            # Not understood right after the plain rule ("what does that mean?"): the rule
            # in plain words once more, without the alternatives; the step does not move.
            self._plain_again[key] = True
            self.last_block, self._block_now = key, True
            ask = (' Would you like one of the alternatives I mentioned, or something else?' if self.last_block_options
                   else ' Is there anything else I can help with?')  # Nothing is listed in this reply.
            return ' '.join(part for part in (*info, self._rule_unless_given(issue)) if part) + ask
        shown = self.block_shown[key] = before + 1
        if shown == 2:
            # Pushed back once: the rule in plain words, and the alternatives one last time.
            body = ' '.join(part for part in (*info, self._rule_unless_given(issue), options) if part)
        elif shown >= 3:
            # Pushed back again: where to call, and the call can move on. Two wordings
            # alternate, so no reply repeats the one before.
            self.last_block_options = False
            ask = ' Is there anything else I can help with?'
            # The phone number once per call; after that, a reminder without it.
            phone = 'The clinic can help by phone.' if self.phone_given else self._blocked_contact(issue).strip()
            lead = ("I can't book that on this call." if shown % 2 else "I'm sorry, that can't be booked here.")
            body = ' '.join(part for part in (*info, lead, phone) if part)
        else:
            # A clinic phone only when no alternative can be booked here, at most once per call.
            contact = '' if self.phone_given or self.last_block_options else self._blocked_contact(issue)
            explain = ''
            if self.r.referral_unknown and issue.get('code') == 'referral_required':
                # "I don't know" to the referral question: what a referral is, once.
                self.r.referral_unknown = False
                explain = ('A referral is a request from your own doctor asking the clinic to see you; since you are '
                           'not sure, I will treat it as not on file. If one is on file, just tell me.')
            text = '' if self._reason_given else text
            body = ' '.join(part for part in (explain, text, *info, self._policy_facts(issue), options) if part) + contact
        self.last_block, self._block_now = key, True
        return body + ask

    def _why_blocked(self, effect, issue):
        """Only an explicit reason act asks why. V1.10 cannot express this attribute;
        sharing a name with the blocked request does not turn a catalog question into why."""
        if effect.get('attribute') != 'block_reason':
            return None
        engine = self.r.engine; catalog = engine.catalog
        kind = 'appointment_type' if effect['entity'] == 'service' else effect['entity']
        current = {'location': engine._location(), 'provider': engine._provider(),
                   'appointment_type': engine._appointment_type()}.get(kind)
        if not current:
            return None
        if not effect.get('name'):
            return self._block_reason(issue)
        found = {m['id'] for m in catalog.search(kind, effect['name'])}
        if kind == 'location':
            found |= {l.id for l in matching_sites(catalog.locations, effect['name'])}
        return self._block_reason(issue) if current.id in found else None

    def _block_reason(self, issue):
        """Why the request cannot be booked, with the catalog facts behind it."""
        engine = self.r.engine; catalog = engine.catalog
        service, provider, site = engine._appointment_type(), engine._provider(), engine._location()
        spoken = spoken_service(service) if service else 'this service'
        code = issue.get('code')
        if code == 'location_missing_capability' and site:
            needed = issue.get('required_capability') or (service.required_capability if service else '')
            has = [c.replace('_', ' ') for c in site.capabilities]
            return (f'{site.name} has {spoken_list(has)} services but no {needed.replace("_", " ")}, which {spoken} needs.'
                    if has else f'{site.name} has no {needed.replace("_", " ")} services, which {spoken} needs.')
        if code == 'provider_not_at_location' and provider and site:
            sites = spoken_list(catalog.locations_by_id[i].name for i in provider.location_ids)
            return f'{self.provider_name(provider)} practices only at {sites}, not at {site.name}.'
        if code in {'no_provider_at_location', 'unbookable_type_no_provider', 'provider_does_not_offer_type',
                    'new_patient_provider_restricted'}:
            return self._block_message(issue)
        return self._plain_rule(issue)

    def _plain_rule(self, issue):
        """The block's rule in simple words."""
        engine = self.r.engine
        service, provider, site = engine._appointment_type(), engine._provider(), engine._location()
        spoken = spoken_service(service) if service else 'this service'
        who = self.provider_name(provider) if provider else 'This provider'
        where = site.name if site else 'That clinic'
        plain = {
            'referral_required': f'In short, the clinic can book {spoken} only once a referral from your doctor is on file.',
            'new_patient_type_restricted': f'In short, {spoken} is only for patients who have already been seen here; '
                                           'a first visit has to be a new-patient appointment.',
            'new_patient_provider_restricted': f'In short, {who} is not taking new patients right now.',
            'location_missing_capability': f'In short, {where} does not have what is needed for {spoken}.',
            'provider_not_at_location': f'In short, {who} does not work at {where}.',
            'provider_does_not_offer_type': f'In short, {who} does not do {spoken}.',
            'unbookable_type_no_provider': f'In short, no provider here does {spoken}.',
            'no_provider_at_location': f'In short, no provider at {where} does {spoken}.'}
        return plain.get(issue.get('code'), 'In short, this request does not meet the booking rules.')

    def _rule_unless_given(self, issue):
        return '' if self._reason_given else self._plain_rule(issue)

    def _block_rule(self, issue):
        """The block's reason, lower-cased to follow a colon."""
        message = self._block_message(issue).split(', so ')[0].rstrip('.') + '.'
        first = message.split(' ', 1)[0]
        return message[0].lower() + message[1:] if first in {'A', 'An', 'This', 'No'} else message

    def _policy_facts(self, issue):
        """The service's other booking rules the caller does not yet meet."""
        service = self.r.engine._appointment_type()
        facts = self.r.engine.state.patient_facts
        if not service or issue.get('code') in {'referral_required', 'new_patient_type_restricted'}:
            return ''
        notes = []
        if service.requires_referral and facts.referral_on_file is not True:
            notes.append('It also needs a referral on file.')
        if not service.new_patients_allowed and facts.is_new_patient is not False:
            notes.append('It is only for existing patients.')
        return ' '.join(notes)

    def _bookable(self, service):
        """The caller meets this service's own rules (new patients, referral)."""
        facts = self.r.engine.state.patient_facts
        return ((service.new_patients_allowed or facts.is_new_patient is not True)
                and (not service.requires_referral or facts.referral_on_file is True))

    def _services_for(self, providers):
        """Services the caller can book with these providers, new-patient visits first."""
        catalog = self.r.engine.catalog
        ids = dict.fromkeys(i for p in providers for i in p.appointment_type_ids)
        services = [catalog.appointment_types_by_id[i] for i in ids if self._bookable(catalog.appointment_types_by_id[i])
                    and any(self._capable(catalog.appointment_types_by_id[i], catalog.locations_by_id[l])
                            for p in providers if i in p.appointment_type_ids for l in p.location_ids)]
        new = self.r.engine.state.patient_facts.is_new_patient is True
        return sorted(services, key=lambda t: (not (new and 'new patient' in t.name.lower()),
                                               'consultation' not in t.name.lower()))

    def _new_patient_alternative(self, provider, service, *, said=False):
        """For a new patient: a new-patient visit with this provider, else with
        providers of the same specialty, else with any provider accepting them."""
        catalog = self.r.engine.catalog
        label = lambda p: self.provider_name(p) + ' in ' + p.specialty
        if provider and provider.accepting_new_patients:
            visits = self._services_for([provider])
            if visits:
                self._offer(services=visits[:1], providers=[provider])
                return (f'As a new patient, you could book {spoken_service(visits[0])} '
                        f'with {self.provider_name(provider)} instead.')
        lead = (f'{self.provider_name(provider)} is not accepting new patients. '
                if provider and not provider.accepting_new_patients and not said else '')
        specialty = provider.specialty if provider else None
        if not specialty and service:
            offering = [p for p in catalog.providers if service.id in p.appointment_type_ids]
            specialty = offering[0].specialty if offering else None
        primary = sorted(catalog.providers, key=lambda p: p.specialty not in PRIMARY_CARE)
        for pool in ([p for p in catalog.providers if p.specialty == specialty], primary):
            pool = [p for p in pool if p.accepting_new_patients and (not provider or p.id != provider.id)]
            for visit in self._services_for(pool):
                if 'new patient' not in visit.name.lower():
                    continue
                who = [p for p in pool if visit.id in p.appointment_type_ids][:3]
                if who:
                    self._offer(services=[visit], providers=who)
                    return (lead + f'As a new patient, you could book {spoken_service(visit)} with '
                            f'{spoken_list(label(p) for p in who)}.')
        return lead.strip()

    def _offer(self, *, services=(), providers=(), locations=()):
        """Records what a block offers, so a yes to it accepts that alternative: a field is
        set only when exactly one option was offered for it."""
        one = lambda items: items[0].id if len(items) == 1 else None
        self.r.block_offer = {'service': one(list(services)), 'provider': one(list(providers)),
                              'location': one(list(locations))}
        self.offered = (list(services), list(providers), list(locations))
        self.r.block_offer_options = {'service': [s.id for s in services], 'provider': [p.id for p in providers],
                                      'location': [l.id for l in locations]}

    def _block_options(self, issue):
        """The valid alternatives for a block, from the catalog."""
        engine = self.r.engine; catalog = engine.catalog
        service, provider, site = engine._appointment_type(), engine._provider(), engine._location()
        code = issue.get('code')
        self._choosable = True
        self.r.block_offer, self.offered = {}, ([], [], [])
        self.r.block_offer_options = {}
        if not service:
            return ''
        label = lambda p: self.provider_name(p) + ' in ' + p.specialty
        spoken = spoken_service(service)
        Spoken = spoken[0].upper() + spoken[1:]
        if code == 'provider_not_at_location' and provider and site:
            capable = [catalog.locations_by_id[i] for i in provider.location_ids
                       if self._capable(service, catalog.locations_by_id[i])]
            sites = [l.name for l in capable]
            others = [label(p) for p in self._offering(service, site=site) if p.id != provider.id]
            if not others:
                self._offer(locations=capable)  # Only the provider's own sites are offered.
            text = f'{self.provider_name(provider)} practices at {spoken_list(sites)}.' if sites else ''
            if others:
                text += f' At {site.name}, {spoken} is offered by {spoken_list(others[:3])}.'
            return text.strip()
        if code == 'location_missing_capability':
            providers = [provider] if provider and service.id in provider.appointment_type_ids else self._offering(service)
            capable = list({i: catalog.locations_by_id[i] for p in providers for i in p.location_ids
                            if self._capable(service, catalog.locations_by_id[i])}.values())
            sites = [l.name for l in capable]
            if not sites:
                return ''
            self._offer(providers=providers if providers == [provider] else [], locations=capable)
            who = f' with {self.provider_name(provider)}' if providers == [provider] else ''
            return f'{Spoken} is available{who} at {spoken_list(sites)}.'
        if code in {'provider_does_not_offer_type', 'new_patient_provider_restricted'}:
            other_providers = [p for p in (self._offering(service, site=site) or self._offering(service))
                               if not provider or p.id != provider.id]
            others = [label(p) for p in other_providers]
            if others:
                self._offer(providers=other_providers[:3])
                return f'{Spoken} is offered by {spoken_list(others[:3])}.'
            if code == 'new_patient_provider_restricted':
                return (f'No other provider offers {spoken} to new patients. '
                        + self._new_patient_alternative(provider, service, said=True)).strip()
            return ''
        if code == 'new_patient_type_restricted':
            return self._new_patient_alternative(provider, service)
        if code == 'no_provider_at_location':
            providers = self._offering(service)
            capable = list({i: catalog.locations_by_id[i] for p in providers for i in p.location_ids
                            if self._capable(service, catalog.locations_by_id[i])}.values())
            if not capable:
                return ''
            self._offer(providers=providers[:1] if len(providers) == 1 else [], locations=capable)
            who = f' with {self.provider_name(providers[0])}' if len(providers) == 1 else ''
            return f'{Spoken} is available{who} at {spoken_list(l.name for l in capable)}.'
        if code == 'unbookable_type_no_provider':
            # What can be booked instead: the same specialty's services that someone offers.
            others = [t for t in catalog.appointment_types if t.specialty == service.specialty and t.id != service.id
                      and self._offering(t) and self._bookable(t)][:3]
            if others:
                self._offer(services=others)
                return f'You could book {spoken_list(spoken_service(t) for t in others)} instead.'
            self._choosable = False
            return f'No other {service.specialty} service can be booked here either.'
        if code == 'referral_required':
            text = 'Once your referral is on file, you can book it.'
            others = [t for t in self._services_for([provider]) if t.id != service.id][:2] if provider else []
            self._choosable = bool(others)
            if others:
                    self._offer(services=others, providers=[provider])
                    text += (f' Without a referral, {self.provider_name(provider)} also offers '
                             f'{spoken_list(spoken_service(t) for t in others)}.')
            return text
        return ''

    def _blocked_contact(self, issue):
        """The phone of a site that can actually provide the service, when known."""
        catalog, engine = self.r.engine.catalog, self.r.engine
        ids = [a.get('location_id') or a.get('id') for a in issue.get('alternatives', []) if isinstance(a, dict)]
        ids = ids or [site.id for site in self.offered[2]]  # A site this reply offers can provide it.
        service = engine._appointment_type()
        if not ids and issue.get('code') == 'location_missing_capability' and service:
            needed = issue.get('required_capability')
            ids = [l.id for l in catalog.locations if needed in l.capabilities and any(
                service.id in p.appointment_type_ids and l.id in p.location_ids for p in catalog.providers)]
        site = next((catalog.locations_by_id[i] for i in ids if i in catalog.locations_by_id), None)
        if not site and issue.get('code') != 'location_missing_capability':
            provider = engine._provider()
            offering = [l for p in catalog.providers if service and service.id in p.appointment_type_ids
                        for l in p.location_ids]
            site = engine._location() or (catalog.locations_by_id[provider.location_ids[0]] if provider else
                                          catalog.locations_by_id[offering[0]] if offering else None)
        if site:
            self.phone_given = True
            return f' You can call {site.name} at {spoken_phone(site.phone)}.'
        return self.contact()

    # -- One reply -------------------------------------------------------------

    def compose(self, results, *, booking=None):
        """One reply, then the loop breaker: the second turn in a row without progress
        re-asks in one short closed question; the third ends the call with the clinic's
        phone (never the emergency message)."""
        previous = self.last_text
        parts = self._compose(results, booking=booking)
        return self._break_loops(results, booking, parts, previous)

    def _progress_signature(self, parts):
        """What the reply asks. A block's escalation step (full, plain rule, phone) is part
        of it, so each new step is progress; the reminders after the phone are not."""
        q = self.r.question
        block = (self.last_block, min(self.block_shown.get(self.last_block, 0), 3)) if self._block_now else None
        return ((q.kind, q.field) if q else None, block)

    def _break_loops(self, results, booking, parts, previous):
        text, proposals, presentations, question = parts
        effects = [e for result in results for e in result.effects]
        if self.r.control == 'urgent' or self.end_call or not self.loop_breaker:
            return parts
        neutral = (question is None or self.r.control == 'paused'
                   or any(e['kind'] in {'repeat_request', 'pause'} for e in effects)
                   or (any(e['kind'] == 'information_question' for e in effects) and self.last_info_answered))
        signature = self._progress_signature(parts)
        offered = self._offer_contents(proposals, presentations)
        progress = (bool(self.r.last_turn_changed) or bool(booking) or bool(offered - self._offers_seen)
                    or signature != self._last_signature)
        self._offers_seen |= offered
        self._last_signature = signature
        if self.r.control == 'human':
            # The honest "I cannot transfer" is progress once; said again, it is a stall.
            self._handoffs += 1
            neutral, progress = False, self._handoffs == 1
        else:
            self._handoffs = 0
        if neutral and not progress:
            return parts
        self.stalled = 0 if progress else self.stalled + 1
        if self.stalled == 2:
            closed = self._closed_question(text, proposals, presentations)
            # Never the same words twice in a row; a reply that already is the short question
            # after a short lead ("Sorry, I still did not get that. ...") is kept.
            short_already = text.endswith(closed or '\0') and len(text) - len(closed) <= 40
            if closed and closed != previous and not short_already:
                self.last_text = closed
                return closed, proposals, presentations, question
        elif self.stalled >= 3:
            self.end_call, self.end_reason = True, 'loop_breaker'
            final = self._final_message()
            self.last_text = final
            return final, (), (), None
        return parts

    def _offer_contents(self, proposals, presentations):
        """What is offered, by content: the same options asked again under a new ID
        are not a new offer."""
        r = self.r
        lists = {('list', p.entity, tuple(p.option_ids)) for p in (r.presentations.get(i) for i in presentations) if p}
        readbacks = {('readback', p.kind, p.slot_id) for p in (r.proposals.get(i) for i in proposals) if p}
        return lists | readbacks

    def _closed_question(self, text, proposals, presentations):
        """The pending question as one short closed question."""
        r = self.r
        if r.question and r.question.kind == 'blocked':
            return ('Would you like one of those instead?' if self.last_block_options
                    else 'Is there anything else I can help with?')
        if proposals:
            proposal = r.proposals.get(proposals[0])
            if proposal and proposal.kind == 'booking':
                return CONSENT_QUESTION
            if proposal and proposal.kind == 'identity':
                return 'Is that name and date of birth right?'
        if presentations and presentations[0] in r.presentations:
            labels = self.short_labels(r.presentations[presentations[0]])
            if len(labels) > 1:
                return 'Which one: ' + ', '.join(labels[:-1]) + ' or ' + labels[-1] + '?'
        sentences = [part.strip() for part in re.split(r'(?<=[.?!])\s+', text) if part.strip()]
        return sentences[-1] if sentences and sentences[-1].endswith('?') else None

    def _final_message(self):
        """One sentence, no question: where to call, and what was asked if a request
        was in progress. The call then ends."""
        engine, catalog = self.r.engine, self.r.engine.catalog
        service, provider, site = engine._appointment_type(), engine._provider(), engine._location()
        if not site and provider:
            site = catalog.locations_by_id[provider.location_ids[0]]
        if not site and service:
            site = next((catalog.locations_by_id[l] for p in catalog.providers
                         if service.id in p.appointment_type_ids for l in p.location_ids), None)
        site = site or catalog.locations[0]
        summary = ''
        if service:
            summary = (f' You asked for {spoken_service(service)}'
                       + (f' with {self.provider_name(provider)}' if provider else '')
                       + ('' if engine.bookings[self.r.bookings_before_request:] else ', and nothing is booked') + '.')
        return (f"I'm sorry I could not finish this on the call.{summary} Please call {site.name} at "
                f'{spoken_phone(site.phone)}. Thank you for calling, goodbye.')

    def _compose(self, results, *, booking=None):
        self._alternative_times = False
        self._reason_given = False
        # In one turn of several fragments, a request after a goodbye ("okay, thanks ...
        # but can I see her for a hearing test instead") wins: compose from what follows.
        ending = {'closing', 'block_declined', 'acknowledge'}
        last_end = max((i for i, result in enumerate(results)
                        if any(e['kind'] in {'closing', 'block_declined'} for e in result.effects)), default=None)
        if last_end is not None and any(
                result.status == 'accepted' and (result.resolution is not None
                                                 or any(e['kind'] not in ending for e in result.effects))
                for result in results[last_end + 1:]):
            results = results[last_end + 1:]
        self._results = results
        # An interrupted question is asked again once, in full, if this turn did not answer it.
        self._interrupted, self.interrupted_text = self.interrupted_text, None
        self._block_prev, self._block_now = self._block_now, False
        self._offered = False
        cancels = [i for i, result in enumerate(results) if any(e['kind'] == 'cancel' for e in result.effects)]
        if cancels:
            # Lookups made for the cancelled request no longer describe the call.
            results = results[cancels[-1]:]
            self.resolution = None
        effects = [effect for result in results for effect in result.effects]
        kinds = {e['kind'] for e in effects}
        if 'closing' in kinds and self.r.control != 'urgent':
            return self._never_twice([], (self._goodbye(effects), (), (), None), effects)
        if 'block_declined' in kinds:
            self.resolution = None  # The declined request's lookups no longer describe the call.
            if self.last_block_options and not any(e.get('thanks') for e in effects):
                return self._never_twice([], self._question(
                    'All right, nothing is booked. Is there anything else I can help with?', 'anything_else'), effects)
            return self._never_twice([], (self._goodbye(effects), (), (), None), effects)
        if 'readback_declined' in kinds:
            self.resolution = None
            if any(e.get('thanks') for e in effects if e['kind'] == 'readback_declined'):
                return self._never_twice([], (DECLINED_GOODBYE, (), (), None), effects)
            return self._never_twice([], self._question(DECLINED_QUESTION, 'declined_booking'), effects)
        if self.r.control in TERMINAL:
            return self._never_twice([], self._terminal_reply(results), effects)
        if self.r.control == 'paused':
            # Holds the pending question (no new question ID), but still invites the caller on.
            return self._never_twice([], ('Take your time. What would you like to check before we continue?',
                                          (), (), None), effects)
        if 'consent_unclear' in kinds:
            parts = self._consent_reask(effects)
            if parts is not None:
                return self._never_twice([], parts, effects)
        if 'more' in kinds:
            return self._never_twice([], self._question('What else can I help you with?', 'service', 'service'), effects)
        needed = next((e for e in effects if e['kind'] == 'choice_needed'), None)
        if needed and needed['presentation_id'] in self.r.presentations:
            lead = 'Which one would you like:' if (self.last_text or '').startswith('Sure,') else 'Sure,'
            return self._never_twice([], self.short_choice(self.r.presentations[needed['presentation_id']], lead), effects)
        return self._never_twice(*self._active(results, effects, booking), effects)

    def _goodbye(self, effects):
        """The one non-terminal reply without a question: the call can end. Thanks
        are answered; a plain no is thanked; a second goodbye is short."""
        if self.last_text in GOODBYES:
            return GOODBYES[3] if self.last_text == GOODBYES[2] else GOODBYES[2]
        return GOODBYES[0] if any(e.get('thanks') for e in effects) else GOODBYES[1]

    def _remember_resolution(self, results):
        for result in results:
            if result.resolution is not None:
                self.resolution = result.resolution

    def _current_resolution(self, results):
        """The resolution the reply uses: this turn's own, else the current request's
        (blocks and lookup errors are never carried over from an earlier request or turn);
        candidates still on offer from an earlier lookup are kept."""
        own = next((result.resolution for result in reversed(results) if result.resolution is not None), None)
        if own is not None:
            return own
        fresh = dict(self.r.engine.resolve_options())
        if self.resolution and self.resolution.get('candidates') and not fresh.get('candidates'):
            fresh['candidates'] = self.resolution['candidates']
        return fresh

    def _terminal_reply(self, results):
        self._remember_resolution(results)
        if self.r.control == 'urgent':
            if self.emergency_given:
                # Any further turn: one short line, then the call ends (never "To repeat:").
                self.end_call, self.end_reason = True, 'emergency'
                return EMERGENCY_AGAIN, (), (), None
            self.emergency_given = True
            return emergency_sentence(self.emergency_lead), (), (), None
        # Asked again, the same facts are repeated ("To repeat:"), never a dead end; the
        # call stays open (a new request, an okay or a yes resumes scheduling).
        return self._question(self.handoff_text() + ' Is there anything else I can help with?', 'anything_else')

    def _consent_reask(self, effects):
        """A restated read-back is not a yes: ask once, then read it back in full."""
        pid = next(e['proposal_id'] for e in effects if e['kind'] == 'consent_unclear')
        p = self.r.proposals.get(pid)
        if not (p and p.status == 'open' and self.r._current_proposal(p)):
            return None
        if self.last_text == CONSENT_QUESTION:
            return self._readback(p)
        return self._question(CONSENT_QUESTION, 'booking_consent', proposal=p)

    def _active(self, results, effects, booking):
        """Statements first (cancel, unsupported, thanks, apology), then exactly
        one forward question from the normal flow."""
        leads = self._statements(results, effects)
        forward = [replace(result, effects=tuple(e for e in result.effects if e['kind'] not in STATEMENTS))
                   for result in results]
        text, proposals, presentations, question = self._forward(forward, booking)
        if self._interrupted and text and self._interrupted.endswith(text):
            # Not the caller's fault: the question was cut off. No apology, just ask it.
            leads = [lead for lead in leads if lead != APOLOGY]
        if not text.rstrip().endswith('?'):
            follow = self._follow_up()
            text = ' '.join(part for part in (text, follow[0]) if part)
            proposals, presentations = proposals + follow[1], presentations + follow[2]
            question = follow[3] or question
        return leads, (text, proposals, presentations, question)

    def _statements(self, results, effects):
        leads = []
        if any(e['kind'] == 'cancel' for e in effects):
            leads.append('I have stopped that booking request. No appointment was booked.')
        for topic in dict.fromkeys(e['topic'] for e in effects if e['kind'] == 'unsupported'):
            text = self.unsupported_text(topic)
            if text:
                leads.append(text)
        if effects and all(e['kind'] == 'acknowledge' for e in effects) and any(
                e.get('quote') is None or THANKS.search(e['quote']) for e in effects):
            leads.append("You're welcome.")
        if self._not_understood(results):
            leads.append(APOLOGY)
        elif self.r.request_cancelled and any(e['kind'] == 'unclear' for e in effects):
            leads.append('Nothing is booked right now.')
        return leads

    def _follow_up(self):
        if self.r.request_finished():
            return 'Is there anything else I can help with?', (), (), None
        return self._next(self._current_resolution(self._results))

    def _forward(self, results, booking):
        """The turn's forward reply: a booking, a block, information, a read-back,
        a repeat, or the next question."""
        self._remember_resolution(results)
        r = self.r
        if r.control == 'cancelled':
            return 'I have stopped this booking request. No appointment was booked.', (), (), None
        if booking and booking['status'] in {'booked', 'idempotent'}:
            return self.slot_text(booking['booking']['slot_id'], booked=True), (), (), None
        effects = [effect for result in results for effect in result.effects]
        resolution = self._current_resolution(results)
        blocked = resolution.get('blocked_options', [])
        issue = next((b for b in blocked if b['code'] == 'location_missing_capability'), blocked[0]) if blocked else None
        info = list(dict.fromkeys(text for text in (self._answer(effect, issue) for effect in effects
                                                    if effect['kind'] == 'information_question') if text))
        self.last_info_answered = bool(info) and not any(part.endswith('?') for part in info)
        if blocked and self._alternative_times:
            # The caller asked about the alternatives: their times, and the same offer stands.
            return self._question(' '.join(info) + ' Would you like one of those?', 'blocked')
        if blocked:
            self._block_unclear = (any(e['kind'] == 'unclear' for e in effects)
                                   or self._not_understood(results))
            return self._question(self.blocked_text(self._block_message(issue), issue, info), 'blocked')
        if info and any(part.endswith('?') for part in info):
            # Do not create a hidden booking/identity question or proposal while
            # asking the caller to disambiguate an information target.
            return self._question(' '.join(info), 'information_clarification')
        text, proposals, presentations, question = self._forward_question(effects, info, resolution)
        text = ' '.join([*info, text]).strip()
        if self._explains_choice(results, effects, booking):
            text = self._choice_explanation(text) + text
        return text, proposals, presentations, question

    def _answer(self, effect, issue):
        """One information answer; under a block, a question about the blocked entity gets the reason."""
        reason = self._why_blocked(effect, issue) if issue else None
        if reason:
            self._reason_given = True
            return reason
        return self.info(effect)

    def _forward_question(self, effects, info, resolution):
        r = self.r
        readbacks = [r.proposals[e['proposal_id']] for e in effects if e['kind'] == 'booking_readback'
                     and r.proposals[e['proposal_id']].status == 'open' and r._current_proposal(r.proposals[e['proposal_id']])]
        if readbacks:
            return self._readback(readbacks[-1])
        if any(e['kind'] == 'repeat_request' for e in effects) and not r.engine.state.selected_slot_id:
            return self._repeat(effects, resolution)
        if r.request_finished():
            return ('Is there anything else I can help with?', (), (), None) if not info else ('', (), (), None)
        return self._next(resolution)

    def _repeat(self, effects, resolution):
        r = self.r
        repeat = next(e for e in reversed(effects) if e['kind'] == 'repeat_request')
        text = self.message_text.get(repeat['message_id'])
        if not text:
            return self._next(resolution)
        reference = r.messages.get(repeat['message_id'])
        presentation = r.presentations.get(reference[1]) if reference and reference[0] == 'presentation' else None
        if (presentation and presentation.entity == 'slot' and repeat.get('part') in {'date', 'time'}
                and presentation is r.open_choice()):
            return self.short_choice(presentation, with_time=True)  # "What time was that?": the times.
        return text, (), (presentation.id,) if presentation else (), r.question.id if r.question else None

    def _explains_choice(self, results, effects, booking):
        """An unclear answer to an ambiguous provider choice gets the facts again."""
        return (self.r.control == 'active' and not booking
                and not any(result.status == 'rejected' for result in results)
                and any(effect['kind'] == 'unclear' for effect in effects)
                and self.r.question and self.r.question.kind == 'provider_choice' and not self._offered)

    def _choice_explanation(self, text):
        r = self.r
        known = []
        if r.engine._appointment_type():
            known.append('You asked for ' + SchedulingDialogue.spoken_service(r.engine._appointment_type().name))
        new = r.engine.state.patient_facts.is_new_patient
        if new is not None:
            known.append('you are a ' + ('new' if new else 'returning') + ' patient')
        intro = ' and '.join(known) + '. ' if known else ''
        if 'closest catalog matches' not in text:
            intro += 'There is more than one provider with that name. '
        return intro

    def _short_reask(self, text, proposals, presentations):
        """The reply with its repeated question in short form, or None to keep it.
        Only the repeated list or read-back is shortened; an answer said before it stays."""
        r = self.r
        if r.question and r.question.kind == 'blocked':
            return None  # Blocks shorten themselves (blocked_text).
        if proposals:
            proposal = r.proposals.get(proposals[0])
            canonical = self.readbacks.get(proposals[0])
            short = (CONSENT_QUESTION if proposal and proposal.kind == 'booking'
                     else 'Is that name and date of birth right?' if proposal and proposal.kind == 'identity' else None)
            if short and canonical and canonical in text:
                return text.replace(canonical, short)
        if presentations and presentations[0] in r.presentations:
            labels = self.short_labels(r.presentations[presentations[0]])
            canonical = self.message_text.get(presentations[0])
            if len(labels) > 1 and canonical and canonical in text:
                question = ', '.join(labels[:-1]) + ' or ' + labels[-1] + '?'
                return text.replace(canonical, question[0].upper() + question[1:])
        sentences = [part.strip() for part in re.split(r'(?<=[.?!])\s+', text) if part.strip()]
        return sentences[-1] if len(sentences) > 1 and sentences[-1].endswith('?') else None

    STALE = {'stale_presentation', 'stale_question', 'stale_proposal'}

    def _not_understood(self, results):
        """A rejected fragment earns an apology, unless another fragment of the same turn
        was understood and the rejected one only pointed at a choice or question that the
        turn had already answered ("yes" then "book that")."""
        rejected = [result for result in results if result.status == 'rejected']
        if not rejected:
            return False
        understood = any(result.status == 'accepted' for result in results)
        return not (understood and all(set(result.errors) <= self.STALE for result in rejected))

    def _never_twice(self, leads, parts, effects):
        """Invariant: no reply is sent twice in a row, except a canonical
        read-back that the caller asked to hear again."""
        text, proposals, presentations, question = parts
        body, self.last_body = text, text
        recent = self._recent_bodies
        side_question = any(e['kind'] == 'information_question' for e in effects)
        # The same reply as the previous one, or a choice list asked in the last few replies
        # (not after a side question, which gets the list once in full; never a read-back,
        # which consent needs in full).
        said = bool(recent) and (body == recent[-1] or (
            body in recent and presentations and not proposals and not side_question
            and not self.r.last_turn_fields))  # A list from earlier, after a change, is said in full.
        if (text and said and question is not None
                and not any(e['kind'] == 'repeat_request' for e in effects)
                and not (self._interrupted is not None and text == self._interrupted)):
            # A long question already asked in the last replies: ask it in short form,
            # after keeping what the caller just said ("Got it.") or saying it was not understood.
            short = self._short_reask(text, proposals, presentations)
            if short:
                text = short
            if not leads:
                leads = ([APOLOGY] if any(e['kind'] == 'unclear' for e in effects)
                         else ['Got it.'] if self.r.last_turn_fields
                         else ['All right.'] if any(e['kind'] == 'acknowledge' for e in effects) else [])
        self._recent_bodies = (recent + [body])[-4:]
        say = lambda statements: ' '.join([*statements, text]).strip()
        reply = say(leads)
        if not reply:
            return parts
        canonical = reply
        repeated_readback = bool(proposals) and any(e['kind'] == 'repeat_request' for e in effects)
        reasked = self._interrupted is not None and reply == self._interrupted
        if reply == self.last_text and not repeated_readback and not reasked:
            if APOLOGY in leads:
                reply = canonical = say([STILL if lead == APOLOGY else lead for lead in leads])
            else:
                lead = ('I am still here.' if self.r.control == 'paused'
                        else 'Sorry, I did not catch that.' if any(e['kind'] == 'unclear' for e in effects)
                        else REPEAT_LEADS[0])
                reply = say([lead, *leads])
                if reply == self.last_text:
                    lead = REPEAT_LEADS[1]
                    reply = say([lead, *leads])
                if lead not in REPEAT_LEADS:
                    canonical = reply
        self.last_text, self.last_canonical = reply, (reply, canonical)
        return reply, proposals, presentations, question
