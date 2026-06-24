# Business Logic Index — Universal Agent UI

## CSV Extraction Priority

The `_extract_and_store_result()` function determines which tabular data to save as CSV files. It uses a **collect-all** strategy with deduplication:

1. **Raw tool outputs** — JSON arrays of dicts from `function_call_output` events
2. **Sub-agent message tables** — Markdown or pipe-delimited tables in intermediate agent messages
3. **Markdown tables in final answer** — Tables in the assistant's final summary text

**Deduplication**: Tables with identical header sets (compared as `frozenset`) are stored only once. First occurrence wins.

**Primary selection**: Among unique tables, the one with the most rows becomes the primary result. This means `result_file_path` points to the largest table, not necessarily the most important one.

**Minimum threshold**: Tables with fewer than 2 data rows (`_RESULT_CSV_MIN_ROWS = 2`) are discarded.

## Thread Title Derivation

The thread title is set automatically on the **first turn** of a conversation:

1. The first user question is truncated to 100 characters
2. Newlines are replaced with spaces
3. The result is stored as `title` in all DatabricksStore namespaces (threads, by_user, by_correlation)
4. Initial title is always `"New conversation"` until the first AI response completes

This means an empty thread (created but never queried) retains the title `"New conversation"`.

## Session Sorting

Threads returned by `list_threads_for_user()` and `list_threads_for_correlation()` are sorted by `created_at` descending (newest first). This happens client-side in Python after the DatabricksStore `asearch()`, not via a database ORDER BY.

## Error Categories

The `ErrorCategory` enum maps Databricks/OpenAI errors to categories:

| Category | Trigger |
|---|---|
| `AUTH_EXPIRED` | `AuthenticationError`, `PermissionDeniedError`, `UNAUTHORIZED`, `UNAUTHENTICATED` |
| `PERMISSION_DENIED` | `FORBIDDEN`, agent message contains "PERMISSION_DENIED" |
| `RESOURCE_NOT_FOUND` | `NotFoundError`, `NOT_FOUND`, agent message contains "DOES NOT EXIST" |
| `TIMEOUT` | `APITimeoutError`, `TIMEOUT`, `TIMED OUT` |
| `INVALID_REQUEST` | `BadRequestError`, `BAD_REQUEST`, `INVALID_PARAMETER_VALUE` |
| `NETWORK` | `APIConnectionError`, connection-level failures |
| `UNKNOWN` | Anything else |

## SSE Streaming via Direct HTTP (bypassing databricks-openai Responses API)

The `_sse_stream()` method in `lg_client.py` replaces `AsyncDatabricksOpenAI.responses.create()` for streaming from the Databricks serving endpoint.

**Why:** `AsyncDatabricksOpenAI.responses.create(stream=True)` calls the standard OpenAI Responses API endpoint (`{base_url}/v1/responses`), but Databricks serving endpoints expect requests at `/invocations`. The result was an empty `AsyncStream` with 0 events — the API call succeeded (no exception) but yielded nothing.

**The fix:** `_sse_stream()` makes a direct `httpx` async HTTP POST to `{host}/serving-endpoints/{endpoint_name}/invocations` with:
1. OAuth headers from `WorkspaceClient.config.authenticate()`
2. JSON body `{"input": [...], "stream": True}` matching the Responses API format
3. SSE line-by-line parsing via `resp.aiter_lines()`
4. Yields `SimpleNamespace` objects that match the event shape `AsyncStreamingResponse.__aiter__` expects

**Event types emitted by the Databricks supervisor endpoint:**
- `response.output_text.delta` — text chunks with `delta` field
- `response.output_item.done` — completed output items with `item` field
- Stream ends with `[DONE]` (no `response.completed` event — a synthetic one is emitted)

**Key differences from OpenAI library response:**
- No `response.completed` event from the endpoint — the synthetic event has `response=None`, so `_check_response_status()` and `_check_databricks_output()` are skipped
- No `databricks_output` field on events — trace ID extraction is skipped
- This means `_PersistingStreamWrapper` still works for text persistence but MLflow trace tagging may not work

## Message History Storage (DatabricksStore)

Message history is stored in the DatabricksStore's `threads` namespace under the key `{thread_id}/messages`, NOT in the LangGraph checkpoint. The checkpoint is written (for backward compatibility) but is unreliable due to PostgreSQL connection pool teardown under uvicorn's async lifecycle.

**Why checkpoints are unreliable:**
1. The `AsyncCheckpointSaver` uses a `psycopg_pool` connection pool
2. Under uvicorn reload or task completion, pool workers are destroyed while tasks are pending (`Task was destroyed but it is pending`)
3. Data is visible within the same connection (wrapper readback works) but invisible to new connections (next turn's `_get_state` returns 0)
4. All writes create separate parallel branches from the initial state instead of a linear chain

**The DatabricksStore approach:**
- Each turn appends user+AI messages to the existing store history
- `_PersistingStreamWrapper.__aiter__()` reads existing messages → appends new turn → writes back
- `get_history()` reads from store first, falls back to checkpoint
- Survives connection pool teardown because `DatabricksStore.aput` is a single atomic write

## CopilotKit v2 Single-Route Mode

The CopilotKit Runtime runs in **single-route mode** (`mode: "single-route"`), where all operations (info, run, connect, stop, threads) go through a single `POST /api/copilotkit` endpoint instead of separate subpaths.

**Why:** Multi-route mode requires a `[...path]` catch-all route and both GET+POST exports. Single-route mode simplifies the Next.js route to a single file at `api/copilotkit/route.ts` with only `POST` export. The CopilotKit frontend provider must set `useSingleEndpoint` to match.

**ForwardedProps flow:**
1. `chat.tsx` sets `customThreadId` via `useAgent({ forwardedProps: { customThreadId } })` (stable UUID per session)
2. `userId` and `agentId` are passed per-call via `copilotkit.runAgent({ agent, forwardedProps: { userId, agentId } })`
3. The runtime passes `forwardedProps` as `input.forwardedProps` to the factory
4. The factory reads `input.state.threadId` (from `agent.setState()`) for the thread_id, `input.forwardedProps.userId/agentId` for auth

**Thread ID stability (Critical):**
- CopilotKit v2 generates a new `input.threadId` per `runAgent()` call
- To maintain a consistent thread_id across turns, `chat.tsx` uses `useState(() => threadId || crypto.randomUUID())` to generate a stable UUID
- This UUID is synchronized to CopilotKit via `agent.setState({ threadId: currentThreadId })` 
- The factory reads `input.state.threadId` (reliable) instead of `input.forwardedProps.customThreadId` (CopilotKit strips/reserved keys)
- This was the most elusive bug during setup — CopilotKit v2 intermittently strips `forwardedProps` keys

**Agent ID flow:**
1. `page.tsx` reads `NEXT_PUBLIC_DEFAULT_AGENT_ID` from env
2. Passes as `agentId` prop to `<Chat>`
3. `chat.tsx` forwards through `copilotkit.runAgent({ agent, forwardedProps: { agentId } })`
4. `route.ts` factory reads `input.forwardedProps.agentId` (fallback to `process.env.NEXT_PUBLIC_DEFAULT_AGENT_ID`)
5. Sent as `agent_id` in JSON body to `/ag-ui/run`
6. Backend looks up agent by ID in SQLite registry to get the endpoint URL

_Last updated: 2026-06-24_
