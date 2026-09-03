from datetime import date
from decimal import Decimal

from app.models.schemas import InvoiceExtraction, InvoiceHeader, LineItem


def test_minimal_extraction_defaults():
    extraction = InvoiceExtraction(header=InvoiceHeader(vendor_name="WeWork"))
    assert extraction.line_items == []
    assert extraction.warnings == []


def test_extraction_parses_from_llm_style_payload():
    payload = {
        "header": {
            "vendor_name": "WeWork Canada LP ULC",
            "client_name": "Pentcho Tchomakov",
            "invoice_number": "PXC7PUAWY2HY-1",
            "invoice_date": "2025-06-17",
            "currency": "CAD",
            "subtotal": "35.00",
            "tax": "1.75",
            "total": "36.75",
        },
        "line_items": [
            {"description": "On Demand Shared Workspace", "amount": "35.00"},
        ],
        "warnings": [],
    }

    extraction = InvoiceExtraction.model_validate(payload)

    assert extraction.header.invoice_date == date(2025, 6, 17)
    assert extraction.header.total == Decimal("36.75")
    assert extraction.line_items[0] == LineItem(
        description="On Demand Shared Workspace", amount=Decimal("35.00")
    )


def test_extraction_round_trips_through_json():
    original = InvoiceExtraction(
        header=InvoiceHeader(vendor_name="Cargo Collective, Inc.", currency="USD", total=Decimal("99")),
        line_items=[LineItem(description="Cargo Subscription", amount=Decimal("99"))],
    )
    assert InvoiceExtraction.model_validate(original.model_dump(mode="json")) == original


def test_unknown_top_level_fields_are_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        InvoiceExtraction.model_validate(
            {"header": {"vendor_name": "x"}, "grand_total": "1.00"}
        )
