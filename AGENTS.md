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
| `frontend/src/components/` | React components: Chat, Sidebar, Messages, MultimodalInput |
| `frontend/src/app/api/copilotkit/` | CopilotKit Runtime — proxies to FastAPI `/ag-ui/run` |

## Architecture

```
CopilotKit Runtime (single-route) → POST /ag-ui/run → SupervisorService (client pool)
                                                        → AsyncLangGraphSupervisor (per endpoint)
                                                            ├── _sse_stream() → direct httpx SSE to /invocations
                                                            └── Databricks Lakebase (dual-store)
                                                                ├── checkpoints (unreliable — not used for reads)
                                                                └── store (threads, by_user, user_memories)
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

## Delete thread — data cleaned from Lakebase

| Store | Namespace | Key |
|-------|-----------|-----|
| DatabricksStore | `("threads",)` | `thread_id` (metadata) |
| DatabricksStore | `("threads",)` | `f"{thread_id}/messages"` (history) |
| DatabricksStore | `("by_user", <user_id>)` | `thread_id` (index) |
| DatabricksStore | `("by_correlation", <corr_id>)` | `thread_id` (index) |
| DatabricksStore | `("messages", <thread_id>)` | each `message_id` (per-turn tracking) |
| CheckpointSaver | thread-scoped | `adelete_thread(thread_id)` (state) |

_Last updated: 2026-06-27_
