"""Scripted-patient text integrations for the development scenarios."""

from dataclasses import dataclass
from datetime import datetime

from scheduling import SchedulingEngine, load_catalog
from scheduling_agent import build_scheduling_agent
from text_runner import TextAgentSession, TextTurnResult

from .loader import DEFAULT_CATALOG_PATH, load_dev_scenarios


FIRST_TEXT_CASES = {"DEV-012", "DEV-004", "DEV-008"}


@dataclass
class ScenarioTextRun:
    scenario_id: str
    call_id: str
    run_id: str
    transcript: list[dict]
    context_messages: list[dict]
    engine: SchedulingEngine
    error: str | None = None


@dataclass
class _PatientDriver:
    scenario: dict
    identity_given: bool = False
    patient_status_given: bool = False
    referral_status_given: bool = False
    provider_clarified: bool = False
    service_escalated: bool = False
    corrected: bool = False
    spelling_repeated: bool = False
    human_accepted: bool = False

    def reply(self, result: TextTurnResult, engine: SchedulingEngine) -> str | None:
        scenario_id = self.scenario["id"]
        text = result.assistant_text.casefold()

        if result.ended or engine.bookings:
            return None

        if scenario_id == "DEV-002" and not self.provider_clarified:
            provider_candidates = {
                item["id"]
                for item in engine.state.last_candidates
                if item["entity"] == "provider"
            }
            if provider_candidates or "which" in text or "maria garcia" in text:
                self.provider_clarified = True
                return (
                    "I mean Maria Garcia, the Family Medicine nurse practitioner, "
                    "and I want the Midtown location."
                )

        if scenario_id == "DEV-007" and not self.service_escalated:
            self.service_escalated = True
            return (
                "I cannot choose between Skin Cancer Screening and Full Body Skin Exam. "
                "Please have a staff member confirm the intended service."
            )

        if scenario_id == "DEV-008" and engine.state.offered_slot_ids and not self.corrected:
            self.corrected = True
            return "Actually, Mission Bay only. I cannot go downtown."

        if scenario_id == "DEV-011":
            if "spell" in text and not self.spelling_repeated:
                self.spelling_repeated = True
                return "It is spelled Zephyr Imaginary. I only want that doctor."
            if any(word in text for word in ("human", "staff", "representative", "follow up")):
                if not self.human_accepted:
                    self.human_accepted = True
                    return "Yes, please have a staff member follow up with me."
            return None

        if self._asks_for_identity(text) and not self.identity_given:
            if scenario_id == "DEV-010":
                return None
            facts = self.scenario["patient_facts"]
            self.identity_given = True
            reply = (
                f"My name is {facts['name']} and my date of birth is "
                f"{facts['date_of_birth']}."
            )
            if "new patient" in text and "is_new_patient" in facts:
                self.patient_status_given = True
                reply += self._patient_status(facts["is_new_patient"])
            if "referral" in text and "referral_on_file" in facts:
                self.referral_status_given = True
                reply += self._referral_status(facts["referral_on_file"])
            return reply

        facts = self.scenario["patient_facts"]
        if self.identity_given and any(phrase in text for phrase in ("confirm", "correct", "right")) and any(
            phrase in text for phrase in ("birth", "born", "dob")):
            return "Yes, my name and date of birth are correct."
        if (
            "new patient" in text
            and "is_new_patient" in facts
            and not self.patient_status_given
        ):
            self.patient_status_given = True
            return self._patient_status(facts["is_new_patient"]).strip()
        if (
            "referral" in text
            and "referral_on_file" in facts
            and not self.referral_status_given
        ):
            self.referral_status_given = True
            return self._referral_status(facts["referral_on_file"]).strip()

        if engine.state.offered_slot_ids:
            if scenario_id == "DEV-009":
                return (
                    "Yes, I confirm the exact earliest slot, clinician, location, service, "
                    "date, and time. Please book it."
                )
            return (
                "Yes. I confirm that exact provider, location, service, date, and time. "
                "Please book it."
            )

        return None

    @staticmethod
    def _asks_for_identity(text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "your name",
                "full name",
                "patient's name",
                "patient name",
                "date of birth",
                "birth date",
                "dob",
                "birthday",
            )
        )

    @staticmethod
    def _patient_status(is_new_patient: bool) -> str:
        return " I am a new patient." if is_new_patient else " I am an existing patient."

    @staticmethod
    def _referral_status(referral_on_file: bool) -> str:
        if referral_on_file:
            return " I have a referral on file."
        return " I do not have a referral on file."


