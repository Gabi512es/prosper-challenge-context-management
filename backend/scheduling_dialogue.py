"""Shared transcript-grounded consent and deterministic booking speech."""
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from pipecat.frames.frames import (TranscriptionFrame, LLMTextFrame,
    LLMFullResponseStartFrame, LLMFullResponseEndFrame, InterruptionFrame,
    FunctionCallsStartedFrame, BotStartedSpeakingFrame, BotStoppedSpeakingFrame, DataFrame)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection


# A repeat request must be the WHOLE utterance, not a word found anywhere in
# it: "pardon" and "sorry" are common interjections inside a real selection
# or correction ("Sorry, can we do Richmond instead?"), the same class of bug
# as matching "ENT" inside "patient". An optional leading "sorry" plus one
# recognized repeat phrase, with only trailing punctuation after, is the only
# shape that counts.
REPEAT_REQUEST_RE = re.compile(
    r"""^\s*
    (?:sorry[,.]?\s*)?
    (?:
        what\s+did\s+you\s+say
      | (?:could|can)\s+you\s+(?:please\s+)?
            (?:repeat(?:\s+(?:that|it))?|say\s+(?:that|it)\s+again)(?:\s+please)?
      | say\s+(?:that|it)\s+again(?:\s+please)?
      | repeat(?:\s+(?:that|it))?(?:\s+please)?
      | come\s+again
      | pardon(?:\s+me)?
      | sorry
    )
    \s*[?.!,]*\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Last-resort speech for a final response with no tool calls. Never consent.
REPEAT_FALLBACK = "Sorry, I didn't catch that. Could you repeat that, please?"
CONSENT_VETO = re.compile(
    r"\b(?:no|nope|not|never|don't|dont|cannot|can't|wrong|wait|stop|change|actually|instead|but|except)\b",
    re.I,
)


@dataclass
class ReadbackDeliveredFrame(DataFrame):
    """Ordered behind the read-back's audio, never an early speaking/VAD event."""
    token: int


class ReadbackDelivery(FrameProcessor):
    """Acknowledge only after TTS and the transport's ordered audio queue."""
    def __init__(self, dialogue):
        super().__init__()
        self.d = dialogue

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, ReadbackDeliveredFrame):
            if direction == FrameDirection.DOWNSTREAM:
                self.d.complete_readback(frame.token)
            return
        await self.push_frame(frame, direction)


