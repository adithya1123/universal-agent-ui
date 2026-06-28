"""Async LangGraph-based supervisor agent client with Lakebase dual-store persistence.

Uses AsyncDatabricksOpenAI (Responses API) for non-blocking streaming queries,
AsyncCheckpointSaver for short-term conversation state, and AsyncDatabricksStore
for long-term thread tracking -- following the Databricks agent-langgraph-advanced
reference architecture.

Dual-store architecture:
    AsyncCheckpointSaver  -> checkpoints table  -> conversation state (messages, results)
    AsyncDatabricksStore  -> store table         -> thread tracking index
        Namespace ("threads",)                   -> thread_id -> full metadata
        Namespace ("by_user", <user_id>)         -> thread_id -> thread ref
        Namespace ("by_correlation", <corr_id>)  -> thread_id -> thread ref
        Namespace ("messages", <thread_id>)      -> message_id -> turn metadata

This module delivers async streaming events with full production error detection:
    - AsyncStreamingResponse yields StreamEvent via ``async for``
    - Full production error detection (databricks_output.error, response.failed,
      response.incomplete, message-level pattern matching)
    - CSV extraction from sub-agent responses, tool outputs, markdown tables
    - _PersistingStreamWrapper auto-persists after stream consumption
    - Per-turn results_index accumulates CSV metadata for UI retrieval

Dependencies:
    pip install databricks-openai "databricks-langchain[memory]" langgraph \\
        uuid-utils typing_extensions --upgrade

Usage:
    import asyncio
    from app.supervisor import AsyncLangGraphSupervisor

    async def main():
        async with AsyncLangGraphSupervisor(
            endpoint_url="https://<host>/serving-endpoints/<name>/invocations",
            client_id="<service-principal-id>",
            client_secret="<oauth-secret>",
            lakebase_project="my-project",
            lakebase_branch="dev",
        ) as client:
            await client.setup()

            thread_id = await client.create_session(
                user_id="user@co.com",
                correlation_id="app-session-abc",
            )

            stream = await client.query_stream(thread_id, "What is the total sales?")
            async for event in stream:
                if event.type == "text_delta":
                    print(event.text, end="", flush=True)
            result = stream.result
            result.display()

            threads = await client.list_threads_for_user("user@co.com")

    asyncio.run(main())

Classes:
    AsyncLangGraphSupervisor   - Async client with LangGraph state management
    AsyncStreamingResponse     - Async iterable yielding StreamEvent, builds AgentResult
    _PersistingStreamWrapper   - Thin wrapper that persists + extracts CSV after consumption
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import AsyncExitStack
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    from databricks_openai import AsyncDatabricksOpenAI
except ImportError:
    raise ImportError(
        "databricks-openai is required. "
        "Install with: pip install databricks-openai --upgrade"
    )

try:
    from databricks.sdk import WorkspaceClient
except ImportError:
    raise ImportError(
        "databricks-sdk is required. "
        "Install with: pip install databricks-sdk --upgrade"
    )

try:
    from databricks_langchain import AsyncCheckpointSaver, AsyncDatabricksStore
except ImportError:
    raise ImportError(
        "databricks-langchain[memory] is required. "
        "Install with: pip install 'databricks-langchain[memory]' --upgrade"
    )

try:
    from langgraph.graph import StateGraph, END
    from langgraph.store.base import GetOp, PutOp
except ImportError:
    raise ImportError(
        "langgraph is required. "
        "Install with: pip install langgraph --upgrade"
    )

try:
    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
except ImportError:
    raise ImportError(
        "langchain-core is required. "
        "Install with: pip install langchain-core --upgrade"
    )

# User memory service + extraction
from app.config import settings
from app.memory import MemoryExtractor, UserMemoryService

# Streaming primitives
from app.supervisor.streaming import (
    AsyncStreamingResponse,
    _ApprovalLoopStream,
    _PersistingStreamWrapper,
)

# Shared types and helpers (self-contained)
from app.supervisor.helpers import (
    AgentResult,
    _Limits,
    _build_config,
    _categorize_exception,
    _create_volume_writer,
    _now_iso,
    _NS_BY_CORRELATION,
    _NS_BY_USER,
    _NS_THREADS,
    _sanitize_ns,
)

# Time-ordered UUIDs (fallback to uuid4)
try:
    import uuid_utils
    def _uuid_gen() -> str:
        return str(uuid_utils.uuid7())
except ImportError:
    import uuid
    def _uuid_gen() -> str:
        return str(uuid.uuid4())

__all__ = [
    "AsyncLangGraphSupervisor",
    "AsyncStreamingResponse",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------

class AgentState(dict):
    """LangGraph state for supervisor agent queries.

    Fields:
        messages:       Conversation history (HumanMessage / AIMessage)
        agent_result:   Last AgentResult as dict (overwritten each turn)
        results_index:  Per-turn metadata accumulator for UI (CSV paths, etc.)
        thread_id:      Thread identifier

    Tracking fields (user_id, correlation_id, message_id) are stored in the
    DatabricksStore, not in checkpoint state -- following the Databricks
    agent-langgraph-advanced template pattern.
    """
    messages: List[BaseMessage]
    agent_result: Optional[dict]
    results_index: List[dict]
    thread_id: str




# ---------------------------------------------------------------------------
# AsyncLangGraphSupervisor
# ---------------------------------------------------------------------------

class AsyncLangGraphSupervisor:
    """Async supervisor agent client with dual-store Lakebase persistence.

    Follows the Databricks agent-langgraph-advanced reference architecture:
        - AsyncCheckpointSaver for short-term conversation state (checkpoints table)
        - AsyncDatabricksStore for long-term thread tracking index (store table)

    Tracking fields (user_id, thread_id, correlation_id, message_id) are
    stored in DatabricksStore namespaces, queryable via list_threads_for_user()
    and list_threads_for_correlation().

    Supports both Lakebase Autoscaling (project + branch) and Provisioned
    (instance_name). Autoscaling is preferred for new deployments.

    Example:
        async with AsyncLangGraphSupervisor(
            endpoint_url=url, token=tok,
            lakebase_project="agent-memory-store",
            lakebase_branch="dev",
        ) as client:
            await client.setup()

            tid = await client.create_session(
                user_id="user@co.com",
                correlation_id="ui-session-xyz",
            )
            stream = await client.query_stream(tid, "What is X?")
            async for event in stream:
                if event.type == "text_delta":
                    print(event.text, end="", flush=True)
            result = stream.result

            # Query by user (uses DatabricksStore)
            threads = await client.list_threads_for_user("user@co.com")
    """

    def __init__(
        self,
        endpoint_url: str,
        token: Optional[str] = None,
        *,
        workspace_client: Optional[WorkspaceClient] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        lakebase_project: Optional[str] = None,
        lakebase_branch: Optional[str] = None,
        lakebase_instance_name: Optional[str] = None,
        embedding_endpoint: str = "databricks-gte-large-en",
        embedding_dims: int = 1024,
        max_history: int = 10,
        timeout: int = 300,
        databricks_host: Optional[str] = None,
        result_volume_path: Optional[str] = None,
        memory_extraction_enabled: bool = True,
        memory_extraction_model: str = "deepseek-v4flash-chat",
    ) -> None:
        parsed = urlparse(endpoint_url)
        self._host = databricks_host or f"{parsed.scheme}://{parsed.netloc}"
        path_parts = parsed.path.strip("/").split("/")
        try:
            idx = path_parts.index("serving-endpoints")
            self.endpoint_name = path_parts[idx + 1]
        except (ValueError, IndexError):
            self.endpoint_name = endpoint_url

        self.max_history = max_history
        self.timeout = timeout
        self._result_volume = result_volume_path or \
            "/Volumes/tpo_d/tpo_data_model/tpo_genai_session_results"
        self._memory_extraction_enabled = memory_extraction_enabled
        self._memory_extraction_model = memory_extraction_model

        # Lakebase connection params (deferred initialization in __aenter__)
        self._lakebase_project = lakebase_project
        self._lakebase_branch = lakebase_branch
        self._lakebase_instance = lakebase_instance_name
        self._embedding_endpoint = embedding_endpoint
        self._embedding_dims = embedding_dims

        if not lakebase_project and not lakebase_instance_name:
            raise ValueError(
                "Provide either lakebase_project (+ lakebase_branch) for Autoscaling "
                "or lakebase_instance_name for Provisioned."
            )

        # Auth priority: workspace_client > client_id/secret (OAuth M2M) > token (PAT).
        # OAuth M2M gives auto-refresh; PAT is static and expires.
        # databricks-openai >= 0.15 requires auth via WorkspaceClient.
        if workspace_client is not None:
            self._ws = workspace_client
        elif client_id and client_secret:
            self._ws = WorkspaceClient(
                host=self._host, client_id=client_id, client_secret=client_secret,
            )
        elif token is not None:
            self._ws = WorkspaceClient(host=self._host, token=token)
        else:
            raise ValueError(
                "Provide one of: workspace_client, client_id+client_secret, or token."
            )
        self._client = AsyncDatabricksOpenAI(workspace_client=self._ws)
        # Dual-mode volume writer: FUSE on Databricks compute, SDK externally
        self._volume_writer = _create_volume_writer(self._ws)

        # Placeholders -- initialized in __aenter__
        self._checkpointer: Optional[AsyncCheckpointSaver] = None
        self._store: Optional[AsyncDatabricksStore] = None
        self._graph: Optional[Any] = None
        self._memory_extractor: Optional[MemoryExtractor] = None
        self._memory_extraction_disabled: List[bool] = [False]
        self._exit_stack: Optional[AsyncExitStack] = None

        logger.info(
            "AsyncLangGraphSupervisor configured: endpoint=%s lakebase=%s/%s",
            self.endpoint_name,
            lakebase_project or lakebase_instance_name,
            lakebase_branch or "",
        )

    async def __aenter__(self) -> AsyncLangGraphSupervisor:
        """Open async connections to Lakebase and build the graph."""
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        # Build connection kwargs shared by both stores
        if self._lakebase_project:
            conn_kwargs = {
                "project": self._lakebase_project,
                "branch": self._lakebase_branch or "main",
            }
        else:
            conn_kwargs = {"instance_name": self._lakebase_instance}

        # Pass workspace_client for unified auth (OAuth M2M auto-refresh)
        conn_kwargs["workspace_client"] = self._ws

        # AsyncCheckpointSaver for conversation state
        self._checkpointer = await self._exit_stack.enter_async_context(
            AsyncCheckpointSaver(**conn_kwargs)
        )

        # AsyncDatabricksStore for thread tracking index
        # Note: embedding_endpoint/dims intentionally omitted — pgvector
        # extension is not enabled on this Lakebase instance. Without
        # embeddings, the store still works for k/v thread tracking.
        self._store = await self._exit_stack.enter_async_context(
            AsyncDatabricksStore(
                **conn_kwargs,
            )
        )

        # Build LangGraph with the async checkpointer
        self._graph = self._build_graph()

        # Memory extractor (LLM-based fact extraction — optional)
        if self._memory_extraction_enabled:
            self._memory_extractor = MemoryExtractor(
                workspace_client=self._ws,
                model_endpoint=self._memory_extraction_model,
                databricks_host=self._host,
            )
            logger.info("MemoryExtractor initialized: model=%s", self._memory_extraction_model)

        logger.info("AsyncLangGraphSupervisor ready (dual-store initialized)")
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Close OpenAI client and Lakebase connections."""
        await self._client.close()
        if self._exit_stack:
            await self._exit_stack.__aexit__(*exc)

    async def close(self) -> None:
        """Explicit close (alternative to async context manager)."""
        await self.__aexit__(None, None, None)

    def _ensure_initialized(self) -> None:
        """Raise RuntimeError if the client has not been initialized via async context manager."""
        if self._graph is None:
            raise RuntimeError(
                "Client not initialized. Use 'async with AsyncLangGraphSupervisor(...) as client' "
                "or call __aenter__() first."
            )

    def _build_graph(self) -> Any:
        """Build the LangGraph StateGraph with async checkpoint persistence."""
        # Placeholder node -- actual queries bypass graph execution and
        # directly call the endpoint. The graph is used solely for state
        # checkpointing (messages + last result + results_index).
        def passthrough(state: AgentState) -> AgentState:
            return state

        graph = StateGraph(AgentState)
        graph.add_node("passthrough", passthrough)
        graph.set_entry_point("passthrough")
        graph.add_edge("passthrough", END)
        return graph.compile(checkpointer=self._checkpointer)

    # -- Setup ---------------------------------------------------------------

    async def setup(self) -> None:
        """Create checkpoint and store tables in Lakebase (idempotent).

        Call once after entering the async context manager. Safe to re-run.

        Replaces the old setup_tracking_columns() -- tracking is now handled
        by the DatabricksStore, no custom DDL or triggers needed.
        """
        self._ensure_initialized()
        await self._checkpointer.setup()
        await self._store.setup()
        logger.info("Lakebase setup complete (checkpoints + store tables)")

    # -- Store-based tracking ------------------------------------------------

    async def _write_thread_tracking(
        self,
        thread_id: str,
        user_id: Optional[str],
        correlation_id: Optional[str],
    ) -> None:
        """Write thread tracking entries to the DatabricksStore.

        Creates three index entries:
          1. ("threads",) / thread_id          -> full metadata
          2. ("by_user", <user_id>) / thread_id -> thread reference
          3. ("by_correlation", <corr>) / thread_id -> thread reference
        """
        ts = _now_iso()
        thread_meta = {
            "thread_id": thread_id,
            "user_id": user_id,
            "correlation_id": correlation_id,
            "created_at": ts,
            "title": "New conversation",
        }

        # Derive index entries from the single source of truth
        user_ref = {k: v for k, v in thread_meta.items() if k != "user_id"}
        corr_ref = {k: v for k, v in thread_meta.items() if k != "correlation_id"}

        # Batch-write all namespaces in one call
        ops = [PutOp(namespace=_NS_THREADS, key=thread_id, value=thread_meta)]
        if user_id:
            ops.append(PutOp(
                namespace=(*_NS_BY_USER, _sanitize_ns(user_id)),
                key=thread_id, value=user_ref,
            ))
        if correlation_id:
            ops.append(PutOp(
                namespace=(*_NS_BY_CORRELATION, _sanitize_ns(correlation_id)),
                key=thread_id, value=corr_ref,
            ))
        await self._store.abatch(ops)

    async def _get_tracking_fields(
        self, thread_id: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Read user_id, correlation_id, and title from the store for a thread."""
        item = await self._store.aget(_NS_THREADS, thread_id)
        if item:
            val = item.value
            return val.get("user_id"), val.get("correlation_id"), val.get("title")
        return None, None, None

    # -- Session lifecycle ---------------------------------------------------

    async def create_session(
        self,
        thread_id: Optional[str] = None,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        """Create a new conversation thread. Returns thread_id.

        Args:
            thread_id:      Optional explicit thread ID (auto-generated if None).
            user_id:        User identifier -- stored in DatabricksStore for querying.
            correlation_id: App-level tracking ID (e.g. UI session, batch run).
        """
        self._ensure_initialized()
        thread_id = thread_id or _uuid_gen()
        config = _build_config(thread_id)

        # Only initialize checkpoint state + tracking for new threads
        existing = await self._store.aget(_NS_THREADS, thread_id)
        if not existing:
            initial_state = AgentState(
                messages=[],
                agent_result=None,
                results_index=[],
                thread_id=thread_id,
            )
            await self._graph.aupdate_state(config, initial_state, as_node="passthrough")
            await self._write_thread_tracking(thread_id, user_id, correlation_id)

        logger.info(
            "Created session thread_id=%s user_id=%s correlation_id=%s",
            thread_id, user_id, correlation_id,
        )
        return thread_id

    # -- State helpers -------------------------------------------------------

    async def _get_state(
        self, thread_id: str, checkpoint_id: Optional[str] = None,
    ) -> Tuple[dict, List[BaseMessage]]:
        """Load current state and messages for a thread."""
        config = _build_config(thread_id, checkpoint_id=checkpoint_id)
        snapshot = await self._graph.aget_state(config)
        state = snapshot.values or {}
        messages = state.get("messages", [])
        return config, messages

    def _messages_to_input(self, messages: List[BaseMessage]) -> List[Dict[str, str]]:
        """Convert LangChain messages to Responses API input format with sliding window."""
        window = messages[-self.max_history * 2:]
        return [
            {"role": "user" if isinstance(m, HumanMessage) else "assistant",
             "content": m.content}
            for m in window
        ]

    # -- Direct SSE streaming (bypass databricks-openai Responses API) -------
    
    async def _sse_stream(
        self,
        input_messages: List[Dict[str, str]],
        *,
        timeout: int = 300,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[SimpleNamespace, None]:
        """Make a direct HTTP request to the Databricks serving endpoint and
        yield SSE events as SimpleNamespace objects matching the OpenAI
        Responses API event shape.
        """
        import httpx

        headers = self._ws.config.authenticate()
        headers["Content-Type"] = "application/json"

        body: Dict[str, Any] = {
            "input": input_messages,
            "stream": True,
            "databricks_options": {"return_trace": True},
        }

        url = f"{self._host}/serving-endpoints/{self.endpoint_name}/invocations"

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            async with client.stream("POST", url, headers=headers, json=body) as resp:
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if line in ("", "data:", "data: [DONE]", "[DONE]"):
                        continue
                    prefix = "data: " if line.startswith("data: ") else "data:" if line.startswith("data:") else ""
                    payload = line[len(prefix):] if prefix else line
                    if not payload.strip():
                        continue
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    evt_type = data.get("type", "")
                    evt = SimpleNamespace()
                    evt.type = evt_type
                    evt.delta = data.get("delta", None) if evt_type == "response.output_text.delta" else None
                    evt.item = data.get("item", None) if evt_type == "response.output_item.done" else None
                    evt.response = data.get("response", None) if evt_type in ("response.completed", "response.failed") else None
                    evt.databricks_output = data.get("databricks_output", None) or \
                        (data.get("response", {}).get("databricks_output") if evt_type in ("response.completed", "response.failed") else None)
                    yield evt

                # Emit a synthetic completed event at [DONE]
                yield SimpleNamespace(type="response.completed", response=None, delta=None, item=None, databricks_output=None)

    # -- Memory context injection --------------------------------------------

    async def _inject_memory_context(
        self,
        input_messages: List[Dict[str, str]],
        user_id: Optional[str],
    ) -> List[Dict[str, str]]:
        """Inject relevant user memories as context before the last user message.

        Uses UserMemoryService.format_for_context() for structured formatting
        with agent instructions. No-op if user_id is missing or no memories found.
        """
        if not user_id:
            return input_messages
        try:
            ms = UserMemoryService(self._store)
            memories = await ms.list_memories_for_injection(
                user_id, limit=settings.memory_injection_max,
            )
        except Exception as e:
            logger.debug("Memory injection skipped: %s", e)
            return input_messages

        if not memories:
            return input_messages

        context_text = ms.format_for_context(memories)

        if input_messages and input_messages[-1].get("role") == "user":
            insert_idx = len(input_messages) - 1
            input_messages.insert(insert_idx, {
                "role": "user",
                "content": context_text,
            })

        # Bump access counts for injected memories (fire-and-forget)
        for mem in memories:
            try:
                await ms.bump_access(user_id, mem.get("key", ""))
            except Exception:
                logger.debug("Failed to bump access for memory key=%s", mem.get("key"))

        logger.info(
            "Injected %d memories for user=%s into query context",
            len(memories), user_id,
        )
        return input_messages

    # -- Async streaming query -----------------------------------------------
    
    async def query_stream(
        self,
        thread_id: str,
        question: str,
        *,
        timeout: Optional[int] = None,
        store_raw: bool = False,
        checkpoint_id: Optional[str] = None,
        auto_approve_tools: bool = True,
        max_approval_rounds: int = 5,
    ) -> AsyncStreamingResponse:
        """Async streaming query with LangGraph session persistence.

        Returns an AsyncStreamingResponse for ``async for`` iteration.
        After iteration, ``.result`` contains the assembled AgentResult.
        The wrapper auto-persists the assistant answer to LangGraph state,
        writes message tracking to DatabricksStore, extracts CSV from
        sub-agent tabular data, and accumulates per-turn metadata in
        results_index.

        Args:
            auto_approve_tools: When True, automatically approves MCP tool
                calls (mcp_approval_request) from the Supervisor without
                user intervention. Useful for agents like tpo_logs_analyzer
                that use MCP connections.
            max_approval_rounds: Maximum number of approval loop iterations
                before failing. Prevents infinite loops. Default 5.

        Usage:
            stream = await client.query_stream(thread_id, "question",
                                              auto_approve_tools=True)
            async for event in stream:
                if event.type == "text_delta":
                    print(event.text, end="", flush=True)
            result = stream.result
        """
        self._ensure_initialized()
        config, messages = await self._get_state(thread_id, checkpoint_id)
        message_id = _uuid_gen()

        # Read tracking fields from store
        user_id, correlation_id, title = await self._get_tracking_fields(thread_id)

        # Append user message to in-memory list (persisted later by _PersistingStreamWrapper)
        messages.append(HumanMessage(content=question))

        # Build sliding-window input
        input_messages = self._messages_to_input(messages)

        # Inject relevant user memories into the message context
        input_messages = await self._inject_memory_context(
            input_messages, user_id,
        )

        # Create the async stream
        start = time.time()

        if auto_approve_tools:
            stream = None
        else:
            try:
                stream = self._sse_stream(
                    input_messages,
                    timeout=timeout or self.timeout,
                )
            except Exception as e:
                error_result = AgentResult(
                    question=question,
                    status_code=getattr(e, "status_code", 0),
                    latency_s=time.time() - start,
                    errors=[str(e)[:_Limits.ERROR_BODY]],
                    error_categories={_categorize_exception(e)},
                )
                error_msg = f"[Connection error] {str(e)[:200]}"
                messages.append(AIMessage(content=error_msg))
                try:
                    await self._graph.aupdate_state(
                        config,
                        {"messages": messages, "agent_result": error_result.to_dict()},
                        as_node="passthrough",
                    )
                except Exception:
                    logger.warning("Failed to persist state for thread %s", thread_id)
                return AsyncStreamingResponse._from_error(error_result)

        if auto_approve_tools:
            # Build a stream factory for the approval loop (re-creates streams per round)
            async def _stream_factory(input_msgs):
                return self._sse_stream(input_msgs, timeout=timeout or self.timeout)
            raw_stream = _ApprovalLoopStream(
                stream_factory=_stream_factory,
                initial_input=input_messages,
                question=question,
                start_time=start,
                store_raw=store_raw,
                max_approval_rounds=max_approval_rounds,
            )
        else:
            raw_stream = AsyncStreamingResponse(stream, question, start, store_raw)

        memory_extractor = None if self._memory_extraction_disabled[0] else self._memory_extractor

        return _PersistingStreamWrapper(
            raw_stream, self._graph, self._store, config, messages,
            thread_id, message_id,
            user_id=user_id,
            correlation_id=correlation_id,
            result_volume=self._result_volume,
            title=title,
            volume_writer=self._volume_writer,
            memory_extractor=memory_extractor,
            user_memory_service=UserMemoryService(self._store) if memory_extractor else None,
            extraction_disabled_ref=self._memory_extraction_disabled,
        )

    # -- Async blocking query (convenience) ----------------------------------

    async def query(
        self,
        thread_id: str,
        question: str,
        *,
        timeout: Optional[int] = None,
        store_raw: bool = False,
        checkpoint_id: Optional[str] = None,
        auto_approve_tools: bool = True,
        max_approval_rounds: int = 5,
    ) -> AgentResult:
        """Async blocking query -- consumes the stream internally.

        Equivalent to:
            stream = await client.query_stream(thread_id, question)
            async for _ in stream: pass
            return stream.result
        """
        self._ensure_initialized()
        stream = await self.query_stream(
            thread_id, question,
            timeout=timeout, store_raw=store_raw,
            checkpoint_id=checkpoint_id,
            auto_approve_tools=auto_approve_tools,
            max_approval_rounds=max_approval_rounds,
        )
        async for _ in stream:
            pass
        return stream.result

    # -- Tracking queries (DatabricksStore) ----------------------------------

    async def list_threads_for_user(
        self, user_id: str, *, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List all threads owned by a user.

        Reads from the DatabricksStore by_user namespace index.
        Each thread includes a ``title`` field derived from the first user
        message. New sessions start with "New conversation"; the title is
        set automatically after the first query.

        Returns list of dicts with: thread_id, title, correlation_id, created_at.
        """
        self._ensure_initialized()
        items = await self._store.asearch(
            (*_NS_BY_USER, _sanitize_ns(user_id)),
            limit=limit,
        )
        threads = [item.value for item in items]

        # Sort by created_at descending (newest first) for UI sidebar ordering
        threads.sort(key=lambda t: t.get("created_at", ""), reverse=True)

        return threads

    async def list_threads_for_correlation(
        self, correlation_id: str, *, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List all threads for a correlation_id.

        Reads from the DatabricksStore by_correlation namespace index.

        Returns list of dicts with: thread_id, user_id, created_at, title.
        """
        self._ensure_initialized()
        items = await self._store.asearch(
            (*_NS_BY_CORRELATION, _sanitize_ns(correlation_id)),
            limit=limit,
        )
        threads = [item.value for item in items]

        # Sort by created_at descending (newest first) for UI sidebar ordering
        threads.sort(key=lambda t: t.get("created_at", ""), reverse=True)

        return threads

    async def get_thread_metadata(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """Get the full tracking metadata for a single thread.

        Returns dict with: thread_id, user_id, correlation_id,
        created_at -- or None if the thread is not found.
        """
        self._ensure_initialized()
        item = await self._store.aget(_NS_THREADS, thread_id)
        return item.value if item else None

    async def delete_thread(self, thread_id: str) -> None:
        """Delete a thread from DatabricksStore and checkpoints.

        Removes thread tracking entries from all namespaces and
        deletes checkpoint data. After this, the thread is fully
        removed from Lakebase storage.
        """
        self._ensure_initialized()

        meta = await self.get_thread_metadata(thread_id)
        user_id = meta.get("user_id") if meta else None
        correlation_id = meta.get("correlation_id") if meta else None

        await self._store.adelete(_NS_THREADS, thread_id)

        if user_id:
            await self._store.adelete(
                (*_NS_BY_USER, _sanitize_ns(user_id)),
                thread_id,
            )

        if correlation_id:
            await self._store.adelete(
                (*_NS_BY_CORRELATION, _sanitize_ns(correlation_id)),
                thread_id,
            )

        try:
            await self._checkpointer.adelete_thread(thread_id)
        except Exception as e:
            logger.warning("Failed to delete checkpoint data: %s", e)

        logger.info("Deleted thread %s from Lakebase", thread_id)

    async def update_thread_title(self, thread_id: str, new_title: str) -> None:
        """Update the title for a thread across all DatabricksStore namespaces.

        Writes the new title to:
            ("threads",) / thread_id
            ("by_user", <user_id>) / thread_id
            ("by_correlation", <corr_id>) / thread_id

        Uses GetOp batch read + PutOp batch write for efficiency.
        """
        self._ensure_initialized()
        new_title = new_title.strip()[:100] if new_title else "Untitled"

        # Read existing metadata to find user_id and correlation_id
        existing_thread = await self._store.aget(_NS_THREADS, thread_id)
        if not existing_thread:
            logger.warning("update_thread_title: thread %s not found", thread_id)
            return

        user_id = existing_thread.value.get("user_id")
        corr_id = existing_thread.value.get("correlation_id")

        # Batch-read all namespace entries
        get_ops = [GetOp(namespace=_NS_THREADS, key=thread_id)]
        if user_id:
            get_ops.append(GetOp(
                namespace=(*_NS_BY_USER, _sanitize_ns(user_id)),
                key=thread_id,
            ))
        if corr_id:
            get_ops.append(GetOp(
                namespace=(*_NS_BY_CORRELATION, _sanitize_ns(corr_id)),
                key=thread_id,
            ))
        get_results = await self._store.abatch(get_ops)

        # Build batch-write with updated title
        put_ops = []
        for i, item in enumerate(get_results):
            if item and item.value:
                ns = get_ops[i].namespace
                put_ops.append(PutOp(
                    namespace=ns,
                    key=thread_id,
                    value={**item.value, "title": new_title},
                ))

        if put_ops:
            await self._store.abatch(put_ops)
            logger.info("Updated title for thread %s: '%s'", thread_id, new_title)

    async def generate_thread_title(self, thread_id: str) -> str:
        """Auto-generate a title for a thread from its conversation history.

        Loads history from checkpoint, calls MemoryExtractor.generate_title()
        via DeepSeek v4 Flash. Falls back to the first user message if the
        extractor is unavailable or LLM call fails.

        Returns:
            The generated title string (max 100 chars).
        """
        self._ensure_initialized()

        # Load conversation history from checkpoint
        history = await self.get_history(thread_id)
        if not history:
            _, _, existing_title = await self._get_tracking_fields(thread_id)
            return existing_title or "New conversation"

        # Try LLM-based title generation
        title = None
        if self._memory_extractor:
            try:
                title = await self._memory_extractor.generate_title(history)
            except PermissionError:
                logger.warning(
                    "Title generation skipped: SP lacks 'Can Query' on "
                    "serving endpoint '%s'", self._memory_extraction_model,
                )
            except Exception as e:
                logger.warning("Title generation failed: %s", e)

        # Fallback: use first user message truncated
        if not title:
            first_user = next(
                (m["content"] for m in history if m.get("role") == "user"),
                "",
            )
            title = first_user.strip().replace("\n", " ")[:100] or "New conversation"

        # Persist the new title
        await self.update_thread_title(thread_id, title)
        return title

    # -- History, results index, and checkpoints -----------------------------

    async def get_history(self, thread_id: str) -> List[Dict[str, str]]:
        """Get full conversation history from checkpoint state."""
        self._ensure_initialized()
        _, messages = await self._get_state(thread_id)
        result = []
        for msg in messages:
            if isinstance(msg, dict):
                msg_type = msg.get("type", "")
                if msg_type in ("human", "user"):
                    role = "user"
                elif msg_type == "constructor":
                    msg_id = msg.get("id", [])
                    role = "user" if any("HumanMessage" in str(x) for x in msg_id) else "assistant"
                else:
                    role = "assistant"
                content = msg.get("content", "") or ""
            else:
                role = "user" if isinstance(msg, HumanMessage) else "assistant"
                content = getattr(msg, "content", "")
            result.append({"role": role, "content": content})
        return result

    async def get_results_index(self, thread_id: str) -> List[Dict[str, Any]]:
        """Get per-turn CSV metadata for all turns in a thread.

        Each entry contains:
            message_id:  Unique turn identifier
            question:    User's question for this turn
            csv_path:    Primary CSV file path (or None)
            result_meta: CSV metadata (row_count, col_count, columns, etc.)
            all_files:   List of all extracted CSV file paths
            latency_s:   Query latency in seconds
            num_steps:   Number of sub-agent routing steps
            success:     Whether the query succeeded

        Usage (UI backend):
            results = await client.get_results_index(thread_id)
            for entry in results:
                if entry['csv_path']:
                    download_url = f"/download?path={entry['csv_path']}"
        """
        self._ensure_initialized()
        config = _build_config(thread_id)
        snapshot = await self._graph.aget_state(config)
        state = snapshot.values or {}
        return state.get("results_index", [])

    async def get_session_metadata(
        self,
        thread_id: str,
        *,
        include_checkpoint_metadata: bool = False,
    ) -> Dict[str, Any]:
        """Get tracking metadata for a thread.

        Reads from the DatabricksStore (primary). Optionally includes
        checkpoint-level metadata (requires an additional round trip).

        Args:
            thread_id: Thread identifier.
            include_checkpoint_metadata: If True, also reads checkpoint
                metadata from the graph state (extra I/O). Default False.
        """
        self._ensure_initialized()
        # Primary source: DatabricksStore (single round trip)
        thread_meta = await self.get_thread_metadata(thread_id) or {}
        result: Dict[str, Any] = {
            "thread_id": thread_id,
            "user_id": thread_meta.get("user_id"),
            "correlation_id": thread_meta.get("correlation_id"),
            "created_at": thread_meta.get("created_at"),
        }
        # Supplementary: checkpoint-level metadata (optional, extra round trip)
        if include_checkpoint_metadata:
            config = _build_config(thread_id)
            snapshot = await self._graph.aget_state(config)
            cp_meta = getattr(snapshot, "metadata", None)
            if isinstance(cp_meta, dict):
                result["checkpoint_metadata"] = cp_meta
        return result

    async def get_checkpoint_history(
        self,
        thread_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Retrieve checkpoint history for time travel.

        Each entry includes checkpoint-level details. Tracking metadata
        (user_id, correlation_id) is available via get_session_metadata().
        """
        self._ensure_initialized()
        config = _build_config(thread_id)
        history = []
        async for state in self._graph.aget_state_history(config):
            if len(history) >= limit:
                break
            messages = state.values.get("messages", [])
            entry = {
                "checkpoint_id": state.config["configurable"]["checkpoint_id"],
                "thread_id": thread_id,
                "timestamp": state.created_at,
                "next_nodes": state.next,
                "message_count": len(messages),
                "last_message": messages[-1].content[:100] if messages else None,
            }
            history.append(entry)
        return history

    async def update_checkpoint_state(
        self,
        thread_id: str,
        checkpoint_id: Optional[str],
        new_messages: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Update state at a checkpoint (conversation forking)."""
        self._ensure_initialized()
        config = _build_config(thread_id, checkpoint_id=checkpoint_id)
        values = {}
        if new_messages:
            lc_messages = [
                HumanMessage(content=m["content"]) if m.get("role") == "user"
                else AIMessage(content=m["content"])
                for m in new_messages
            ]
            values["messages"] = lc_messages
        new_config = await self._graph.aupdate_state(config, values, as_node="passthrough")
        return {
            "thread_id": thread_id,
            "checkpoint_id": new_config["configurable"]["checkpoint_id"],
            "parent_checkpoint_id": checkpoint_id,
        }
