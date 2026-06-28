# Contract: Sessions Router

`backend/app/routers/sessions.py`

FastAPI router providing session listing, history, results, metadata, deletion,
auto-title generation, and title updates.

---

### `GET /api/sessions?agent_id=...&amp;user_id=...&amp;limit=50` → `SessionListResponse`
- **Produces**: List of `SessionSummary` with `thread_id`, `title`, `created_at`, `correlation_id`
- Reads from DatabricksStore `by_user` namespace (thread tracking index)
- Returns empty `sessions` list if user has no threads (never raises)

### `GET /api/sessions/{thread_id}?agent_id=...` → `SessionHistoryResponse`
- Returns full message history with `role` and `content`
- Reads from checkpoint (not DatabricksStore)

### `GET /api/sessions/{thread_id}/results?agent_id=...` → `list[ResultsIndexEntry]`
- Per-turn CSV metadata
- Reads from checkpoint's `results_index`

### `GET /api/sessions/{thread_id}/metadata?agent_id=...` → `ThreadMetadata`
- Tracking metadata: user_id, correlation_id, created_at
- Raises 404 if thread not found

### `DELETE /api/sessions/{thread_id}?agent_id=...` → `{"status": "deleted"}`
- Deletes from all DatabricksStore namespaces + checkpoint

### `POST /api/sessions/{thread_id}/auto-title?agent_id=...` → `TitleResponse`
- **Produces**: `{"title": "generated title string"}`
- Calls `SupervisorService.generate_thread_title()` → `AsyncLangGraphSupervisor.generate_thread_title()`
  → `MemoryExtractor.generate_title()`
- Loads conversation history from checkpoint, calls DeepSeek v4 Flash, persists to all namespaces
- Falls back to first user message if LLM unavailable
- Always returns a title (never raises, never returns error)

### `PATCH /api/sessions/{thread_id}/title?agent_id=...` → `{"status": "updated", "title": "..."}`
- Body: `{"title": "custom title text"}`
- Title is trimmed and truncated to 100 characters
- Calls `SupervisorService.update_thread_title()` → `AsyncLangGraphSupervisor.update_thread_title()`
- Writes to all 3 DatabricksStore namespaces (threads, by_user, by_correlation)
- Logs warning if thread not found, but does NOT raise

---

## Common failure modes
- Agent not found in SQLite registry → `404` from `_get_agent_endpoint()`
- Both endpoints are silent on DatabricksStore write failures (logged at WARNING)

→ See also: `contracts/async_langgraph_supervisor.md`, `contracts/memory.md`, `contracts/supervisor_service.md`
