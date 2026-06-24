# Playbook: Register a Supervisor Agent

## When to use
A new Databricks Mosaic AI supervisor endpoint has been deployed and needs to be registered so the UI can chat with it.

## Fast path

```bash
curl -X POST http://localhost:8000/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Supervisor",
    "endpoint_url": "https://adb-xxx.azuredatabricks.net/serving-endpoints/my-supervisor/invocations",
    "endpoint_type": "supervisor",
    "description": "What this agent does"
  }'
```

## Response
```json
{
  "id": "uuid-string",
  "name": "My Supervisor",
  "endpoint_url": "https://.../invocations",
  "endpoint_type": "supervisor",
  "description": "What this agent does",
  "created_at": "2026-06-23T..."
}
```

Save the `id` — it's used as `agent_id` in the frontend and API calls.

## How it works
- The agent is stored in the `universal_agent_ui.db` SQLite database
- `SupervisorService` lazily initializes a supervisor client for the `endpoint_url` on first use
- Each unique `endpoint_url` gets its own `AsyncLangGraphSupervisor` with its own Lakebase connections

## Common failure modes

| Symptom | Fix |
|---|---|
| Backend returns 503 on first chat | Backend is initializing the supervisor client (takes ~2-3s for first connection to Lakebase) |
| Agent not found | Verify the agent was registered: `curl http://localhost:8000/api/agents` |
| Wrong `endpoint_type` | The UI doesn't use this field yet, but set it to `"supervisor"` for consistency |

_Last updated: 2026-06-23_
