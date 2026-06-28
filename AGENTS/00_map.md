# Structural Map — Universal Agent UI

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16.2 (App Router), React 19, TypeScript 5 |
| Agent Runtime | CopilotKit v1.60 (React SDK + Runtime in Next.js API route) |
| Backend | FastAPI, Python 3.13, Uvicorn |
| Auth | Databricks SP OAuth M2M (via `WorkspaceClient`) |
| State Store | Databricks Lakebase Autoscaling (`agent-memory-poc/production`) |
| Agent Protocol | AG-UI over SSE (CopilotKit Runtime → FastAPI `/ag-ui/run`) |
| Agent Registry | SQLite (via SQLAlchemy async) |
| Package Manager | pnpm (frontend), uv (backend) |

## Entry Points

| Path | Purpose |
|---|---|
| `backend/app/main.py` | FastAPI app — lifespan, CORS, route registration, health check |
| `frontend/src/app/page.tsx` | Main Next.js page — sidebar + chat layout, session fetch |
| `frontend/src/app/api/copilotkit/route.ts` | CopilotKit Runtime — custom agent factory proxying to FastAPI |
| `frontend/src/app/layout.tsx` | Root layout — CopilotKit provider (single-route mode) |

## Module Index

| Module | Path | Key contracts |
|---|---|---|
| Supervisor client | `backend/app/supervisor/` | → `contracts/async_langgraph_supervisor.md`, → `contracts/streaming.md` |
| Supervisor service | `backend/app/services/supervisor_service.py` | → `contracts/supervisor_service.md` |
| Agent CRUD | `backend/app/routers/agents.py` | — |
| AG-UI streaming | `backend/app/routers/ag_ui.py` | — |
| Session management | `backend/app/routers/sessions.py` | → `contracts/sessions.md` |
| User memory | `backend/app/memory.py` | → `contracts/memory.md` |
| Database | `backend/app/db/` | — |
| Auth | `backend/app/auth.py` | → `contracts/auth.md` (legacy) |
| Message store | `backend/app/supervisor/streaming.py` | → `contracts/streaming.md` |
| CopilotKit route | `frontend/src/app/api/copilotkit/route.ts` | — |
| Chat components | `frontend/src/components/` | — |

## Environment Configuration

| Variable | Default | Used by |
|---|---|---|
| `DATABRICKS_HOST` | — | Supervisor client (WorkspaceClient) |
| `DATABRICKS_CLIENT_ID` | — | Supervisor client (OAuth M2M) |
| `DATABRICKS_CLIENT_SECRET` | — | Supervisor client (OAuth M2M) |
| `LAKEBASE_AUTOSCALING_PROJECT` | `agent-memory-poc` | AsyncCheckpointSaver + AsyncDatabricksStore |
| `LAKEBASE_AUTOSCALING_BRANCH` | `production` | AsyncCheckpointSaver + AsyncDatabricksStore |
| `RESULT_VOLUME_PATH` | `/Volumes/tpo_d/tpo_data_model/tpo_genai_session_results` | CSV extraction |
| `MAX_HISTORY` | `10` | Sliding window size |
| `SUPERVISOR_TIMEOUT` | `300` | Request timeout in seconds |
| `AUTO_APPROVE_TOOLS` | `True` | Auto-approve MCP tool calls from the Supervisor (set `False` to require manual approval) |
| `MEMORY_EXTRACTION_ENABLED` | `True` | Memory extraction + auto-title via DeepSeek v4 Flash |
| `MEMORY_EXTRACTION_MODEL` | `deepseek-v4flash-chat` | Serving endpoint for memory extraction + title generation |
| `MEMORY_MAX_PER_USER` | `100` | Max user memories before LRU eviction |
| `NEXT_PUBLIC_DEFAULT_AGENT_ID` | — | Frontend env — agent UUID for CopilotKit runtime |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend env — backend base URL |
| `BACKEND_URL` | `http://localhost:8000` | CopilotKit Runtime — backend URL for proxy |

## Test Commands

```bash
# Backend lint
cd backend && uv run ruff check app/

# Frontend lint
cd frontend && pnpm lint

# Import check
cd backend && uv run python -c "from app.main import app; print('OK')"
```

_Last updated: 2026-06-27_
