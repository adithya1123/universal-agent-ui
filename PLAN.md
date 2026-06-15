# Universal Agent UI — Build Plan

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js (App Router) + CopilotKit React SDK |
| Agent runtime | CopilotKit Runtime (Next.js API route, factory mode) |
| Backend | FastAPI (Python) — agent adapters + state management |
| State store | Databricks Lakebase (managed PostgreSQL) |
| Agent protocol | AG-UI (SSE streaming, open standard) |
| First adapter | MLflow ResponsesAgent (`POST /invocations`) |
| Auth | Databricks — SP OAuth (recommended), PAT fallback, CLI OAuth U2M fallback |
| ORM / migrations | Drizzle (borrowed from Databricks template patterns) |

## Architecture

```
Frontend (Next.js)
  CopilotKit React UI (CopilotChat, CopilotSidebar, Generative UI)
    ↕ AG-UI over SSE
  CopilotKit Runtime (api/copilotkit/route.ts)
    └── custom factory → HTTP → FastAPI

Backend (FastAPI/Python)
  ┌─────────────────┐  ┌──────────────────────┐
  │ MLflow RA        │  │ Lakebase Store       │
  │ Adapter          │  │ (agent registry,     │
  │ (→ /invocations) │  │  conversations,      │
  │ (→ /v1/responses)│  │  checkpoints)        │
  └─────────────────┘  └──────────────────────┘
```

## What CopilotKit gives us (zero build effort)

- Chat UI — CopilotChat, CopilotSidebar, CopilotPopup
- Streaming — AG-UI protocol (SSE events: text delta, tool calls, reasoning)
- Threads + persistence — automatic session management
- Generative UI — agent renders real React components at runtime
- Multi-agent routing — switch agents by `agentId`
- Human-in-the-loop — agent pauses for user approval
- Shared state — bidirectional agent ↔ app state sync
- Frontend tools + backend tool rendering

## What we build

### Phase 1 — MVP

1. **Scaffold Next.js + CopilotKit**
   - `npx create-next-app frontend`
   - Install `@copilotkit/react-core`, `@copilotkit/react-ui`, `@copilotkit/runtime`
   - Create `/api/copilotkit/route.ts` with CopilotKit Runtime
   - Register `CopilotKit` provider in layout
   - Add `CopilotSidebar` to main page

2. **Scaffold FastAPI backend**
   - FastAPI app with CORS, health check
   - Lakebase connection via `databricks-sdk` + SQLAlchemy
   - Drizzle-style schema for: `registered_agents`, `conversations`, `messages`
   - `POST /ag-ui/run` — agent invocation endpoint (AG-UI SSE streaming)

3. **MLflow ResponsesAgent adapter**
   - Translate AG-UI input → MLflow `/invocations` format (`dataframe_split`)
    - Translate MLflow response → AG-UI event stream
    - Support streaming and non-streaming modes
    - Auth: global Databricks credentials from `.env` (SP OAuth > PAT > CLI)

4. **Wire CopilotKit Runtime → FastAPI**
   - Custom factory (`type: "custom"`) in `/api/copilotkit/route.ts`
   - Proxy messages + threadId + agentId to FastAPI
   - Stream AG-UI events back through the runtime

5. **Agent registry CRUD**
    - FastAPI routes: `POST /api/agents`, `GET /api/agents`, `DELETE /api/agents/:id`
    - Frontend: Agent registration form (name, endpoint URL)
   - Store in Lakebase `registered_agents` table

6. **End-to-end chat flow**
   - Register an agent → chat via CopilotSidebar → response streams from MLflow endpoint → persisted in Lakebase

### Phase 2 — Production polish

7. **Borrowed from Databricks template**
   - Lakebase permission grant script (`grant_lakebase_permissions.py`)
   - Preflight check script
   - `start-app.py` dual-process runner (Next.js + FastAPI)
   - MLflow experiment for feedback collection

8. **Session management**
   - Conversation history sidebar
   - Resume past conversations via thread_id
   - Session list by agent

9. **Multi-agent switching**
   - Agent selector in chat header
   - Agent-specific tool configuration

10. **Generative UI examples**
    - Agent renders data cards, charts, tables as React components
    - Uses CopilotKit `useComponent` / `useAction` hooks

## Directory structure

```
universal-agent-ui/
  frontend/
    app/
      api/copilotkit/route.ts      # CopilotKit Runtime
      page.tsx                     # Main page with CopilotSidebar
      agents/[id]/page.tsx         # Per-agent chat (optional)
    components/
      AgentRegistrationForm.tsx
      AgentCard.tsx
    lib/
      api.ts                       # Fetch → FastAPI
    providers.tsx                  # CopilotKit provider
  backend/
    app/
      main.py                      # FastAPI entry
      routers/
        agents.py                  # POST/GET/DELETE agents
        ag_ui.py                   # POST /ag-ui/run (SSE stream)
      adapters/
        __init__.py                # Abstract agent adapter
        mlflow_responses.py        # MLflow ResponsesAgent
      auth.py                      # Databricks auth (SP OAuth / PAT / CLI)
      db/
        engine.py                  # Lakebase connection
        models.py                  # SQLAlchemy ORM
        schema.sql                 # DDL for tables
      schemas/
        agent.py                   # Pydantic models
        chat.py                    # Message/session models
    scripts/
      grant_lakebase_permissions.py
      preflight.py
    requirements.txt
    .env.example
```

## Key design decisions

- **CopilotKit Runtime in Next.js, not FastAPI** — Keeps the runtime (auth, middleware, routing) in the JS ecosystem where CopilotKit is native. FastAPI handles only agent logic and state.
- **AG-UI via HTTP proxy, not direct** — The Runtime factory proxies to FastAPI. This gives us the Runtime's auth/middleware while keeping Python for Lakebase/MLflow.
- **Adapters are backend-only** — All agent format translation happens in FastAPI. The frontend only speaks AG-UI.
- **Lakebase for persistence, not agent communication** — Lakebase stores metadata (agent configs, conversation history). Agent responses stream live through AG-UI.

## Commands

```bash
# Frontend
cd frontend && pnpm dev          # Next.js on :3000

# Backend
cd backend && uv run uvicorn app.main:app --reload --port 8000

# Full stack
cd backend && uv run python scripts/start_app.py
```

## Databricks template learnings

| What we borrowed | Why |
|---|---|
| Lakebase permission scripts | Postgres-level ACLs for app service principals |
| Drizzle ORM schema management | Migration-driven schema for reliability |
| MLflow feedback collection | Thumbs up/down → MLflow assessments |
| Three-auth-method module (`detect_auth_method`) | SP OAuth (oidc/v1/token), PAT (env var), CLI U2M (`databricks auth token`) |
| Dual-process runner | `start-app.py` coordinating frontend + backend |
