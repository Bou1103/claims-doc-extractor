"""Domain schemas (the contract between pipeline stages and the API).

These are the *transfer* objects: what the LLM is asked to produce, what
validation checks, and what the API returns. Persistence tables live in
``app.models.tables``.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class InputMode(str, Enum):
    """Which representation of the PDF was sent to the model."""

    TEXT = "text"
    VISION = "vision"


class LineItem(BaseModel):
    description: str = Field(description="Line item text as printed on the invoice")
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = Field(default=None, description="Line total for this row")


class InvoiceHeader(BaseModel):
    vendor_name: str | None = None
    vendor_tax_id: str | None = Field(
        default=None, description="GST/HST/VAT/QST registration number if present"
    )
    client_name: str | None = Field(default=None, description="Party the invoice is billed to")
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = Field(default=None, description="ISO 4217 code when determinable")
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None


class InvoiceExtraction(BaseModel):
    """Structured result for one invoice PDF."""

    model_config = ConfigDict(extra="forbid")

    header: InvoiceHeader
    line_items: list[LineItem] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal issues, e.g. line items do not sum to the subtotal",
    )


class JobCreatedResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobResultResponse(BaseModel):
    job_id: str
    status: JobStatus
    result: InvoiceExtraction | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
