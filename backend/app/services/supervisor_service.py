"""Pool of AsyncLangGraphSupervisor clients, one per agent endpoint.

Maintains a dict[endpoint_url -> AsyncLangGraphSupervisor] so that
multiple agents (different supervisor endpoints) each get their own
client with its own Lakebase checkpointer and store connections.
Clients are lazily initialized on first use and cleaned up on shutdown.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.memory import MemoryExtractor, UserMemoryService
from app.supervisor import AsyncLangGraphSupervisor

logger = logging.getLogger(__name__)


class SupervisorService:
    """Manages a pool of AsyncLangGraphSupervisor instances.

    Usage:
        svc = SupervisorService()
        await svc.start()
        stream = await svc.query_stream(
            endpoint_url="https://.../serving-endpoints/name/invocations",
            thread_id="...",
            question="What is X?",
            user_id="user@co.com",
        )
        async for event in stream:
            ...
        await svc.stop()
    """

    def __init__(self) -> None:
        self._clients: Dict[str, AsyncLangGraphSupervisor] = {}
        self._started = False

    async def start(self) -> None:
        """Pre-warm: no-op. Clients are created lazily on first use."""
        self._started = True
        logger.info("SupervisorService started (lazy client initialization)")

    async def stop(self) -> None:
        """Close all supervisor clients."""
        for url, client in self._clients.items():
            try:
                await client.close()
                logger.info("Closed supervisor client for endpoint: %s", url)
            except Exception as e:
                logger.warning("Error closing supervisor client %s: %s", url, e)
        self._clients.clear()
        self._started = False
        logger.info("SupervisorService stopped")

    async def _get_client(self, endpoint_url: str) -> AsyncLangGraphSupervisor:
        """Get or create a supervisor client for the given endpoint URL."""
        if endpoint_url in self._clients:
            return self._clients[endpoint_url]

        # Sanitize empty string defaults to None
        def _val(v: str) -> str | None:
            return v if v else None

        client = AsyncLangGraphSupervisor(
            endpoint_url=endpoint_url,
            client_id=_val(settings.databricks_client_id),
            client_secret=_val(settings.databricks_client_secret),
            token=_val(settings.databricks_token),
            lakebase_project=_val(settings.lakebase_autoscaling_project),
            lakebase_branch=_val(settings.lakebase_autoscaling_branch),
            lakebase_instance_name=_val(settings.lakebase_instance_name),
            embedding_endpoint=settings.embedding_endpoint,
            embedding_dims=settings.embedding_dims,
            max_history=settings.max_history,
            timeout=settings.supervisor_timeout,
            databricks_host=_val(settings.databricks_host),
            result_volume_path=_val(settings.result_volume_path),
            memory_extraction_enabled=settings.memory_extraction_enabled,
            memory_extraction_model=settings.memory_extraction_model,
        )
        await client.__aenter__()
        await client.setup()
        self._clients[endpoint_url] = client
        logger.info(
            "Initialized supervisor client for endpoint: %s",
            endpoint_url,
        )
        return client

    async def create_session(
        self,
        endpoint_url: str,
        thread_id: Optional[str] = None,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        """Create or reuse a conversation thread. If thread_id is provided,
        it reuses that thread and writes tracking metadata (idempotent PutOp)."""
        client = await self._get_client(endpoint_url)
        return await client.create_session(
            thread_id=thread_id,
            user_id=user_id,
            correlation_id=correlation_id,
        )

    async def query_stream(
        self,
        endpoint_url: str,
        thread_id: str,
        question: str,
        *,
        auto_approve_tools: bool | None = None,
    ):
        """Stream a query through the supervisor client.

        Defaults to settings.auto_approve_tools (env AUTO_APPROVE_TOOLS).

        Returns an object that can be iterated with ``async for``,
        yielding StreamEvent objects.
        """
        if auto_approve_tools is None:
            auto_approve_tools = settings.auto_approve_tools
        client = await self._get_client(endpoint_url)
        return await client.query_stream(
            thread_id=thread_id,
            question=question,
            auto_approve_tools=auto_approve_tools,
        )

    async def list_threads_for_user(
        self, endpoint_url: str, user_id: str, *, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List all threads for a user."""
        client = await self._get_client(endpoint_url)
        return await client.list_threads_for_user(user_id, limit=limit)

    async def get_history(
        self, endpoint_url: str, thread_id: str,
    ) -> List[Dict[str, str]]:
        """Get full conversation history for a thread."""
        client = await self._get_client(endpoint_url)
        return await client.get_history(thread_id)

    async def get_results_index(
        self, endpoint_url: str, thread_id: str,
    ) -> List[Dict[str, Any]]:
        """Get per-turn CSV metadata for a thread."""
        client = await self._get_client(endpoint_url)
        return await client.get_results_index(thread_id)

    async def get_thread_metadata(
        self, endpoint_url: str, thread_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get tracking metadata for a thread."""
        client = await self._get_client(endpoint_url)
        return await client.get_thread_metadata(thread_id)

    async def delete_thread(
        self, endpoint_url: str, thread_id: str,
    ) -> None:
        """Delete a thread from Lakebase (store + checkpoints)."""
        client = await self._get_client(endpoint_url)
        await client.delete_thread(thread_id)

    async def update_thread_title(
        self, endpoint_url: str, thread_id: str, title: str,
    ) -> None:
        """Update the title for a thread in DatabricksStore."""
        client = await self._get_client(endpoint_url)
        await client.update_thread_title(thread_id, title)

    async def generate_thread_title(
        self, endpoint_url: str, thread_id: str,
    ) -> str:
        """Auto-generate a title for a thread via LLM. Returns the new title."""
        client = await self._get_client(endpoint_url)
        return await client.generate_thread_title(thread_id)

    async def get_memory_service(
        self, endpoint_url: str,
    ) -> UserMemoryService:
        """Get a UserMemoryService backed by the store of the given endpoint."""
        client = await self._get_client(endpoint_url)
        if client._store is None:
            raise RuntimeError("Store not initialized for endpoint: %s", endpoint_url)
        return UserMemoryService(client._store)

    async def get_memory_bundle(
        self, endpoint_url: str,
    ) -> tuple[UserMemoryService, MemoryExtractor | None]:
        """Get both UserMemoryService and MemoryExtractor for the endpoint."""
        client = await self._get_client(endpoint_url)
        if client._store is None:
            raise RuntimeError("Store not initialized for endpoint: %s", endpoint_url)
        return UserMemoryService(client._store), client._memory_extractor


# Global singleton
supervisor_service = SupervisorService()
