# Universal Agent UI — AGENTS.md

## Project

Universal frontend + backend for interacting with AI agents. New project — structure is still being established.

## Global rules

This repo inherits the instructions in `~/.claude/CLAUDE.md`. That file takes precedence for code accuracy, documentation lookup, and verification requirements. Always read it first in a session.

## Projected structure

Use the following layout unless a task explicitly overrides it:

```
universal_agent_ui/
  frontend/       # Next.js / React app (UI)
  backend/        # Python service (agent orchestration, API)
  packages/       # Shared TypeScript/Python packages (if monorepo)
```

- `frontend/` — own `package.json`, Next.js config, tailwind, etc.
- `backend/` — own `pyproject.toml` or `requirements.txt`, FastAPI preferred
- Keep root `package.json` only for workspace orchestration, never app code
- Do not put source code at the root level

## Tech stack conventions (decide on first use, then pin here)

- **Frontend**: Next.js (App Router), TypeScript, Tailwind CSS
- **Backend**: Python, FastAPI
- **State/API client**: tRPC or plain fetch (decide at first endpoint)
- **Package manager**: pnpm (frontend), uv or pip (backend)
- **Agent SDK**: LangChain / LangGraph (likely, based on sibling projects)
- **Auth**: Databricks auth module (`backend/app/auth.py`) — service principal OAuth (client credentials via `/oidc/v1/token`), PAT fallback, CLI fallback. Auto-detected by `detect_auth_method()`. Tokens cached with automatic refresh.

## Developer workflow

- `pnpm dev` — start frontend dev server (in `frontend/`)
- `uv run uvicorn app.main:app --reload` — start backend (in `backend/`)
- `pnpm lint` / `pnpm typecheck` — run before committing frontend changes
- `ruff check backend/ && mypy backend/` — run before committing backend changes
- Always lint + typecheck + test before opening a PR

## Testing

- Frontend: Vitest + React Testing Library
- Backend: pytest
- Integration tests: use a shared compose file or test harness

## Key constraints

- Never commit secrets, `.env` files, or API keys
- Use `AGENTS.md` as a living document — update it when you establish a new convention
- If a sibling project (e.g., `crawl-prod-agent`, `foundry_agent`) has relevant patterns, reference them rather than re-deriving
- Generated code and schema changes must be committed separately from logic changes
