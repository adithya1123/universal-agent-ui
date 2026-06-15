from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import agents, ag_ui

app = FastAPI(title="Universal Agent UI Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router, prefix="/api")
app.include_router(ag_ui.router, prefix="")


@app.get("/health")
async def health():
    return {"status": "ok"}
