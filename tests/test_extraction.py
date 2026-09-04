from sqlmodel import select

from app.core.config import Settings
from app.models.tables import Extraction, LineItemRecord, ProcessingEvent
from app.services.extraction import run_extraction
from app.services.ingestion import ingest_pdf
from tests.conftest import DEFAULT_EXTRACTION_JSON as _GOOD_JSON
from tests.conftest import FakeLLMClient

_SETTINGS = Settings(llm_max_reasks=1)


def _ingest(session, storage, pdf) -> str:
    return ingest_pdf(session, data=pdf, filename="in.pdf", storage=storage).id


def test_happy_path_completes_and_persists(db_session, storage, text_invoice_pdf):
    job_id = _ingest(db_session, storage, text_invoice_pdf)

    job = run_extraction(
        db_session, job_id, storage=storage,
        llm_client=FakeLLMClient(responses=[_GOOD_JSON]), settings=_SETTINGS,
    )

    assert job.status == "completed"
    assert job.model == "fake" and job.prompt_version

    extraction = db_session.exec(select(Extraction).where(Extraction.job_id == job_id)).one()
    assert extraction.header["vendor_name"] == "ACME Legal"
    assert extraction.input_mode == "text"

    items = db_session.exec(
        select(LineItemRecord).where(LineItemRecord.extraction_id == extraction.id)
    ).all()
    assert len(items) == 1 and items[0].amount == 100.0

    stages = [e.stage for e in db_session.exec(
        select(ProcessingEvent).where(ProcessingEvent.job_id == job_id)
    ).all()]
    assert stages == ["ingestion", "processing", "pdf_processing", "validation"]


def test_reask_recovers_from_unparseable_output(db_session, storage, text_invoice_pdf):
    job_id = _ingest(db_session, storage, text_invoice_pdf)

    job = run_extraction(
        db_session, job_id, storage=storage,
        llm_client=FakeLLMClient(responses=["not json", _GOOD_JSON]), settings=_SETTINGS,
    )

    assert job.status == "completed"
    events = db_session.exec(
        select(ProcessingEvent).where(ProcessingEvent.job_id == job_id)
    ).all()
    assert any(e.level == "warning" and "rejected" in e.message for e in events)


def test_unparseable_output_fails_job_after_reasks(db_session, storage, text_invoice_pdf):
    job_id = _ingest(db_session, storage, text_invoice_pdf)

    job = run_extraction(
        db_session, job_id, storage=storage,
        llm_client=FakeLLMClient(responses=["nope", "still nope", "nope again"]),
        settings=_SETTINGS,
    )

    assert job.status == "failed"
    assert "could not parse" in job.error
    assert db_session.exec(select(Extraction).where(Extraction.job_id == job_id)).first() is None

    failure = db_session.exec(
        select(ProcessingEvent).where(ProcessingEvent.job_id == job_id, ProcessingEvent.stage == "failed")
    ).one()
    assert failure.payload["retryable"] is False
    assert failure.payload["raw_response"] == "still nope"  # last attempt's raw output is kept


def test_transient_llm_failure_marks_job_retryable(db_session, storage, text_invoice_pdf):
    job_id = _ingest(db_session, storage, text_invoice_pdf)

    job = run_extraction(
        db_session, job_id, storage=storage,
        llm_client=FakeLLMClient(responses=[_GOOD_JSON], transient_failures=99),
        settings=_SETTINGS,
    )

    assert job.status == "failed"
    failure = db_session.exec(
        select(ProcessingEvent).where(ProcessingEvent.job_id == job_id, ProcessingEvent.stage == "failed")
    ).one()
    assert failure.payload["retryable"] is True


def test_image_only_pdf_flows_through(db_session, storage, image_only_pdf):
    job_id = _ingest(db_session, storage, image_only_pdf)

    job = run_extraction(
        db_session, job_id, storage=storage,
        llm_client=FakeLLMClient(responses=[_GOOD_JSON]), settings=_SETTINGS,
    )

    assert job.status == "completed"
    extraction = db_session.exec(select(Extraction).where(Extraction.job_id == job_id)).one()
    assert extraction.input_mode == "vision"
