"""Ingestion: accept raw PDF bytes, validate, store, and open a job.

This stage does not touch the LLM. It produces a persisted Job in ``pending``
state plus the stored original bytes; the extraction pipeline (later step) picks
the job up from there.
"""

import hashlib

import pymupdf
from sqlmodel import Session, select

from app.core.errors import (
    CorruptDocumentError,
    EncryptedDocumentError,
    UnsupportedDocumentError,
)
from app.core.logging import get_logger
from app.models.tables import Document, Job, ProcessingEvent
from app.services.storage import Storage

logger = get_logger(__name__)


def _validate_pdf(data: bytes) -> int:
    """Return the page count, or raise a DocumentError."""
    if not data[:1024].lstrip().startswith(b"%PDF-"):
        raise UnsupportedDocumentError("file is not a PDF (missing %PDF- header)")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise CorruptDocumentError(f"could not open PDF: {exc}") from exc
    with doc:
        if doc.needs_pass:
            raise EncryptedDocumentError("PDF is password-protected")
        if doc.page_count == 0:
            raise CorruptDocumentError("PDF has no pages")
        return doc.page_count


def ingest_pdf(session: Session, *, data: bytes, filename: str, storage: Storage) -> Job:
    page_count = _validate_pdf(data)
    sha256 = hashlib.sha256(data).hexdigest()

    document = session.exec(select(Document).where(Document.sha256 == sha256)).first()
    deduplicated = document is not None
    if document is None:
        storage_uri = storage.save(f"{sha256}.pdf", data)
        document = Document(
            sha256=sha256,
            filename=filename,
            size_bytes=len(data),
            storage_uri=storage_uri,
        )
        session.add(document)
        session.flush()  # populate document.id

    job = Job(document_id=document.id)
    session.add(job)
    session.flush()

    session.add(
        ProcessingEvent(
            job_id=job.id,
            stage="ingestion",
            message="document ingested" + (" (deduplicated)" if deduplicated else ""),
            payload={"sha256": sha256, "pages": page_count, "deduplicated": deduplicated},
        )
    )
    session.commit()
    session.refresh(job)

    logger.info(
        "document_ingested",
        job_id=job.id,
        document_id=document.id,
        sha256=sha256,
        pages=page_count,
        filename=filename,
        deduplicated=deduplicated,
    )
    return job
