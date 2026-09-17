"""Phase 10 — API request/response models (§10.2). Requests validated here;
detail/audit payloads are the JSON documents Phase 9's recorder already emits."""
from typing import Literal

from pydantic import BaseModel, Field


class ReviewIn(BaseModel):
    reviewer: str = Field(min_length=1)
    action: Literal["approve", "reject", "correct", "request_info"]
    comments: str | None = None
    corrections: dict[str, object] | None = None  # extracted-invoice field name -> new value


class UploadOut(BaseModel):
    invoice_id: str
    status: str
    decision: str
    rule_id: str
    reasons: list[str]


class ReviewOut(BaseModel):
    invoice_id: str
    status: str


class InvoiceListRow(BaseModel):
    invoice_id: str
    invoice_number: str
    vendor_id: str
    total: float
    currency: str
    status: str