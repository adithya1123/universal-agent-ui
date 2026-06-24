# Contract: Streaming Classes

`backend/app/supervisor/streaming.py`

Three streaming classes that handle parsing the OpenAI Responses API stream, auto-approving MCP tool calls, and persisting results.

## `AsyncStreamingResponse`

Parses a single Responses API `stream=True` response, yielding `StreamEvent` objects.

### Constructor
```python
AsyncStreamingResponse(openai_stream, question, start_time, store_raw=False)
```

### `__aiter__()` — async generator
Yields `StreamEvent` with types:
- `text_delta` — incremental text chunk from the agent's answer
- `routing` — supervisor dispatching to a sub-agent (`function_call`)
- `reasoning` — sub-agent reasoning/thinking step
- `annotation` — source citation
- `item_done` — complete output item (message, function_call, function_call_output)
- `tool_approval` — MCP approval request
- `completed` — stream finished; final AgentResult available via `.result`

### `result` property
Must iterate (`async for`) before accessing. Raises `RuntimeError("Stream not consumed...")` if accessed too early.

### `_from_error(result)` — classmethod
Creates a pre-failed response for connection-level errors. Sets `_consumed = True` immediately.

## `_ApprovalLoopStream(AsyncStreamingResponse)`

Auto-approves MCP tool approval requests from the Supervisor without user intervention.

### Behavior
- Re-creates streams per round via a factory function
- Accumulates `conversation_items` (output items + approval responses) across rounds
- Bounded by `max_approval_rounds` (default 5) — prevents infinite loops
- Sends `{"type": "mcp_approval_response", "approve": True}` for each pending request

## `_PersistingStreamWrapper(AsyncStreamingResponse)`

Wraps an `AsyncStreamingResponse` and adds post-stream side effects.

### Post-stream behavior (after inner stream completes)
1. Extracts CSV from tool outputs, sub-agent messages, and markdown tables
2. Strips `raw_output` from tool calls (memory management)
3. Persists `AIMessage` + `results_index` to graph state
4. Writes message tracking to `("messages", thread_id)` namespace in DatabricksStore
5. Sets thread title on first turn (batch read + write across 3 namespaces)
6. Tags MLflow traces (2-attempt retry)

### Persistence gate
Check is `if self._result`, not `if self._result.final_answer`. Empty responses still get persisted.

### Failure modes
- CSV extraction failure → logged at WARNING, returns `(None, None, [])`
- DatabricksStore message tracking failure → logged at WARNING, continues
- Thread title update failure → logged at WARNING, continues
- MLflow tagging failure → logged at WARNING, continues

## Note on stream source

The `AsyncStreamingResponse` was designed to consume OpenAI library `AsyncStream` objects. However, due to `databricks-openai` URL routing issues, the actual stream used is produced by `_sse_stream()` in `lg_client.py`, which yields `SimpleNamespace` objects matching the same `type`/`delta`/`item` attribute shape. The `AsyncStreamingResponse.__aiter__` code works identically with both sources because it uses `getattr()` throughout.

## Message Persistence Architecture

Messages are persisted to the **DatabricksStore** (k/v store), NOT the LangGraph checkpoint. The checkpoint is unreliable due to PostgreSQL pool teardown under uvicorn's async lifecycle.

**Write path** (`_PersistingStreamWrapper.__aiter__`):
1. Read existing history: `aget(threads, "{thread_id}/messages")`
2. Append current turn (user + AI) to the list
3. Write back: `aput(threads, "{thread_id}/messages")`

**Read path** (`get_history` in `lg_client.py`):
1. Try DatabricksStore first: `aget(threads, "{thread_id}/messages")`
2. Fall back to checkpoint if store read fails

**Why checkpoints are dead code**: The `AsyncCheckpointSaver`'s PostgreSQL connection pool destroys workers under uvicorn's async lifecycle (`Task was destroyed but it is pending!`). Data committed in one connection is invisible to new connections. The `_PersistingStreamWrapper` no longer writes to the checkpoint (persisted only to store).

## Thread ID Synchronization

The `chat.tsx` component maintains a stable thread ID per chat session using CopilotKit's `state` mechanism:

1. `useState(() => threadId || crypto.randomUUID())` — stable UUID on mount
2. `useEffect(() => agent.setState({ threadId: currentThreadId }))` — sync via state (never filtered)
3. Factory reads `input.state.threadId` — reliable path
4. Per-call props via `copilotkit.runAgent({ agent, forwardedProps: { userId, agentId } })`

**Bug avoided**: CopilotKit v2 strips `threadId` from `forwardedProps` (reserved key). `agent.setState()` uses CopilotKit's state mechanism which is never filtered.

_Last updated: 2026-06-24_
