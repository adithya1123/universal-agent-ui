# Playbook: Start the Frontend

## When to use
The user wants to start the Next.js frontend dev server for local development.

## Fast path

```bash
cd frontend && pnpm dev
```

The server starts on `http://localhost:3000`.

## Why this is the direct route
- `pnpm dev` uses Next.js's built-in dev server with hot module replacement
- The `.env.local` file (gitignored) sets `NEXT_PUBLIC_API_URL=http://localhost:8000`
- CopilotKit Runtime at `/api/copilotkit` proxies to the backend at `http://localhost:8000`

## Prerequisites
Backend must be running on port 8000 (or updated `BACKEND_URL` in `.env.local`).

## Validation
Open `http://localhost:3000` in a browser. You should see a sidebar and a chat area. The agent list will be empty until an agent is registered.

## Common failure modes

| Symptom | Fix |
|---|---|
| `Module not found: Can't resolve '@copilotkit/...'` | Run `pnpm install` |
| Frontend loads but shows "[Backend error: ...]" in chat | Backend not running; start it on port 8000 |
| Page is blank with console error about CopilotKit | Ensure `layout.tsx` wraps app in `<CopilotKit runtimeUrl="/api/copilotkit">` |
| Port 3000 already in use | Kill the existing process or set `PORT=3001 pnpm dev` |

## Misleading paths to avoid
- Do NOT run `next start` (that starts the production build, not dev mode)
- Do NOT run from the repo root — always `cd frontend` first

_Last updated: 2026-06-23_
