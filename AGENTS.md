# Universal Agent UI

Frontend (Next.js + CopilotKit) + Backend (FastAPI) for interacting with Databricks Mosaic AI supervisor agents via the LangGraph supervisor client.

## Quick start

```bash
# Terminal 1 — Backend
cd backend && uv run uvicorn app.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend && pnpm dev
```

## Modules

| Module | Description |
|---|---|
| `backend/app/supervisor/` | LangGraph supervisor client (copied from `langgraph_supervisor`) — dual-store Lakebase persistence |
| `backend/app/services/` | SupervisorService — pool of `AsyncLangGraphSupervisor` clients, one per agent endpoint |
| `backend/app/routers/` | FastAPI routes: agent CRUD, AG-UI SSE streaming, session management |
| `backend/app/schemas/` | Pydantic models for agents, chat, sessions |
| `backend/app/db/` | SQLAlchemy async engine + SQLite agent registry |
| `backend/app/memory.py` | UserMemoryService (CRUD) + MemoryExtractor (LLM fact extraction) |
| `frontend/src/components/` | React components: Chat, Sidebar, Messages, MultimodalInput, PlotlyChart |
| `frontend/src/app/api/copilotkit/` | CopilotKit Runtime — proxies to FastAPI `/ag-ui/run` |

## Architecture

```
CopilotKit Runtime (single-route) → POST /ag-ui/run → SupervisorService (client pool)
                                                        → AsyncLangGraphSupervisor (per endpoint)
                                                            ├── _sse_stream() → direct httpx SSE to /invocations
                                                            └── Databricks Lakebase (dual-store)
                                                                ├── checkpoints (unreliable — not used for reads)
                                                                └── store (threads, by_user, user_memories)

Memory (streaming.py:670-771):

  PersistingStreamWrapper.__aiter__()
    │
    ├── Gate 1: short response skip (<50 chars → no extraction)
    ├── Gate 2: cooldown rate-limit (5 min interval)
    │
    └── _do_memory_extraction()
        ├── list_keys() (lightweight dedup, keys-only)
        ├── MemoryExtractor.extract_from_turn() → LLM call
        │   └── _parse_response() → [{"key", "value", "category"}]
        └── UserMemoryService.save_memory() × N
            └── _evict_stale() (TTL: 90d + <2 accesses)

Injection (lg_client.py:566-610):
  _inject_memory_context()
    ├── list_memories_for_injection() → ranked by access×0.3 + recency×0.7
    ├── format_for_context() → [Memory System] header
    ├── injects as user message before last user query
    └── batch_bump_access() (10 memories at once, fire-and-forget)
```

## Notable fixes during setup

| Issue | Cause | Fix |
|---|---|---|
| `databricks-openai` Responses API empty stream | `responses.create()` routes to `{base_url}/v1/responses` not `/invocations` | `_sse_stream()` — direct `httpx` SSE to serving endpoint |
| `forwardedProps` always undefined | Destructured from factory param instead of `input.forwardedProps` | `input.forwardedProps` |
| CopilotKit 404 on runtime info | Missing `GET` export + wrong route mode | Single-route mode with `basePath` + `useSingleEndpoint` |
| `type "vector" does not exist` | Lakebase PG missing `pgvector` extension | Omitted `embedding_endpoint` from `AsyncDatabricksStore` |
| PG password auth failed | SP had no Lakebase role on the branch | Created role with `LAKEBASE_OAUTH_V1` + `SERVICE_PRINCIPAL` |
| Thread tracking broken | `create_session()` skipped when `thread_id` provided | Always call `create_session()` with `thread_id` |
| AI messages not persisted | `break` on `completed` killed generator before wrapper persist | Changed `break` to `pass` |
| Checkpoint data lost between turns | `user_id` in persist config created separate scope; PG pool tear-down lost transactions | Removed `user_id` from config; bypassed checkpoints — message history via DatabricksStore |
| Thread_id changes each turn | CopilotKit generates new `input.threadId` per run | `agent.setState({ threadId })` synchronized to `input.state.threadId` |
| New Chat doesn't create new thread | CopilotKit caches `forwardedProps` from `useAgent()` | Use `agent.setState()` (not `forwardedProps`) for thread_id |
| CopilotKit strips `threadId` from forwardedProps | Reserved key conflict | Use `input.state.threadId` via `agent.setState()` |
| New Chat shows old messages | CopilotKit provider persists across remounts; `agent.messages` never cleared | `agent.setMessages([])` on new chat |
| Delete thread was a no-op | `supervisor_service.delete_thread()` only logged | `AsyncDatabricksStore.adelete()` + `AsyncCheckpointSaver.adelete_thread()` across all 5 store namespaces |
| Frontend delete didn't call API | `handleDeleteSession` only removed local state | `apiDelete()` to `DELETE /api/sessions/{thread_id}` |
| Title generation fails | SP lacks `Can Query` on `deepseek-v4flash-chat` endpoint | `PermissionError` handled, falls back to first user message; log tells you which endpoint needs permission |
| Auto-title not working | User didn't click sparkle icon | Auto-title is manual (click sparkle), not automatic — preserves existing first-turn fallback |
| No streaming status while agent processing | Non-text events dropped, AwaitingResponse only before first text | JSON SSE events with routing/reasoning + persistent smart status bar |
| Memory duplicates on re-save | save_memory overwrote or rejected same-key facts | Same-key merge (appends new info) + timestamps + importance ranking |
| Agent selection hardcoded | DEFAULT_AGENT_ID from env only, no UI | Agent selector dropdown + registration modal with endpoint URL |
| LLM extraction after every turn (wasteful) | No rate-limiting, one LLM call per user message | Gate 1: skip if response < 50 chars; Gate 2: 5 min cooldown via store timestamp |
| List memories loaded ALL items for dedup | `list_memories()` fetched full values | `list_keys()` — lightweight keys-only fetch |
| Access bumps: 10 reads + 10 writes per injection | Individual `bump_access` per memory | `batch_bump_access()` — single loop with error isolation |
| No TTL eviction for stale memories | Old/low-access facts lived forever | `_evict_stale(90d, min_access=2)` runs after successful extraction |
| Eviction race condition | Between `count_memories()` and `aput()` | Post-save count check + second eviction |
| Nested data shapes caused confusion | `_parse_response` returned `{data: {value, category}}` | Flattened to `{value, category}` in both extraction and storage |
| Extraction window too narrow | Last 6 messages only | Increased to 10 messages (configurable via `memory_extraction_window`) |
| No bulk delete API | `delete_all_memories()` existed but no route | Added `DELETE /api/memory` endpoint |

## Delete thread — data cleaned from Lakebase

| Store | Namespace | Key |
|-------|-----------|-----|
| DatabricksStore | `("threads",)` | `thread_id` (metadata) |
| DatabricksStore | `("threads",)` | `f"{thread_id}/messages"` (history) |
| DatabricksStore | `("by_user", <user_id>)` | `thread_id` (index) |
| DatabricksStore | `("by_correlation", <corr_id>)` | `thread_id` (index) |
| DatabricksStore | `("messages", <thread_id>)` | each `message_id` (per-turn tracking) |
| CheckpointSaver | thread-scoped | `adelete_thread(thread_id)` (state) |

_Last updated: 2026-06-30_
