"""Minimal local API for the JSON graph editor."""

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent_store import AgentStore, AgentStoreError
from scheduling_agent import SCHEDULING_TOOL_NAMES


class CreateAgentRequest(BaseModel):
    id: str
    name: str | None = None


class DuplicateAgentRequest(BaseModel):
    id: str


app = FastAPI(title="Prosper Agent Editor API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
store = AgentStore()


def _error(error: AgentStoreError, status_code: int = 422) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"message": str(error), "errors": [str(error)]},
    )


@app.get("/api/agents")
def list_agents():
    return {"agents": store.list(), "active_agent_id": store.active_id()}


@app.get("/api/agents/{agent_id}")
def get_agent(agent_id: str):
    try:
        return {"id": agent_id, "config": store.load(agent_id)}
    except AgentStoreError as error:
        raise _error(error, 404) from error


@app.post("/api/agents", status_code=201)
def create_agent(request: CreateAgentRequest):
    try:
        return {"id": request.id, "config": store.create(request.id, name=request.name)}
    except AgentStoreError as error:
        raise _error(error) from error


@app.post("/api/agents/{agent_id}/duplicate", status_code=201)
def duplicate_agent(agent_id: str, request: DuplicateAgentRequest):
    try:
        return {"id": request.id, "config": store.duplicate(agent_id, request.id)}
    except AgentStoreError as error:
        raise _error(error) from error


@app.delete("/api/agents/{agent_id}", status_code=204)
def delete_agent(agent_id: str):
    try:
        store.delete(agent_id)
    except AgentStoreError as error:
        raise _error(error, 404) from error


@app.put("/api/agents/{agent_id}")
def save_agent(agent_id: str, config: dict):
    try:
        return {"id": agent_id, "config": store.save(agent_id, config)}
    except AgentStoreError as error:
        raise _error(error) from error


@app.post("/api/agents/{agent_id}/test-call")
def test_call(agent_id: str):
    try:
        store.activate(agent_id)
    except AgentStoreError as error:
        raise _error(error) from error
    return {
        "agent_id": agent_id,
        "url": os.getenv("CALL_CLIENT_URL", "http://localhost:7860/client/"),
        "selection": "next_call",
    }


@app.get("/api/tools")
def list_tools():
    return {"tools": list(SCHEDULING_TOOL_NAMES)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
