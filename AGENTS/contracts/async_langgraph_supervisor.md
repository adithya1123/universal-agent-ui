# Contract: `AsyncLangGraphSupervisor`

`backend/app/supervisor/lg_client.py`

The central async client for communicating with a Databricks Mosaic AI supervisor endpoint. Manages session lifecycle, streaming queries, and dual-store Lakebase persistence.

## Constructor

```python
AsyncLangGraphSupervisor(
    endpoint_url: str,
    token: str | None = None,
    *,
    workspace_client: WorkspaceClient | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    lakebase_project: str | None = None,
    lakebase_branch: str | None = None,
    lakebase_instance_name: str | None = None,
    embedding_endpoint: str = "databricks-gte-large-en",
    embedding_dims: int = 1024,
    max_history: int = 10,
    timeout: int = 300,
    databricks_host: str | None = None,
    result_volume_path: str | None = None,
)
```

### Required invariants before calling
- Either `lakebase_project` + `lakebase_branch` OR `lakebase_instance_name` must be provided
- One of: `workspace_client`, `(client_id + client_secret)`, or `token` must be provided
- Caller MUST enter the async context manager (`__aenter__`/`__aexit__`) before calling any other method

### Auth priority
1. `workspace_client` — reuse caller's WorkspaceClient (auto-refresh)
2. `client_id` + `client_secret` — class creates WorkspaceClient internally (OAuth M2M)
3. `token` — static PAT (no refresh, expires)

## Key Methods

### `create_session(thread_id, user_id, correlation_id) -> str`
- **Produces**: A new thread with initial state in checkpoint + tracking metadata in DatabricksStore
- **Side effect**: Writes to 3 DatabricksStore namespaces (threads, by_user, by_correlation)
- Generator behavior: Auto-generates UUID7 thread_id if not provided

### `query_stream(thread_id, question, *, auto_approve_tools=False, ...) -> AsyncStreamingResponse`
- **Produces**: A streamable response that yields `StreamEvent` objects
- **Side effect**: Appends `HumanMessage` to checkpoint, calls Responses API, returns `_PersistingStreamWrapper`
- **Failure mode**: Returns `AsyncStreamingResponse._from_error(error_result)` — never raises for network errors. The error is embedded in the result.

### `list_threads_for_user(user_id, limit=50) -> list[dict]`
- Returns dicts with keys: `thread_id`, `title`, `correlation_id`, `created_at`
- Sorted newest-first (not database-level, Python sort)

### `get_history(thread_id) -> list[dict]`
- Returns `[{"role": "user"|"assistant", "content": str}]`
- Reads from DatabricksStore first (`{thread_id}/messages` key), falls back to checkpoint
- The DatabricksStore path is reliable; the checkpoint fallback is unreliable (PostgreSQL pool teardown)

## Side Effects
- Message history is persisted to DatabricksStore under `threads/{thread_id}/messages`
- Checkpoint persist is dead code (deprecated — PostgreSQL pool loses data between requests)
- CSV files are extracted and written to UC Volumes
- MLflow trace tags are set on the trace_id

## Failure Modes
- Not initialized via async context manager → `RuntimeError("Client not initialized...")`
- Lakebase project/branch not provided → `ValueError`
- No auth method provided → `ValueError("Provide one of: workspace_client, client_id+client_secret, or token.")`
- Supervisor endpoint error → `AgentResult.status_code` is non-200, `errors` list is populated

## Read source when
- You need to understand the exact Responses API call format → `query_stream()` at `lg_client.py:498`
- You need to modify the dual-store persistence flow → `create_session()` and `_write_thread_tracking()`
- You need to understand the sliding window logic → `_messages_to_input()` at `lg_client.py:487`

## Internal Method

### `_sse_stream(input_messages, timeout=300) -> AsyncGenerator[SimpleNamespace, None]`
- **Produces**: An async generator yielding SSE events parsed from a direct HTTP POST to the Databricks serving endpoint (`/serving-endpoints/{name}/invocations`)
- **Auth**: Uses `WorkspaceClient.config.authenticate()` for OAuth headers
- **Event types yielded**: `response.output_text.delta` (with `.delta`), `response.output_item.done` (with `.item`), synthetic `response.completed` (at `[DONE]`)
- **Failure mode**: Connection/HTTP errors propagate up to `query_stream()` which catches them and returns `AsyncStreamingResponse._from_error()`
- **Why direct HTTP instead of `databricks-openai`**: `AsyncDatabricksOpenAI.responses.create(stream=True)` routes to `{base_url}/v1/responses` which the Databricks serving endpoint doesn't support, returning an empty stream. Direct SSE to `/invocations` works correctly.

_Last updated: 2026-06-24_
