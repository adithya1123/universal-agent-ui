# Playbook: Memory System (Short-term + Long-term)

_Last updated: 2026-06-28_

## Use when

Understanding, debugging, or extending the memory system — what is remembered across
turns, how it's stored, how it's injected into agent context, and how memories are
consolidated over time.

## Overview

Two independent memory systems with different scopes and lifetimes:

| Dimension | Short-term (Session) | Long-term (User) |
|---|---|---|
| **Scope** | One conversation thread | One user across all threads |
| **Lifetime** | Until thread is deleted | Indefinite (up to 100 per user) |
| **Storage** | LangGraph checkpoint (Databricks Lakebase PG) | DatabricksStore (Lakebase k/v) |
| **Namespace** | `thread_id` → checkpoint state | `("user_memories", <sanitized_user_id>)` |
| **Content** | Messages, results_index, agent_result | Facts with key/value/category |
| **Persistence** | Written every turn by `_PersistingStreamWrapper` | Written after extraction or explicit CRUD |
| **Injection** | N/A (is the conversation) | Injected before every query (up to 10 memories) |

---

## Short-term Memory (Checkpoint)

### Storage location

LangGraph checkpoint in Databricks Lakebase PostgreSQL. Each thread has one checkpoint
chain (linear, one checkpoint per turn). Written via `graph.aupdate_state()` → `AsyncCheckpointSaver`.

### What is stored per turn

```python
state = {
    "messages": [HumanMessage, AIMessage, ...],   # full conversation
    "agent_result": { ... },                        # last AgentResult as dict
    "results_index": [{ ... }, ...],               # per-turn CSV metadata
    "thread_id": "uuid-string",                    # thread identifier
}
```

- **messages**: Full history of `HumanMessage` + `AIMessage` objects. Appended each turn.
- **results_index**: List of per-turn metadata entries (question, csv_path, latency, success).
- **agent_result**: The last query's AgentResult (overwritten each turn — only latest is kept).

### Write path

In `_PersistingStreamWrapper.__aiter__()` in `streaming.py`:

```
1. User sends message → appended to in-memory messages list
2. Stream runs (yield events to caller)
3. After stream ends:
   a. Build turn_entry for results_index
   b. Append AIMessage(content=answer) to messages
   c. Push results_index entry to existing_results
   d. aupdate_state({"messages": messages, "results_index": existing_results})
```

This is a single `aupdate_state` call per turn — one read (to load existing results_index)
and one write. There is no intermediate state write (removed to avoid orphaned checkpoints).

### Read path

`get_history(thread_id)` in `lg_client.py`:
```
1. _get_state(thread_id) → aget_state(config) → snapshot.values["messages"]
2. Convert BaseMessage objects to {"role": "...", "content": "..."} dicts
3. Returns full conversation (no truncation — truncation is on injection, not storage)
```

### Reliability note

The `AsyncCheckpointSaver` uses PostgreSQL via `psycopg_pool`. Under uvicorn reload or
async lifecycle changes, pool workers may be destroyed while tasks are pending
("Task was destroyed but it is pending!"). Data committed in one connection can be
invisible to new connections. This is a known issue — message history is single-source
from checkpoint (no dual-store fallback), so thread deletion must also clean checkpoints.

---

## Long-term Memory (User Memories)

### Storage location

DatabricksStore at namespace `("user_memories", <sanitized_user_id>)`. Each memory is a
key-value pair where the key is a short descriptive name (e.g., `preferred_language`) and
the value is a JSON dict:

```json
{
  "value": "Python",
  "category": "preference",
  "created_at": "2026-06-28T12:00:00+00:00",
  "updated_at": "2026-06-28T12:00:00+00:00",
  "access_count": 3
}
```

### Extraction (auto-detection)

After every turn, `MemoryExtractor.extract_from_turn()` in `memory.py` is called from
`_PersistingStreamWrapper.__aiter__()`:

