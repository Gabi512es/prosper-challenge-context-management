"""Shared transcript-grounded consent and deterministic booking speech."""
import re
from collections import deque
from datetime import datetime

from pipecat.frames.frames import (TranscriptionFrame, LLMTextFrame,
    LLMFullResponseStartFrame, LLMFullResponseEndFrame, InterruptionFrame,
    FunctionCallsStartedFrame)
from pipecat.processors.frame_processor import FrameProcessor


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
        self.location_intent_question = None
        self.location_intent_stage = None
        self.global_soonest = False
        self.location_clarifications = 0
        self.last_code_question = None
        self.question_history = deque(maxlen=6)
        self.stage = "service"
        self.partial_birth_date = None
        self.catalog_answer = False
        self.last_resolution = None
        # The last spoken multi-slot offer, with its service/provider/site
        # context. It is durable dialogue state: an interruption or a side
        # question must never roll the conversation back behind this choice.
        self.slot_options = None
        self.repeat_requested = False

    def next_step(self):
        """Single ordered source for the next missing slot; engine owns facts."""
        state = self.engine.state
        if self.engine.bookings:
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

    def booking_gate(self):
        step = self.next_step()
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
        self.slot_options = (context + ", I have " + " or ".join(rendered)
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
        # Questions and statements both enter the history: a looping canned
        # statement is as much a dead end as a looping question.
        if text not in self.question_history:
            self.last_code_question = text if "?" in text else None
            self.question_history.append(text)
            return text
        if text in self.question_history:
            step = self.next_step()
            alternatives = {
                "location": self.site_choices(),
                "identity": "Please give just the birth year." if self.partial_birth_date else "Please provide the missing name or birth date.",
                "identity_confirmation": self.identity_message().replace("is that right?", "are these details correct?") if all(self.identity()) else "Please confirm your identity.",
                "provider": "Please spell the provider's first name and surname, or say any eligible provider.",
                "service": "Please name the service you want to schedule.",
                "slot_choice": ("To continue, please pick one of these. " + self.slot_options
                                if self.slot_options else "Which of the offered times works for you?"),
            }
            alternative = alternatives.get(step["stage"], text)
            if alternative == text or alternative in self.question_history:
                contacts = self.engine._clinic_contacts()
                alternative = (f"You can call {contacts[0]['location']} at {contacts[0]['phone']} for help choosing. Would you like that number repeated?"
                               if contacts else "I couldn't narrow the request. Would you like to change the provider or service?")
            if alternative in self.question_history:
                alternative = "I need the missing detail to proceed. You can provide it or ask to speak with a person."
            if alternative == self.last_code_question:
                return ""
            text = alternative
        self.last_code_question = text
        self.question_history.append(text)
        return text

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
        text = text.casefold().replace("’", "'").strip(" .!?,")
        if re.search(r"\b(no|not|don't|wait|stop|actually|but|except)\b", text):
            return False
        normalized = re.sub(r"[.,!?]", " ", text)
        normalized = " ".join(normalized.split())
        if normalized == "yes my name and date of birth are correct":
            return True
        if re.fullmatch(r"(?:yeah|yes)(?: so)?(?: yeah| yes)?(?: you can)? book it", normalized):
            return True
        if re.fullmatch(r"yes i confirm (?:the|that) exact (?:provider|clinician|earliest|slot|location|service|date|time|and| )+ please book it", normalized):
            return True
        return bool(re.fullmatch(r"(?:yes|yeah|correct|i confirm|please book(?: it)?|that's fine|okay,? book it)(?:[, ]+(?:please|sure|book it|please book it|that exact provider, location, service, date, and time))*", text))

    def patient(self, text):
        self.catalog_answer = False
        self.patient_text = text
        self.pending = None
        self.waiting = bool(re.search(r"\b(wait|stop|hold on)\b", text, re.I))
        # An explicit repeat request gets the pending choice once, verbatim.
        # The whole utterance must be a repeat request; a word match anywhere
        # in it is not enough (see REPEAT_REQUEST_RE).
        self.repeat_requested = bool(REPEAT_REQUEST_RE.fullmatch(text))
        affirmative = self.is_affirmative(text)
        identity_answer = self.identity_readback is not None
        if identity_answer and affirmative and self.identity_readback == self.identity():
            self.identity_confirmed = self.identity()
        elif identity_answer:
            self.identity_confirmed = None
        self.identity_readback = None
        if self.readback and affirmative and not self.waiting and not identity_answer and self.identity_confirmed == self.identity():
            slot_id, snapshot = self.readback
            if snapshot == self.engine._current_snapshot(slot_id):
                self.engine.confirm_selected_slot()
        else:
            self.engine.state.confirmation = None
        self.readback = None
        self.capture_identity_segment(text)
        self.location_reply(text)
        # Negated sites are never positive selections. Multiple positive sites
        # require clarification instead of catalog iteration order choosing one.
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
            self.global_soonest = False
            self.location_intent_question = None
            self.location_intent_stage = None
            self.location_clarifications = 0
            self.location = positives[0]
            self.location_conflict = None
            self.engine.resolve_options({"location_id": self.location})
        elif len(positives) > 1:
            self.location_conflict = "Which location would you like?"
        from scheduling.catalog import _specialty_matches
        specialties = {provider.specialty for provider in self.engine.catalog.providers
                       if _specialty_matches(text, provider.specialty)}
        if specialties:
            self.specialty = next(iter(specialties)) if len(specialties) == 1 else None
        candidates = [item for item in self.engine.state.last_candidates
                      if item.get("entity") == "provider" and item.get("specialty") == self.specialty]
        if len(candidates) == 1 and not self.global_soonest:
            self.engine.resolve_options({"provider_id": candidates[0]["id"]})

    def handoff_requested(self):
        return bool(re.search(
            r"\b(?:talk|speak)\s+to\s+(?:a\s+|an\s+)?(?:someone|person|human|representative|staff member|real person)\b|"
            r"\b(?:want|need|request)\s+(?:a\s+|an\s+)?(?:human|representative|staff member|real person)\b|\btransfer me\b",
            self.patient_text, re.I)) and not bool(re.search(r"\b(?:don't|do not)\s+(?:want|need)\b", self.patient_text, re.I))

    def authorize_transition(self, name):
        if name != "request_human_transfer":
            return True
        if not self.handoff_requested():
            return False
        contacts = self.engine._clinic_contacts()
        message = "This prototype cannot connect a live transfer or record a callback."
        if contacts:
            message += f" You can call {contacts[0]['location']} at {contacts[0]['phone']}."
        self.pending = ("message", message)
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
    def __init__(self, dialogue):
        super().__init__()
        self.d = dialogue
        self.text = []
        self.has_tools = False

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            # Interruption frames carry no semantics. PatientInput decides
            # consent from the transcript, including affirmative barge-in.
            self.text = []
        if isinstance(frame, LLMFullResponseStartFrame):
            self.text = []
            self.has_tools = False
        if isinstance(frame, FunctionCallsStartedFrame):
            self.has_tools = True
        if isinstance(frame, LLMTextFrame):
            self.text.append(frame.text)
            return
        if isinstance(frame, LLMFullResponseEndFrame):
            if self.has_tools:
                self.text = []
                await self.push_frame(frame, direction)
                return
            text = "".join(self.text)
            active = bool(self.d.engine.state.appointment_type_id or self.d.engine.state.provider_id or any(self.d.identity())) and not self.d.catalog_answer
            step = self.d.next_step() if active else {"stage": "idle", "question": None}
            if self.d.waiting:
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
                if step["stage"] == "identity_confirmation":
                    self.d.identity_readback = self.d.identity()
            elif self.d.pending:
                kind, slot = self.d.pending
                self.d.pending = None
                text = slot if kind in {"message", "identity", "options"} else self.d.render(slot, booked=kind == "booked")
                if kind == "identity":
                    self.d.identity_readback = self.d.identity()
                if kind == "prepare":
                    self.d.readback = (slot["slot_id"], self.d.engine._current_snapshot(slot["slot_id"]))
            elif active and step["stage"] == "offer":
                # Never claim a check is happening: no tool ran in this turn.
                text = "Would you like me to search for available appointments now?"
            if re.search(r"hold on|connect you|staff.{0,15}follow up|someone.{0,15}reach out", text, re.I):
                contacts = self.d.engine._clinic_contacts()
                text = "No transfer or callback is recorded. " + " ".join(
                    f"You can call {c['location']} at {c['phone']}." for c in contacts[:1])
            if text:
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
                    self.d.readback = None
                    same_identity = (step["stage"] == "identity_confirmation" and
                                     revised.startswith(self.d.identity_message().rsplit(", is that right?", 1)[0]))
                    self.d.identity_readback = self.d.identity() if same_identity else None
                text = revised
                await self.push_frame(LLMTextFrame(text))
            self.text = []
        await self.push_frame(frame, direction)
