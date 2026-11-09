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

    @staticmethod
    def is_affirmative(text):
        text = text.casefold().replace("’", "'").strip(" .!?,")
        if re.search(r"\b(no|not|don't|wait|stop|actually|but|except)\b", text):
            return False
        normalized = re.sub(r"[.,!?]", " ", text)
        normalized = " ".join(normalized.split())
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
        if self.readback and affirmative and not self.waiting:
            slot_id, snapshot = self.readback
            if snapshot == self.engine._current_snapshot(slot_id):
                self.engine.confirm_selected_slot()
        else:
            self.engine.state.confirmation = None
        self.readback = None
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
        if len(candidates) == 1:
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
        e = self.engine
        facts = e.state.patient_facts
        dob = datetime.fromisoformat(facts.date_of_birth).strftime("%B %d, %Y").replace(" 0", " ")
        start = datetime.fromisoformat(slot["start"])
        date = start.strftime("%A %B %d").replace(" 0", " ")
        time = start.strftime("%I:%M %p").lstrip("0")
        intro = "Booked" if booked else "I'll book"
        return (f"{intro} {self.spoken_service(slot['service'])} for {facts.name}, born {dob}, with {slot['provider']} "
                f"at {slot['location']}, {date} at {time}. " +
                ("Is there anything else I can help with?" if booked else "Shall I book it?"))

    @staticmethod
    def spoken_service(name):
        parts = re.split(r"\s+-\s+", name, maxsplit=1)
        phrase = (parts[1].lower() + " " + parts[0]) if len(parts) == 2 else name
        return ("an " if phrase[0].lower() in "aeiou" else "a ") + phrase

    def prepare_booking(self, slot_id):
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
            if self.d.location_conflict:
                text = self.d.location_conflict
                self.d.pending = None
            elif self.d.waiting:
                text = "Of course. What would you like to change?"
                self.d.waiting = False
                self.d.pending = None
            elif self.d.pending:
                kind, slot = self.d.pending
                self.d.pending = None
                if kind == "offer":
                    start = datetime.fromisoformat(slot["start"])
                    text = (f"There is {self.d.spoken_service(slot['service'])} with {slot['provider']} at {slot['location']}, "
                            f"{start.strftime('%A %B %d at %I:%M %p')}. Would you like this slot?")
                else:
                    text = slot if kind == "message" else self.d.render(slot, booked=kind == "booked")
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
