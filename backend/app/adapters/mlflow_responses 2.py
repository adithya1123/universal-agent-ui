import json
from collections.abc import AsyncGenerator

import httpx

from app.adapters import AgentAdapter
from app.auth import get_databricks_token
from app.schemas.chat import Message


class MLflowResponsesAdapter(AgentAdapter):

    def __init__(self, endpoint_url: str):
        self.endpoint_url = endpoint_url

    async def invoke(
        self,
        messages: list[Message],
        api_key: str = "",
        thread_id: str | None = None,
    ) -> Message:
        token = await get_databricks_token()
        headers = self._build_headers(token)
        payload = self._build_payload(messages, thread_id)

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.endpoint_url,
                    json=payload,
                    headers=headers,
                    timeout=120,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Agent invoke failed: {e.response.status_code} {e.response.text}"
            )
        except (httpx.RequestError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Agent invoke failed: {e}")

        return Message(role="assistant", content=data.get("output", ""))

    async def stream(
        self,
        messages: list[Message],
        api_key: str = "",
        thread_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        token = await get_databricks_token()
        headers = self._build_headers(token)
        payload = self._build_payload(messages, thread_id, stream=True)

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                self.endpoint_url,
                json=payload,
                headers=headers,
                timeout=300,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        yield line.removeprefix("data: ")

    def _build_headers(self, token: str) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

    def _build_payload(
        self,
        messages: list[Message],
        thread_id: str | None = None,
        stream: bool = False,
    ) -> dict:
        return {
            "input": [m.model_dump(exclude_none=True) for m in messages],
            "stream": stream,
            "custom_inputs": {"thread_id": thread_id} if thread_id else {},
        }


async def invoke_agent(
    endpoint_url: str,
    messages: list[Message],
    api_key: str = "",
    thread_id: str | None = None,
) -> Message:
    adapter = MLflowResponsesAdapter(endpoint_url)
    return await adapter.invoke(messages, api_key, thread_id)


async def stream_agent(
    endpoint_url: str,
    messages: list[Message],
    api_key: str = "",
    thread_id: str | None = None,
) -> AsyncGenerator[str, None]:
    adapter = MLflowResponsesAdapter(endpoint_url)
    async for chunk in adapter.stream(messages, api_key, thread_id):
        yield chunk
