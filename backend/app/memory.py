"""User long-term memory service + automatic extraction.

Two parts:
    1. UserMemoryService — CRUD for user memories in DatabricksStore
    2. MemoryExtractor — LLM-based fact extraction from conversation

Uses namespace ("user_memories", sanitized_user_id) following the
Databricks agent-langgraph-advanced template pattern.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

try:
    import httpx
except ImportError:
    httpx = None

try:
    from databricks_langchain import AsyncDatabricksStore
except ImportError:
    raise ImportError(
        "databricks-langchain[memory] is required. "
        "Install with: pip install 'databricks-langchain[memory]' --upgrade"
    )

logger = logging.getLogger(__name__)

_NS_USER_MEMORIES = ("user_memories",)


def _sanitize(value: str) -> str:
    return value.replace(".", "-")

EXTRACTION_PROMPT = """\
You are a memory extraction system. Analyze the conversation below and extract \
any important facts about the user that should be remembered across sessions.

Only extract information that:
- Is explicitly stated by the user (or strongly implied by their direct statement)
- Is likely to remain true for weeks or longer (preferences, background, projects, \
expertise, recurring constraints)
- Would meaningfully improve future responses if remembered

Do NOT extract:
- Temporary or short-lived facts ("I'm tired today", "I need this done by 5pm")
- Trivial one-off details (what they ate, a single troubleshooting step)
- Highly sensitive information (health conditions, politics, religion, criminal history) \
unless the user explicitly asks you to store it
- Information that's already captured in the existing memory keys list below

Existing memory keys to skip: [{existing_keys}]

Conversation:
{conversation}

Return ONLY a JSON array of facts (or [] if nothing worth remembering).
Each fact MUST be: {{"key": "short_unique_name", "data": {{"value": "the fact text", "category": "preference|project|background|constraint|other"}}}}

JSON:"""

TITLE_PROMPT = """\
Generate a short, descriptive title (3-5 words) for this conversation.
Output ONLY the title text — no quotes, no formatting, no explanation.

Conversation:
{conversation}

