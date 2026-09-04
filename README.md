# Claims Document Extraction Service (POC)

A backend service that ingests PDF invoices and extracts header + line-item data
into structured, queryable, audit-trailed records using an LLM/VLM. Built for the
AI Engineer case (Document Intelligence Pipeline for a Legal Analytics).

**Slides:** [Case study — high-level overview & execution pipeline](https://docs.google.com/presentation/d/1DIj32klgswy7jGqSw9_eKf15g7vOWD99BhmVzzKkiBM/edit?usp=sharing)

## Stack

- **API:** FastAPI, async, non-blocking job submission
- **Extraction:** Claude (`claude-sonnet-5`), vision-capable — one model handles both text-layer PDFs and image-only scans
- **PDF handling:** PyMuPDF — text extraction + page rasterization
- **Validation:** Pydantic — strict schema, arithmetic sanity checks
- **Persistence:** SQLModel over SQLite (Postgres-ready) — append-only, audit-trailed
- **Retry:** tenacity — exponential backoff on transient LLM failures
- **Logging:** structlog, JSON, bound with job id / stage
- **Frontend:** React (Vite) test console

## Run it

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env      # add your ANTHROPIC_API_KEY
pytest                     # 48 tests, fully offline (LLM calls are stubbed in tests)

uvicorn app.main:app --reload
```

## Test it with the frontend

```bash
npm --prefix frontend install
npm --prefix frontend run build   # served by the API at http://localhost:8000/
```

or for hot-reload during development:

```bash
npm --prefix frontend run dev     # http://localhost:5173, proxies the API
```

Upload a PDF, watch the job go `pending → processing → completed/failed`, see
the extracted header, line items, and warnings — or the error.

## Endpoints

**`POST /v1/extractions`** — multipart `file` upload. Validates and stores the
PDF inline (bad uploads are rejected immediately: `400`/`415`/`422`), queues the
extraction, and returns right away:
```json
{"job_id": "...", "status": "pending"}
```

**`GET /v1/extractions/{job_id}`** — current status and, once available, the
result or the error:
```json
{"job_id": "...", "status": "completed", "result": {...}, "error": null, ...}
```
`status` is one of `pending | processing | completed | failed`. `404` for an
unknown id.

Interactive docs: `http://localhost:8000/docs`.

## Project layout

```
app/
  core/       settings, logging, database, error types
  models/     schemas.py (LLM/API contracts) · tables.py (append-only persistence)
  services/   ingestion · pdf_processor · llm_client · prompts · validation · extraction
  workers/    background job queue
  api/        FastAPI app + routes
frontend/     React test console
tests/        48 tests, offline (LLM calls stubbed with a test double)
```
