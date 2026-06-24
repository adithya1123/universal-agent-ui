from pydantic import BaseModel


class Message(BaseModel):
    role: str
    content: str
    tool_calls: list[dict] | None = None


class ChatRequest(BaseModel):
    messages: list[Message]
    thread_id: str | None = None
    agent_id: str
    user_id: str | None = None
    stream: bool = True


class ChatResponse(BaseModel):
    thread_id: str
    message: Message
