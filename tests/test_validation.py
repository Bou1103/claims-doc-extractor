import json

from app.services.validation import parse_extraction

_GOOD = {
    "header": {
        "vendor_name": "WeWork",
        "invoice_number": "PXC7-1",
        "currency": "CAD",
        "subtotal": "35.00",
        "tax": "1.75",
        "total": "36.75",
    },
    "line_items": [{"description": "Workspace", "amount": "35.00"}],
    "warnings": [],
}


def test_clean_json_parses():
    result = parse_extraction(json.dumps(_GOOD))
    assert result.ok
    assert result.extraction.header.vendor_name == "WeWork"
    assert result.extraction.warnings == []


def test_markdown_fenced_json_parses():
    result = parse_extraction("```json\n" + json.dumps(_GOOD) + "\n```")
    assert result.ok


def test_json_with_surrounding_prose_parses():
    raw = "Here is the extraction:\n" + json.dumps(_GOOD) + "\nLet me know if you need more."
    result = parse_extraction(raw)
    assert result.ok


def test_invalid_json_is_rejected_with_feedback():
    result = parse_extraction("{ not json at all")
    assert not result.ok
    assert "JSON" in result.error


def test_schema_violation_is_rejected_with_feedback():
    result = parse_extraction(json.dumps({"header": {"vendor_name": "x"}, "grand_total": 5}))
    assert not result.ok
    assert "schema" in result.error


def test_missing_header_is_rejected():
    result = parse_extraction(json.dumps({"line_items": []}))
    assert not result.ok


def test_totals_mismatch_adds_warning():
    payload = json.loads(json.dumps(_GOOD))
    payload["header"]["total"] = "99.00"  # 35 + 1.75 != 99
    result = parse_extraction(json.dumps(payload))
    assert result.ok
    assert any("does not equal total" in w for w in result.extraction.warnings)


def test_line_items_not_summing_adds_warning():
    payload = json.loads(json.dumps(_GOOD))
    payload["line_items"] = [{"description": "a", "amount": "10.00"}]
    result = parse_extraction(json.dumps(payload))
    assert any("line items sum to" in w for w in result.extraction.warnings)


def test_missing_total_adds_warning():
    payload = json.loads(json.dumps(_GOOD))
    payload["header"]["total"] = None
    payload["header"]["subtotal"] = None
    payload["line_items"] = []
    result = parse_extraction(json.dumps(payload))
    assert any("no invoice total" in w for w in result.extraction.warnings)
