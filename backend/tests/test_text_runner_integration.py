"""Opt-in OpenAI integration test. It incurs cost and model output may vary."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from text_runner import TextAgentSession


@unittest.skipUnless(
    os.getenv("RUN_OPENAI_INTEGRATION") == "1",
    "set RUN_OPENAI_INTEGRATION=1 to run the paid OpenAI integration check",
)
class TextRunnerIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_scripted_example_booking_completes_with_real_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics_log = Path(directory) / "turns.jsonl"
            session = TextAgentSession(
                metrics_log=metrics_log,
                run_id="integration-example",
                turn_timeout=45.0,
            )
            results = []
            try:
                initial = await session.start()
                results.append(initial)
                self.assertEqual(initial.node, "greeting")
                self.assertFalse(
                    any(message.get("role") == "user" for message in session.context_messages)
                )

                results.append(await session.send("I want to book an appointment."))
                results.append(
                    await session.send(
                        "My name is Ana Torres and I need a routine checkup."
                    )
                )
                final = await session.send("Tuesday at 10 AM.")
                results.append(final)
            finally:
                await session.close()

            self.assertEqual(
                [result.node for result in results],
                ["greeting", "collect_details", "offer_times", "confirm"],
            )
            self.assertEqual(
                final.state,
                {
                    "intent": "book",
                    "full_name": "Ana Torres",
                    "reason": "routine checkup",
                    "slot": "Tuesday 10 AM",
                },
            )
            self.assertTrue(final.ended)
            self.assertIn("Ana Torres", final.assistant_text)
            self.assertIn("Tuesday", final.assistant_text)

            records = [
                json.loads(line) for line in metrics_log.read_text().splitlines()
            ]
            self.assertEqual(
                len(records),
                sum(result.model_calls for result in results),
            )
            self.assertTrue(all(record["call_id"] == final.call_id for record in records))
            self.assertTrue(all(record["run_id"] == final.run_id for record in records))
            self.assertEqual(
                [(record["patient_turn"], record["trigger"]) for record in records],
                [
                    (0, "startup"),
                    (1, "patient"),
                    (1, "tool_result"),
                    (2, "patient"),
                    (2, "tool_result"),
                    (3, "patient"),
                    (3, "tool_result"),
                ],
            )