async def run_dev_case(scenario_id: str, *, run_id: str) -> ScenarioTextRun:
    """Run one development case without exposing its expected outcome to the agent."""
    dataset = load_dev_scenarios()
    scenarios = {item["id"]: item for item in dataset["scenarios"]}
    if scenario_id not in scenarios:
        raise ValueError(f"Unknown development scenario: {scenario_id}")
    scenario = scenarios[scenario_id]
    catalog = load_catalog(DEFAULT_CATALOG_PATH)
    engine = SchedulingEngine(
        catalog,
        scenario["availability_fixture"],
        now=datetime.fromisoformat("2026-11-07T00:00:00-08:00"),
    )
    session = TextAgentSession(
        builder=build_scheduling_agent(engine, catalog),
        run_id=run_id,
        faults=scenario.get("faults", []),
        on_slot_taken=engine.mark_slot_unavailable,
        turn_timeout=45.0,
    )
    transcript: list[dict] = []
    driver = _PatientDriver(scenario)
    error: str | None = None
    context_messages: list[dict] = []
    try:
        initial = await session.start()
        transcript.append({"role": "assistant", "text": initial.assistant_text})
        result = await session.send(scenario["opening"])
        _append_turn(transcript, scenario["opening"], result)

        for _ in range(8):
            if _conversation_complete(scenario, result, engine, driver):
                break
            patient_text = driver.reply(result, engine)
            if patient_text is None:
                raise RuntimeError(
                    f"No scripted patient reply after: {result.assistant_text!r}"
                )
            result = await session.send(patient_text)
            _append_turn(transcript, patient_text, result)
        else:
            raise RuntimeError("Conversation exceeded eight scripted patient turns.")
    except Exception as caught:
        error = (
            f"{type(caught).__name__}: {caught}; state={engine.state!r}; "
            f"bookings={engine.bookings!r}; recent_context={session.context_messages[-6:]!r}"
        )
    finally:
        context_messages = session.context_messages
        await session.close()
    return ScenarioTextRun(
        scenario_id=scenario_id,
        call_id=session.call_id,
        run_id=session.run_id,
        transcript=transcript,
        context_messages=context_messages,
        engine=engine,
        error=error,
    )


async def run_first_text_case(scenario_id: str, *, run_id: str) -> ScenarioTextRun:
    """Compatibility wrapper for the original three-case integration test."""
    if scenario_id not in FIRST_TEXT_CASES:
        raise ValueError(f"Initial text integration is limited to {sorted(FIRST_TEXT_CASES)}")
    result = await run_dev_case(scenario_id, run_id=run_id)
    if result.error:
        raise RuntimeError(result.error)
    return result


def _append_turn(transcript: list[dict], patient_text: str, result: TextTurnResult) -> None:
    transcript.extend(
        [
            {"role": "patient", "text": patient_text},
            {
                "role": "assistant",
                "text": result.assistant_text,
                "tools": list(result.tool_calls),
                "node": result.node,
            },
        ]
    )


def _conversation_complete(
    scenario: dict,
    result: TextTurnResult,
    engine: SchedulingEngine,
    driver: _PatientDriver,
) -> bool:
    if result.ended or engine.bookings:
        return True
    scenario_id = scenario["id"]
    current = engine.resolve_options()
    blocked = {item["code"] for item in current["blocked_options"]}
    if scenario["expected_outcome"] == "no_booking" and blocked:
        return True
    text = result.assistant_text.casefold()
    if scenario_id == "DEV-007" and driver.service_escalated:
        return any(word in text for word in ("staff", "human", "cannot", "can't"))
    if scenario_id == "DEV-010":
        digits = "".join(character for character in text if character.isdigit())
        opening = "8:00" in text or "8 am" in text or "8 a.m." in text
        closing = any(
            value in text for value in ("17:00", "5 pm", "5:00 pm", "5 p.m.", "5:00 p.m.")
        )
        return "4155554657" in digits and opening and closing
    if scenario_id == "DEV-011":
        return any(
            phrase in text
            for phrase in (
                "couldn't find",
                "could not find",
                "not found",
                "no provider",
                "not in our",
                "don't have",
            )
        )
    return False
