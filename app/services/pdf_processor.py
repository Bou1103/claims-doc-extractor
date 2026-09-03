"""Turn PDF bytes into something the LLM can consume.

Two outcomes:
  * TEXT   - the PDF has a trustworthy embedded text layer; we send the text.
  * VISION - no text, or the text is garbage (broken font encoding / scan);
             we rasterize the pages and send images.

"No text layer" has two shapes in practice and both must land on VISION:
  1. genuinely empty  -> char count is ~0
  2. present but garbled -> plenty of characters, almost no letters
The alpha-ratio check below is what catches shape 2.
"""

import base64

import pymupdf
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.errors import CorruptDocumentError
from app.models.schemas import InputMode

_USABLE_ALPHA_RATIO = 0.5


class PageText(BaseModel):
    page_number: int
    char_count: int
    alpha_ratio: float
    usable: bool


class PageImage(BaseModel):
    page_number: int
    media_type: str = "image/png"
    data_base64: str


class PdfContent(BaseModel):
    page_count: int
    input_mode: InputMode
    text: str | None = None
    page_images: list[PageImage] = Field(default_factory=list)
    pages: list[PageText] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _alpha_ratio(text: str) -> float:
    non_space = [c for c in text if not c.isspace()]
    if not non_space:
        return 0.0
    return sum(c.isalpha() for c in non_space) / len(non_space)


def _page_usable(text: str, min_chars: int) -> tuple[bool, float]:
    ratio = _alpha_ratio(text)
    usable = len(text.strip()) >= min_chars and ratio >= _USABLE_ALPHA_RATIO
    return usable, ratio


def _render_pages(doc: "pymupdf.Document", *, dpi: int, max_pages: int) -> list[PageImage]:
    zoom = dpi / 72
    matrix = pymupdf.Matrix(zoom, zoom)
    images: list[PageImage] = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        png = page.get_pixmap(matrix=matrix).tobytes("png")
        images.append(
            PageImage(page_number=i + 1, data_base64=base64.b64encode(png).decode("ascii"))
        )
    return images


def process_pdf(data: bytes, *, dpi: int = 200, max_pages: int = 15) -> PdfContent:
    settings = get_settings()
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # pymupdf raises several unrelated exception types
        raise CorruptDocumentError(f"could not open PDF: {exc}") from exc

    with doc:
        if doc.page_count == 0:
            raise CorruptDocumentError("PDF has no pages")

        pages: list[PageText] = []
        usable_texts: list[str] = []
        for i, page in enumerate(doc):
            text = page.get_text("text")
            usable, ratio = _page_usable(text, settings.text_layer_min_chars)
            pages.append(
                PageText(
                    page_number=i + 1,
                    char_count=len(text),
                    alpha_ratio=round(ratio, 3),
                    usable=usable,
                )
            )
            if usable:
                usable_texts.append(text)

        notes: list[str] = []
        usable_chars = sum(len(t) for t in usable_texts)

        if usable_chars >= settings.text_layer_min_chars:
            if len(usable_texts) < doc.page_count:
                notes.append(
                    f"{doc.page_count - len(usable_texts)} of {doc.page_count} pages "
                    "had no usable text and were dropped from the text payload"
                )
            return PdfContent(
                page_count=doc.page_count,
                input_mode=InputMode.TEXT,
                text="\n\n".join(usable_texts),
                pages=pages,
                notes=notes,
            )

        notes.append("no usable embedded text layer; routing to vision path")
        images = _render_pages(doc, dpi=dpi, max_pages=max_pages)
        if doc.page_count > max_pages:
            notes.append(f"rendered first {max_pages} of {doc.page_count} pages")
        return PdfContent(
            page_count=doc.page_count,
            input_mode=InputMode.VISION,
            page_images=images,
            pages=pages,
            notes=notes,
        )
