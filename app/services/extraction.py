"""Extraction orchestrator.

Runs the full pipeline for one job:

    load bytes -> process_pdf -> LLM call (+ re-ask) -> validate -> persist

and moves the Job through pending -> processing -> completed / failed, writing a
ProcessingEvent at every stage so the whole run is reconstructable from the
audit trail. Persistence of the Extraction only happens on the success path, so
a failure never leaves a half-written result.
"""

from datetime import datetime, timezone

from sqlmodel import Session

from app.core.config import Settings, get_settings
from app.core.errors import DocumentError
from app.core.logging import get_logger
from app.models.schemas import InvoiceExtraction, JobStatus
from app.models.tables import Document, Extraction, Job, LineItemRecord, ProcessingEvent
from app.services.llm_client import LLMPermanentError, LLMTransientError
from app.services.pdf_processor import process_pdf
from app.services.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_reask_message,
    build_user_message,
)
from app.services.validation import parse_extraction

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _event(session, job_id, stage, message, *, level="info", payload=None) -> None:
    session.add(
        ProcessingEvent(
            job_id=job_id, stage=stage, level=level, message=message, payload=payload
        )
    )


class ExtractionFailed(Exception):
    def __init__(self, message, *, retryable=False, raw="", attempts=0):
        super().__init__(message)
        self.retryable = retryable
        self.raw = raw
        self.attempts = attempts


def run_extraction(
    session: Session,
    job_id: str,
    *,
    storage,
    llm_client,
    settings: Settings | None = None,
) -> Job:
    settings = settings or get_settings()
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")

    log = logger.bind(job_id=job_id, document_id=job.document_id)

    job.status = JobStatus.PROCESSING.value
    job.started_at = job.updated_at = _utcnow()
    _event(session, job_id, "processing", "extraction started")
    session.commit()
    log.info("extraction_started")

    try:
        document = session.get(Document, job.document_id)
        data = storage.read(document.storage_uri)

        content = process_pdf(data)
        _event(
            session,
            job_id,
            "pdf_processing",
            f"routed to the {content.input_mode.value} path",
            payload={
                "pages": content.page_count,
                "mode": content.input_mode.value,
                "notes": content.notes,
            },
        )
        session.commit()

        extraction, raw, model, attempts = _extract_with_reask(
            session, job_id, content, llm_client, settings, log
        )
    except ExtractionFailed as exc:
        return _fail(
            session, job_id, str(exc),
            retryable=exc.retryable, raw=exc.raw, attempts=exc.attempts, log=log,
        )
    except DocumentError as exc:
        return _fail(session, job_id, f"document error: {exc}", log=log)
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        log.exception("extraction_crashed")
        return _fail(session, job_id, f"unexpected error: {exc}", log=log)

    _persist_success(session, job, content.input_mode.value, extraction, raw, model, attempts)
    _event(
        session,
        job_id,
        "validation",
        "extraction stored",
        payload={
            "warnings": extraction.warnings,
            "line_items": len(extraction.line_items),
        },
    )
    session.commit()
    log.info(
        "extraction_completed",
        warnings=len(extraction.warnings),
        line_items=len(extraction.line_items),
    )
    return session.get(Job, job_id)


def _extract_with_reask(
    session, job_id, content, llm_client, settings, log
) -> tuple[InvoiceExtraction, str, str, int]:
    messages = [build_user_message(content)]
    total_attempts = 0
    last_raw = ""

    for round_index in range(settings.llm_max_reasks + 1):
        try:
            response = llm_client.complete(system=SYSTEM_PROMPT, messages=messages)
        except LLMTransientError as exc:
            raise ExtractionFailed(
                f"LLM unavailable after retries: {exc}",
                retryable=True, raw=last_raw, attempts=total_attempts,
            ) from exc
        except LLMPermanentError as exc:
            raise ExtractionFailed(
                f"LLM error: {exc}", retryable=False, raw=last_raw, attempts=total_attempts
            ) from exc

        total_attempts += response.attempts
        last_raw = response.text

        result = parse_extraction(response.text)
        if result.ok:
            return result.extraction, response.text, response.model, total_attempts

        _event(
            session,
            job_id,
            "validation",
            f"attempt {round_index + 1} rejected: {result.error}",
            level="warning",
        )
        session.commit()
        log.warning("output_rejected", attempt=round_index + 1, reason=result.error)

        messages = messages + [
            {"role": "assistant", "content": response.text},
            build_reask_message(result.error),
        ]

    raise ExtractionFailed(
        f"could not parse a valid extraction after {settings.llm_max_reasks + 1} "
        f"attempts; last error: {result.error}",
        retryable=False,
        raw=last_raw,
        attempts=total_attempts,
    )


def _persist_success(
    session, job, input_mode, extraction, raw, model, attempts
) -> None:
    row = Extraction(
        job_id=job.id,
        header=extraction.header.model_dump(mode="json"),
        warnings=extraction.warnings,
        raw_llm_response=raw,
        input_mode=input_mode,
        model=model,
        prompt_version=PROMPT_VERSION,
    )
    session.add(row)
    session.flush()

    for item in extraction.line_items:
        session.add(
            LineItemRecord(
                extraction_id=row.id,
                description=item.description,
                quantity=float(item.quantity) if item.quantity is not None else None,
                unit_price=float(item.unit_price) if item.unit_price is not None else None,
                amount=float(item.amount) if item.amount is not None else None,
            )
        )

    job.status = JobStatus.COMPLETED.value
    job.model = model
    job.prompt_version = PROMPT_VERSION
    job.attempts = attempts
    job.finished_at = job.updated_at = _utcnow()


def _fail(session, job_id, message, *, retryable=False, raw="", attempts=0, log) -> Job:
    job = session.get(Job, job_id)
    job.status = JobStatus.FAILED.value
    job.error = message
    if attempts:
        job.attempts = attempts
    job.finished_at = job.updated_at = _utcnow()
    _event(
        session,
        job_id,
        "failed",
        message,
        level="error",
        payload={"retryable": retryable, "raw_response": raw or None},
    )
    session.commit()
    log.error("extraction_failed", error=message, retryable=retryable)
    return job