```
1. Take last 6 messages from conversation
2. Build prompt with existing memory keys (to avoid duplicates)
3. Call DeepSeek v4 Flash serving endpoint (temperature=0.0, max_tokens=1500)
4. Parse JSON response → list of {"key": str, "data": {"value": str, "category": str}}
5. For each fact: call save_memory() → dedup + merge + quota check
```

The extraction prompt tells the LLM:
- Only extract facts explicitly stated by the user
- Only extract facts likely to remain true for weeks
- Do NOT extract temporary facts, trivial one-off details, or sensitive info
- Return `[]` if nothing worth remembering

### CRUD API

| Method | Endpoint | Action |
|---|---|---|
| GET | `/api/memory?agent_id=...&user_id=...&query=...` | List/search memories |
| GET | `/api/memory/{key}?agent_id=...&user_id=...` | Get specific memory |
| POST | `/api/memory` | Save memory (body: agent_id, user_id, key, data) |
| DELETE | `/api/memory/{key}?agent_id=...&user_id=...` | Delete memory |

### save_memory() behavior

```
if key exists:
    if new_value already in existing_value → return False (no-op)
    append new_value: f"{existing_value}. {new_value}"
    update updated_at = now
    upgrade category from "other" if new category is specific
else:
    add created_at = now, updated_at = now, access_count = 0
    
    if count >= MAX_PER_USER (100):
        evict memory with oldest updated_at
        if eviction fails → return False
    
    store via aput()
```

### Quota enforcement

- `MAX_PER_USER = 100` (config: `MEMORY_MAX_PER_USER`)
- `MAX_VALUE_SIZE = 4096` bytes (config: `MEMORY_MAX_VALUE_SIZE`)
- Eviction policy: least-recently-updated by `updated_at` (reads all 100, sorts ascending, deletes first)

### Injection into query

Before every query, `_inject_memory_context()` in `lg_client.py`:

```
1. list_memories_for_injection(user_id, limit=INJECTION_MAX=10)
   → returns top-10 memories ranked by importance score
2. format_for_context(memories) → formatted block:
   [Memory System]
   ...
   - [preference] preferred_language: Python
   - [project] current_project: Sales Dashboard
   [/Memory System]
3. Insert formatted block before last user message in input_messages
4. bump_access(key) for each injected memory (fire-and-forget)
```

### Importance score

```
score = min(access_count / 10, 1.0) × 0.3 + (1 / (1 + days_since_update)) × 0.7
```

- `access_count` is incremented each time the memory is injected (persisted in the store)
- `recency_score` decays from 1.0 (updated just now) toward 0
- Higher score = more important → appears earlier in injection
- Missing `access_count` (legacy) → treated as 0
- Missing `updated_at` (legacy) → recency_score = 0.5

### format_for_context()

```python
"[Memory System]\n"
"The following information about the user is available. Use it to "
"personalize your responses when relevant. Do NOT mention that you "
"are reading from memory — just use the information naturally.\n"
"- [preference] preferred_language: Python\n"
"- [project] current_project: Sales Dashboard\n"
"[/Memory System]"
```

The block is wrapped with instructions telling the remote agent to use the
information naturally (not mention "memory"). This is a best-effort hint —
the agent's system prompt may dominate over injected context.

### Frontend display

The Memories tab in the sidebar (`memory-panel.tsx`) shows:
- Key (bold, truncated)
- Category badge (colored: preference=blue, project=green, background=purple, constraint=amber)
- Value text (gray, 3-line clamp)
- Relative timestamp ("Updated 3h ago", "2d ago", etc.)
- Delete button (on hover)
- Sorted by importance (access_count descending)
- Memory count header: "Memories (N)"
- Add form: key input, value textarea, category dropdown, Save button

---

## Title Generation (Separate from memory, reuses the same LLM)

### Auto-title endpoint

`POST /api/sessions/{thread_id}/auto-title?agent_id=...`

1. Load conversation history from checkpoint (`get_history()`)
2. Call `MemoryExtractor.generate_title(history)` → DeepSeek v4 Flash with short prompt
3. LLM returns 3-5 word title
4. Persist via `update_thread_title()` to all 3 store namespaces
5. Fallback: if LLM unavailable, use first user message truncated to 100 chars

