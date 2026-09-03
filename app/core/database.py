"""Database engine + session helpers.

SQLite for the POC (persists across restarts, gives the audit trail for free).
Swap DATABASE_URL for Postgres in a real deployment; nothing else changes.
"""

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings

_settings = get_settings()

_connect_args = (
    {"check_same_thread": False}
    if _settings.database_url.startswith("sqlite")
    else {}
)
engine = create_engine(_settings.database_url, echo=False, connect_args=_connect_args)


def init_db() -> None:
    # Importing the module registers the tables on SQLModel.metadata.
    from app.models import tables  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
