# Contract: `MemoryExtractor` + `UserMemoryService`

`backend/app/memory.py`

Two classes that provide user memory CRUD and LLM-based extraction/generation.

---

## `UserMemoryService`

### `list_memories(user_id, limit=100) -> list[dict]`
- Returns `[{"key": str, "value": str, "category": str, ...}]`
- Uses `asearch()` on namespace `("user_memories", sanitized_user_id)`
- Never raises — returns `[]` on error

### `save_memory(user_id, key, data) -> bool`
- **Side effect**: Writes to DatabricksStore namespace `("user_memories", user_id)`
- **Produces**: A persistent user memory entry
- **Same-key merge**: If the key already exists, the new value is appended to the existing
  value (separator: ". "). If the existing category is "other" and the new one is specific,
  the category is upgraded. `updated_at` is set to now.
- **New memory**: Sets `created_at`, `updated_at`, and `access_count = 0`.
- **Failure modes**:
  - Returns `False` (no exception) when value exceeds 4096 bytes
  - Returns `False` (no exception) when exact key+value already exists (dedup)
  - Evicts least-recently-updated memory if quota (100) is reached — returns `False` if eviction fails
- **Idempotency**: SAFE — identical data returns `False` without writing

### `delete_memory(user_id, key) -> bool`
- Returns `True` if a memory was actually deleted, `False` if key didn't exist

### `bump_access(user_id, key) -> None`
- **Side effect**: Increments `access_count` by 1, updates `updated_at` to now
- **Produces**: Updated memory with higher importance score
- **Called by**: `_inject_memory_context()` for each injected memory (fire-and-forget)

### `list_memories_for_injection(user_id, *, limit=10) -> list[dict]`
- Returns top-N memories ranked by importance score
- **Score formula**: `min(access_count / 10, 1.0) × 0.3 + (1 / (1 + days_since_update)) × 0.7`
- Each entry includes: `key`, `value`, `category`, `access_count`, `created_at`, `updated_at`
- Missing `access_count` → treated as 0; missing `updated_at` → `recency_score = 0.5`
- Returns `[]` if no memories exist for the user

### `format_for_context(memories, max_items=10) -> str`
- Returns formatted block with `[Memory System]` header + `[/Memory System]` footer
- Returns `""` if memories list is empty
- Each memory line: `- [{category}] {key}: {value}`
- Max 10 items, truncated at `INJECTION_MAX` (config: `memory_injection_max`)

---

## `MemoryExtractor`

### Constructor
```python
MemoryExtractor(workspace_client, model_endpoint, databricks_host)
```
- **Env dependencies**: `workspace_client` must have OAuth M2M auth configured

### `extract_from_turn(conversation, existing_keys=None) -> list[dict]`
- **Produces**: List of `{"key": str, "data": dict}` facts extracted from conversation
- **Side effect**: Calls DeepSeek v4 Flash serving endpoint (cheap inference, ~2s latency)
- **Failure modes**:
  - `PermissionError` when SP lacks `Can Query` on serving endpoint — must be handled by caller
  - Returns `[]` on any other LLM failure (logged at WARNING)
- **Read source when**: Changing extraction prompt format — read `EXTRACTION_PROMPT` at `memory.py:38`

### `generate_title(conversation) -> str | None`
- **Produces**: Short 3-5 word title string (max 100 chars)
- **Input**: Full conversation history; only the last 6 messages are used (`conversation[-6:]`)
- **Failure modes**:
  - `PermissionError` when SP lacks `Can Query` on serving endpoint — caller must handle
  - Returns `None` on any other LLM failure (logged at WARNING)
- Fallback: caller should use first user message truncated to 100 chars

### `_call_llm(prompt, *, max_tokens=1500) -> str`
- **Side effect**: HTTP POST to `{databricks_host}/serving-endpoints/{model_endpoint}/invocations`
- **Auth**: Uses `WorkspaceClient.config.authenticate()`
- Returns the text content from `choices[0].message.content`
- **Failure modes**:
  - 403 → raises `PermissionError` with actionable error message
  - Any other HTTP error → raises `httpx.HTTPStatusError`

→ See also: `01_hazards.md#🔴-never-item-6`, `02_business_logic.md#thread-title-derivation`
