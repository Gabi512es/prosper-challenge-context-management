import asyncio
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pipecat.frames.frames import (
    EndFrame,
    FunctionCallInProgressFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    StartFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from agent_builder import AgentBuilder
from text_runner import TextAgentSession, TextToolFaultInjector, TextTurnCollector


FLOW_PATH = Path(__file__).parents[1] / "example_flow.json"


class AgentBehaviorTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_transition_handlers_preserve_supplied_booking_facts(self):
        builder = AgentBuilder.from_json(FLOW_PATH)
        manager = SimpleNamespace(state={})
        node = builder.build_initial_node()
        visited = [node["name"]]

        supplied_turns = [
            {"intent": "book"},
            {"full_name": "Ana Torres", "reason": "routine checkup"},
            {"slot": "Tuesday 10 AM"},
        ]
        for supplied in supplied_turns:
            function = node["functions"][0]
            result, node = await function.handler(supplied, manager)
            self.assertEqual(result["status"], "success")
            visited.append(node["name"])

        self.assertEqual(
            manager.state,
            {
                "intent": "book",
                "full_name": "Ana Torres",
                "reason": "routine checkup",
                "slot": "Tuesday 10 AM",
            },
        )
        self.assertEqual(
            visited,
            ["greeting", "collect_details", "offer_times", "confirm"],
        )
        self.assertTrue(builder.current_node_is_terminal)


class TextTurnCollectorTest(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_post_tool_assistant_generation(self):
        collector = TextTurnCollector()
        await collector.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        collector.begin_turn()

        await collector.process_frame(
            LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM
        )
        await collector.process_frame(
            FunctionCallInProgressFrame(
                "choose_intent", "tool-1", {"intent": "book"}
            ),
            FrameDirection.DOWNSTREAM,
        )
        await collector.process_frame(
            LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM
        )

        wait_task = asyncio.create_task(collector.wait(timeout=1.0))
        await asyncio.sleep(0)
        self.assertFalse(wait_task.done())

        await collector.process_frame(
            LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM
        )
        await collector.process_frame(
            LLMTextFrame("What is the patient's name?"),
            FrameDirection.DOWNSTREAM,
        )
        await collector.process_frame(
            LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM
        )

        captured = await wait_task
        self.assertEqual(captured.assistant_text, "What is the patient's name?")
        self.assertEqual(captured.tool_calls, ("choose_intent",))
        self.assertEqual(captured.model_calls, 2)

    async def test_terminal_end_frame_completes_instead_of_timing_out(self):
        collector = TextTurnCollector()
        await collector.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        collector.begin_turn()

        await collector.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)

        captured = await collector.wait(timeout=1.0)
        self.assertEqual(captured.assistant_text, "")


class TextAgentSessionConfigurationTest(unittest.IsolatedAsyncioTestCase):
    async def test_each_eval_run_gets_its_own_default_log_file(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "offline-test-key"}):
            first = TextAgentSession(run_id="dev-run-001")
            second = TextAgentSession(run_id="dev-run-002")

        self.assertEqual(first.metrics_log.name, "dev-run-001.jsonl")
        self.assertEqual(second.metrics_log.name, "dev-run-002.jsonl")
        self.assertNotEqual(first.metrics_log, second.metrics_log)


class TextToolFaultInjectorTest(unittest.IsolatedAsyncioTestCase):
    async def test_error_mode_returns_structured_error_on_every_attempt(self):
        calls = 0

        async def real_handler(args, flow_manager):
            nonlocal calls
            calls += 1
            return {"status": "ok"}

        injector = TextToolFaultInjector(
            [
                {
                    "mode": "error",
                    "tool": "find_slots",
                    "code": "availability_shutdown",
                    "message": "Availability service is offline.",
                }
            ]
        )
        handler = injector.wrap("find_slots", real_handler)

        first = await handler({}, SimpleNamespace())
        second = await handler({}, SimpleNamespace())

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "error")
        self.assertEqual(first["code"], "availability_shutdown")
        self.assertEqual(first["tool"], "find_slots")
        self.assertFalse(first["retryable"])
        self.assertEqual(calls, 0)

    async def test_slot_taken_fault_fails_n_writes_then_stays_unavailable(self):
        unavailable = set()
        real_calls = 0

        def mark_unavailable(slot_id):
            unavailable.add(slot_id)

        async def real_handler(args, flow_manager):
            nonlocal real_calls
            real_calls += 1
            if args["slot_id"] in unavailable:
                return {
                    "status": "error",
                    "code": "slot_taken",
                    "slot_id": args["slot_id"],
                }
            return {"status": "booked"}

        injector = TextToolFaultInjector(
            [
                {
                    "mode": "slot taken",
                    "tool": "book_appointment",
                    "slot_id": "slot-1",
                    "attempts": 2,
                }
            ],
            on_slot_taken=mark_unavailable,
        )
        handler = injector.wrap("book_appointment", real_handler)

        results = [
            await handler({"slot_id": "slot-1"}, SimpleNamespace())
            for _ in range(4)
        ]

        self.assertTrue(all(result["code"] == "slot_taken" for result in results))
        self.assertEqual(unavailable, {"slot-1"})
        self.assertEqual(real_calls, 2)
