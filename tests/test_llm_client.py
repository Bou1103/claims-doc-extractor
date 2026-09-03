import httpx2
import anthropic
import pytest
from tenacity import wait_none

from app.core.config import Settings
from app.models.schemas import InputMode, InvoiceExtraction
from app.services.llm_client import (
    AnthropicLLMClient,
    LLMPermanentError,
    LLMTransientError,
    MockLLMClient,
    build_client,
)
from app.services.pdf_processor import PageImage, PdfContent
from app.services.prompts import SYSTEM_PROMPT, build_user_message

_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(status: int) -> anthropic.APIStatusError:
    return anthropic.APIStatusError(
        "boom", response=httpx2.Response(status, request=_REQUEST), body=None
    )


def _connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=_REQUEST)


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Usage:
    def model_dump(self) -> dict:
        return {"input_tokens": 10, "output_tokens": 20}


class _Message:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.content = [_Block(text)]
        self.model = "claude-test"
        self.stop_reason = stop_reason
        self.usage = _Usage()
        self._request_id = "req_test"


class _FakeMessages:
    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.calls = 0

    def create(self, **kwargs):
        item = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


class _FakeClient:
    def __init__(self, script: list) -> None:
        self.messages = _FakeMessages(script)


def _client(script: list, **kwargs) -> AnthropicLLMClient:
    return AnthropicLLMClient(
        client=_FakeClient(script),
        model="claude-test",
        max_attempts=kwargs.get("max_attempts", 3),
        retry_wait=wait_none(),
    )


# --- retry / classification -------------------------------------------------


def test_success_on_first_attempt():
    response = _client([_Message('{"header": {}}')]).complete(system="s", messages=[])

    assert response.text == '{"header": {}}'
    assert response.attempts == 1
    assert response.usage["output_tokens"] == 20


def test_retries_transient_failures_then_succeeds():
    client = _client([_connection_error(), _status_error(503), _Message("{}")])

    response = client.complete(system="s", messages=[])

    assert response.attempts == 3


def test_exhausted_retries_raise_transient():
    client = _client([_status_error(503)] * 5)

    with pytest.raises(LLMTransientError):
        client.complete(system="s", messages=[])


def test_client_error_is_permanent_and_not_retried():
    fake = _FakeClient([_status_error(400)])
    client = AnthropicLLMClient(client=fake, model="x", retry_wait=wait_none())

    with pytest.raises(LLMPermanentError):
        client.complete(system="s", messages=[])
    assert fake.messages.calls == 1


def test_rate_limit_is_retried():
    client = _client([_status_error(429), _Message("{}")])
    assert client.complete(system="s", messages=[]).attempts == 2


def test_refusal_is_permanent():
    client = _client([_Message("no", stop_reason="refusal")])
    with pytest.raises(LLMPermanentError):
        client.complete(system="s", messages=[])


def test_empty_response_is_permanent():
    client = _client([_Message("   ")])
    with pytest.raises(LLMPermanentError):
        client.complete(system="s", messages=[])


# --- mock client ----------------------------------------------------------


def test_mock_client_returns_schema_valid_json():
    response = MockLLMClient().complete(system=SYSTEM_PROMPT, messages=[])
    InvoiceExtraction.model_validate_json(response.text)  # must not raise


def test_mock_client_scripts_responses_and_failures():
    client = MockLLMClient(responses=["not json", '{"header": {}}'], transient_failures=1)

    with pytest.raises(LLMTransientError):
        client.complete(system="s", messages=[])
    assert client.complete(system="s", messages=[]).text == "not json"
    assert client.complete(system="s", messages=[]).text == '{"header": {}}'


# --- factory ------------------------------------------------------------


def test_build_client_returns_mock_when_configured():
    assert isinstance(build_client(Settings(mock_llm=True)), MockLLMClient)


def test_build_client_requires_key_when_not_mocked():
    with pytest.raises(LLMPermanentError):
        build_client(Settings(mock_llm=False, anthropic_api_key=""))


# --- prompt assembly ----------------------------------------------------


def test_user_message_text_mode_carries_document_text():
    content = PdfContent(page_count=1, input_mode=InputMode.TEXT, text="INVOICE total 5")
    message = build_user_message(content)

    assert message["role"] == "user"
    assert any(
        b["type"] == "text" and "INVOICE total 5" in b["text"] for b in message["content"]
    )


def test_user_message_vision_mode_includes_images():
    content = PdfContent(
        page_count=1,
        input_mode=InputMode.VISION,
        page_images=[PageImage(page_number=1, data_base64="AAAA")],
    )
    message = build_user_message(content)

    assert "image" in [b["type"] for b in message["content"]]


def test_user_message_appends_feedback():
    content = PdfContent(page_count=1, input_mode=InputMode.TEXT, text="x")
    message = build_user_message(content, feedback="missing 'total'")

    assert any("rejected" in b["text"] for b in message["content"] if b["type"] == "text")
