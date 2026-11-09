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
        for provider in self.engine.catalog.providers:
            if provider.specialty.casefold() in text.casefold() or any(
                _specialty_matches(word, provider.specialty) for word in re.findall(r"[A-Za-z]+", text)):
                self.specialty = provider.specialty
        candidates = [item for item in self.engine.state.last_candidates
                      if item.get("entity") == "provider" and item.get("specialty") == self.specialty]
        if len(candidates) == 1:
            self.engine.resolve_options({"provider_id": candidates[0]["id"]})

    def handoff_requested(self):
        return bool(re.search(
            r"\b(?:talk|speak)\s+to\s+(?:a\s+|an\s+)?(?:someone|person|human|representative|staff member|real person)\b|"
            r"\b(?:want|need|request)\s+(?:a\s+|an\s+)?(?:human|representative|staff member|real person)\b|\btransfer me\b",
            self.patient_text, re.I)) and not bool(re.search(r"\b(?:don't|do not)\s+(?:want|need)\b", self.patient_text, re.I))

    def render(self, slot, booked=False):
        e = self.engine
        facts = e.state.patient_facts
        dob = datetime.fromisoformat(facts.date_of_birth).strftime("%B %d, %Y").replace(" 0", " ")
        start = datetime.fromisoformat(slot["start"])
        date = start.strftime("%A %B %d").replace(" 0", " ")
        time = start.strftime("%I:%M %p").lstrip("0")
        intro = "Booked" if booked else "I'll book"
        return (f"{intro} {slot['service']} for {facts.name}, born {dob}, with {slot['provider']} "
                f"at {slot['location']}, {date} at {time}. " +
                ("Is there anything else I can help with?" if booked else "Shall I book it?"))


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
            self.d.readback = None
            self.d.engine.state.confirmation = None
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
                text = self.d.render(slot, booked=kind == "booked")
                if kind == "offer":
                    self.d.engine.select_slot(slot["slot_id"])
                    self.d.readback = (slot["slot_id"], self.d.engine._current_snapshot(slot["slot_id"]))
            if re.search(r"hold on|connect you|staff.{0,15}follow up|someone.{0,15}reach out", text, re.I):
                contacts = self.d.engine._clinic_contacts()
                text = "No transfer or callback is recorded. " + " ".join(
                    f"You can call {c['location']} at {c['phone']}." for c in contacts[:1])
            if text:
                await self.push_frame(LLMTextFrame(text))
            self.text = []
        await self.push_frame(frame, direction)
