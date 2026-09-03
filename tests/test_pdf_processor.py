from pathlib import Path

import pytest

from app.core.errors import CorruptDocumentError
from app.models.schemas import InputMode
from app.services.pdf_processor import process_pdf

DATASET = Path(__file__).resolve().parents[1] / "case_interview_dataset.pdf"


def test_text_pdf_uses_text_mode(text_invoice_pdf):
    result = process_pdf(text_invoice_pdf)

    assert result.input_mode == InputMode.TEXT
    assert "INV-2025-001" in result.text
    assert result.page_images == []
    assert result.pages[0].usable


def test_image_only_pdf_falls_back_to_vision(image_only_pdf):
    result = process_pdf(image_only_pdf)

    assert result.input_mode == InputMode.VISION
    assert len(result.page_images) == 1
    assert result.page_images[0].data_base64
    assert not result.pages[0].usable
    assert any("vision" in note for note in result.notes)


def test_garbled_text_layer_falls_back_to_vision(garbled_pdf):
    result = process_pdf(garbled_pdf)

    assert result.input_mode == InputMode.VISION
    assert result.pages[0].char_count > 100  # there IS text...
    assert result.pages[0].alpha_ratio < 0.2  # ...but it is not letters


def test_corrupt_bytes_raise():
    with pytest.raises(CorruptDocumentError):
        process_pdf(b"%PDF-1.4 this is not actually a pdf body")


@pytest.mark.skipif(not DATASET.exists(), reason="case dataset PDF not present")
def test_real_case_dataset_routes_to_vision():
    result = process_pdf(DATASET.read_bytes())

    assert result.page_count == 3
    # page 1 & 3 are image-only, page 2 has a garbled text layer -> all vision
    assert result.input_mode == InputMode.VISION
    assert len(result.page_images) == 3
