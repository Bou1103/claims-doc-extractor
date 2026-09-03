"""The extraction prompt and the code that turns a PdfContent into a user message.

PROMPT_VERSION is stored on every Extraction row so a stored result can always be
traced back to the exact instructions that produced it. Bump it whenever the
prompt text or the requested shape changes.
"""

from app.models.schemas import InputMode
from app.services.pdf_processor import PdfContent

PROMPT_VERSION = "invoice-extraction-v1"

SYSTEM_PROMPT = """\
You extract structured data from invoice documents for a legal claims team.

Return ONLY a single JSON object. No prose, no explanation, no markdown fences.

Shape:
{
  "header": {
    "vendor_name": string|null,
    "vendor_tax_id": string|null,      // GST/HST/VAT/QST registration number
    "client_name": string|null,        // the party the invoice is billed to
    "invoice_number": string|null,
    "invoice_date": "YYYY-MM-DD"|null,
    "due_date": "YYYY-MM-DD"|null,
    "currency": string|null,           // ISO 4217, e.g. "CAD", "USD"
    "subtotal": string|null,           // decimal string, no currency symbol or separators
    "tax": string|null,
    "total": string|null
  },
  "line_items": [
    {"description": string, "quantity": string|null, "unit_price": string|null, "amount": string|null}
  ],
  "warnings": [string]                  // note anything ambiguous, missing, or unusual
}

Rules:
- Use null when a value is not present. Do not guess.
- Amounts are decimal strings: "1234.56", never "$1,234.56".
- Convert every date to ISO 8601 (YYYY-MM-DD).
- If the document is not an invoice, set all header fields to null and add a
  warning saying what it appears to be.
"""


def build_user_message(content: PdfContent, feedback: str | None = None) -> dict:
    """Assemble the user turn: document text, or page images, plus optional
    correction feedback from a previous rejected attempt."""
    blocks: list[dict] = []

    if content.input_mode == InputMode.TEXT:
        blocks.append(
            {"type": "text", "text": f"Invoice document text:\n\n{content.text}"}
        )
    else:
        blocks.append(
            {"type": "text", "text": "Invoice document pages follow as images:"}
        )
        for image in content.page_images:
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.media_type,
                        "data": image.data_base64,
                    },
                }
            )

    if feedback:
        blocks.append(
            {
                "type": "text",
                "text": (
                    "Your previous response was rejected: "
                    f"{feedback}\nReturn corrected JSON only."
                ),
            }
        )

    return {"role": "user", "content": blocks}
