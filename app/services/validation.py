"""Output validation.

Takes the raw text the model returned and decides whether it is a usable
InvoiceExtraction:
  1. pull the JSON out of the text (handles markdown fences / stray prose)
  2. parse it
  3. validate it against the schema
  4. run arithmetic / sanity checks -> these add *warnings*, they never fail

A non-ok result carries a human-readable ``error`` string that is fed straight
back to the model as re-ask feedback.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import json

from pydantic import ValidationError

from app.models.schemas import InvoiceExtraction

_TOLERANCE = Decimal("0.01")


@dataclass
class ValidationResult:
    ok: bool
    extraction: InvoiceExtraction | None = None
    error: str | None = None


def _extract_json(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            text = text[start : end + 1]
    return text


def _format_errors(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


def parse_extraction(raw: str) -> ValidationResult:
    candidate = _extract_json(raw)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return ValidationResult(ok=False, error=f"response is not valid JSON: {exc}")

    try:
        extraction = InvoiceExtraction.model_validate(data)
    except ValidationError as exc:
        return ValidationResult(
            ok=False,
            error=f"JSON does not match the required schema: {_format_errors(exc)}",
        )

    _apply_sanity_checks(extraction)
    return ValidationResult(ok=True, extraction=extraction)


def _apply_sanity_checks(extraction: InvoiceExtraction) -> None:
    """Append warnings for anything that looks internally inconsistent.

    These are advisory: a mismatched total is still stored, just flagged for a
    human to review downstream.
    """
    header = extraction.header
    warnings = extraction.warnings

    line_amounts = [li.amount for li in extraction.line_items if li.amount is not None]
    if line_amounts:
        line_sum = sum(line_amounts, Decimal("0"))
        reference = header.subtotal if header.subtotal is not None else header.total
        if reference is not None and abs(line_sum - reference) > _TOLERANCE:
            warnings.append(
                f"line items sum to {line_sum} but subtotal/total is {reference}"
            )

    if (
        header.subtotal is not None
        and header.tax is not None
        and header.total is not None
        and abs(header.subtotal + header.tax - header.total) > _TOLERANCE
    ):
        warnings.append(
            f"subtotal ({header.subtotal}) + tax ({header.tax}) "
            f"does not equal total ({header.total})"
        )

    if header.total is None:
        warnings.append("no invoice total was found")

    if header.currency is not None and len(header.currency) != 3:
        warnings.append(f"currency {header.currency!r} is not a 3-letter ISO code")

    for value, name in (
        (header.subtotal, "subtotal"),
        (header.total, "total"),
    ):
        try:
            if value is not None and value < 0:
                warnings.append(f"{name} is negative ({value})")
        except (TypeError, InvalidOperation):
            pass
