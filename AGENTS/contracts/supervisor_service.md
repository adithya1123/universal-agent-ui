# Contract: `SupervisorService`

`backend/app/services/supervisor_service.py`

Manages a pool of `AsyncLangGraphSupervisor` instances, one per unique endpoint URL. Lazily initializes clients on first use and shuts them all down on app stop.

## Constructor

```python
SupervisorService()
```

No arguments. Reads config from `app.config.settings`.

## Key Methods

### `start() -> None`
- **Side effect**: Sets `_started = True`. Does NOT pre-warm any clients.

### `stop() -> None`
- **Side effect**: Calls `close()` on every client in the pool, clears the dict. Logs and swallows per-client errors.

### `_get_client(endpoint_url) -> AsyncLangGraphSupervisor`
- **Return behavior**: Returns cached client if exists, otherwise creates new client, calls `__aenter__()` and `setup()`, stores in pool
- **Failure mode**: Can raise `ValueError` if no auth credentials are configured in settings
- **Side effect**: Opens persistent Lakebase connections

### `create_session(endpoint_url, user_id, correlation_id) -> str`
Delegates to `AsyncLangGraphSupervisor.create_session()`. Will init client if needed.

### `query_stream(endpoint_url, thread_id, question, *, auto_approve_tools=False)`
Returns the stream from `AsyncLangGraphSupervisor.query_stream()`. Will init client if needed.

### `delete_thread(endpoint_url, thread_id) -> None`
**No-op**: logs the intent but does not delete from Lakebase. Threads persist indefinitely.

## Side Effects
- First call to any method with a new endpoint_url opens persistent Lakebase connections
- Each client maintains control over its own checkpoint saver + store
- Calling `stop()` closes all connections gracefully

## Empty-string sanitization
Settings returns `""` for unset env vars. The service sanitizes these with a `_val()` helper that converts empty strings to `None` before passing to the supervisor client constructor. New code should follow the same pattern.

## Consumed by
- `routers/ag_ui.py` (the CopilotKit streaming endpoint)
- `routers/sessions.py` (thread listing, history, metadata)
- `routers/agents.py` (the `/chat` endpoint)
- `app/main.py` lifecycle (start/stop in lifespan)

_Last updated: 2026-06-23_
