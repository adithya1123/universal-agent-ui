"""User memory API — long-term memory CRUD via DatabricksStore.

Follows the Databricks agent-langgraph-advanced template pattern for
user memories: stored under ("user_memories", sanitized_user_id).

Usage:
    GET    /api/memory?agent_id=...&user_id=...&query=...  -> search/list
    GET    /api/memory/{key}?agent_id=...&user_id=...      -> get specific
    POST   /api/memory                                      -> save
    DELETE /api/memory/{key}?agent_id=...&user_id=...      -> delete
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import AgentModel
from app.memory import UserMemoryService
from app.services.supervisor_service import supervisor_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["memory"])


class SaveMemoryRequest(BaseModel):
    agent_id: str
    user_id: str
    key: str
    data: dict


async def _get_memory_service(
    agent_id: str,
    session: AsyncSession,
) -> UserMemoryService:
    result = await session.execute(
        select(AgentModel).where(AgentModel.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return await supervisor_service.get_memory_service(agent.endpoint_url)


@router.get("")
async def list_memories(
    agent_id: str = Query(..., description="Agent/supervisor ID"),
    user_id: str = Query(..., description="User identifier"),
    query: Optional[str] = Query(None, description="Optional search query"),
    limit: int = Query(50, description="Max results"),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    ms = await _get_memory_service(agent_id, session)
    if query:
        return await ms.search_memories(user_id, query, limit=limit)
    return await ms.list_memories(user_id, limit=limit)


@router.get("/{key}")
async def get_memory(
    key: str,
    agent_id: str = Query(..., description="Agent/supervisor ID"),
    user_id: str = Query(..., description="User identifier"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ms = await _get_memory_service(agent_id, session)
    memory = await ms.get_memory(user_id, key)
    if not memory:
        raise HTTPException(status_code=404, detail=f"Memory '{key}' not found for user")
    return memory


@router.post("")
async def save_memory(
    req: SaveMemoryRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    ms = await _get_memory_service(req.agent_id, session)
    await ms.save_memory(req.user_id, req.key, req.data)
    return {"status": "saved", "key": req.key, "user_id": req.user_id}


@router.delete("/{key}")
async def delete_memory(
    key: str,
    agent_id: str = Query(..., description="Agent/supervisor ID"),
    user_id: str = Query(..., description="User identifier"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ms = await _get_memory_service(agent_id, session)
    existed = await ms.delete_memory(user_id, key)
    if not existed:
        raise HTTPException(status_code=404, detail=f"Memory '{key}' not found for user")
    return {"status": "deleted", "key": key, "user_id": user_id}
