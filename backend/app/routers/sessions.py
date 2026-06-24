"""Session management API — lists threads, history, results from Lakebase.

Uses the supervisor service to query DatabricksStore for thread tracking
data. Requires agent_id to identify which supervisor endpoint to query.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import AgentModel
from app.schemas.session import (
    MessageEntry,
    ResultsIndexEntry,
    SessionHistoryResponse,
    SessionListResponse,
    SessionSummary,
    ThreadMetadata,
)
from app.services.supervisor_service import supervisor_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


async def _get_agent_endpoint(
    agent_id: str,
    session: AsyncSession,
) -> str:
    """Look up a registered agent and return its endpoint_url."""
    result = await session.execute(
        select(AgentModel).where(AgentModel.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return agent.endpoint_url


@router.get("")
async def list_sessions(
    agent_id: str = Query(..., description="ID of the agent/supervisor"),
    user_id: str = Query(..., description="User identifier"),
    limit: int = Query(50, description="Max threads to return"),
    session: AsyncSession = Depends(get_session),
) -> SessionListResponse:
    """List all conversation threads for a user on a given agent."""
    endpoint_url = await _get_agent_endpoint(agent_id, session)
    threads = await supervisor_service.list_threads_for_user(
        endpoint_url, user_id, limit=limit,
    )
    summaries = [
        SessionSummary(
            thread_id=t.get("thread_id", ""),
            title=t.get("title", "New conversation"),
            created_at=t.get("created_at", ""),
            correlation_id=t.get("correlation_id"),
        )
        for t in threads
    ]
    return SessionListResponse(sessions=summaries)


@router.get("/{thread_id}")
async def get_session_history(
    thread_id: str,
    agent_id: str = Query(..., description="ID of the agent/supervisor"),
    session: AsyncSession = Depends(get_session),
) -> SessionHistoryResponse:
    """Get full conversation history for a thread."""
    endpoint_url = await _get_agent_endpoint(agent_id, session)
    messages = await supervisor_service.get_history(endpoint_url, thread_id)
    entries = [MessageEntry(role=m["role"], content=m["content"]) for m in messages]
    return SessionHistoryResponse(thread_id=thread_id, messages=entries)


@router.get("/{thread_id}/results")
async def get_session_results(
    thread_id: str,
    agent_id: str = Query(..., description="ID of the agent/supervisor"),
    session: AsyncSession = Depends(get_session),
) -> List[ResultsIndexEntry]:
    """Get per-turn CSV metadata for a thread."""
    endpoint_url = await _get_agent_endpoint(agent_id, session)
    results = await supervisor_service.get_results_index(endpoint_url, thread_id)
    return [ResultsIndexEntry(**r) for r in results]


@router.get("/{thread_id}/metadata")
async def get_session_metadata(
    thread_id: str,
    agent_id: str = Query(..., description="ID of the agent/supervisor"),
    session: AsyncSession = Depends(get_session),
) -> ThreadMetadata:
    """Get tracking metadata for a thread."""
    endpoint_url = await _get_agent_endpoint(agent_id, session)
    meta = await supervisor_service.get_thread_metadata(endpoint_url, thread_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Thread not found")
    return ThreadMetadata(
        thread_id=meta.get("thread_id", thread_id),
        user_id=meta.get("user_id"),
        correlation_id=meta.get("correlation_id"),
        created_at=meta.get("created_at"),
    )


@router.delete("/{thread_id}")
async def delete_session(
    thread_id: str,
    agent_id: str = Query(..., description="ID of the agent/supervisor"),
    session: AsyncSession = Depends(get_session),
):
    """Delete a thread from Lakebase (store + checkpoints)."""
    endpoint_url = await _get_agent_endpoint(agent_id, session)
    await supervisor_service.delete_thread(endpoint_url, thread_id)
    return {"status": "deleted", "thread_id": thread_id}
