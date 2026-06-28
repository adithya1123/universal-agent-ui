# Hazard Map — Universal Agent UI

## 🔴 NEVER

1. **Never hardcode credentials** — `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`, and `DATABRICKS_TOKEN` must come from `.env`, never from source. The `.env` file is gitignored.

2. **Never use `uvicorn.run()` with `uv run` in production** — Use the command form `uv run uvicorn app.main:app --reload --port 8000`. Using `python -c "import uvicorn; uvicorn.run(...)"` can cause module import issues.

3. **Never use `databricks-openai`'s `responses.create(stream=True)`** — It sends requests to `{base_url}/v1/responses` which Databricks serving endpoints don't support. The endpoint expects `/invocations`. Always use `_sse_stream()` (direct `httpx` SSE to `/invocations`) instead.

4. **Never modify `backend/app/supervisor/` files without updating the `langgraph_supervisor` source** — These files are copied from `/Users/adithya/Desktop/LLM/langgraph_supervisor`. Changes should be made upstream and re-copied.

5. **Never delete the SQLite database manually while the app is running** — It holds the agent registry. Delete only when the server is stopped.

6. **Never assume the memory extraction model has permissions** — The service principal
   needs `Can Query` on the serving endpoint defined by `MEMORY_EXTRACTION_MODEL`.
   Without it, `_call_llm()` raises `PermissionError`, which permanently disables
   extraction for that session. The error message tells you exactly which endpoint
   needs permission. Always verify SP permissions after deploying or changing the
   extraction model.

7. **Never use auto-title generation without checking for memory extraction model permission** —
   `generate_title()` also calls `_call_llm()` which raises `PermissionError` if the
   SP lacks `Can Query`. The same endpoint serves both extraction and title generation.

## 🟡 CAUTION

1. **OAuth tokens expire** — The `WorkspaceClient` handles OAuth M2M auto-refresh, but if the SP secret is rotated, the backend must be restarted.

2. **Lakebase tables are created once** — `AsyncLangGraphSupervisor.setup()` creates checkpoint + store tables idempotently. Safe to re-run, but may cause a brief connection blip. NOTE: the `AsyncDatabricksStore` does NOT use embeddings (pgvector not enabled on this Lakebase instance). The store works for k/v thread tracking but not for semantic/vector search.

3. **Empty string settings** — `pydantic-settings` returns `""` (not `None`) for unset env vars. The supervisor service sanitizes these with `_val(v)`, but new code reading `settings` directly may pass empty strings to APIs that expect `None`.

4. **mlflow tagging may fail silently** — `_PersistingStreamWrapper` attempts MLflow trace tagging with a 2-attempt retry. Failures are logged at WARNING, not raised. Don't rely on trace tags for critical audits.

5. **Thread deletion is a no-op** — `SupervisorService.delete_thread()` logs intent but does not delete from Lakebase. Threads persist indefinitely.

6. **CopilotKit Runtime must match frontend mode** — If the runtime uses `mode: "single-route"`, the frontend `<CopilotKit>` must set `useSingleEndpoint`. If modes mismatch, every request returns 404.

7. **`threadId` in `forwardedProps` is stripped by CopilotKit** — CopilotKit v2 reserves the `threadId` key. Use a different key name (`customThreadId`) or use `agent.setState({ threadId })` / `input.state.threadId` (preferred — state is never filtered by CopilotKit).

8. **Lakebase roles must be assigned for SP** — The service principal needs a Lakebase role on the branch with `auth_method=LAKEBASE_OAUTH_V1`, `identity_type=SERVICE_PRINCIPAL`, and `membership_roles=[DATABRICKS_SUPERUSER]`. Without this, `generate_database_credential()` mints a token but PostgreSQL rejects it with "password authentication failed".

9. **pgvector extension must be enabled before using embedddings** — If embeddings are needed, `CREATE EXTENSION vector` must be run on the Lakebase database by an admin. The SP currently lacks `CREATE` privilege.

10. **LangGraph checkpoint is unreliable for message history** — The `AsyncCheckpointSaver`'s PostgreSQL connection pool destroys workers under uvicorn's async lifecycle (`Task was destroyed but it is pending!`). Data committed in one connection is lost before the next HTTP request. Do NOT rely on `aget_state()` for message history across requests. Use the DatabricksStore (under `threads/{thread_id}/messages`) for reliable message persistence. The `_PersistingStreamWrapper` only writes to the store (checkpoint persists are dead code).

11. **Title generation uses the last 6 messages only** — `generate_title()` takes
    `conversation[-6:]` (~3 recent turns). If the conversation is very long (>20 turns),
    earlier context is lost. Users can re-click the sparkle icon after more conversation
    to update the title with current context. This is by design — it keeps tokens low
    and titles relevant to the current topic.

12. **Auto-title is NOT automatically triggered on new conversations** — On first turn,
    the title is set to the first user question (truncated). Auto-title must be explicitly
    triggered by the user clicking the sparkle icon. The existing first-turn fallback
    behavior is preserved to avoid an extra LLM call on every single conversation.

13. **SSE event format changed to JSON** — `ag_ui.py` now sends structured JSON SSE events
    (`{"type":"text","content":"..."}`, `{"type":"routing","agent":"..."}`,
    `{"type":"reasoning","content":"..."}`) instead of raw bytes. The `route.ts` SSE parser
    must match this format. If events are malformed, the CopilotKit runtime silently drops them.
    Always verify both sides when changing the SSE protocol.

14. **Memory persisted per-agent** — `page.tsx` now manages agent selection via `activeAgentId`
    state. Sessions, memories, and title operations are all scoped to the active agent. Switching
    agents remounts the Chat component and refetches sessions for the new agent.

15. **Memory save now merges by key** — `UserMemoryService.save_memory()` appends new value
    content to existing memory when the same key is saved again (was: overwrite or reject).
    Existing value is preserved; new information is appended with ". " separator. If the new
    value is already contained in the existing value, the save is a no-op (returns False).

## ⚪ CONVENTION

1. **Three-router pattern** — Backend routes are split into `agents.py` (CRUD), `ag_ui.py` (streaming), and `sessions.py` (thread management). New routes should follow this split: agent lifecycle → `agents`, agent communication → `ag_ui`, thread/session queries → `sessions`.

2. **Pydantic schemas per module** — Each router has a matching schema file: `schemas/agent.py`, `schemas/chat.py`, `schemas/session.py`.

3. **Supervisor client is a lazy singleton pool** — `SupervisorService._get_client()` creates clients on first use per endpoint URL. Always get a client through the service, never instantiate `AsyncLangGraphSupervisor` directly outside of the service.

_Last updated: 2026-06-28_
