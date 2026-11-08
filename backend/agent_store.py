"""Filesystem persistence for editable JSON agents and next-call selection."""

import json
import re
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from agent_builder import AgentBuilder
from scheduling_agent import SCHEDULING_TOOL_NAMES


BACKEND_DIR = Path(__file__).parent
DEFAULT_AGENTS_DIR = BACKEND_DIR / "agents"
DEFAULT_ACTIVE_AGENT_FILE = BACKEND_DIR / "logs" / "active_agent.txt"
DEFAULT_AGENT_ID = "catalog_scheduler"
_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class AgentStoreError(ValueError):
    pass


class AgentStore:
    def __init__(
        self,
        agents_dir: Path = DEFAULT_AGENTS_DIR,
        active_file: Path = DEFAULT_ACTIVE_AGENT_FILE,
    ):
        self.agents_dir = agents_dir
        self.active_file = active_file
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.active_file.parent.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        agents = []
        active = self.active_id()
        for path in sorted(self.agents_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            agents.append(
                {
                    "id": path.stem,
                    "name": data.get("name", path.stem),
                    "nodes": len(data.get("nodes", [])),
                    "active": path.stem == active,
                }
            )
        return agents

    def load(self, agent_id: str) -> dict:
        path = self.path(agent_id)
        if not path.exists():
            raise AgentStoreError(f"Unknown agent: {agent_id}")
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as error:
            raise AgentStoreError(f"Agent JSON is invalid: {error}") from error

    def save(self, agent_id: str, data: dict) -> dict:
        self.validate(data)
        path = self.path(agent_id)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        temporary.replace(path)
        return self.load(agent_id)

    def create(self, agent_id: str, *, name: str | None = None) -> dict:
        path = self.path(agent_id)
        if path.exists():
            raise AgentStoreError(f"Agent already exists: {agent_id}")
        data = {
            "name": name or agent_id.replace("_", " ").title(),
            "initial_node": "start",
            "nodes": [
                {
                    "name": "start",
                    "role_message": None,
                    "task_messages": [
                        {
                            "role": "developer",
                            "content": "Greet the caller and ask how you can help.",
                        }
                    ],
                    "edges": [],
                    "functions": [],
                    "pre_actions": [],
                    "post_actions": [],
                    "end": False,
                    "auto_end": True,
                }
            ],
            "persona": "You are a concise voice assistant.",
            "voice_id": "21m00Tcm4TlvDq8ikWAM",
            "model": "gpt-4o",
        }
        return self.save(agent_id, data)

    def duplicate(self, source_id: str, target_id: str) -> dict:
        data = self.load(source_id)
        if self.path(target_id).exists():
            raise AgentStoreError(f"Agent already exists: {target_id}")
        data["name"] = f"{data.get('name', source_id)} Copy"
        return self.save(target_id, data)

    def delete(self, agent_id: str) -> None:
        path = self.path(agent_id)
        if not path.exists():
            raise AgentStoreError(f"Unknown agent: {agent_id}")
        was_active = self.active_id() == agent_id
        path.unlink()
        if was_active:
            remaining = self.list()
            if remaining:
                self.activate(remaining[0]["id"])
            elif self.active_file.exists():
                self.active_file.unlink()

    def activate(self, agent_id: str) -> Path:
        path = self.path(agent_id)
        if not path.exists():
            raise AgentStoreError(f"Unknown agent: {agent_id}")
        self.validate(self.load(agent_id))
        self.active_file.write_text(agent_id + "\n")
        return path

    def active_id(self) -> str:
        if self.active_file.exists():
            candidate = self.active_file.read_text().strip()
            if candidate and self.path(candidate).exists():
                return candidate
        if self.path(DEFAULT_AGENT_ID).exists():
            return DEFAULT_AGENT_ID
        agents = sorted(self.agents_dir.glob("*.json"))
        return agents[0].stem if agents else ""

    def active_path(self) -> Path:
        agent_id = self.active_id()
        if not agent_id:
            raise AgentStoreError("No saved agent is available.")
        return self.path(agent_id)

    def path(self, agent_id: str) -> Path:
        if not _ID_PATTERN.fullmatch(agent_id):
            raise AgentStoreError(
                "Agent id must use lowercase letters, numbers, '-' or '_'."
            )
        return self.agents_dir / f"{agent_id}.json"

    @staticmethod
    def validate(data: dict) -> None:
        try:
            builder = AgentBuilder.from_dict(
                data,
                function_registry={name: None for name in SCHEDULING_TOOL_NAMES},
            )
            # Force schema conversion to remain the persisted contract.
            asdict(builder.config)
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise AgentStoreError(str(error)) from error
