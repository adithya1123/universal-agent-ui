from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from app.schemas.chat import Message


class AgentAdapter(ABC):

    @abstractmethod
    async def invoke(
        self,
        messages: list[Message],
        api_key: str = "",
        thread_id: str | None = None,
    ) -> Message: ...

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        api_key: str = "",
        thread_id: str | None = None,
    ) -> AsyncGenerator[str, None]: ...
