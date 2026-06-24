from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.engine import close_engine
from app.db.models import init_schema
from app.routers import agents, ag_ui, sessions
from app.services.supervisor_service import supervisor_service


@asynccontextmanager
async def lifespan(app: FastAPI):
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
app.include_router(ag_ui.router, prefix="")


@app.get("/health")
async def health():
    return {"status": "ok"}
