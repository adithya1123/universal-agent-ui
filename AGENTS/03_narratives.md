# Module Narratives — Universal Agent UI

## `backend/app/supervisor/` — LangGraph Supervisor Client

Adapted from the `langgraph_supervisor` project. Provides `AsyncLangGraphSupervisor`, an async client for Databricks Mosaic AI supervisor endpoints with dual-store Lakebase persistence.

**Why it exists**: The supervisor client encapsulates all the complexity of streaming from the Databricks serving endpoint, managing conversation state in checkpoints, tracking threads in DatabricksStore, extracting CSV results, classifying errors, and auto-approving MCP tool calls. Without this layer, every route handler would need to duplicate this logic.

**Key divergence from `langgraph_supervisor` source**: The original code uses `AsyncDatabricksOpenAI.responses.create(stream=True)` for streaming, but `databricks-openai` routes Responses API calls to `{base_url}/v1/responses` which doesn't match the Databricks serving endpoint URL path (`/invocations`). The result is an empty stream (0 events, no error). The fixed code uses a direct `httpx` async SSE stream to the serving endpoint's `/invocations` URL, bypassing the library entirely. See `_sse_stream()` in `lg_client.py`.

**What it does NOT handle**: Agent registration (SQLite), user management, frontend rendering. It is purely a network+persistence client.

**Failure modes**: 
- Connection errors to Lakebase → `RuntimeError` from `_ensure_initialized()`
- Missing auth credentials → `ValueError("Provide one of: workspace_client, client_id+client_secret, or token.")`
- Supervisor endpoint errors → `AgentResult` with non-200 `status_code` and populated `errors`/`error_categories`

## `backend/app/services/supervisor_service.py` — Client Pool

Manages a dictionary of `AsyncLangGraphSupervisor` instances keyed by endpoint URL. Creates clients lazily on first use and closes all on shutdown.

**Why it exists**: Multiple agents (different supervisor endpoints) each need their own client with their own Lakebase checkpointer and store connections. The service prevents redundant connections and ensures proper lifecycle (init + setup on create, close on shutdown).

**What it does NOT handle**: Direct agent communication routing. The calling router decides which endpoint URL to use based on the agent registry.

## `backend/app/routers/ag_ui.py` — AG-UI Streaming Endpoint

Bridges the CopilotKit Runtime (Next.js) to the supervisor service. Accepts POST requests with messages, threadId, and agentId; returns a text/event-stream.

**Why it exists**: The CopilotKit Runtime is in JavaScript and cannot call the Databricks Responses API directly. This endpoint acts as the translation layer between the AG-UI protocol (used by CopilotKit) and the supervisor client (used by the backend). The `/ag-ui/run` endpoint extracts the last user message, looks up the agent endpoint URL from SQLite, creates/reuses a thread, and streams text deltas from the supervisor.

**What it does NOT handle**: Authentication, user management, agent registration. It trusts the CopilotKit Runtime to pass the correct agentId.

## `frontend/src/app/api/copilotkit/route.ts` — CopilotKit Runtime

Next.js API route that creates a `CopilotRuntime` with a custom `BuiltInAgent` in **single-route mode** (`mode: "single-route"`). The custom agent factory POSTs to the backend `/ag-ui/run` and wraps the response bytes into AG-UI `TEXT_MESSAGE_CHUNK` events.

**Why single-route mode**: Avoids the `[...path]` catch-all complexity. All operations (info, run, connect, threads) go through a single `POST /api/copilotkit` endpoint. The frontend `CopilotKit` provider must set `useSingleEndpoint` to match.

**ForwardedProps wiring**: The factory reads `input.forwardedProps` (NOT a top-level destructured parameter). Per-call props (`userId`, `agentId`) are passed via `copilotkit.runAgent({ agent, forwardedProps: {...} })`.

**Thread ID via agent.setState()**: The persistent `threadId` is synchronized via CopilotKit's `state` mechanism rather than `forwardedProps` (which CopilotKit intermittently strips). `chat.tsx` maintains a stable UUID via `useState(() => threadId || crypto.randomUUID())` and syncs it via `useEffect(() => agent.setState({ threadId: currentThreadId }), [...])`. The factory reads `input.state.threadId`.

**What it does NOT handle**: Session persistence, agent communication. It is purely a proxy.

## `frontend/src/components/` — React UI Components

Seven client components that make up the chat interface: Chat, ChatHeader, Messages, Message, MultimodalInput, Sidebar, ThemeProvider.

**Why it exists**: Provides a polished, responsive chat UI with dark/light mode support, session sidebar, and streaming text display. The `Chat` component manages thread identity via `useState` stable UUID and `agent.setState({ threadId })`, dispatches messages via `copilotkit.runAgent()`, and calls `onThreadCreated` to refresh the sidebar on new conversations.

**What it does NOT handle**: Agent logic. All components are presentational and delegate to CopilotKit's `useAgent` hook.

## `backend/app/supervisor/streaming.py` — Message Persistence

`_PersistingStreamWrapper` is the final link in the streaming chain — it persists messages after the SSE stream completes.

**Why it exists**: After the supervisor agent responds, the results (conversation messages, CSV extractions, trace data) must be persisted so they survive page refreshes and appear when clicking past sessions.

**Key insight — checkpoint bypass**: The original architecture used LangGraph's `AsyncPostgresSaver` for message history. However, the PostgreSQL connection pool (`psycopg_pool`) tears down under uvicorn's async lifecycle, destroying pending workers and losing committed data between HTTP requests. The backup solution uses the DatabricksStore (a reliable k/v store) for message history. Each turn reads existing messages, appends the current turn's exchange, and writes back. The checkpoint persists remain for backward compatibility but are unreliable — `get_history()` reads from the DatabricksStore first.

**Failure modes**:
- DatabricksStore write failure → logged at WARNING level, messages are lost for that turn only
- MLflow trace tagging failure → logged at WARNING, non-critical
- CSV volume write failure → logged at WARNING, non-critical

_Last updated: 2026-06-24_
