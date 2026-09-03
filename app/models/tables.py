"""Persistence tables.

Design notes (audit trail requirement):
  * Rows are append-only. Re-processing a document creates a new Job and a new
    Extraction; nothing is mutated in place except a Job's own status/timestamps.
  * Every Extraction records which model and prompt version produced it, plus the
    raw model response, so any stored result can be traced back to its inputs.
  * ProcessingEvent is the append-only per-stage log that backs the audit trail.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from app.models.schemas import JobStatus


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: str = Field(default_factory=_uuid, primary_key=True)
    sha256: str = Field(index=True, description="Content hash: dedup + audit")
    filename: str
    mime_type: str = "application/pdf"
    size_bytes: int
    storage_uri: str = Field(description="Where the original bytes are stored")
    received_at: datetime = Field(default_factory=_utcnow)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(default_factory=_uuid, primary_key=True)
    document_id: str = Field(foreign_key="documents.id", index=True)
    status: str = Field(default=JobStatus.PENDING.value, index=True)
    attempts: int = 0
    model: str | None = None
    prompt_version: str | None = None
    error: str | None = Field(default=None, description="Failure reason when status=failed")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Extraction(SQLModel, table=True):
    __tablename__ = "extractions"

    id: str = Field(default_factory=_uuid, primary_key=True)
    job_id: str = Field(foreign_key="jobs.id", index=True)
    header: dict = Field(default_factory=dict, sa_column=Column(JSON))
    warnings: list = Field(default_factory=list, sa_column=Column(JSON))
    raw_llm_response: str | None = None
    input_mode: str | None = Field(default=None, description="text | vision")
    model: str | None = None
    prompt_version: str | None = None
    token_usage: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)


class LineItemRecord(SQLModel, table=True):
    """Line items broken out into rows so downstream analytics can aggregate."""

    __tablename__ = "line_items"

    id: str = Field(default_factory=_uuid, primary_key=True)
    extraction_id: str = Field(foreign_key="extractions.id", index=True)
    description: str
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None


class ProcessingEvent(SQLModel, table=True):
    """Append-only per-stage log line. Backs the audit trail."""

    __tablename__ = "processing_events"

    id: str = Field(default_factory=_uuid, primary_key=True)
    job_id: str = Field(foreign_key="jobs.id", index=True)
    stage: str = Field(description="e.g. ingestion, pdf_processing, llm_call, validation")
    level: str = "info"
    message: str
    payload: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
