import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.adapters.mlflow_responses import invoke_agent, stream_agent
from app.schemas.chat import ChatRequest
from app.schemas.agent import AgentConfig, AgentResponse

router = APIRouter(prefix="/agents", tags=["agents"])

_agents_store: dict[str, AgentConfig] = {}


@router.get("")
async def list_agents() -> list[AgentResponse]:
    return [
        AgentResponse(
            id=aid,
            name=cfg.name,
            endpoint_url=cfg.endpoint_url,
            endpoint_type=cfg.endpoint_type,
            description=cfg.description,
            created_at="",
        )
        for aid, cfg in _agents_store.items()
    ]


@router.post("")
async def register_agent(cfg: AgentConfig) -> AgentResponse:
    agent_id = str(uuid.uuid4())
    cfg.id = agent_id
    _agents_store[agent_id] = cfg
    return AgentResponse(
        id=agent_id,
        name=cfg.name,
        endpoint_url=cfg.endpoint_url,
        endpoint_type=cfg.endpoint_type,
        description=cfg.description,
        created_at="",
    )


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    if agent_id not in _agents_store:
        raise HTTPException(status_code=404, detail="Agent not found")
    del _agents_store[agent_id]
    return {"status": "deleted"}


@router.post("/{agent_id}/chat")
async def chat(agent_id: str, req: ChatRequest):
    if agent_id not in _agents_store:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = _agents_store[agent_id]

    if req.stream:
        return StreamingResponse(
            stream_agent(agent.endpoint_url, req.messages, agent.api_key, req.thread_id),
            media_type="text/event-stream",
        )

    result = await invoke_agent(agent.endpoint_url, req.messages, agent.api_key, req.thread_id)
    return {"thread_id": req.thread_id or "", "message": result.model_dump()}
