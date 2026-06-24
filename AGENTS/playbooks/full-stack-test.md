# Playbook: Full Stack Test

## When to use
After starting both servers, verify the entire stack works end-to-end.

## Fast path

### 1. Health check
```bash
curl http://localhost:8000/health
# → {"status":"ok"}
```

### 2. Register the supervisor agent
```bash
curl -s -X POST http://localhost:8000/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "TPO Supervisor",
    "endpoint_url": "https://adb-4462387864835334.14.azuredatabricks.net/serving-endpoints/mas-bca2870e-endpoint/invocations",
    "endpoint_type": "supervisor",
    "description": "Production TPO supervisor agent"
  }'
```
Save the returned `id`.

### 3. Test the AG-UI streaming endpoint
```bash
AGENT_ID="<id-from-step-2>"
curl -N -X POST http://localhost:8000/ag-ui/run \
  -H "Content-Type: application/json" \
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"Hello, what can you do?\"}],\"agent_id\":\"$AGENT_ID\",\"user_id\":\"test@user.com\"}"
```
You should see streaming text chunks from the supervisor agent.

### 4. Verify the session was tracked
```bash
# List sessions for the user
curl "http://localhost:8000/api/sessions?agent_id=$AGENT_ID&user_id=test@user.com"
# → Should list one session with the thread_id
```

### 5. Frontend check
Open `http://localhost:3000`. The frontend should:
- Display an empty sidebar (no prior sessions loaded for the anonymous user)
- Allow typing in the chat input
- Stream responses from the supervisor

## Common failure modes

| Step | Symptom | Fix |
|---|---|---|
| 1 | Connection refused | Backend not running; start it |
| 3 | 404 agent not found | Agent not registered; run step 2 |
| 3 | 500 or hang (slow first response) | Backend is initializing the supervisor client; wait ~3s |
| 3 | Error with Databricks auth | Verify `.env` credentials are correct |
| 5 | "[Backend error: ...]" in chat | Backend not running or wrong BACKEND_URL in `.env.local` |

## Debugging the streaming response
If the AG-UI stream returns an error instead of text:
```bash
curl -N -X POST http://localhost:8000/ag-ui/run ... 2>&1 | head -20
```
Look for `[Backend error: ...]` or read the uvicorn server logs for the full stack trace.

_Last updated: 2026-06-23_
