from sqlmodel import Session, SQLModel, create_engine, select

from app.models import tables


def test_metadata_creates_all_tables_and_rows_persist():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        doc = tables.Document(
            sha256="abc123", filename="wework.pdf", size_bytes=1024, storage_uri="mem://wework.pdf"
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        assert doc.id and doc.received_at is not None

        job = tables.Job(document_id=doc.id)
        session.add(job)
        session.commit()
        session.refresh(job)

        session.add(
            tables.ProcessingEvent(job_id=job.id, stage="ingestion", message="stored document")
        )
        session.commit()

    with Session(engine) as session:
        assert session.exec(select(tables.Job)).one().status == "pending"
        assert session.exec(select(tables.ProcessingEvent)).one().stage == "ingestion"
