"""No-network regression for a scheduling -> no-tools handoff transition."""

import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from openai import NOT_GIVEN
from openai.resources.chat.completions import AsyncCompletions
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregatorParams
from pipecat.services.openai.llm import OpenAILLMService

from agent_runtime import build_agent_runtime
from scheduling import SchedulingEngine, load_catalog
from scheduling_agent import build_scheduling_agent


BACKEND = Path(__file__).resolve().parents[1]


class ToolRequestParametersTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_tools_handoff_omits_parallel_flag_and_scheduling_keeps_it(self):
        catalog = load_catalog(BACKEND / "data/catalog.json")
        engine = SchedulingEngine(catalog, [], now=datetime.fromisoformat("2026-11-07T00:00:00-08:00"))
        builder = build_scheduling_agent(engine, catalog, availability_mode="unit_fixture")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "offline-no-network"}), patch.object(
            AsyncCompletions, "create", new_callable=AsyncMock
        ) as network:
            runtime = build_agent_runtime(builder=builder, user_params=LLMUserAggregatorParams())
            llm = runtime.llm
            try:
                # Use the real factory, graph nodes and installed OpenAI adapter.
                # Flows represents a node with no functions as NOT_GIVEN.
                for name in ("scheduling", "human_handoff", "scheduling"):
                    with self.subTest(node=name):
                        node = builder._make_node(builder._nodes_by_name[name])
                        tools = (ToolsSchema(standard_tools=[f.to_function_schema() for f in node["functions"]])
                                 if node["functions"] else NOT_GIVEN)
                        context = LLMContext(messages=node["task_messages"], tools=tools)
                        invocation = llm.get_llm_adapter().get_llm_invocation_params(
                            context, system_instruction=node["role_message"], convert_developer_to_user=False)
                        original = OpenAILLMService.build_chat_completion_params(llm, invocation)
                        actual = llm.build_chat_completion_params(invocation)
                        if node["functions"]:
                            self.assertIs(actual["parallel_tool_calls"], False)
                        else:
                            self.assertNotIn("parallel_tool_calls", actual)
                            original.pop("parallel_tool_calls")
                        self.assertEqual(actual, original)

                # All supported empty-tool representations must behave alike.
                for empty in (NOT_GIVEN, None, []):
                    with self.subTest(empty_tools=repr(empty)):
                        self.assertNotIn("parallel_tool_calls", llm.build_chat_completion_params(
                            {"messages": [], "tools": empty}))
                self.assertNotIn("parallel_tool_calls", llm.build_chat_completion_params({"messages": []}))
                self.assertIs(llm._settings.extra["parallel_tool_calls"], False)
                network.assert_not_called()
            finally:
                await llm._client.close()
