"""WMS schemas."""
from decimal import Decimal

from pydantic import BaseModel, Field


class WarehouseCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    address: str = Field(default="", max_length=500)
    type: str = Field(default="center")
    is_active: bool = True


class WarehouseResponse(BaseModel):
    id: str
    code: str
    name: str
    address: str
    type: str
    is_active: bool
    created_at: str

    model_config = {"from_attributes": True}


class LocationCreate(BaseModel):
    zone: str = Field(..., min_length=1, max_length=50)
    aisle: str = Field(..., min_length=1, max_length=50)
    shelf: str = Field(..., min_length=1, max_length=50)
    bin: str = Field(..., min_length=1, max_length=50)
    type: str = Field(default="storage", pattern=r"^(storage|picking|receiving|shipping|damage)$")
    max_weight_kg: Decimal | None = None


class LocationUpdate(BaseModel):
    zone: str | None = Field(default=None, min_length=1, max_length=50)
    aisle: str | None = Field(default=None, min_length=1, max_length=50)
    shelf: str | None = Field(default=None, min_length=1, max_length=50)
    bin: str | None = Field(default=None, min_length=1, max_length=50)
    type: str | None = Field(default=None, pattern=r"^(storage|picking|receiving|shipping|damage)$")
    max_weight_kg: Decimal | None = None


class LocationResponse(BaseModel):
    id: str
    warehouse_id: str
    location_code: str
    zone: str
    aisle: str
    shelf: str
    bin: str
    type: str
    is_occupied: bool
    created_at: str

    model_config = {"from_attributes": True}


class InventoryResponse(BaseModel):
    id: str
    warehouse_id: str
    location_id: str
    sku: str
    quantity: float
    reserved_qty: float
    available_qty: float
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class InventoryAdjust(BaseModel):
    warehouse_id: str = Field(..., min_length=1)
    location_id: str = Field(..., min_length=1)
    sku: str = Field(..., min_length=1, max_length=50)
    quantity: Decimal = Field(..., description="Positive=in, Negative=out")
    reason: str = Field(default="adjustment", max_length=500)


class StockMovementResponse(BaseModel):
    id: str
    warehouse_id: str
    from_location_id: str | None = None
    to_location_id: str | None = None
    sku: str
    quantity: float
    type: str
    reference_no: str
    created_at: str

    model_config = {"from_attributes": True}


class PickingWaveCreate(BaseModel):
    warehouse_id: str = Field(..., min_length=1)
    order_ids: list[str] = Field(..., min_length=1)


class PickingWaveResponse(BaseModel):
    id: str
    wave_no: str
    warehouse_id: str
    status: str
    order_ids: list[str]
    total_items: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ── Address Master / Customer / Vendor ───────────────────────────────────────


class AddressCreate(BaseModel):
    entity_type: str  # 'customer' | 'vendor'
    entity_id: str | None = None
    address_type: str  # 'shipping' | 'billing' | 'warehouse'
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None


class AddressResponse(BaseModel):
    id: str
    entity_type: str
    entity_id: str | None = None
    address_type: str
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None

    model_config = {"from_attributes": True}


class CustomerCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)


class VendorCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)


# ── Purchase Order ───────────────────────────────────────────────────────────


class PurchaseOrderCreate(BaseModel):
    po_number: str = Field(..., min_length=1, max_length=50)
    vendor_id: str | None = None
    expected_date: str | None = None
    notes: str | None = None


class PurchaseOrderResponse(BaseModel):
    id: str
    po_number: str
    vendor_id: str | None
    status: str
    total_amount: float
    notes: str | None = None

    model_config = {"from_attributes": True}


class PurchaseOrderLineCreate(BaseModel):
    sku_id: str | None = None
    description: str | None = None
    quantity: Decimal
    unit_price: Decimal


# ── Invoice ─────────────────────────────────────────────────────────────────

class InvoiceCreate(BaseModel):
    invoice_number: str = Field(..., min_length=1, max_length=50)
    entity_type: str  # 'customer' | 'vendor'
    entity_id: str | None = None
    issue_date: str | None = None
    due_date: str | None = None
    notes: str | None = None


class InvoiceResponse(BaseModel):
    id: str
    invoice_number: str
    entity_type: str
    entity_id: str | None = None
    status: str
    total_amount: float
    paid_amount: float
    reference_number: str | None = None

    model_config = {"from_attributes": True}


class InvoiceLineCreate(BaseModel):
    description: str | None = None
    quantity: Decimal
    unit_price: Decimal


class CreditMemoCreate(BaseModel):
    credit_memo_number: str = Field(..., min_length=1, max_length=50)
    invoice_id: str | None = None
    entity_type: str
    entity_id: str | None = None
    issue_date: str | None = None
    reason: str = ""
    notes: str | None = None
    lines: list["InvoiceLineCreate"] = []


class CreditMemoResponse(BaseModel):
    id: str
    credit_memo_number: str
    invoice_id: str | None = None
    entity_type: str
    entity_id: str | None = None
    status: str
    total_amount: float
    reason: str
    notes: str | None = None

    model_config = {"from_attributes": True}
