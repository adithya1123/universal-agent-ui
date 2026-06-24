import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import AgentModel
from app.schemas.chat import ChatRequest, Message
from app.schemas.agent import AgentConfig, AgentResponse
from app.services.supervisor_service import supervisor_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


def _to_response(model: AgentModel) -> AgentResponse:
    return AgentResponse(
        id=model.id,
        name=model.name,
        endpoint_url=model.endpoint_url,
        endpoint_type=model.endpoint_type,
        description=model.description,
        created_at=model.created_at,
    )


@router.get("")
async def list_agents(session: AsyncSession = Depends(get_session)) -> list[AgentResponse]:
    result = await session.execute(select(AgentModel).order_by(AgentModel.created_at.desc()))
    agents = result.scalars().all()
    return [_to_response(a) for a in agents]


@router.post("")
async def register_agent(
    cfg: AgentConfig,
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    model = AgentModel(
        name=cfg.name,
        endpoint_url=cfg.endpoint_url,
        endpoint_type=cfg.endpoint_type or "supervisor",
        api_key=cfg.api_key or "",
        description=cfg.description or "",
    )
    session.add(model)
    await session.commit()
    await session.refresh(model)
    return _to_response(model)


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(AgentModel).where(AgentModel.id == agent_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Agent not found")
    await session.delete(model)
    await session.commit()
    return {"status": "deleted"}


async def _extract_question(messages: list[Message]) -> str:
    """Extract the last user message content."""
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    last_msg = messages[-1]
    if last_msg.role != "user" or not last_msg.content:
        raise HTTPException(status_code=400, detail="Last message must be from user with content")
    return last_msg.content


@router.post("/{agent_id}/chat")
async def chat(
    agent_id: str,
    req: ChatRequest,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(AgentModel).where(AgentModel.id == agent_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Agent not found")

    endpoint_url = model.endpoint_url
    question = await _extract_question(req.messages)

    thread_id = await supervisor_service.create_session(
        endpoint_url=endpoint_url,
        thread_id=req.thread_id,
        user_id=req.user_id,
        correlation_id=None,
    )

    if req.stream:
        async def _stream():
            stream = await supervisor_service.query_stream(
                endpoint_url=endpoint_url,
                thread_id=thread_id,
                question=question,
            )
            async for event in stream:
                if event.type == "text_delta":
                    yield event.text.encode("utf-8")
                elif event.type == "completed":
                    pass

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={
                "X-Thread-Id": thread_id,
                "X-Accel-Buffering": "no",
                "Cache-Control": "no-cache",
            },
        )

    # Non-streaming: consume the stream and return the result
    stream_resp = await supervisor_service.query_stream(
        endpoint_url=endpoint_url,
        thread_id=thread_id,
        question=question,
    )
    async for _ in stream_resp:
        pass

    result_text = stream_resp.result.final_answer if stream_resp.result else ""
    return {
        "thread_id": thread_id,
        "message": Message(role="assistant", content=result_text).model_dump(),
    }
