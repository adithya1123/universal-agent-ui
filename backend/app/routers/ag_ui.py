"""AG-UI endpoint — bridges CopilotKit Runtime to the supervisor client.

Expects POST /ag-ui/run with:
    messages: list[{"role": "user", "content": "..."}]
    thread_id: str | null (null = new conversation)
    agent_id: str | null (identifies which registered agent/supervisor to use)
    user_id: str | null

Returns a text/event-stream with JSON SSE events:
    {"type": "text", "content": "..."}      — text delta from the agent
    {"type": "routing", "agent": "..."}     — supervisor dispatching to a sub-agent
    {"type": "reasoning", "content": "..."} — intermediate thinking/reasoning
    data: [DONE]                            — stream complete
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import AgentModel
from app.services.supervisor_service import supervisor_service
from fastapi import Depends

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ag-ui"])


class RunRequest(BaseModel):
    messages: list[dict]
    thread_id: str | None = None
    agent_id: str | None = None
    user_id: str | None = None


async def _stream_agent_response(
    endpoint_url: str,
    thread_id: str,
    question: str,
) -> AsyncGenerator[bytes, None]:
    """Stream supervisor agent response as JSON SSE events."""
    stream = await supervisor_service.query_stream(
        endpoint_url=endpoint_url,
        thread_id=thread_id,
        question=question,
    )

    async for event in stream:
        if event.type == "text_delta":
            payload = json.dumps({"type": "text", "content": event.text})
            yield f"data: {payload}\n\n".encode()
        elif event.type == "routing":
            payload = json.dumps({"type": "routing", "agent": event.agent})
            yield f"data: {payload}\n\n".encode()
        elif event.type == "reasoning":
            payload = json.dumps({"type": "reasoning", "content": event.text})
            yield f"data: {payload}\n\n".encode()
        elif event.type == "completed":
            pass

    yield b"data: [DONE]\n\n"


@router.post("/ag-ui/run")
async def ag_ui_run(
    req: RunRequest,
    session: AsyncSession = Depends(get_session),
):
    # Extract the last user message as the question
    if not req.messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    last_msg = req.messages[-1]
    if last_msg.get("role") != "user" or not last_msg.get("content"):
        raise HTTPException(status_code=400, detail="Last message must be from user with content")

    question = last_msg["content"]

    # Look up agent endpoint
    if not req.agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")

    result = await session.execute(
        select(AgentModel).where(AgentModel.id == req.agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent {req.agent_id} not found",
        )

    endpoint_url = agent.endpoint_url

    # Create or re-use thread (always call create_session to write tracking metadata)
    thread_id = await supervisor_service.create_session(
        endpoint_url=endpoint_url,
        thread_id=req.thread_id,
        user_id=req.user_id,
        correlation_id=None,
    )

    return StreamingResponse(
        _stream_agent_response(
            endpoint_url=endpoint_url,
            thread_id=thread_id,
            question=question,
        ),
        media_type="text/event-stream",
        headers={
            "X-Thread-Id": thread_id,
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )
