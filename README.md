# Claims Document Extraction Service (POC)

A backend service that ingests PDF invoices from the firm's **Claims** line of
business and extracts header + line-item data into a structured, queryable form
using an LLM/VLM. Built for the AI Engineer case.

Design priorities (per the brief): **structure and judgment**, especially how the
service behaves when things go wrong. It is not production-complete.

## Architecture

```
app/
  core/
    config.py       # settings (env / .env)
    logging.py      # structlog JSON logging, bound with job_id / stage
    database.py     # engine + session; SQLite for the POC, Postgres in prod
  models/
    schemas.py      # domain transfer objects (LLM output contract, API responses)
    tables.py       # persistence: Document, Job, Extraction, LineItem, ProcessingEvent
```

Progress:

| Step | Adds | Status |
|------|------|--------|
| 1 | config, logging, schemas, data model | done |
| 2 | `services/ingestion.py`, `services/pdf_processor.py` — file handling, hashing, text-layer detection, rasterization | done |
| 3 | `services/llm_client.py`, `services/prompts.py` — LLM/VLM call, transient-failure retry, mock mode | done |
| 4 | `services/validation.py`, `services/extraction.py` — schema parsing + re-ask, arithmetic checks, orchestration | done |
| 5 | `api/`, `workers/` — async `POST /v1/extractions` (returns job id) and `GET /v1/extractions/{id}` | done |

### Audit trail

Rows are append-only. Re-processing a document creates a new `Job` + `Extraction`
rather than overwriting. Each `Extraction` stores the model id, prompt version,
and raw model response. `ProcessingEvent` is the append-only per-stage log.

## Getting started

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env          # MOCK_LLM=true works with no API key
pytest
```

## Running the API

```bash
uvicorn app.main:app --reload
```

```bash
# submit — returns immediately with a job id
curl -sF file=@invoice.pdf http://localhost:8000/v1/extractions
# {"job_id": "...", "status": "pending"}

# poll — status is pending | processing | completed | failed
curl -s http://localhost:8000/v1/extractions/<job_id>
```

Interactive docs at `http://localhost:8000/docs`.

The POST validates + stores the PDF inline (so bad uploads are rejected on the
spot) and queues the LLM extraction. For the POC the queue is an in-process
thread pool (`app/workers/queue.py`); that module is the seam where Celery / RQ /
SQS drops in for real scale.

## Configuration

See `.env.example`. Key switches:

- `MOCK_LLM` — when true the LLM client returns a deterministic fake result, so
  the pipeline runs fully offline (CI, local dev before a key is available).
- `DATABASE_URL` — `sqlite:///./claims.db` by default.
- `TEXT_LAYER_MIN_CHARS` — page text below this is treated as image-only.
