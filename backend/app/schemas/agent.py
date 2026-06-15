from pydantic import BaseModel


class AgentConfig(BaseModel):
    id: str | None = None
    name: str
    endpoint_url: str
    endpoint_type: str = "mlflow_responses"
    api_key: str = ""
    description: str = ""


class AgentResponse(BaseModel):
    id: str
    name: str
    endpoint_url: str
    endpoint_type: str
    description: str
    created_at: str