### Manual rename endpoint

`PATCH /api/sessions/{thread_id}/title?agent_id=...` with body `{"title": "..."}`

Trims and truncates to 100 chars, then calls `update_thread_title()`.

### Title update path

`update_thread_title()` in `lg_client.py`:
1. Get existing metadata from `("threads",)` namespace
2. Batch-read all 3 namespace entries via `GetOp`
3. Batch-write updated title to all 3 via `PutOp` (threads, by_user, by_correlation)

---

## Frontend components involved

| Component | File | Role in memory |
|---|---|---|
| `Sidebar` | `sidebar.tsx` | Shows session list with titles; agent selector dropdown |
| `MemoryPanel` | `memory-panel.tsx` | Shows user memories with CRUD, timestamps, importance sort |
| `Chat` | `chat.tsx` | Orchestrates query, loads session history on mount |
| `Messages` | `messages.tsx` | Shows smart status bar with reasoning text during streaming |
| `Route` | `api/copilotkit/route.ts` | SSE parser for text/routing/reasoning events |
| `api.ts` | `lib/api.ts` | API helpers for all memory CRUD + title operations |

---

## Source landmarks

- **Memory extraction + CRUD**: `backend/app/memory.py` — `UserMemoryService` + `MemoryExtractor`
- **Memory injection**: `backend/app/supervisor/lg_client.py:566` — `_inject_memory_context()`
- **Post-stream extraction trigger**: `backend/app/supervisor/streaming.py:610` — `__aiter__()` memory extraction block
- **Memory API endpoints**: `backend/app/routers/memory.py`
- **Checkpoint write**: `backend/app/supervisor/streaming.py:559` — `aupdate_state()`
- **Thread tracking + title update**: `backend/app/supervisor/helpers.py:808` — `_NS_THREADS`, `_build_config()`
- **Frontend memory panel**: `frontend/src/components/memory-panel.tsx`
- **Frontend API client**: `frontend/src/lib/api.ts` — `listMemories()`, `saveMemory()`, `deleteMemory()`

---

## Validation

```bash
# List all memories for a user
curl "http://localhost:8000/api/memory?agent_id=$AGENT_ID&user_id=test@user.com"

# Save a memory
curl -X POST http://localhost:8000/api/memory \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "...", "user_id": "test@user.com", "key": "preferred_language", "data": {"value": "Python", "category": "preference"}}'

# Delete a memory
curl -X DELETE "http://localhost:8000/api/memory/preferred_language?agent_id=$AGENT_ID&user_id=test@user.com"

# Check checkpoint history counts (for debugging injection)
curl -s "http://localhost:8000/api/sessions/$THREAD_ID/history?agent_id=$AGENT_ID" | python3 -c "import sys,json; msgs=json.load(sys.stdin)['messages']; print(f'{len(msgs)} messages')"
```

---

## Common pitfalls

| Symptom | Root cause | Fix |
|---|---|---|
| Memories not extracted | SP lacks `Can Query` on `deepseek-v4flash-chat` endpoint | Grant permission in Databricks UI, or set `MEMORY_EXTRACTION_ENABLED=False` |
| Memories not injected | `INJECTION_MAX` is 0 or `user_id` is missing | Check `settings.memory_injection_max` in `.env`; ensure `user_id` is set in CopilotKit forwardedProps |
| Same memory keeps showing old value | Same-key merge appends new info; old value is preserved | Use DELETE endpoint to remove the memory, then let auto-extraction recreate it |
| Memory count stuck at 0 | `agent_id` not found in SQLite registry | Register the agent first via `POST /api/agents` |
| Checkpoint not persisting between requests | `psycopg_pool` connections destroyed under uvicorn reload | This is a known limitation — messages survive the current HTTP request but may not survive server restart |
| Title not updating after auto-title | Thread not found in DatabricksStore | `update_thread_title()` silently skips missing threads (logged at WARNING) |

→ See also: `contracts/memory.md`, `contracts/async_langgraph_supervisor.md`, `02_business_logic.md#memory-importance-score`
