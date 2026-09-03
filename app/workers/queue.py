"""Job queue + worker.

The API hands a job id to a queue and returns immediately; the queue runs the
extraction off the request path. For the POC the "queue" is an in-process thread
pool. In production this is the seam where Celery / RQ / SQS goes: same
``enqueue`` call, a real broker and separate worker processes behind it, scaled
on queue depth.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from sqlmodel import Session

from app.core.config import Settings, get_settings
from app.core.database import get_engine
from app.core.logging import get_logger
from app.services.extraction import run_extraction
from app.services.llm_client import build_client
from app.services.storage import LocalFileStorage

logger = get_logger(__name__)


def process_job(
    job_id: str,
    *,
    session: Session | None = None,
    storage=None,
    llm_client=None,
    settings: Settings | None = None,
) -> None:
    """Run one extraction job to completion. Overridable pieces make it testable."""
    settings = settings or get_settings()
    storage = storage or LocalFileStorage(settings.upload_dir)
    llm_client = llm_client or build_client(settings)

    own_session = session is None
    session = session or Session(get_engine())
    try:
        run_extraction(
            session, job_id, storage=storage, llm_client=llm_client, settings=settings
        )
    finally:
        if own_session:
            session.close()


class ExtractionQueue(Protocol):
    def enqueue(self, job_id: str) -> None: ...


class ThreadPoolQueue:
    """Default queue: runs jobs on a background thread pool in this process."""

    def __init__(self, *, max_workers: int = 4, run=process_job) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="extraction"
        )
        self._run = run

    def enqueue(self, job_id: str) -> None:
        self._executor.submit(self._safe_run, job_id)

    def _safe_run(self, job_id: str) -> None:
        try:
            self._run(job_id)
        except Exception:  # noqa: BLE001 - never let a worker thread die silently
            logger.exception("worker_crashed", job_id=job_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class InlineQueue:
    """Runs jobs synchronously inside ``enqueue``. For tests and simple local use."""

    def __init__(self, *, run=process_job) -> None:
        self._run = run

    def enqueue(self, job_id: str) -> None:
        self._run(job_id)
