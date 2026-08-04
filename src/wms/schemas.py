"""WMS schemas."""
from decimal import Decimal
from enum import StrEnum
from typing import Literal

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
    status: str | None = None
    position: str | None = None
    is_occupied: bool
    created_at: str

    model_config = {"from_attributes": True}


class LocationListResponse(BaseModel):
    items: list[LocationResponse]
    total: int
    page: int
    page_size: int


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
    created_at: str | None = None
    updated_at: str | None = None

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


class VendorResponse(BaseModel):
    id: str
    code: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool
    created_at: str

    model_config = {"from_attributes": True}


class VendorListResponse(BaseModel):
    items: list[VendorResponse]
    total: int
    page: int
    page_size: int


class ShipmentResponse(BaseModel):
    id: str
    order_id: str
    warehouse_id: str
    packing_record_id: str | None = None
    tracking_number: str | None = None
    carrier: str | None = None
    status: str
    shipped_at: str | None = None
    delivered_at: str | None = None
    notes: str | None = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


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
    expected_date: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


class PurchaseOrderListResponse(BaseModel):
    items: list[PurchaseOrderResponse]
    total: int
    page: int
    page_size: int


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


# ── Transfer Order ───────────────────────────────────────────────────────────

__ALL_TRANSFER_STATUSES: tuple[str] = (
    "DRAFT", "CONFIRMED", "IN_TRANSIT", "DELIVERED", "CANCELLED",
)


class TransferOrderItemCreate(BaseModel):
    item_type: Literal["SKU", "LOCATION", "WAREHOUSE"]
    sku_id: str | None = None
    location_from_id: str | None = None
    quantity: Decimal


class TransferOrderCreate(BaseModel):
    source_warehouse_id: str = Field(..., min_length=1)
    target_warehouse_id: str = Field(..., min_length=1)
    type: Literal["SKU", "LOCATION", "WAREHOUSE"] = "SKU"
    lines: list[TransferOrderItemCreate]


class TransferOrderUpdate(BaseModel):
    source_warehouse_id: str | None = None
    target_warehouse_id: str | None = None
    ref_no: str | None = None
    type: Literal["SKU", "LOCATION", "WAREHOUSE"] | None = None
    lines: list[TransferOrderItemCreate] | None = None


class TransferOrderLineResponse(BaseModel):
    id: str
    transfer_order_id: str
    item_type: str
    sku_id: str | None = None
    location_from_id: str | None = None
    quantity: float
    available_qty: float
    picked_qty: float
    shipped_qty: float
    received_qty: float

    model_config = {"from_attributes": True}


class TransferOrderResponse(BaseModel):
    id: str
    code: str
    source_warehouse_id: str
    target_warehouse_id: str
    type: str
    status: str
    total_weight_kg: float | None = None
    total_volume_m3: float | None = None
    total_pieces: int | None = None
    ref_no: str | None = None
    ref_type: str | None = None
    remarks: str | None = None

    model_config = {"from_attributes": True}


class TransferOrderResponseWithLines(TransferOrderResponse):
    lines: list[TransferOrderLineResponse]


class TransferLogCreate(BaseModel):
    transfer_order_id: str = Field(..., min_length=1)
    operator_id: str | None = None
    remark: str | None = None
    from_warehouse_id: str | None = None
    to_warehouse_id: str | None = None
    from_location_id: str | None = None
    to_location_id: str | None = None
    quantity_change: Decimal




# ── Stock In / Out ───────────────────────────────────────────────────


class StockInCreate(BaseModel):
    warehouse_id: str = Field(..., min_length=1)
    type: Literal["PURCHASE", "RETURN", "TRANSFER_IN", "ADJUSTMENT"] = "PURCHASE"
    ref_no: str | None = None
    reference_type: str | None = None
    supplier_id: str | None = None
    lines: list[dict] = Field(default_factory=list)


class StockInItemCreate(BaseModel):
    """单个入库项（SKU + 批次）"""
    sku: str = Field(..., min_length=1, max_length=50)
    quantity: Decimal = Field(..., gt=0)
    batch_no: str | None = Field(default=None, max_length=30)
    expiry_date: str | None = Field(default=None)  # ISO date string
    manufacturing_date: str | None = Field(default=None)  # ISO date string


