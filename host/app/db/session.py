from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from host.app.config import Settings


def make_engine(settings: Settings):
    if settings.sqlite_path:
        Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, echo=settings.debug, connect_args=connect_args)


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)


def get_session(engine):
    with Session(engine) as session:
        yield session