class SchedulingDialogue:
    def __init__(self, engine):
        self.engine = engine
        self.patient_text = ""
        self.location = None
        self.specialty = None
        self.readback = None
        self.pending = None
        self.waiting = False
        self.location_conflict = None
        self.identity_confirmed = None
        self.identity_readback = None
        self.delivery_serial = 0
        self.delivery_pending = None
        self.location_intent_question = None
        self.location_intent_stage = None
        self.global_soonest = False
        self.location_clarifications = 0
        self.last_code_question = None
        self.question_history = deque(maxlen=6)
        self.question_attempts = {}
        self.last_question_key = None
        self.patient_turn = 0
        self.stage = "service"
        self.partial_birth_date = None
        self.catalog_answer = False
        self.last_resolution = None
        # The last spoken multi-slot offer, with its service/provider/site
        # context. It is durable dialogue state: an interruption or a side
        # question must never roll the conversation back behind this choice.
        self.slot_options = None
        self.repeat_requested = False
        self.cancelled = False
        self.handed_off = False
        self._request_key = self.request_key()

    def request_key(self):
        state = self.engine.state
        facts = state.patient_facts
        return (state.appointment_type_id, state.provider_id, state.location_id,
                state.any_provider, state.any_location, facts.name, facts.date_of_birth,
                facts.is_new_patient, facts.referral_on_file)

    def sync_request(self):
        """Retire derived dialogue together when authoritative request facts change."""
        current = self.request_key()
        if current == self._request_key:
            return
        identity_changed = current[5:7] != self._request_key[5:7]
        birthday_changed = current[6] != self._request_key[6]
        request_changed = current[:3] != self._request_key[:3]
        self._request_key = current
        self.pending = self.slot_options = self.readback = self.identity_readback = None
        self.delivery_pending = None
        self.last_resolution = self.last_code_question = None
        self.question_history.clear()
        self.question_attempts.clear()
        self.last_question_key = None
        if request_changed and not (current[3] or current[4]):
            self.global_soonest = False
        self.catalog_answer = self.waiting = self.repeat_requested = False
        self.location_conflict = self.location_intent_question = self.location_intent_stage = None
        self.location_clarifications = 0
        self.stage = "service"  # Recomputed from current facts by next_step.
        if identity_changed:
            self.identity_confirmed = None
            self.engine._invalidate_slot_choice()
            if birthday_changed and current[6] is not None:
                self.partial_birth_date = None

    def next_step(self):
        """Single ordered source for the next missing slot; engine owns facts."""
        self.sync_request()
        if not self.engine.bookings:
            self.repair_provider_location()
            self.select_only_site()
        state = self.engine.state
        if self.cancelled:
            stage, question = "cancelled", "Okay, I won't book that. Let me know if you'd like to start again."
        elif self.engine.bookings:
            stage, question = "complete", None
        elif not state.appointment_type_id:
            stage, question = "service", "What appointment service do you need?"
        elif not state.provider_id and not state.any_provider:
            stage, question = "provider", "Which provider would you like, or is any eligible clinician fine?"
            resolution = self.last_resolution or {}
            candidates = [c for c in resolution.get("candidates", []) if c["entity"] == "provider"]
            if candidates:
                if any(c.get("requires_confirmation") for c in candidates):
                    question = "Did you mean " + " or ".join(dict.fromkeys(c["name"] for c in candidates)) + "?"
                else:
                    question = "Which provider did you mean: " + "; ".join(f"{c['name']}, {c['specialty']} ({c['title']})" for c in candidates) + "?"
            elif any(e["entity"] == "provider" for e in resolution.get("errors", [])):
                question = "I couldn't find a provider with that name. Could you repeat or spell the first name and surname?"
        elif (not state.location_id and not state.any_location) or self.location_conflict or self.location_intent_question:
            stage, question = "location", self.location_conflict or self.location_intent_question or self.site_choices()
        elif self.engine._policy_issues():
            issues = self.engine._policy_issues()
            blocked = [i for i in issues if i["kind"] == "blocked"]
            stage = "eligibility"
            question = self.capability_message({"issues": issues}) if blocked else None
            if not question:
                question = ("This request is blocked: " + ", ".join(i["code"].replace("_", " ") for i in blocked) + ". Would you like to change the service or provider?" if blocked
                            else "Please confirm " + ", ".join(i["field"].replace("_", " ") for i in issues) + ".")
        elif self.partial_birth_date or not all(self.identity()):
            stage = "identity"
            question = ("What year were you born?" if self.partial_birth_date else
                        "What is your full name?" if not self.identity()[0] and self.identity()[1] else
                        "What is your date of birth?" if self.identity()[0] else "What is your full name and date of birth?")
        elif self.identity_confirmed != self.identity():
            stage, question = "identity_confirmation", self.identity_message()
        elif state.selected_slot_id and state.confirmation is None:
            stage, question = "consent", None
        elif self.slot_options and state.offered_slot_ids:
            # A pending slot choice survives interruptions and side questions.
            # The engine clears offered_slot_ids whenever constraints change,
            # which retires a stale choice here automatically.
            stage, question = "slot_choice", self.slot_options
        else:
            stage, question = "offer", None
        self.stage = stage
        return {"stage": stage, "question": question}

    def repair_provider_location(self):
        provider = self.engine._provider()
        location_id = self.engine.state.location_id
        if not provider or not location_id or location_id in provider.location_ids:
            return False
        # A stale/information-only site must not turn a valid provider request
        # into a refusal. Clear it through normal invalidation, never pick a site.
        self.engine.resolve_options({"location_id": None})
        self.sync_request()
        self.location_conflict = None
        self.slot_options = None
        names = [self.engine.catalog.locations_by_id[i].name for i in provider.location_ids]
        sites = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        self.location_intent_question = (f"{provider.name} ({provider.specialty}) practices at {sites}. "
                                         "Which would you prefer?")
        self.location_intent_stage = "provider_sites"
        return True

    def select_only_site(self):
        state = self.engine.state
        if not (state.provider_id and state.appointment_type_id) or state.location_id:
            return False
        sites = self.engine.eligible_locations()
        if len(sites) != 1:
            return False
        self.engine.resolve_options({'location_id': sites[0]['id']})
        self.sync_request()
        return True

    def booking_gate(self):
        step = self.next_step()
        if self.cancelled:
            return {"status": "cancelled", "technical_failure": False, "next_action": "wait_for_patient"}
        if step["stage"] in {"offer", "slot_choice", "consent", "complete"}:
            return None
        if step["stage"] in {"identity", "identity_confirmation"}:
            return self.require_identity()
        self.pending = ("message", step["question"])
        return {"status": "clarify", "technical_failure": False, "dialogue_step": step}

    def identity_message(self):
        name, birthday = self.identity()
        dob = datetime.fromisoformat(birthday).strftime("%B %d, %Y").replace(" 0", " ")
        return f"{name}, born {dob}, is that right?"

    def capture_identity_segment(self, text):
        # Bounded English month/day fragments; no invented year or inferred DOB.
        months = "January February March April May June July August September October November December".split()
        match = re.fullmatch(r"\s*(?:My name is )?([A-Za-z][A-Za-z' -]+),\s*(" + "|".join(months) +
                             r")\s+(\d{1,2})(?:st|nd|rd|th)?[.! ]*", text, re.I)
        if match:
            try:
                datetime(2000, months.index(match[2].title()) + 1, int(match[3]))
            except ValueError:
                return
            self.engine.resolve_options({"name": match[1].strip()})
            self.partial_birth_date = (months.index(match[2].title()) + 1, int(match[3]))
            self.identity_confirmed = None
        elif self.partial_birth_date and re.fullmatch(r"\s*\d{4}[.! ]*", text):
            year = int(re.search(r"\d{4}", text)[0])
            try:
                birthday = datetime(year, *self.partial_birth_date).date()
            except ValueError:
                return
            if birthday <= self.engine.now.date():
                self.engine.resolve_options({"date_of_birth": birthday.isoformat()})
                self.partial_birth_date = None
                self.identity_confirmed = None

    def location_reply(self, text):
        """Only explicit yes to a scope-change question is handled here."""
        if self.location_intent_stage == "widen" and self.is_affirmative(text):
            self.engine.state.hard_constraints.difference_update({"provider", "provider_id", "location", "location_id"})
            self.enable_global_soonest()

    def offer_options(self, slots):
        """Render a multi-slot choice with its service/provider/site context.

        The context is stated once; per-slot location or provider is repeated
        only when it differs between the offered slots.
        """
        providers = list(dict.fromkeys(slot["provider"] for slot in slots))
        locations = list(dict.fromkeys(slot["location"] for slot in slots))
        rendered = []
        for slot in slots:
            start = datetime.fromisoformat(slot["start"])
            item = (start.strftime("%A %B %d").replace(" 0", " ")
                    + " at " + start.strftime("%I:%M %p").lstrip("0"))
            if len(locations) > 1:
                item += f" at {slot['location']}"
            if len(providers) > 1:
                item += f" with {slot['provider']}"
            rendered.append(item)
        service = re.sub(r"^an? ", "", self.spoken_service(slots[0]["service"]))
        context = f"For your {service}"
        if len(providers) == 1:
            context += f" with {providers[0]}"
        if len(locations) == 1:
            context += f" at {locations[0]}"
        provider = self.engine._provider()
        if provider and len(providers) == len(locations) == 1 and len(self.engine.eligible_locations()) == 1:
            practice = (f"only practices at {locations[0]}" if len(provider.location_ids) == 1
                        else f"has one eligible site for this service: {locations[0]}")
            context = f"For your {service}, {provider.name} ({provider.specialty}) {practice}. There"
        connector = " I have " if context.endswith('. There') else ", I have "
        self.slot_options = (context + connector + " or ".join(rendered)
                             + ". Which works for you?")
        return self.slot_options

    def mentions_offered_slot(self, text):
        """True when the text already presents one of the offered slots."""
        for slot_id in self.engine.state.offered_slot_ids:
            slot = self.engine._slots.get(slot_id)
            if slot is None:
                continue
            day = re.search(
                rf"\b{slot.start.strftime('%B')}\s+{slot.start.day}(?:st|nd|rd|th)?\b",
                text, re.I)
            hour = int(slot.start.strftime("%I"))
            minute = slot.start.strftime("%M")
            time = re.search(rf"\b{hour}(?::{minute})?\s*(?:a\.?m\.?|p\.?m\.?|o'clock)\b", text, re.I)
            if day and time:
                return True
        return False

    def site_choices(self):
        names = [item["name"] for item in self.engine.eligible_locations()]
        if names:
            return "Eligible sites are " + ", ".join(names[:4]) + ". Which would you prefer?"
        return "Please confirm the provider and service so I can list their eligible sites."

    def set_location_preference(self, preference):
        if preference not in {"time", "place", "unclear"}:
            return {"status": "clarify", "code": "invalid_location_preference",
                    "message": "location_preference must be time, place or unclear"}
        if self.engine.state.location_id:
            self.location_intent_question = None
            self.location_intent_stage = None
            return None
        if preference == "time":
            if self.engine.state.hard_constraints.intersection({"provider", "provider_id", "location", "location_id"}):
                self.location_intent_question = "May I widen your provider and location constraints to find the soonest eligible appointment?"
                self.location_intent_stage = "widen"
            else:
                self.enable_global_soonest()
        elif preference == "place":
            self.location_intent_stage = "place"
            self.location_intent_question = "I can't tell which clinic is nearest. " + self.site_choices()
        else:
            self.location_clarifications += 1
            self.location_intent_stage = "meaning"
            self.location_intent_question = ("Do you mean the soonest appointment in time, or the nearest clinic geographically?"
                if self.location_clarifications == 1 else self.site_choices())
        return None

    def avoid_repeated_question(self, text):
        if not text or not text.strip():
            return self.empty_reply()
        # These are protocol messages, not unanswered-question strategies.
        # Never rewrite their question, replace them with a phone, or append a
        # second copy. BookingSpeech owns the one canonical presentation.
        if (all(self.identity()) and text == self.identity_message()) or (self.engine.state.selected_slot_id and
                text == self.render(self.engine._present_slot(
                    self.engine._slots[self.engine.state.selected_slot_id]))):
            return text
        if re.search(r"\bmissing details?\b", text, re.I):
            text = self.missing_detail_question()
        repeated = text in self.question_history
        if "?" in text or repeated:
            step = self.next_step()
            key = (step['stage'], self.identity(), self.partial_birth_date,
                   self.engine.state.selected_slot_id, tuple(sorted(self.engine.state.offered_slot_ids)))
            if step['stage'] == 'slot_choice' and not repeated and text != self.slot_options:
                # A useful side answer already contains or precedes one valid
                # offer. Preserve it; it is not an unanswered choice attempt.
                self.last_code_question = text
                self.question_history.append(text)
                return text
            attempts, last_turn = self.question_attempts.get(key, (0, None))
            unanswered = attempts
            if last_turn != self.patient_turn:
                attempts += 1
            self.question_attempts[key] = (attempts, self.patient_turn)
            self.last_question_key = key
            if repeated or attempts > 1:
                help_requested = self.handoff_requested() or bool(re.search(
                    r"\b(?:help me|(?:can|could) you help|I need help|I want help)\b", self.patient_text, re.I))
                contacts = self.engine._clinic_contacts() if (unanswered >= 3 and last_turn != self.patient_turn) or help_requested else []
                if contacts:
                    text = (f"You can call {contacts[0]['location']} at {contacts[0]['phone']} for help choosing. "
                            "Would you like that number repeated?")
                elif step['stage'] == 'slot_choice' and self.slot_options:
                    text = ('To continue, please pick one of these. ' if attempts % 2 == 0 else
                            'Please tell me which date and time you prefer. ') + self.slot_options
                else:
                    missing = self.missing_detail_question()
                    text = ('To continue, ' if attempts % 2 == 0 else 'I still need your answer: ') + missing
        if text == self.last_code_question:
            if self.stage == 'slot_choice' and self.slot_options:
                text = ('To continue, please pick one of these. ' if not text.startswith('To continue') else
                        'Please tell me which date and time you prefer. ') + self.slot_options
            else:
                text = ('To continue, ' if not text.startswith('To continue') else 'I still need your answer: ') + self.missing_detail_question()
        self.last_code_question = text if '?' in text else None
        self.question_history.append(text)
        return text

    def missing_detail_question(self):
        """Name the actual missing field or decision, never an unnamed detail."""
        stage = self.next_step()["stage"]
        if stage == "identity":
            if self.partial_birth_date:
                return "What year were you born?"
            missing = [label for label, value in zip(("full name", "date of birth"), self.identity()) if not value]
            return "Please provide your " + " and ".join(missing) + "."
        return {
            "identity_confirmation": "Please confirm whether the name and date of birth I read back are correct.",
            "service": "Which appointment service would you like?",
            "provider": "Which provider would you like, or is any eligible provider fine?",
            "location": "Please choose a clinic. " + self.site_choices(),
            "eligibility": self.next_step()["question"],
            "slot_choice": "Which of the offered appointment dates and times would you like?",
            "consent": "May I book the appointment I just read back?",
            "offer": "Would you like me to search for available appointments now?",
            "complete": "Is there anything else I can help with?",
        }[stage]

    def empty_reply(self):
        if self.engine.bookings:
            return self.render(self.engine.bookings[-1], booked=True)
        return REPEAT_FALLBACK

    def enable_global_soonest(self):
        self.global_soonest = True
        self.location = None
        self.location_conflict = None
        self.location_intent_question = None
        self.location_intent_stage = None
        self.engine.resolve_options({"any_provider": True, "any_location": True})

    def identity(self):
        facts = self.engine.state.patient_facts
        return (facts.name, facts.date_of_birth)

    def require_identity(self):
        self.sync_request()
        if self.partial_birth_date:
            self.pending = ("message", "What year were you born?")
            return {"status": "missing_identity", "technical_failure": False, "next_action": "collect_birth_year"}
        current = self.identity()
        if self.identity_confirmed == current and all(current):
            return None
        self.engine.state.confirmation = None
        self.readback = None
        if not all(current):
            return {"status": "missing_identity", "technical_failure": False,
                    "next_action": "collect_name_and_date_of_birth"}
        message = self.identity_message()
        self.pending = ("identity", message)
        return {"status": "needs_identity_confirmation", "technical_failure": False,
                "readback": message, "next_action": "say_identity_and_wait"}

    @staticmethod
    def is_affirmative(text):
        text = text.casefold().replace("’", "'")
        if CONSENT_VETO.search(text):
            return False
        normalized = re.sub(r"[.,!?]", " ", text)
        normalized = " ".join(normalized.split())
        if re.fullmatch(r"(?:i already told you )?i want .+? please and book it", normalized):
            return True
        phrases = (r"yes|yeah|yep|sure|correct|that's (?:right|correct|fine)|that is (?:right|correct)|"
                   r"they are correct|i confirm|please do|go ahead|sounds good|book (?:it|the appointment)|"
                   r"my name and date of birth are correct")
        affirmative = re.compile(r"\b(?:" + phrases + r")\b")
        if not affirmative.search(normalized):
            return False
        remaining = affirmative.sub(" ", normalized)
        # Bounded polite/repetition wording can accompany confirmations; unknown
        # content still fails closed rather than consenting to an unseen change.
        remaining = re.sub(r"\bi already told you\b|\b(?:the|that) exact "
                           r"(?:provider|clinician|earliest|slot|location|service|date|time|and| )+\b", " ", remaining)
        remaining = re.sub(r"\b(?:please|sure|so|and|okay|you can)\b", " ", remaining)
        return not remaining.strip()

    def patient(self, text):
        self.sync_request()
        self.patient_turn += 1
        self.catalog_answer = False
        self.patient_text = text
        # Location mentions are evidence for checking this turn's tool arguments,
        # never booking updates. Do not reuse a previous turn's mention.
        self.location = None
        self.location_conflict = None
        self.specialty = None
        self.pending = None
        self.waiting = bool(re.search(r"\b(wait|stop|hold on)\b", text, re.I))
        # An explicit repeat request gets the pending choice once, verbatim.
        # The whole utterance must be a repeat request; a word match anywhere
        # in it is not enough (see REPEAT_REQUEST_RE).
        self.repeat_requested = bool(REPEAT_REQUEST_RE.fullmatch(text))
        if not self.engine.bookings and re.fullmatch(
                r"\s*(?:never\s*mind[,.! ]*)?(?:cancel\s+(?:that|it|the\s+(?:request|booking|appointment)))?[.! ]*",
                text, re.I) and re.search(r"never\s*mind|cancel", text, re.I):
            self.cancelled = True
            self.slot_options = self.readback = self.identity_readback = None
            self.delivery_pending = None
            self.question_history.clear()
            self.last_code_question = None
            self.engine._invalidate_slot_choice()
            return
        if self.cancelled and re.search(r"\b(?:book|schedule|start|continue)\b", text, re.I):
            self.cancelled = False
        # The delivered window survives STT splitting a reply into several
        # finals. A later veto cancels it; a polite fragment never erases yes.
        affirmative = self.is_affirmative(text) or bool(
            (self.readback or self.identity_readback) and re.fullmatch(r"\s*please[.!?, ]*", text, re.I))
        veto = bool(CONSENT_VETO.search(text.replace('’', "'")))
        identity_answer = self.identity_readback is not None and self.identity_confirmed != self.identity()
        if identity_answer and affirmative and self.identity_readback == self.identity():
            self.identity_confirmed = self.identity()
        elif identity_answer:
            self.identity_confirmed = None
        if self.readback and affirmative and not self.waiting and not identity_answer and self.identity_confirmed == self.identity():
            slot_id, snapshot = self.readback
            if snapshot == self.engine._current_snapshot(slot_id):
                self.engine.confirm_selected_slot()
        elif veto:
            self.engine.state.confirmation = None
        if veto:
            self.readback = self.identity_readback = None
            self.delivery_pending = None
        self.capture_identity_segment(text)
        self.location_reply(text)
        # Negated sites provide no positive conflict evidence. Multiple mentions
        # provide no unique transcript location to compare with a tool argument.
        positives = []
        for site in self.engine.catalog.locations:
            words = [w for w in site.name.split() if w.casefold() not in
                     {"health", "center", "clinic", "medical", "group", "specialty", "family", "care", "community"}]
            alias = " ".join(words)
            for match in re.finditer(r"\b" + re.escape(alias) + r"\b", text, re.I):
                clause = re.split(r"[.!?;]", text[:match.start()])[-1]
                if not re.search(r"\b(can't|cannot|won't|not|no|don't)\b", clause, re.I):
                    positives.append(site.id)
        positives = list(dict.fromkeys(positives))
        if len(positives) == 1:
            self.location = positives[0]
        from scheduling.catalog import _specialty_matches
        specialties = {provider.specialty for provider in self.engine.catalog.providers
                       if _specialty_matches(text, provider.specialty)}
        if specialties:
            self.specialty = next(iter(specialties)) if len(specialties) == 1 else None
        candidates = [item for item in self.engine.state.last_candidates
                      if item.get("entity") == "provider" and item.get("specialty") == self.specialty]
        if len(candidates) == 1 and not self.global_soonest:
            self.engine.resolve_options({"provider_id": candidates[0]["id"]})
        self.sync_request()

    def queue_readback(self, kind, value, text):
        """Generation is not delivery; the voice output queue supplies the ack."""
        self.delivery_serial += 1
        self.delivery_pending = (self.delivery_serial, kind, value, text)
        return self.delivery_serial

    def complete_readback(self, token):
        if self.delivery_pending is None or self.delivery_pending[0] != token:
            return
        _, kind, value, _ = self.delivery_pending
        self.delivery_pending = None
        if kind == 'identity' and value == self.identity():
            self.identity_readback = value
        elif kind == 'booking' and value[1] == self.engine._current_snapshot(value[0]):
            self.readback = value

    def interrupt_readback(self):
        if self.delivery_pending is not None:
            self.delivery_pending = None
            self.readback = self.identity_readback = None
            self.engine.state.confirmation = None

    def handoff_requested(self):
        text = self.patient_text.casefold().replace("’", "'")
        if re.search(r"\b(?:don't|do not|never)\s+(?:want|need|talk|speak|transfer|connect)\b", text):
            return False
        return bool(re.search(
            r"\b(?:talk|speak)\s+(?:to|with)\s+(?:a\s+|an\s+)?(?:someone|person|human|representative|staff member|real person)\b|"
            r"\b(?:want|need|request|would like)\s+(?:a\s+|an\s+)?(?:human|representative|staff member|real person)\b|\btransfer me\b",
            text)) or bool(re.fullmatch(r"\s*(?:a\s+|an\s+)?(?:real person|human|representative)(?:\s+please)?[.!? ]*", text))

    def handoff_message(self):
        contacts = self.engine._clinic_contacts()
        message = "This prototype cannot transfer calls or record a callback."
        if contacts:
            message += f" You can call {contacts[0]['location']} at {contacts[0]['phone']}."
        return message

    def authorize_transition(self, name):
        if name != "request_human_transfer":
            return True
        if not self.handoff_requested():
            return False
        self.handed_off = True
        self.pending = ("message", self.handoff_message())
        return True

    def capability_message(self, result):
        issues = result.get("blocked_options", result.get("issues", []))
        blocked = next((i for i in issues if i.get("code") == "location_missing_capability"), None)
        if not blocked:
            return None
        site = self.engine._location()
        service = self.engine._appointment_type()
        contacts = self.engine._clinic_contacts()
        message = f"{site.name} cannot provide {service.name} because it lacks {blocked['required_capability']}. "
        if any(i.get("code") == "new_patient_type_restricted" for i in issues):
            message += "This service also does not accept new patients. "
        if contacts:
            message += f"You can call {contacts[0]['location']} at {contacts[0]['phone']} to discuss options."
        else:
            message += "Would you like help finding another service?"
        return message

    def render(self, slot, booked=False):
        start = datetime.fromisoformat(slot["start"])
        date = start.strftime("%A %B %d").replace(" 0", " ")
        time = start.strftime("%I:%M %p").lstrip("0")
        if booked:
            return (f"You're all set for {start.strftime('%A')}, {start.strftime('%B %d').replace(' 0', ' ')} "
                    f"at {time} at {slot['location']}. Is there anything else I can help with?")
        return (f"I'll book {self.spoken_service(slot['service'])} with {slot['provider']} "
                f"at {slot['location']}, {date} at {time}. Shall I book it?")

    @staticmethod
    def spoken_service(name):
        parts = re.split(r"\s+-\s+", name, maxsplit=1)
        phrase = (parts[1].lower() + " " + parts[0]) if len(parts) == 2 else name
        return ("an " if phrase[0].lower() in "aeiou" else "a ") + phrase

    def prepare_booking(self, slot_id):
        identity_step = self.booking_gate()
        if identity_step:
            return identity_step
        # Revalidate against the live session and full availability, rather
        # than requiring a separate model selection or a truncated offer list.
        self.engine.find_slots(30, limit=len(self.engine._slots))
        slot = self.engine.select_slot(slot_id)
        slot = self.engine._present_slot(self.engine._slots[slot_id])
        # No consent is created here. Only a subsequent patient turn can do so.
        self.engine.state.confirmation = None
        self.readback = None
        text = self.render(slot)
        self.pending = ("prepare", slot)
        return {"status": "needs_confirmation", "technical_failure": False,
                "next_action": "say_readback_and_wait_for_patient", "slot_id": slot_id, "readback": text}


