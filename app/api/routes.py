from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from app.api.dependencies import get_db, get_queue, get_storage
from app.core.errors import (
    CorruptDocumentError,
    DocumentError,
    EncryptedDocumentError,
    UnsupportedDocumentError,
)
from app.core.logging import get_logger
from app.models.schemas import (
    InvoiceExtraction,
    InvoiceHeader,
    JobCreatedResponse,
    JobResultResponse,
    JobStatus,
    LineItem,
)
from app.models.tables import Extraction, Job, LineItemRecord
from app.services.ingestion import ingest_pdf

logger = get_logger(__name__)
router = APIRouter(prefix="/v1")


@router.post(
    "/extractions",
    status_code=202,
    response_model=JobCreatedResponse,
    summary="Submit a PDF invoice for extraction",
)
async def create_extraction(
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
    storage=Depends(get_storage),
    queue=Depends(get_queue),
) -> JobCreatedResponse:
    data = await file.read()
    filename = file.filename or "upload.pdf"

    # Ingestion is fast (validate + hash + store). It runs inline so malformed
    # uploads are rejected synchronously; the slow LLM work is queued.
    try:
        job = ingest_pdf(session, data=data, filename=filename, storage=storage)
    except UnsupportedDocumentError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except EncryptedDocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (CorruptDocumentError, DocumentError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    queue.enqueue(job.id)
    logger.info("extraction_accepted", job_id=job.id, filename=filename)
    return JobCreatedResponse(job_id=job.id, status=JobStatus.PENDING)


@router.get(
    "/extractions/{job_id}",
    response_model=JobResultResponse,
    summary="Get job status and result",
)
async def get_extraction(
    job_id: str, session: Session = Depends(get_db)
) -> JobResultResponse:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    result = None
    if job.status == JobStatus.COMPLETED.value:
        result = _load_result(session, job_id)

    return JobResultResponse(
        job_id=job.id,
        status=JobStatus(job.status),
        result=result,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _load_result(session: Session, job_id: str) -> InvoiceExtraction | None:
    extraction = session.exec(
        select(Extraction)
        .where(Extraction.job_id == job_id)
        .order_by(Extraction.created_at.desc())
    ).first()
    if extraction is None:
        return None

    items = session.exec(
        select(LineItemRecord).where(LineItemRecord.extraction_id == extraction.id)
    ).all()
    return InvoiceExtraction(
        header=InvoiceHeader.model_validate(extraction.header),
        line_items=[
            LineItem(
                description=i.description,
                quantity=i.quantity,
                unit_price=i.unit_price,
                amount=i.amount,
            )
            for i in items
        ],
        warnings=list(extraction.warnings),
    )