Title:"""


class UserMemoryService:
    """Long-term user memory CRUD via AsyncDatabricksStore.

    Memories are scoped per user under namespace ("user_memories", <user_id>).
    Each memory is a key-value pair with JSON-serializable data.

    Usage:
        ms = UserMemoryService(store)
        contexts = ms.format_for_context(memories)
        await ms.save("user@co.com", "preferred_lang", {"value": "Python"})
    """

    MAX_PER_USER: int = 100
    MAX_VALUE_SIZE: int = 4096
    INJECTION_MAX: int = 10

    MEMORY_CONTEXT_HEADER = (
        "[Memory System]\n"
        "The following information about the user is available. Use it to "
        "personalize your responses when relevant. Do NOT mention that you\n"
        "are reading from memory \u2014 just use the information naturally.\n"
    )

    def __init__(self, store: AsyncDatabricksStore) -> None:
        self._store = store

    def _ns(self, user_id: str) -> tuple:
        return (*_NS_USER_MEMORIES, _sanitize(user_id))

    async def list_memories(self, user_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        items = await self._store.asearch(self._ns(user_id), query="", limit=limit)
        if items:
            return [{"key": item.key, **item.value} for item in items]
        return []

    async def search_memories(self, user_id: str, query: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            items = await self._store.asearch(self._ns(user_id), query=query, limit=limit)
            if items:
                return [{"key": item.key, **item.value} for item in items]
        except Exception:
            pass
        return []

    async def count_memories(self, user_id: str) -> int:
        items = await self._store.asearch(self._ns(user_id), query="", limit=10000)
        return len(items) if items else 0

    async def get_memory(self, user_id: str, key: str) -> Optional[Dict[str, Any]]:
        item = await self._store.aget(self._ns(user_id), key)
        if item and item.value:
            return {"key": item.key, **item.value}
        return None

    async def save_memory(self, user_id: str, key: str, data: Dict[str, Any]) -> bool:
        value_bytes = len(json.dumps(data).encode("utf-8"))
        if value_bytes > self.MAX_VALUE_SIZE:
            logger.warning(
                "Memory value too large: %d bytes (max %d). Skipping key=%s user=%s",
                value_bytes, self.MAX_VALUE_SIZE, key, user_id,
            )
            return False

        current_count = await self.count_memories(user_id)
        if current_count >= self.MAX_PER_USER:
            existing = await self.get_memory(user_id, key)
            if existing is None:
                logger.info(
                    "Memory quota reached: %d/%d. Evicting oldest. user=%s",
                    current_count, self.MAX_PER_USER, user_id,
                )
                oldest = await self._evict_oldest(user_id)
                if not oldest:
                    return False

        existing_data = await self.get_memory(user_id, key)
        if existing_data and existing_data.get("value") == data.get("value"):
            return False

        await self._store.aput(self._ns(user_id), key, data)
        logger.info("Saved memory key=%s for user=%s", key, user_id)
        return True

    async def delete_memory(self, user_id: str, key: str) -> bool:
        existing = await self.get_memory(user_id, key)
        await self._store.adelete(self._ns(user_id), key)
        if existing:
            logger.info("Deleted memory key=%s for user=%s", key, user_id)
        return existing is not None

    async def delete_all_memories(self, user_id: str) -> int:
        items = await self._store.asearch(self._ns(user_id), query="", limit=10000)
        count = 0
        for item in items:
            await self._store.adelete(self._ns(user_id), item.key)
            count += 1
        logger.info("Deleted %d memories for user=%s", count, user_id)
        return count

    async def _evict_oldest(self, user_id: str) -> Optional[str]:
        """Remove the oldest memory (by key sort) to free quota."""
        items = await self._store.asearch(self._ns(user_id), query="", limit=1)
        if items:
            oldest_key = items[0].key
            await self._store.adelete(self._ns(user_id), oldest_key)
            logger.info("Evicted memory key=%s for user=%s", oldest_key, user_id)
            return oldest_key
        return None

    def format_for_context(self, memories: List[Dict[str, Any]], max_items: int = 10) -> str:
        """Format memories into a context block for agent injection.

        Includes instructions telling the remote agent how to use the
        memory data naturally.
        """
        if not memories:
            return ""

        lines = [self.MEMORY_CONTEXT_HEADER]
        for m in memories[:max_items]:
            key = m.get("key", "")
            value = m.get("data", {}).get("value", "") if isinstance(m.get("data"), dict) else m.get("value", "")
            category = m.get("data", {}).get("category", "") if isinstance(m.get("data"), dict) else ""
            if isinstance(value, dict):
                value = "; ".join(f"{k}={v}" for k, v in value.items())
            label = f"[{category}] " if category else ""
            lines.append(f"- {label}{key}: {value}")

        lines.append("[/Memory System]")
        return "\n".join(lines)


class MemoryExtractor:
    """LLM-based extraction of storable facts from conversation.

    Uses a cheap/fast Databricks serving endpoint for extraction
    (default: deepseek-v4flash-chat). Runs after each turn to
    identify facts worth remembering long-term.
    """

    def __init__(self, workspace_client: Any, model_endpoint: str, databricks_host: str) -> None:
        self._ws = workspace_client
        self._endpoint = model_endpoint
        self._base_url = databricks_host.rstrip("/")

    async def extract_from_turn(
        self,
        conversation: List[Dict[str, str]],
        existing_keys: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Analyze a conversation turn and return extracted facts.

        Args:
            conversation: List of {"role": "user"|"assistant", "content": "..."}
            existing_keys: Keys already stored (avoid duplicates).

        Returns:
            List of {"key": str, "data": dict} to save, or empty list.
        """
        if not conversation:
            return []

        conv_text = "\n".join(
            f"{m['role'].title()}: {m['content']}" for m in conversation
        )
        keys_str = ", ".join(existing_keys or [])
        prompt = EXTRACTION_PROMPT.format(
            existing_keys=keys_str,
            conversation=conv_text,
        )

        try:
            raw = await self._call_llm(prompt)
            return self._parse_response(raw)
        except PermissionError:
            raise
        except Exception as e:
            logger.warning("Memory extraction LLM call failed: %s", e)
            return []

    async def generate_title(
        self,
        conversation: List[Dict[str, str]],
    ) -> Optional[str]:
        """Generate a short title (3-5 words) from conversation history.

        Uses the same LLM endpoint as memory extraction. Falls back to
        None if the LLM call fails (caller should handle fallback).

        Args:
            conversation: List of {"role": "user"|"assistant", "content": "..."}

        Returns:
            Title string (max 100 chars) or None if generation failed.
        """
        if not conversation:
            return None

        conv_text = "\n".join(
            f"{m['role'].title()}: {m['content'][:500]}"
            for m in conversation[-6:]
        )
        prompt = TITLE_PROMPT.format(conversation=conv_text)

        try:
            raw = await self._call_llm(prompt, max_tokens=60)
        except PermissionError:
            raise
        except Exception as e:
            logger.warning("Title generation LLM call failed: %s", e)
            return None

        title = raw.strip().strip('"').strip("'").replace("\n", " ").strip()
        if len(title) > 100:
            title = title[:100]
        return title if title else None

    async def _call_llm(self, prompt: str, *, max_tokens: int = 1500) -> str:
        headers = self._ws.config.authenticate()
        headers["Content-Type"] = "application/json"

        body = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }

        url = f"{self._base_url}/serving-endpoints/{self._endpoint}/invocations"
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code == 403:
                logger.error(
                    "Memory extraction disabled: App Service Principal lacks "
                    "'Can Query' permission on serving endpoint '%s'. "
                    "Grant access in Databricks UI → serving endpoint → Permissions → "
                    "Add principal → 'Can Query'. Skipping extraction.",
                    self._endpoint,
                )
                raise PermissionError(
                    f"SP lacks 'Can Query' on serving endpoint '{self._endpoint}'"
                )
            resp.raise_for_status()
            data = resp.json()

        return data["choices"][0]["message"]["content"]

    def _parse_response(self, raw: str) -> List[Dict[str, Any]]:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        if not text or text in ("[]", "{}"):
            return []

        try:
            facts = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end > start:
                try:
                    facts = json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    return []
            else:
                return []

        if not isinstance(facts, list):
            facts = [facts]

        validated = []
        for f in facts:
            if isinstance(f, dict) and "key" in f and "data" in f:
                validated.append({"key": str(f["key"]), "data": f["data"]})
            elif isinstance(f, dict) and "key" in f:
                validated.append({"key": str(f["key"]), "data": {k: v for k, v in f.items() if k != "key"}})

        return validated
