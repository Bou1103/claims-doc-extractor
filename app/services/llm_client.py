"""LLM interaction.

Responsibility boundary: this module *only* talks to the model. It sends a
prompt, returns the raw text, and classifies failures. It does not parse or
validate the model's output against the invoice schema - that is the validation
step's job (next step), which also owns the re-ask loop.

Failure classification:
  * LLMTransientError  - retryable (timeout, connection drop, 429, 5xx). Retried
    here with exponential backoff; re-raised if the attempts are exhausted.
  * LLMPermanentError  - not retryable (bad request, auth, refusal, empty body).

The SDK's own retry layer is disabled (max_retries=0) so retry behaviour lives
in one visible, testable place.
"""

from dataclasses import dataclass, field

import anthropic
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import Settings, get_settings
from app.core.logging import get_logger


class LLMError(Exception):
    """Base class for LLM interaction failures."""


class LLMTransientError(LLMError):
    """Retryable failure; raised to the caller only after retries are exhausted."""


class LLMPermanentError(LLMError):
    """Non-retryable failure."""


@dataclass
class LLMResponse:
    text: str
    model: str
    stop_reason: str | None
    attempts: int
    usage: dict = field(default_factory=dict)
    request_id: str | None = None


class AnthropicLLMClient:
    def __init__(
        self,
        *,
        client: anthropic.Anthropic | None = None,
        api_key: str = "",
        model: str = "claude-sonnet-5",
        max_attempts: int = 3,
        timeout: float = 60.0,
        max_output_tokens: int = 4096,
        retry_wait=None,
        logger=None,
    ) -> None:
        self._client = client or anthropic.Anthropic(
            api_key=api_key or None, timeout=timeout, max_retries=0
        )
        self._model = model
        self._max_attempts = max_attempts
        self._max_output_tokens = max_output_tokens
        self._retry_wait = retry_wait or wait_exponential_jitter(initial=1, max=30)
        self._log = logger or get_logger(__name__)

    def complete(self, *, system: str, messages: list[dict]) -> LLMResponse:
        state = {"attempt": 0}

        def _call():
            state["attempt"] += 1
            self._log.info("llm_request", model=self._model, attempt=state["attempt"])
            try:
                return self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_output_tokens,
                    system=system,
                    messages=messages,
                )
            except anthropic.APIConnectionError as exc:  # includes APITimeoutError
                raise LLMTransientError(f"connection error: {exc}") from exc
            except anthropic.APIStatusError as exc:
                if exc.status_code == 429 or exc.status_code >= 500:
                    raise LLMTransientError(f"HTTP {exc.status_code}") from exc
                raise LLMPermanentError(f"HTTP {exc.status_code}: {exc}") from exc

        retryer = Retrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=self._retry_wait,
            retry=retry_if_exception_type(LLMTransientError),
            reraise=True,
            before_sleep=lambda rs: self._log.warning(
                "llm_retry",
                attempt=rs.attempt_number,
                error=str(rs.outcome.exception()),
            ),
        )
        try:
            message = retryer(_call)
        except LLMTransientError:
            self._log.error("llm_exhausted_retries", attempts=state["attempt"])
            raise

        if message.stop_reason == "refusal":
            raise LLMPermanentError("model refused the request")

        text = "".join(
            b.text for b in message.content if getattr(b, "type", None) == "text"
        )
        if not text.strip():
            raise LLMPermanentError("model returned no text content")

        usage = message.usage.model_dump() if getattr(message, "usage", None) else {}
        self._log.info(
            "llm_response",
            model=message.model,
            attempts=state["attempt"],
            stop_reason=message.stop_reason,
            usage=usage or None,
        )
        return LLMResponse(
            text=text,
            model=message.model or self._model,
            stop_reason=message.stop_reason,
            attempts=state["attempt"],
            usage=usage,
            request_id=getattr(message, "_request_id", None),
        )


def build_client(settings: Settings | None = None) -> AnthropicLLMClient:
    settings = settings or get_settings()
    if not settings.anthropic_api_key:
        raise LLMPermanentError("ANTHROPIC_API_KEY is not set")
    return AnthropicLLMClient(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model,
        max_attempts=settings.llm_max_attempts,
        timeout=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
    )
