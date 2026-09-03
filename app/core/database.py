"""Database engine + session helpers.

SQLite for the POC (persists across restarts, gives the audit trail for free).
Swap DATABASE_URL for Postgres in a real deployment; nothing else changes.

The engine is process-wide and lazily built. ``set_engine`` lets tests point the
whole app at an isolated database.
"""

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings

_engine = None


def _build_engine(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, echo=False, connect_args=connect_args)


def get_engine():
    global _engine
    if _engine is None:
        _engine = _build_engine(get_settings().database_url)
    return _engine


def set_engine(engine) -> None:
    """Override the process-wide engine (tests). Pass None to reset."""
    global _engine
    _engine = engine


def init_db() -> None:
    from app.models import tables  # noqa: F401  (registers tables on the metadata)

    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
