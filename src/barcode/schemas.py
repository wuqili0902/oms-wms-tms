"""Barcode schemas."""

from pydantic import BaseModel, Field


class BarcodeGenerateRequest(BaseModel):
    gtin_prefix: str = Field(..., min_length=7, max_length=12, description="First 7-12 digits of GTIN")
    entity_type: str = Field(..., pattern=r"^(order|inventory|location|device)$")
    entity_id: str = Field(..., min_length=1)
    format: str = Field(default="ean13", pattern=r"^(ean13|code128|qr|datamatrix)$")


class BarcodeValidateRequest(BaseModel):
    gtin: str = Field(..., min_length=8, max_length=14)


class BarcodeScanRequest(BaseModel):
    raw_data: str = Field(..., min_length=1)
    scanner_id: str | None = None
    location_id: str | None = None


class BarcodeResponse(BaseModel):
    id: str
    gtin: str
    entity_type: str
    entity_id: str
    format: str
    raw_data: str
    created_at: str

    model_config = {"from_attributes": True}


class LabelTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    code: str = Field(..., min_length=1, max_length=50)
    format: str = Field(default="zpl", pattern=r"^(zpl|ezpl)$")
    width_mm: float = Field(default=50, gt=0, le=200)
    height_mm: float = Field(default=30, gt=0, le=200)
    content: dict = Field(default_factory=dict)
    is_default: bool = False


class LabelTemplateResponse(BaseModel):
    id: str
    name: str
    code: str
    format: str
    width_mm: float
    height_mm: float
    is_default: bool
    created_at: str

    model_config = {"from_attributes": True}
