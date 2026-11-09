"""Shared transcript-grounded consent and deterministic booking speech."""
import re
from datetime import datetime

from pipecat.frames.frames import (TranscriptionFrame, LLMTextFrame,
    LLMFullResponseStartFrame, LLMFullResponseEndFrame, InterruptionFrame,
    FunctionCallsStartedFrame)
from pipecat.processors.frame_processor import FrameProcessor


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

    def location_reply(self, text):
        """Handle bounded time/place replies without inventing proximity."""
        normalized = " ".join(re.findall(r"[a-z]+", text.casefold()))
        if re.search(r"\b(closest|nearest)\b", normalized) and self.location_intent_stage != "place":
            self.location_intent_stage = "meaning"
            self.location_intent_question = "Do you mean the soonest appointment in time, or the nearest clinic geographically?"
            return
        if self.location_intent_stage in {"meaning", "place"} and re.search(r"\b(place|geographic|geographically|distance|neighborhood|near me)\b", normalized):
            self.location_intent_stage = "place"
        if self.location_intent_stage == "place":
            # No geocoding/distance service: ask the patient to choose a site.
            names = sorted({self.engine.catalog.locations_by_id[s.location_id].name
                for s in self.engine._slots.values()
                if s.appointment_type_id == self.engine.state.appointment_type_id
                and (not self.engine.state.provider_id or s.provider_id == self.engine.state.provider_id)
                and not self.engine._slot_patient_issues(s)
                and self.engine._slot_within_opening_hours(s)
                and s.start >= self.engine.now and s.slot_id not in self.engine._unavailable_slot_ids})
            self.location_intent_question = ("I can't calculate which clinic is nearest. " +
                ("Available sites for this request are " + ", ".join(names[:4]) + ". Which would you prefer?" if names
                 else "Please name a preferred clinic so I can check its eligibility and availability."))
        if normalized in {"whichever is soonest", "whatever is soonest", "the soonest", "soonest", "earliest", "the earliest", "earliest available", "the earliest available", "soonest in time", "earliest in time"} or (self.location_intent_stage == "meaning" and normalized in {"time", "in time", "the time"}):
            if self.engine.state.hard_constraints.intersection({"provider", "provider_id", "location", "location_id"}):
                self.location_intent_question = "May I widen your provider and location constraints to find the soonest eligible appointment?"
                self.location_intent_stage = "widen"
                return
            self.enable_global_soonest()
        elif self.location_intent_stage == "widen" and self.is_affirmative(text):
            self.engine.state.hard_constraints.difference_update({"provider", "provider_id", "location", "location_id"})
            self.enable_global_soonest()

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
        current = self.identity()
        if self.identity_confirmed == current and all(current):
            return None
        self.engine.state.confirmation = None
        self.readback = None
        if not all(current):
            return {"status": "missing_identity", "technical_failure": False,
                    "next_action": "collect_name_and_date_of_birth"}
        dob = datetime.fromisoformat(current[1]).strftime("%B %d, %Y").replace(" 0", " ")
        message = f"{current[0]}, born {dob}, is that right?"
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
        self.patient_text = text
        self.pending = None
        self.waiting = bool(re.search(r"\b(wait|stop|hold on)\b", text, re.I))
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
        identity_step = self.require_identity()
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
            # Identity is spoken immediately once captured, before any offer.
            if all(self.d.identity()) and self.d.identity_confirmed != self.d.identity():
                self.d.require_identity()
            if self.d.location_intent_question:
                text = self.d.location_intent_question
                self.d.pending = None
            elif self.d.location_conflict:
                text = self.d.location_conflict
                self.d.pending = None
            elif self.d.waiting:
                text = "Of course. What would you like to change?"
                self.d.waiting = False
                self.d.pending = None
            elif self.d.pending:
                kind, slot = self.d.pending
                self.d.pending = None
                text = slot if kind in {"message", "identity", "options"} else self.d.render(slot, booked=kind == "booked")
                if kind == "identity":
                    self.d.identity_readback = self.d.identity()
                if kind == "prepare":
                    self.d.readback = (slot["slot_id"], self.d.engine._current_snapshot(slot["slot_id"]))
            if re.search(r"hold on|connect you|staff.{0,15}follow up|someone.{0,15}reach out", text, re.I):
                contacts = self.d.engine._clinic_contacts()
                text = "No transfer or callback is recorded. " + " ".join(
                    f"You can call {c['location']} at {c['phone']}." for c in contacts[:1])
            if text:
                await self.push_frame(LLMTextFrame(text))
            self.text = []
        await self.push_frame(frame, direction)
