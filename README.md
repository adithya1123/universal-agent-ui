# Universal Agent UI

Unified frontend + backend for chatting with any AI agent. Uses [CopilotKit](https://docs.copilotkit.ai) (AG-UI protocol) for streaming chat and [FastAPI](https://fastapi.tiangolo.com/) for agent orchestration.

## Quick start

```bash
# Terminal 1 — Backend
cd backend
cp .env.example .env
uv venv && uv pip install -r requirements.txt
uv run uvicorn app.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
pnpm install
pnpm dev
```

Open http://localhost:3000.

## Connecting a Databricks agent

Authentication is handled globally by the backend — credentials go in `.env`, not per-agent.

### 1. Set up Databricks credentials

Pick one:

#### Service Principal OAuth (recommended for production)

Create a service principal in your Databricks Account Console, then:

```bash
echo "DATABRICKS_HOST=https://<workspace>.cloud.databricks.com" >> backend/.env
echo "DATABRICKS_CLIENT_ID=<service-principal-client-id>" >> backend/.env
echo "DATABRICKS_CLIENT_SECRET=<service-principal-secret>" >> backend/.env
```

Grant it access to your agent's serving endpoint:

```bash
databricks serving-endpoints update-permissions <endpoint-name> \
  --json '{ "access_control_list": [{ "service_principal_name": "<sp-id>", "permission_level": "CAN_QUERY" }] }'
```

#### Personal Access Token (local dev)

```bash
echo "DATABRICKS_HOST=https://<workspace>.cloud.databricks.com" >> backend/.env
echo "DATABRICKS_TOKEN=dapi_your_token_here" >> backend/.env
```

#### CLI OAuth U2M (local dev)

```bash
databricks auth login
echo "DATABRICKS_CONFIG_PROFILE=DEFAULT" >> backend/.env
```

### 2. Find your agent endpoint

Your MLflow ResponsesAgent is deployed as a Databricks Model Serving endpoint:

```
https://<workspace>.cloud.databricks.com/serving-endpoints/<endpoint-name>/invocations
```

List endpoints:

```bash
databricks serving-endpoints list
```

### 3. Register the agent via the API

```bash
curl -X POST http://localhost:8000/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-agent",
    "endpoint_url": "https://<workspace>.cloud.databricks.com/serving-endpoints/<endpoint-name>/invocations",
    "endpoint_type": "mlflow_responses",
    "description": "My Databricks agent"
  }'
```

Save the returned `id` — you'll use it for chat requests.

### 4. Chat with the agent

```bash
curl -X POST http://localhost:8000/api/agents/<agent-id>/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

## Connecting Lakebase

Lakebase stores agent configurations, conversation history, and checkpoints.

### Prerequisites

- A Databricks workspace with Unity Catalog enabled
- A Lakebase instance or autoscaling project

### 1. Create a Lakebase instance

```bash
# Via Databricks CLI
databricks lakehouse create-instance <instance-name>

# Or via the UI: Catalog > Lakebase > Create Instance
```

### 2. Configure backend/.env

For a **provisioned instance**:

```env
LAKEBASE_INSTANCE_NAME=<instance-name>
LAKEBASE_URL=postgresql://<user>@<host>:5432/<database>
```

For an **autoscaling project**:

```env
LAKEBASE_AUTOSCALING_PROJECT=<project-name>
LAKEBASE_AUTOSCALING_BRANCH=<branch-name>
```

### 3. Grant permissions

After deploying your app as a Databricks App, grant its service principal access to Lakebase tables:

```sql
-- Run on your Lakebase instance
DO $$
DECLARE
   app_sp text := '<app-service-principal-id>';
BEGIN
   EXECUTE format('GRANT USAGE, CREATE ON SCHEMA public TO %I;', app_sp);
   EXECUTE format('GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO %I;', app_sp);
END $$;
```

### 4. Run migrations

```bash
cd backend
uv run python -c "from app.db.engine import init_db; import asyncio; asyncio.run(init_db())"
```

## MLflow tracing

Enable agent tracing by setting an MLflow experiment ID:

```env
MLFLOW_EXPERIMENT_ID=<experiment-id>
```

Create one if needed:

```bash
USER=$(databricks current-user me | jq -r .userName)
databricks experiments create-experiment /Users/$USER/universal-agent-ui
```

## Project structure

```
universal_ui/
  frontend/          # Next.js + CopilotKit
    src/
      app/
        api/copilotkit/route.ts    # CopilotKit Runtime → FastAPI
        layout.tsx                  # CopilotKit provider
        page.tsx                    # Sidebar + Chat layout
      components/
        chat.tsx                    # Chat orchestrator (useAgent)
        chat-header.tsx             # Top bar
        message.tsx                 # Message bubbles
        messages.tsx                # Scrollable message list
        multimodal-input.tsx        # Chat input
        sidebar.tsx                 # Collapsible session sidebar
        theme-provider.tsx          # Dark/light mode
      lib/
        api.ts                      # API client
  backend/           # FastAPI
    app/
      main.py                       # App entry + routes
      config.py                     # Settings
      auth.py                       # Databricks auth (SP OAuth / PAT / CLI)
      routers/
        agents.py                   # Agent CRUD + chat
        ag_ui.py                    # AG-UI endpoint
      adapters/
        mlflow_responses.py         # MLflow ResponsesAgent adapter
      schemas/
        agent.py                    # Pydantic models
        chat.py
```

## API reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/api/agents` | List registered agents |
| `POST` | `/api/agents` | Register an agent |
| `DELETE` | `/api/agents/:id` | Remove an agent |
| `POST` | `/api/agents/:id/chat` | Send message (streams SSE when `stream: true`) |
| `POST` | `/ag-ui/run` | AG-UI protocol endpoint (used by CopilotKit Runtime) |
