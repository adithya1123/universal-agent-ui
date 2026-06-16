from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["ag-ui"])


class RunRequest(BaseModel):
    messages: list[dict]
    thread_id: str | None = None
    agent_id: str | None = None


@router.post("/ag-ui/run")
async def ag_ui_run(req: RunRequest):
    return {"status": "not_implemented", "message": "AG-UI endpoint coming in Phase 2"}
