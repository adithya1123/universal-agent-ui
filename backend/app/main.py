from contextlib import asynccontextmanager

import mlflow
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.engine import close_engine
from app.db.models import init_schema
from app.routers import agents, ag_ui, memory, sessions
from app.services.supervisor_service import supervisor_service

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.mlflow_tracking_uri:
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    init_schema()
    await supervisor_service.start()
    yield
    await supervisor_service.stop()
    await close_engine()


app = FastAPI(title="Universal Agent UI Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(memory.router, prefix="/api")
app.include_router(ag_ui.router, prefix="")


@app.get("/health")
async def health():
    return {"status": "ok"}
