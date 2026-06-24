# Playbook: Start the Backend

## When to use
The user wants to start the FastAPI backend server for local development.

## Fast path

```bash
cd backend && uv run uvicorn app.main:app --reload --port 8000
```

The server starts on `http://localhost:8000`. The `/health` endpoint returns `{"status": "ok"}`.

## Why this is the direct route
- `uv run` activates the venv managed by uv
- `--reload` automatically restarts on Python file changes
- `--port 8000` matches the frontend's default `BACKEND_URL`

## Validation
```bash
curl http://localhost:8000/health
# → {"status":"ok"}
curl http://localhost:8000/api/agents
# → [] (empty array, no agents registered yet)
```

## Common failure modes

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'fastapi'` | Run `uv pip install -r requirements.txt` first |
| `.env` style credentials not found → `ValueError` | Create `backend/.env` from `.env.example` with valid Databricks credentials |
| Port 8000 already in use | Check for existing uvicorn process: `lsof -i :8000`, kill it, or change port |
| Route not found (404) on existing endpoint | Server started without `--reload` after a file change; restart it |

## Misleading paths to avoid
- Do NOT use `python -m uvicorn app.main:app` — this can activate the wrong Python interpreter
- Do NOT run from the repo root — always `cd backend` first so relative SQLite path works

_Last updated: 2026-06-23_
