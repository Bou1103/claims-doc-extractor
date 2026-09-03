from collections.abc import Iterator

from fastapi import Request
from sqlmodel import Session

from app.core.database import get_engine
from app.services.storage import Storage
from app.workers.queue import ExtractionQueue


def get_db() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


def get_queue(request: Request) -> ExtractionQueue:
    return request.app.state.queue
