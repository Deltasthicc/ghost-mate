from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class GameRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    game_id: str = Field(index=True, unique=True)
    start_fen: str
    final_fen: str | None = None
    result: str | None = None
    pgn_path: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MoveRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    game_id: str = Field(index=True)
    ply: int
    uci: str
    san: str | None = None
    source: str = "local"
    fen_after: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CalibrationRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
