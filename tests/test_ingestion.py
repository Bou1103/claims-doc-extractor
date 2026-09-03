import pymupdf
import pytest
from sqlmodel import select

from app.core.errors import EncryptedDocumentError, UnsupportedDocumentError
from app.models.tables import Document, Job, ProcessingEvent
from app.services.ingestion import ingest_pdf


def test_ingest_creates_document_job_and_event(db_session, storage, text_invoice_pdf):
    job = ingest_pdf(db_session, data=text_invoice_pdf, filename="acme.pdf", storage=storage)

    assert job.status == "pending"
    document = db_session.get(Document, job.document_id)
    assert document.size_bytes == len(text_invoice_pdf)
    assert storage.read(document.storage_uri) == text_invoice_pdf

    events = db_session.exec(
        select(ProcessingEvent).where(ProcessingEvent.job_id == job.id)
    ).all()
    assert [e.stage for e in events] == ["ingestion"]


def test_identical_bytes_are_deduplicated(db_session, storage, text_invoice_pdf):
    job_a = ingest_pdf(db_session, data=text_invoice_pdf, filename="a.pdf", storage=storage)
    job_b = ingest_pdf(db_session, data=text_invoice_pdf, filename="b.pdf", storage=storage)

    assert job_a.document_id == job_b.document_id
    assert job_a.id != job_b.id
    assert len(db_session.exec(select(Document)).all()) == 1
    assert len(db_session.exec(select(Job)).all()) == 2


def test_non_pdf_is_rejected(db_session, storage):
    with pytest.raises(UnsupportedDocumentError):
        ingest_pdf(db_session, data=b"just a text file", filename="notes.txt", storage=storage)


def test_encrypted_pdf_is_rejected(db_session, storage):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "confidential invoice")
    encrypted = doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user"
    )

    with pytest.raises(EncryptedDocumentError):
        ingest_pdf(db_session, data=encrypted, filename="locked.pdf", storage=storage)
