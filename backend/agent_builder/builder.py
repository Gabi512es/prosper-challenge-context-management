#
# AgentBuilder — loads a declarative agent (JSON / dict) and compiles its node
# graph into Pipecat Flows objects.
#
#   JSON  ->  AgentConfig (validated)  ->  Pipecat Flows NodeConfig graph
#
# This is the seam between "agent as data" (what the Phase 2 Copilot produces)
# and "agent as a running conversation" (what bot.py executes). Keeping the
# compile + validation here means bot.py never touches the graph internals.
#

import json
from dataclasses import replace
from pathlib import Path
from typing import Callable, Union

from loguru import logger
from pipecat_flows import FlowManager, FlowsFunctionSchema, NodeConfig

from .schema import AgentConfig, Edge, Node


class AgentBuilder:
    """Builds a runnable Pipecat Flows graph from a declarative AgentConfig."""

    def __init__(
        self,
        config: AgentConfig,
        function_registry: dict[str, FlowsFunctionSchema] | None = None,
    ):
        self.config = config
        self._function_registry = function_registry or {}
        self._function_handler_wrapper: Callable | None = None
        self._nodes_by_name = {n.name: n for n in config.nodes}
        # Runtime attribution for metrics. Each AgentBuilder belongs to one call,
        # so this remains session-local and never mixes concurrent callers.
        self.current_node = config.initial_node
        self._validate()
        dialogue = getattr(function_registry, "dialogue", None)
        if dialogue is not None:
            self.dialogue = dialogue
            self.transition_guard = dialogue.authorize_transition

    # ---- loading -----------------------------------------------------------
    @classmethod
    def from_dict(
        cls,
        data: dict,
        function_registry: dict[str, FlowsFunctionSchema] | None = None,
    ) -> "AgentBuilder":
        return cls(AgentConfig.from_dict(data), function_registry=function_registry)

    @classmethod
    def from_json(
        cls,
        path: Union[str, Path],
        function_registry: dict[str, FlowsFunctionSchema] | None = None,
    ) -> "AgentBuilder":
        data = json.loads(Path(path).read_text())
        return cls.from_dict(data, function_registry=function_registry)

    # ---- validation --------------------------------------------------------
    def _validate(self) -> None:
        names = set(self._nodes_by_name)
        if not names:
            raise ValueError("Agent has no nodes.")
        if len(names) != len(self.config.nodes):
            raise ValueError("Node names must be unique.")
        if self.config.initial_node not in names:
            raise ValueError(
                f"initial_node '{self.config.initial_node}' is not a defined node."
            )
        for node in self.config.nodes:
            edge_names = {edge.function for edge in node.edges}
            if len(edge_names) != len(node.edges):
                raise ValueError(
                    f"Node '{node.name}' has duplicate edge function names."
                )
            duplicate_names = edge_names.intersection(node.functions)
            if duplicate_names:
                raise ValueError(
                    f"Node '{node.name}' repeats functions as edges: "
                    f"{sorted(duplicate_names)}"
                )
            unknown_functions = set(node.functions) - set(self._function_registry)
            if unknown_functions:
                raise ValueError(
                    f"Node '{node.name}' references unregistered functions: "
                    f"{sorted(unknown_functions)}"
                )
            for edge in node.edges:
                if edge.target not in names:
                    raise ValueError(
                        f"Edge '{edge.function}' in node '{node.name}' targets "
                        f"unknown node '{edge.target}'."
                    )

    # ---- compilation -------------------------------------------------------
    def build_initial_node(self) -> NodeConfig:
        """Return the entry NodeConfig; downstream nodes are built lazily on transition."""
        return self._make_node(self._nodes_by_name[self.config.initial_node])

    @property
    def current_node_is_terminal(self) -> bool:
        """Whether the active configured node ends the conversation."""
        return self._nodes_by_name[self.current_node].end

    @property
    def function_names(self) -> set[str]:
        """All transition and registered tool names exposed by this graph."""
        return {
            name
            for node in self.config.nodes
            for name in (*[edge.function for edge in node.edges], *node.functions)
        }

    def set_function_handler_wrapper(self, wrapper: Callable) -> None:
        """Wrap every exposed tool handler for this builder's single session."""
        if self._function_handler_wrapper is not None:
            raise RuntimeError("A function handler wrapper is already installed.")
        self._function_handler_wrapper = wrapper

    def _make_node(self, node: Node) -> NodeConfig:
        functions = [self._make_edge_function(edge) for edge in node.edges] + [
            self._function_registry[name] for name in node.functions
        ]
        if self._function_handler_wrapper:
            functions = [
                replace(
                    function,
                    handler=self._function_handler_wrapper(
                        function.name,
                        function.handler,
                    ),
                )
                for function in functions
            ]
        node_config: NodeConfig = {
            "name": node.name,
            "role_message": node.role_message or self.config.persona,
            "task_messages": node.task_messages,
            "functions": functions,
        }
        if node.pre_actions:
            node_config["pre_actions"] = node.pre_actions
        # Explicit post_actions win; otherwise a terminal node ends the call.
        if node.post_actions:
            node_config["post_actions"] = node.post_actions
        elif node.end and node.auto_end:
            node_config["post_actions"] = [{"type": "end_conversation"}]
        return node_config

    def _make_edge_function(self, edge: Edge) -> FlowsFunctionSchema:
        async def handler(args: dict, flow_manager: FlowManager):
            guard = getattr(self, "transition_guard", None)
            is_handoff = edge.function == "request_human_transfer" or "handoff" in edge.target.casefold()
            if guard and is_handoff and not guard("request_human_transfer"):
                return {"status": "error", "code": "explicit_human_request_required"}
            # Persist what the caller gave us so later nodes can use it.
            flow_manager.state.update(args)
            logger.info(f"[{edge.function}] -> {edge.target} | collected: {args}")
            next_node = self._make_node(self._nodes_by_name[edge.target])
            self.current_node = edge.target
            return {"status": "success", **args}, next_node

        return FlowsFunctionSchema(
            name=edge.function,
            description=edge.description,
            properties=edge.properties,
            required=edge.required,
            handler=handler,
        )
