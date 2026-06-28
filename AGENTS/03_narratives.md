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

**What it does NOT handle**: Authentication, user management, agent registration, session title generation. It trusts the CopilotKit Runtime to pass the correct agentId.

**Key evolution — JSON SSE events**: The endpoint originally yielded raw text bytes from
`text_delta` events, dropping `routing` and `reasoning` events entirely. It now encodes ALL
event types as JSON SSE lines:
- `{"type":"text","content":"..."}` — text delta (same as before, now JSON-wrapped)
- `{"type":"routing","agent":"..."}` — sub-agent dispatch notice
- `{"type":"reasoning","content":"..."}` — intermediate thinking/reasoning text

The CopilotKit Runtime (`route.ts`) parses these JSON events, forwarding text to `TEXT_MESSAGE_CHUNK`
and routing/reasoning to the UI for display. Reasoning text appears in the smart status bar as
live-updating "Thinking: ..." text. Routing events appear as inline italic notices in the message.

## `frontend/src/app/api/copilotkit/route.ts` — CopilotKit Runtime

Next.js API route that creates a `CopilotRuntime` with a custom `BuiltInAgent` in **single-route mode** (`mode: "single-route"`). The custom agent factory POSTs to the backend `/ag-ui/run` and wraps the response bytes into AG-UI `TEXT_MESSAGE_CHUNK` events.

**Why single-route mode**: Avoids the `[...path]` catch-all complexity. All operations (info, run, connect, threads) go through a single `POST /api/copilotkit` endpoint. The frontend `CopilotKit` provider must set `useSingleEndpoint` to match.

**ForwardedProps wiring**: The factory reads `input.forwardedProps` (NOT a top-level destructured parameter). Per-call props (`userId`, `agentId`) are passed via `copilotkit.runAgent({ agent, forwardedProps: {...} })`.

**Thread ID via agent.setState()**: The persistent `threadId` is synchronized via CopilotKit's `state` mechanism rather than `forwardedProps` (which CopilotKit intermittently strips). `chat.tsx` maintains a stable UUID via `useState(() => threadId || crypto.randomUUID())` and syncs it via `useEffect(() => agent.setState({ threadId: currentThreadId }), [...])`. The factory reads `input.state.threadId`.

**What it does NOT handle**: Session persistence, agent communication. It is purely a proxy.

**SSE parser added**: The factory now includes a line-buffered SSE parser that splits incoming
bytes on `\n\n` boundaries into complete events. It processes three event types:
- `text` → `TEXT_MESSAGE_CHUNK` (rendered as message content)
- `routing` → `TEXT_MESSAGE_CHUNK` with `\n\n*→ agent name*\n\n` formatting (renders as italic)
- `reasoning` → `TEXT_MESSAGE_CHUNK` with `[REASONING]` prefix (stripped by Messages component,
  shown in the smart status bar instead)

The SSE parser handles partial chunk boundaries where a single `reader.read()` may split a
JSON event across multiple bytes. Incomplete events are buffered until the next chunk.

## `frontend/src/components/` — React UI Components

Seven client components that make up the chat interface: Chat, ChatHeader, Messages, Message, MultimodalInput, Sidebar, ThemeProvider.

**Why it exists**: Provides a polished, responsive chat UI with dark/light mode support, session sidebar, and streaming text display. The `Chat` component manages thread identity via `useState` stable UUID and `agent.setState({ threadId })`, dispatches messages via `copilotkit.runAgent()`, and calls `onThreadCreated` to refresh the sidebar on new conversations.

**What it does NOT handle**: Agent logic. All components are presentational and delegate to CopilotKit's `useAgent` hook.

**Features**:
- **Agent selector** — Header shows active agent name with `Bot` icon. Click opens a dropdown
  of all registered agents (fetched from `GET /api/agents`). Select to switch; Chat remounts
  and sessions refetch for the new agent. "Register new agent" button opens a modal dialog.
- **Session list** — Shows all sessions for the active agent. Hover reveals sparkle icon (auto-title),
  pencil icon (inline rename), and delete button. Double-click title or click pencil to edit inline.