class StockInItemResponse(BaseModel):
    id: str
    sku: str
    quantity: float
    batch_no: str | None = None
    expiry_date: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


class StockInResponse(BaseModel):
    """入库单响应（含所有条目）"""
    id: str
    warehouse_id: str
    type: str
    ref_no: str | None = None
    reference_type: str | None = None
    supplier_id: str | None = None
    status: str  # "DRAFT" | "CONFIRMED" | "RECEIVED" | "CANCELLED"
    total_qty: float
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class StockInResponseWithItems(StockInResponse):
    items: list[StockInItemResponse]


class StockInUpdate(BaseModel):
    status: Literal["DRAFT", "CONFIRMED", "RECEIVED", "CANCELLED"] | None = None
    ref_no: str | None = None


class StockInLineCreate(BaseModel):
    sku_id: str | None = None
    sku_name: str | None = None
    qty: Decimal
    batch_no: str | None = None
    lot_no: str | None = None
    expiry_date: str | None = None
    metadata_: dict | None = Field(default=None, alias="metadata")


class StockInLineResponse(BaseModel):
    id: str
    stock_in_id: str
    sku_id: str | None = None
    qty_received: float
    batch_no: str | None = None
    lot_no: str | None = None
    expiry_date: str | None = None

    model_config = {"from_attributes": True}


class StockInResponse(BaseModel):
    id: str
    warehouse_id: str
    type: str
    ref_no: str | None = None
    reference_type: str | None = None
    supplier_id: str | None = None
    total_qty: float
    status: str
    created_at: str

    model_config = {"from_attributes": True}


class StockInResponseWithLines(StockInResponse):
    lines: list[StockInLineResponse]


class StockOutCreate(BaseModel):
    warehouse_id: str = Field(..., min_length=1)
    type: Literal["SALE", "TRANSFER_OUT", "ADJUSTMENT"] = "SALE"
    ref_no: str | None = None
    reference_type: str | None = None
    lines: list[dict] = Field(default_factory=list)


class StockOutUpdate(BaseModel):
    status: Literal["DRAFT", "CONFIRMED", "SHIPPED", "CANCELLED"] | None = None
    ref_no: str | None = None


class StockOutLineCreate(BaseModel):
    sku_id: str | None = None
    sku_name: str | None = None
    qty: Decimal
    batch_no: str | None = None
    lot_no: str | None = None
    expiry_date: str | None = None
    metadata_: dict | None = Field(default=None, alias="metadata")


class StockOutLineResponse(BaseModel):
    id: str
    stock_out_id: str
    sku_id: str | None = None
    qty_shipped: float
    batch_no: str | None = None
    lot_no: str | None = None
    expiry_date: str | None = None

    model_config = {"from_attributes": True}


class StockOutResponse(BaseModel):
    id: str
    warehouse_id: str
    type: str
    ref_no: str | None = None
    reference_type: str | None = None
    total_qty: float
    status: str
    created_at: str

    model_config = {"from_attributes": True}


class StockOutResponseWithLines(StockOutResponse):
    lines: list[StockOutLineResponse]


# ── Inventory Log ────────────────────────────────────────────────────


class InventoryLogType(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    ADJUSTMENT_IN = "ADJUSTMENT_IN"
    ADJUSTMENT_OUT = "ADJUSTMENT_OUT"


class InventoryLogResponse(BaseModel):
    id: str
    warehouse_id: str
    sku: str
    type: str
    reference_type: str | None = None
    reference_id: str | None = None
    quantity_change: float
    operator_id: str | None = None
    reason: str | None = None
    remark: str | None = None

    model_config = {"from_attributes": True}


# ── Adjust Stock ─────────────────────────────────────────────────────


class AdjustStockRequest(BaseModel):
    """Adjust stock up or down."""
    warehouse_id: str
    sku_id: str
    quantity: Decimal  # positive for IN, negative for OUT
    type: Literal["ADJUSTMENT_IN", "ADJUSTMENT_OUT"] = "ADJUSTMENT_IN"
    reason: str | None = None
    remark: str | None = None
