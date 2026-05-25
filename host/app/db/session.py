"""SQLite session with WAL, busy_timeout, and reasonable pragmas."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from host.app.config import Settings


def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute("PRAGMA temp_store=MEMORY;")
    cur.execute("PRAGMA cache_size=-20000;")  # ~20 MB page cache
    cur.execute("PRAGMA mmap_size=134217728;")  # 128 MB mmap
    cur.execute("PRAGMA busy_timeout=5000;")
    cur.execute("PRAGMA foreign_keys=ON;")
    cur.close()


def make_engine(settings: Settings):
    is_sqlite = settings.database_url.startswith("sqlite")
    if settings.sqlite_path:
        Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)

    connect_args = {"check_same_thread": False, "timeout": 5} if is_sqlite else {}
    engine = create_engine(
        settings.database_url,
        echo=settings.sql_echo,
        connect_args=connect_args,
        pool_pre_ping=True,
    )
    if is_sqlite:
        event.listen(engine, "connect", _apply_sqlite_pragmas)
    return engine


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)


def get_session(engine):
    with Session(engine) as session:
        yield session