- **Messages component** — Shows a smart status bar while streaming: a spinning `Loader2` icon +
  the latest reasoning text from the agent (extracted from `[REASONING]` markers). Falls back
  to "Agent is responding..." when no reasoning is flowing. Reasoning markers are stripped
  from displayed message content so they only appear in the status bar.
- **MultimodalInput** — Textarea auto-resizes from 1 row up to 200px using a `useRef` +
  `useEffect` that sets `height` to `min(scrollHeight, 200px)` on input change.

## `backend/app/memory.py` — Memory Extraction &amp; CRUD

Two classes that together provide long-term user memory: `UserMemoryService` for CRUD,
and `MemoryExtractor` for LLM-based fact extraction from conversation.

**Why it exists**: Without long-term memory, the supervisor agent treats every turn as
a cold start — it remembers nothing about the user from previous sessions. The dual-design
separates storage concerns (UserMemoryService) from LLM querying (MemoryExtractor),
so the extraction model can be swapped independently of storage.

**UserMemoryService**: Manages user memories in the DatabricksStore under namespace
`("user_memories", <sanitized_user_id>)`. Features:
- **Same-key merge**: If a new fact uses a key that already exists, its value is appended
  to the existing value (e.g., "Python. Also Rust for systems work"). The category is only
  upgraded from "other" to a specific one if the new fact has one.
- **Timestamps + access tracking**: Every memory stores `created_at`, `updated_at` (ISO
  timestamps), and `access_count` (incremented on each injection via `bump_access()`).
- **Ranked injection**: `list_memories_for_injection()` returns top-N memories by composite
  importance score (access_count × 0.3 + recency × 0.7).
- **Fixed eviction**: `_evict_oldest()` now reads all memories and evicts the one with the
  oldest `updated_at` (was: first result from `asearch` with no sort).
- Value size checks (`memory_max_value_size = 4096`), and `format_for_context()` for
  structured injection.

**MemoryExtractor**: Calls a Databricks serving endpoint (default: `deepseek-v4flash-chat`)
with a structured extraction prompt that instructs the LLM to return a JSON array of facts.
Also provides `generate_title()` for auto-title generation using the same endpoint but
simpler prompt and `max_tokens=60`.

**What it does NOT handle**: Conversation state, checkpoint management, user auth, CSV extraction.

**Failure modes**:
- PermissionError from `_call_llm()` when SP lacks `Can Query` on the serving endpoint
- Memory quota exceeded results in oldest memory eviction (silent, logged at INFO)
- Title generation LLM failure ⇒ falls back to first user message (soft degradation)

**Auto-title generation flow**:
1. User clicks ✨ sparkle in sidebar
2. Frontend calls `POST /api/sessions/{thread_id}/auto-title`
3. Backend loads conversation history from checkpoint (last 6 messages)
4. `MemoryExtractor.generate_title()` sends them to DeepSeek v4 Flash
5. LLM returns 3-5 word title → persisted via `update_thread_title()` to all namespaces
6. Frontend receives `{"title": "..."}` and updates sidebar in place

## `backend/app/supervisor/streaming.py` — Message Persistence

`_PersistingStreamWrapper` is the final link in the streaming chain — it persists messages after the SSE stream completes.

**Why it exists**: After the supervisor agent responds, the results (conversation messages, CSV extractions, trace data) must be persisted so they survive page refreshes and appear when clicking past sessions.

**Key insight — checkpoint bypass**: The original architecture used LangGraph's `AsyncPostgresSaver` for message history. However, the PostgreSQL connection pool (`psycopg_pool`) tears down under uvicorn's async lifecycle, destroying pending workers and losing committed data between HTTP requests. The backup solution uses the DatabricksStore (a reliable k/v store) for message history. Each turn reads existing messages, appends the current turn's exchange, and writes back. The checkpoint persists remain for backward compatibility but are unreliable — `get_history()` reads from the DatabricksStore first.

**Failure modes**:
- DatabricksStore write failure → logged at WARNING level, messages are lost for that turn only
- MLflow trace tagging failure → logged at WARNING, non-critical
- CSV volume write failure → logged at WARNING, non-critical

_Last updated: 2026-06-28_
