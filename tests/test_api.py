import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.core.config import Settings
from app.workers.queue import InlineQueue, process_job
from tests.conftest import DEFAULT_EXTRACTION_JSON as _GOOD_JSON
from tests.conftest import FakeLLMClient

_TEST_SETTINGS = Settings(llm_max_reasks=1)


def _client(storage, *, responses) -> TestClient:
    def runner(job_id: str) -> None:
        process_job(
            job_id,
            storage=storage,
            llm_client=FakeLLMClient(responses=responses),
            settings=_TEST_SETTINGS,
        )

    app = create_app(
        settings=_TEST_SETTINGS, storage=storage, queue=InlineQueue(run=runner)
    )
    return TestClient(app)


def _upload(client: TestClient, name: str, data: bytes):
    return client.post(
        "/v1/extractions", files={"file": (name, data, "application/pdf")}
    )


def test_submit_returns_job_id_immediately(api_engine, storage, text_invoice_pdf):
    with _client(storage, responses=[_GOOD_JSON]) as client:
        response = _upload(client, "acme.pdf", text_invoice_pdf)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["job_id"]


def test_retrieve_returns_completed_result(api_engine, storage, text_invoice_pdf):
    with _client(storage, responses=[_GOOD_JSON]) as client:
        job_id = _upload(client, "acme.pdf", text_invoice_pdf).json()["job_id"]

        result = client.get(f"/v1/extractions/{job_id}")

    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "completed"
    assert body["result"]["header"]["vendor_name"] == "ACME Legal"
    assert float(body["result"]["line_items"][0]["amount"]) == 100.0
    assert body["error"] is None


def test_retrieve_reports_failure(api_engine, storage, text_invoice_pdf):
    with _client(storage, responses=["not json", "still not", "nope"]) as client:
        job_id = _upload(client, "acme.pdf", text_invoice_pdf).json()["job_id"]

        body = client.get(f"/v1/extractions/{job_id}").json()

    assert body["status"] == "failed"
    assert body["result"] is None
    assert "could not parse" in body["error"]


def test_unknown_job_is_404(api_engine, storage):
    with _client(storage, responses=[_GOOD_JSON]) as client:
        assert client.get("/v1/extractions/does-not-exist").status_code == 404


def test_non_pdf_upload_is_415(api_engine, storage):
    with _client(storage, responses=[_GOOD_JSON]) as client:
        response = _upload(client, "notes.txt", b"just some text")

    assert response.status_code == 415


def test_encrypted_pdf_upload_is_422(api_engine, storage, encrypted_pdf):
    with _client(storage, responses=[_GOOD_JSON]) as client:
        response = _upload(client, "locked.pdf", encrypted_pdf)

    assert response.status_code == 422


def test_health(api_engine, storage):
    with _client(storage, responses=[_GOOD_JSON]) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_frontend_served_when_built(api_engine, storage):
    from app.api.app import _FRONTEND_DIST

    if not _FRONTEND_DIST.is_dir():
        pytest.skip("frontend not built (npm --prefix frontend run build)")

    with _client(storage, responses=[_GOOD_JSON]) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
