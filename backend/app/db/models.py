import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.engine import DATABASE_URL


class Base(DeclarativeBase):
    pass


class AgentModel(Base):
    __tablename__ = "registered_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_type: Mapped[str] = mapped_column(String(64), default="mlflow_responses")
    api_key: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(32), default=lambda: datetime.now(timezone.utc).isoformat())


def init_schema() -> None:
    engine = create_engine(DATABASE_URL.replace("+aiosqlite", ""))
    Base.metadata.create_all(engine)
    engine.dispose()
