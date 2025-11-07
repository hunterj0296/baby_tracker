from __future__ import annotations

import os
from datetime import datetime
from typing import Generator, Optional

from sqlmodel import Field, SQLModel, Session, create_engine


# Prefer /data when running in Docker; otherwise fall back to local ./data
DEFAULT_DIR = "/data" if os.path.isdir("/data") else "data"
os.makedirs(DEFAULT_DIR, exist_ok=True)
DATA_PATH = os.getenv("DATA_PATH", os.path.join(DEFAULT_DIR, "baby_tracking.db"))
DATABASE_URL = f"sqlite:///{DATA_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


class Feed(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp_utc: datetime
    amount_ml: float
    amount_oz: float


class Pee(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp_utc: datetime


class Poop(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp_utc: datetime


class PumpingSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # Timestamp marking when the session was saved (end time)
    timestamp_utc: datetime
    # Total duration pumped in seconds (can exceed 900)
    duration_seconds: int
    # Amount over the 15-minute target in seconds (0 if not exceeded)
    extra_seconds: int
    # Target seconds for countdown (defaults to 900 = 15 minutes)
    target_seconds: int = 900


class PumpedMilk(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="pumpingsession.id")
    amount_ml: float
    amount_oz: float
    # Original unit provided by the user ("oz" or "ml")
    unit: str


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


