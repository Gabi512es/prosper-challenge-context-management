"""Offline baseline measurement and request-prefix check. Never sends a request."""
import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import tiktoken
from openai.resources.chat.completions import AsyncCompletions
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.openai.llm import OpenAILLMService

from baseline_agent import build_baseline_agent, render_catalog
from scheduling import SchedulingEngine, load_catalog

BACKEND = Path(__file__).resolve().parents[1]


def request_parameters(llm, node, history):
    """Use the installed adapter/serializer, stopping before HTTP creation."""
    context = LLMContext(
        messages=[*node["task_messages"], *history],
        tools=ToolsSchema(standard_tools=[f.to_function_schema() for f in node["functions"]]),
    )
    invocation = llm.get_llm_adapter().get_llm_invocation_params(
        context, system_instruction=node["role_message"], convert_developer_to_user=False,
    )
    return llm.build_chat_completion_params(invocation)


async def check_prefix():
    catalog = load_catalog(BACKEND / "data/catalog.json")
    reference = render_catalog(catalog)
    histories = [
        [],
        [{"role": "user", "content": "I need an appointment."}],
        [{"role": "user", "content": "I need an appointment."},
         {"role": "assistant", "content": "Which service?"},
         {"role": "user", "content": "Whichever is soonest."}],
        [{"role": "user", "content": "Please check availability."},
         {"role": "assistant", "tool_calls": [{"id": "offline-tool", "type": "function", "function": {
             "name": "find_slots", "arguments": "{\"horizon_days\":7}"}}]},
         {"role": "tool", "tool_call_id": "offline-tool", "content": "{\"slots\":[]}"}],
    ]
    hashes, tool_hashes, roles = [], [], []
    with patch.object(AsyncCompletions, "create", new_callable=AsyncMock) as network:
        for i, history in enumerate(histories):
            engine = SchedulingEngine(catalog, [], now=datetime.fromisoformat("2026-11-07T00:00:00-08:00"))
            if i:
                engine.state.patient_facts.name = "Different Patient"
            builder = build_baseline_agent(engine, catalog, availability_mode="eval_fixture")
            node = builder.build_initial_node()
            llm = OpenAILLMService(api_key="offline-no-network", settings=OpenAILLMService.Settings(
                model=builder.config.model, extra={"parallel_tool_calls": False}))
            try:
                params = request_parameters(llm, node, history)
                assert params["messages"][0] == {"role": "system", "content": node["role_message"]}
                assert node["role_message"].startswith(reference)
                # All system + initial task messages precede variable history.
                prefix = params["messages"][:1 + len(node["task_messages"])]
                roles.append(node["role_message"])
                hashes.append(hashlib.sha256(json.dumps(prefix, ensure_ascii=False).encode()).hexdigest())
                tool_hashes.append(hashlib.sha256(json.dumps(params["tools"], sort_keys=True).encode()).hexdigest())
            finally:
                await llm._client.close()
        network.assert_not_called()
    assert len(set(hashes)) == len(set(tool_hashes)) == 1
    encoder = tiktoken.encoding_for_model(builder.config.model)
    return {
        "model": builder.config.model, "tokenizer": encoder.name,
        "catalog_tokens": len(encoder.encode(reference)),
        "catalog_characters": len(reference), "catalog_utf8_bytes": len(reference.encode()),
        "catalog_sha256": hashlib.sha256(reference.encode()).hexdigest(),
        "role_tokens": len(encoder.encode(roles[0])),
        "prefix_content_tokens": sum(len(encoder.encode(m["content"])) for m in prefix),
        "prefix_content_tokens_note": "System and initial task text only; excludes API framing and tool schema tokens.",
        "request_prefix_hashes": hashes, "tool_schema_hashes": tool_hashes,
        "checked_requests": len(histories), "network_calls": 0,
        "source_proposed_agent_sha256": builder.source_proposed_revision,
        "baseline_agent_sha256": builder.session_metadata["agent_revision"],
        "limitation": "Identical serialized prefixes enable caching; server cache hits require a paid measurement.",
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(check_prefix()), indent=2))
