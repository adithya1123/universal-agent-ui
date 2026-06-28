from pydantic import BaseModel


class SessionSummary(BaseModel):
    thread_id: str
    title: str
    created_at: str
    correlation_id: str | None = None


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]


class MessageEntry(BaseModel):
    role: str
    content: str


class SessionHistoryResponse(BaseModel):
    thread_id: str
    messages: list[MessageEntry]


class ResultsIndexEntry(BaseModel):
    message_id: str
    question: str
    csv_path: str | None = None
    result_meta: dict | None = None
    all_files: list[str] = []
    latency_s: float
    num_steps: int
    success: bool


class ThreadMetadata(BaseModel):
    thread_id: str
    user_id: str | None = None
    correlation_id: str | None = None
    created_at: str | None = None


class TitleUpdateRequest(BaseModel):
    title: str


class TitleResponse(BaseModel):
    title: str
