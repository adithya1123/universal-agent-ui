# Universal Agent UI — Agent Instructions

This is a full-stack application with a Python FastAPI backend and a TypeScript Next.js frontend. It provides a chat UI for interacting with Databricks Mosaic AI supervisor agents. The supervisor client library (`backend/app/supervisor/`) handles all agent communication, session management, and Lakebase persistence.

## Document Inventory

| Document | What it covers |
|---|---|
| `AGENTS/00_map.md` | Full module index, entry points, environment config |
| `AGENTS/01_hazards.md` | Sharp edges, auth pitfalls, Lakebase state management |
| `AGENTS/02_business_logic.md` | Domain calculations — CSV extraction, session scoring formula |
| `AGENTS/03_narratives.md` | What each module does, why it exists |
| `AGENTS/contracts/` | Key function/class contracts with non-obvious behavior |
| `AGENTS/playbooks/` | Start backend, start frontend, register agent, full-stack test |

## Memory format

Directory format. Start with `AGENTS/00_map.md` for orientation.

_Last updated: 2026-06-23_
