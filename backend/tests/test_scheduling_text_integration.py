"""Paid, variable OpenAI checks for the first three development scenarios."""

import os
import unittest
from uuid import uuid4

from evals.text_integration import run_first_text_case


@unittest.skipUnless(
    os.getenv("RUN_OPENAI_INTEGRATION") == "1",
    "set RUN_OPENAI_INTEGRATION=1 to run paid scheduling text integrations",
)
class SchedulingTextIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_dev_012_dev_004_and_dev_008(self):
        run_id = f"first-three-{uuid4().hex[:8]}"
        dev_012 = await run_first_text_case("DEV-012", run_id=run_id)
        dev_004 = await run_first_text_case("DEV-004", run_id=run_id)
        dev_008 = await run_first_text_case("DEV-008", run_id=run_id)

        self.assertEqual(len(dev_012.engine.bookings), 1)
        self.assertEqual(
            dev_012.engine.bookings[0]["slot_id"],
            "dev012-s1",
        )
        self.assertEqual(dev_004.engine.bookings, [])
        self.assertEqual(dev_008.engine.bookings, [])
        self.assertEqual(dev_008.engine.state.location_id, "loc_000")
        self.assertIsNone(dev_008.engine.state.selected_slot_id)
        self.assertIsNone(dev_008.engine.state.confirmation)