class PatientInput(FrameProcessor):
    def __init__(self, dialogue):
        super().__init__()
        self.dialogue = dialogue

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            self.dialogue.patient(frame.text)
        await self.push_frame(frame, direction)


class BookingSpeech(FrameProcessor):
    def __init__(self, dialogue, *, audio_delivery=False):
        super().__init__()
        self.d = dialogue
        self.audio_delivery = audio_delivery
        self.text = []
        self.has_tools = False
        self.response_id = None
        self.retired_responses = deque(maxlen=8)
        self.interrupted = False
        self.bot_speaking = False

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            # Delivered windows survive a later affirmative barge-in. An
            # unfinished read-back cannot authorize anything, even if its
            # cancelled transport marker arrives late.
            self.d.interrupt_readback()
            self.text = []
            self.has_tools = False
            self.interrupted = True
            if self.response_id is not None:
                self.retired_responses.append(self.response_id)
                self.response_id = None
            if self.bot_speaking and self.d.last_code_question in self.d.question_history:
                # A cut-off question may need repeating; generated is not heard.
                self.d.question_history.remove(self.d.last_code_question)
                self.d.last_code_question = None
                key = self.d.last_question_key
                if key in self.d.question_attempts:
                    count, _ = self.d.question_attempts[key]
                    self.d.question_attempts[key] = (max(0, count - 1), None)
        if isinstance(frame, BotStartedSpeakingFrame):
            self.bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.bot_speaking = False
        if isinstance(frame, LLMFullResponseStartFrame):
            self.text = []
            self.has_tools = False
            self.response_id = getattr(frame, 'response_id', None)
            self.interrupted = False
        if isinstance(frame, FunctionCallsStartedFrame):
            self.has_tools = True
        if isinstance(frame, LLMTextFrame):
            response_id = getattr(frame, 'response_id', None)
            if response_id is not None and response_id in self.retired_responses:
                return
            if response_id is not None and self.response_id not in {None, response_id}:
                return
            if self.response_id is None:
                self.response_id = response_id
            self.interrupted = False
            self.text.append(frame.text)
            return
        if isinstance(frame, LLMFullResponseEndFrame):
            response_id = getattr(frame, 'response_id', None)
            if (getattr(frame, 'interrupted', False) or
                    (response_id is not None and response_id in self.retired_responses) or
                    (response_id is not None and self.response_id not in {None, response_id}) or
                    (self.interrupted and not self.text)):
                return
            if response_id is not None:
                self.retired_responses.append(response_id)
            # False on the ordered producer frame overrides stale system flags.
            if getattr(frame, "has_tool_calls", self.has_tools):
                self.text = []
                self.has_tools = False
                await self.push_frame(frame, direction)
                return
            text = "".join(self.text)
            active = bool(self.d.engine.state.appointment_type_id or self.d.engine.state.provider_id or any(self.d.identity())) and not self.d.catalog_answer
            step = self.d.next_step() if active else {"stage": "idle", "question": None}
            if self.d.handoff_requested() or self.d.handed_off:
                # Human help takes priority over unfinished booking/identity
                # gates, including after the transition has already succeeded.
                text = self.d.handoff_message()
                if not self.d.handoff_requested():
                    text += " To continue automated scheduling, please start a new call."
                self.d.pending = None
                await self.push_frame(LLMTextFrame(text))
                self.text = []
                await self.push_frame(frame, direction)
                return
            if self.d.catalog_answer:
                # A factual side answer and its preserved choice are assembled
                # here once, never by the intermediate tool completion.
                choice = self.d.slot_options if self.d.engine.state.offered_slot_ids else None
                if choice and not self.d.mentions_offered_slot(text):
                    text = text.strip() + " " + choice
                self.d.pending = None
            elif self.d.waiting:
                text = "Of course. What would you like to change?"
                self.d.waiting = False
                self.d.pending = None
            elif step["question"]:
                spoken = text.strip()
                if step["stage"] == "slot_choice" and self.d.pending is None:
                    if self.d.repeat_requested or not spoken or step["question"] in spoken:
                        # A repeat request gets the choice once, nothing else.
                        text = step["question"]
                    elif self.d.mentions_offered_slot(spoken):
                        # Never two slot presentations in one turn: the model
                        # already named an offered slot, so nothing is appended.
                        text = spoken
                    else:
                        # A side answer first, then the choice with its context.
                        text = spoken + " " + step["question"]
                else:
                    text = step["question"]
                self.d.pending = None
            elif step['stage'] == 'consent':
                slot_id = self.d.engine.state.selected_slot_id
                text = self.d.render(self.d.engine._present_slot(self.d.engine._slots[slot_id]))
                self.d.pending = None
            elif self.d.pending:
                kind, slot = self.d.pending
                self.d.pending = None
                text = slot if kind in {"message", "identity", "options"} else self.d.render(slot, booked=kind == "booked")
            elif active and step["stage"] == "offer":
                # Never claim a check is happening: no tool ran in this turn.
                text = "Would you like me to search for available appointments now?"
            if re.search(r"hold on|connect you|staff.{0,15}follow up|someone.{0,15}reach out", text, re.I):
                contacts = self.d.engine._clinic_contacts()
                text = "No transfer or callback is recorded. " + " ".join(
                    f"You can call {c['location']} at {c['phone']}." for c in contacts[:1])
            if text and not self.d.catalog_answer and not self.d.cancelled:
                if self.d.repeat_requested and step["stage"] == "slot_choice":
                    # An explicit repeat request is never a loop: say the
                    # choice verbatim and leave the repeat history untouched.
                    self.d.repeat_requested = False
                    await self.push_frame(LLMTextFrame(text))
                    self.text = []
                    await self.push_frame(frame, direction)
                    return
                revised = self.d.avoid_repeated_question(text)
                if revised != text:
                    same_proposal = (self.d.readback and revised.startswith(
                        self.d.render(self.d.engine._present_slot(self.d.engine._slots[self.d.readback[0]])).rsplit(' Shall I book it?', 1)[0]))
                    if not same_proposal:
                        self.d.readback = None
                    same_identity = (step["stage"] == "identity_confirmation" and
                                     revised.startswith(self.d.identity_message().rsplit(", is that right?", 1)[0]))
                    self.d.identity_readback = self.d.identity() if same_identity else None
                text = revised
            if not text or not text.strip():
                text = self.d.empty_reply()
                self.d.readback = None
                self.d.identity_readback = None
            token = None
            if step['stage'] == 'identity_confirmation' and text == self.d.identity_message():
                token = self.d.queue_readback('identity', self.d.identity(), text)
            elif self.d.engine.state.selected_slot_id:
                slot_id = self.d.engine.state.selected_slot_id
                if text == self.d.render(self.d.engine._present_slot(self.d.engine._slots[slot_id])):
                    token = self.d.queue_readback('booking', (slot_id, self.d.engine._current_snapshot(slot_id)), text)
            await self.push_frame(LLMTextFrame(text))
            self.text = []
            await self.push_frame(frame, direction)
            if token is not None:
                if self.audio_delivery:
                    await self.push_frame(ReadbackDeliveredFrame(token), direction)
                else:
                    # Text mode has no audio: its complete downstream reply is
                    # the equivalent delivery boundary, not model generation.
                    self.d.complete_readback(token)
            return
        await self.push_frame(frame, direction)
