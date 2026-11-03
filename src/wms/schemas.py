"""WMS schemas."""
import uuid as _uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

from src.core.schemas import PayloadBody


class _DocumentBody(PayloadBody):
    """Base for the write bodies that accept the ``{"data": {...}}`` envelope.

    ``src/routes/stock.py`` read every write body as ``req.get("data", {})``,
    which made the envelope the contract; and a flat body — the shape
    ``frontend/src/services/inventory.ts`` posts — landed on an empty dict and
    reached ``data["warehouse_id"]``, a KeyError and a 500 for a request that
    was merely missing a field.  Both shapes are accepted here, and the field
    names in a validation error are the payload's own, not ``data.warehouse_id``
    in one shape and ``warehouse_id`` in the other.

    The envelope unwrapping, the unknown-key refusal and ``populate_by_name``
    are :class:`src.core.schemas.PayloadBody` — the same base the TMS write
    bodies stand on, which is what keeps a write body in one service from
    drifting into a different language from a write body in another.  The alias
    stays because the document bodies built on it are spread across the WMS and
    stock sections below, in an order that predates the shared class.
    """


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
    # Stock is keyed by batch, and FEFO picking orders by expiry — neither is
    # actionable if the API never says which batch a quantity sits in.
    # ``_inv_to_dict`` already computes all four; the response model was
    # filtering them out on the way out.
    batch_no: str | None = None
    expiry_date: date | None = None
    manufacturing_date: date | None = None
    received_at: str | None = None

    model_config = {"from_attributes": True}


class InventoryAdjust(BaseModel):
    warehouse_id: str = Field(..., min_length=1)
    location_id: str = Field(..., min_length=1)
    sku: str = Field(..., min_length=1, max_length=50)
    quantity: Decimal = Field(..., description="Positive=in, Negative=out")
    reason: str = Field(default="adjustment", max_length=500)
    # adjust_inventory() already keys stock by batch and honours expiry dates;
    # without these fields the batch a PDA operator scanned was dropped by
    # ``model_dump()`` and the movement landed on the "DEFAULT" batch instead.
    batch_no: str | None = Field(default=None, max_length=30)
    expiry_date: date | None = Field(default=None, description="ISO date, e.g. 2026-12-31")
    manufacturing_date: date | None = Field(default=None, description="ISO date, e.g. 2026-01-05")
    picking_strategy: Literal["fefo", "fifo", "batch"] = Field(
        default="fefo",
        description="How batches are chosen when quantity is negative",
    )


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
    # The number the 发货管理 list, the carrier handover and the reconciliation
    # sheet all call a shipment by.  It was the one column on that screen that
    # had no field behind it.
    shipment_no: str = ""
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


# ── Packing / shipping write bodies ─────────────────────────────────────────


class PackingCreate(_DocumentBody):
    """Body for ``POST /warehouses/packing``.

    Two keys name the wave, and the screen and the service disagreed about
    which one: ``ShipmentList.vue``'s 打包记录 form posts ``{"wave_id": …}``
    (its input is labelled 波次ID), and the service read ``data["picking_wave_id"]``
    — so 记录打包 was a KeyError and a 500 for every wave, from the day the
    screen shipped.  Both spellings are accepted; the guard that refuses a body
    naming no wave is in ``create_packing``, where the direct callers are.
    """

    picking_wave_id: str = Field(validation_alias=AliasChoices("picking_wave_id", "wave_id"))
    box_count: int = Field(1, ge=1)
    packed_by: str = ""
    notes: str = ""


class ShipmentCreate(_DocumentBody):
    """Body for ``POST /warehouses/shipments``.

    The 新建发货单 dialog collects 仓库ID and a textarea of 订单ID列表 and
    posts ``{"warehouse_id": …, "order_ids": […]}`` — one shipment per order.
    The service read ``data["order_id"]``, so 提交 on that screen was a KeyError
    and a 发货单创建失败 toast that never explained itself.  Both keys are
    declared here: ``order_ids`` is the screen's, ``order_id`` the shape the
    single-order callers already send.  Which of the two must be present, and
    that at least one order must be named, is decided in ``create_shipment``.
    """

    warehouse_id: str
    order_ids: list[str] = []
    order_id: str | None = None
    packing_record_id: str | None = None
    tracking_number: str = ""
    carrier: str = ""
    notes: str = ""


class ShipmentShip(_DocumentBody):
    """Body for ``POST /warehouses/shipments/{id}/ship``, every field optional.

    The 发货 button on the shipment list posts no body at all — marking shipped
    with the tracking number the shipment already carries is what that button
    means — so the route takes this body optionally.  What *is* sent must still
    be the two fields it names; a body that spells ``tracking`` is refused
    rather than ignored, which is how an unrecorded tracking number starts.
    """

    tracking_number: str = ""
    carrier: str = ""


class PackingRecordResponse(BaseModel):
    """A packing record, as the endpoint that created it presents it."""

    id: str
    picking_wave_id: str
    box_count: int
    packed_by: str = ""
    notes: str = ""
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class ShipmentCreateResult(BaseModel):
    """What ``POST /warehouses/shipments`` created, for one order or for many.

    One shape: the screen that lists five order ids gets five shipments, not
    the first one with the other four silently dropped.
    """

    count: int
    shipments: list[ShipmentResponse]


# ── Purchase Order ───────────────────────────────────────────────────────────


class PurchaseOrderLineCreate(BaseModel):
    sku_id: str | None = None
    # SKU code, for callers that know what they are ordering but not its id
    # (a PDA scan resolves to a code).  Without it, a line created through the
    # API could carry a description only — and a line with no SKU has no
    # inventory row to receive into.
    sku: str | None = Field(None, max_length=60)
    description: str | None = None
    quantity: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(Decimal("0"), ge=0)


class PurchaseOrderCreate(BaseModel):
    po_number: str = Field(..., min_length=1, max_length=50)
    vendor_id: str | None = None
    expected_date: date | None = None
    notes: str | None = None
    # create_purchase_order() already looped over data["lines"], but the schema
    # dropped the key on model_dump(): every PO created through the API arrived
    # with zero lines, and an order with no lines is not receivable.
    lines: list[PurchaseOrderLineCreate] = []


class PurchaseOrderLineResponse(BaseModel):
    """One ordered line, with how much of it has actually landed.

    ``sku`` is carried alongside ``sku_id`` because the PDA matches a scan
    (a barcode resolves to a SKU code, not to a UUID), and because a line
    without its code is a line the operator cannot verify against the carton.
    """

    id: str
    sku_id: str | None = None
    sku: str | None = None
    description: str | None = None
    quantity: Decimal
    received_qty: Decimal = Decimal("0")
    unit_price: Decimal = Decimal("0")
    received_at: str | None = None

    model_config = {"from_attributes": True}


class PurchaseOrderResponse(BaseModel):
    id: str
    po_number: str
    vendor_id: str | None
    status: str
    total_amount: float
    notes: str | None = None
    # A `date` (serialised to YYYY-MM-DD on the wire), not `str`: model_to_dict()
    # hands back the date object it read from the column, and pydantic refuses to
    # squeeze a date into a str field — so setting expected_date on a PO made the
    # response model fail, i.e. a 500 for a valid create.
    expected_date: date | None = None
    created_at: str
    # A PO reported without its lines cannot be received: the receiving screen
    # had nothing to put quantities into, so it showed an empty order and the
    # operator confirmed a receipt for goods they could not list.
    lines: list[PurchaseOrderLineResponse] = []

    model_config = {"from_attributes": True}


class PurchaseOrderListResponse(BaseModel):
    items: list[PurchaseOrderResponse]
    total: int
    page: int
    page_size: int


class PurchaseOrderReceiveLine(BaseModel):
    """What arrived for one ordered line."""

    line_id: str | None = None
    # Either handle identifies the line.  A PDA knows the SKU it scanned;
    # a screen that loaded the PO knows the line id.
    sku: str | None = Field(None, max_length=60)
    received_qty: Decimal = Field(..., ge=0)
    batch_no: str | None = Field(None, max_length=30)
    expiry_date: date | None = None
    manufacturing_date: date | None = None


class PurchaseOrderReceive(BaseModel):
    """Body of ``POST /purchase-orders/{po_id}/receive``.

    ``warehouse_id``/``location_id`` are required, not optional: a receipt
    records where the goods went.  They were absent entirely, which is why
    receiving could only ever flip a status — there was no destination to book
    inventory into.
    """

    warehouse_id: str = Field(..., min_length=1)
    location_id: str = Field(..., min_length=1)
    lines: list[PurchaseOrderReceiveLine] | None = None
    notes: str | None = None


# ── Invoice ─────────────────────────────────────────────────────────────────

class InvoiceCreate(BaseModel):
    invoice_number: str = Field(..., min_length=1, max_length=50)
    entity_type: str  # 'customer' | 'vendor'
    entity_id: str | None = None
    # Typed as dates, not strings: a ``str`` field accepted "next friday" and
    # the service's fromisoformat() then raised, which the global handler
    # reported as a 500 — a server error for a typo in a request.
    issue_date: date | None = None
    due_date: date | None = None
    notes: str | None = None
    # create_invoice() already built the lines and totalled them, but this
    # schema dropped the key on model_dump(): every invoice created through the
    # API arrived with nothing on it and — the total being the sum of the lines
    # — an amount of zero.
    lines: list["InvoiceLineCreate"] = []


class InvoiceResponse(BaseModel):
    id: str
    invoice_number: str
    entity_type: str
    entity_id: str | None = None
    status: str
    total_amount: float
    paid_amount: float
    reference_number: str | None = None
    # An invoice without its dates is not a receivable: nothing downstream can
    # tell one that is due from one that is overdue.
    issue_date: date | None = None
    due_date: date | None = None
    lines: list["InvoiceLineResponse"] = []

    model_config = {"from_attributes": True}


class InvoiceLineCreate(BaseModel):
    description: str | None = None
    quantity: Decimal
    unit_price: Decimal


class InvoiceLineResponse(BaseModel):
    id: str
    description: str | None = None
    quantity: Decimal
    unit_price: Decimal

    model_config = {"from_attributes": True}


class CreditMemoCreate(BaseModel):
    credit_memo_number: str = Field(..., min_length=1, max_length=50)
    invoice_id: str | None = None
    entity_type: str
    entity_id: str | None = None
    issue_date: date | None = None
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
    issue_date: date | None = None
    lines: list[InvoiceLineResponse] = []

    model_config = {"from_attributes": True}


# ── Transfer Order ───────────────────────────────────────────────────────────

__ALL_TRANSFER_STATUSES: tuple[str] = (
    "DRAFT", "CONFIRMED", "IN_TRANSIT", "DELIVERED", "CANCELLED",
)


class TransferLineCreate(BaseModel):
    """One line of a transfer order.

    ``sku_id`` is the spelling ``docs/functional-test-plan.md`` documents;
    ``sku`` is the spelling the mobile screen and the frontend service send.
    The route read ``item_data["sku"]`` and ``item_data["quantity"]`` straight
    out of the dict, so the documented body — a line named by ``sku_id`` —
    raised KeyError in the handler and answered 500, and a line whose quantity
    was ``"5x"`` reached ``Decimal("5x")``, the same answer.  A quantity of zero
    asks the warehouse to move nothing to another building, so it is refused.
    """

    sku: str | None = Field(default=None, max_length=64)
    sku_id: _uuid.UUID | None = None
    qty: Decimal = Field(..., gt=Decimal("0"), validation_alias=AliasChoices("quantity", "qty"))

    model_config = {"extra": "forbid", "populate_by_name": True}


class TransferOrderCreate(_DocumentBody):
    """Create a transfer order: stock moving from one warehouse to another.

    The source is required, and it is a warehouse.  ``src/wms/service.py`` read
    the source from ``data["source_location"]`` only, so the source named by
    ``docs/functional-test-plan.md`` (``source_warehouse_id``) was dropped and
    the order was filed with ``source_warehouse_id = NULL`` — a transfer with no
    origin — while that same key, read as a fallback for the *destination*, made
    an order whose destination is the warehouse the caller named as its source.
    A warehouse code typed into the mobile field is a code, not a UUID, and
    ``_to_uuid`` returned None for it: same silent NULL.  Both ends are required
    here, both are resolved by id *or* code, and an unresolvable one is refused
    by the field name the caller used.

    ``source_location`` is accepted as a spelling of the source because
    ``mobile/src/screens/TransferOrderScreen.js`` sends that key; the service has
    always treated its value as a warehouse, and ``TransferOrder.source_warehouse_id``
    is what it writes.
    """

    source_warehouse_id: str = Field(
        ..., min_length=1, max_length=64,
        validation_alias=AliasChoices("source_warehouse_id", "source_warehouse_code", "source_location"),
    )
    target_warehouse_id: str = Field(
        ..., min_length=1, max_length=64,
        validation_alias=AliasChoices("target_warehouse_id", "destination_warehouse_id", "dest_warehouse_id"),
    )
    type: Literal["SKU", "LOCATION", "WAREHOUSE"] = "SKU"
    ref_no: str | None = Field(default=None, max_length=100)
    remarks: str | None = Field(default=None, max_length=500)
    lines: list[TransferLineCreate] = Field(
        min_length=1, validation_alias=AliasChoices("lines", "items"),
    )


class StockCountLineCreate(BaseModel):
    """One counted line of a stock count (盘点) result.

    ``sku_code`` and ``actual_qty_count`` are the spellings the PDA sends;
    ``sku``/``actual_qty`` are what ``docs/functional-test-plan.md`` 4.7.5
    documents.  The service read those keys with ``.get`` and raised a
    ValidationException naming the SKU when a quantity was missing, so a
    quantity written under a fourth key — ``counted_qty`` — reached the
    comparison as None and ``Decimal(str(None))``, a 500 in the route.
    Zero is a legal count: 盘亏到零 is a result, not an omission.
    """

    sku: str = Field(..., min_length=1, max_length=64, validation_alias=AliasChoices("sku", "sku_code"))
    actual_qty: Decimal = Field(
        ..., ge=Decimal("0"),
        validation_alias=AliasChoices("actual_qty", "actual_qty_count", "qty_counted"),
    )

    model_config = {"extra": "forbid", "populate_by_name": True}


class StockCountSubmit(_DocumentBody):
    """Submit the counted quantities of a location.

    Dumping this model answers the service's own key spellings: the aliases the
    mobile client sends (``source_warehouse_code``, ``target_location_id``,
    ``results``) arrive, and the service's ``data.get(...)`` reads the canonical
    one.  A count with no lines is refused here rather than in the loop.
    """

    warehouse_id: str = Field(
        ..., min_length=1, max_length=64,
        validation_alias=AliasChoices("warehouse_id", "source_warehouse_code", "warehouse_code"),
    )
    location_id: str = Field(
        ..., min_length=1, max_length=64,
        validation_alias=AliasChoices("location_id", "target_location_id"),
    )
    count_results: list[StockCountLineCreate] = Field(
        min_length=1, validation_alias=AliasChoices("count_results", "results", "items"),
    )


class TransferOrderUpdate(BaseModel):
    source_warehouse_id: str | None = None
    target_warehouse_id: str | None = None
    ref_no: str | None = None
    type: Literal["SKU", "LOCATION", "WAREHOUSE"] | None = None
    lines: list[TransferLineCreate] | None = None


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
# (``_DocumentBody``, the envelope-accepting base these bodies build on, is at
# the top of this file.)


class StockLineCreate(BaseModel):
    """One line of a stock-in receipt or a stock-out shipment.

    The route pulled the quantity out of whichever of four key spellings
    ``_extract_qty`` found, so a line typed ``{"qtyy": 3}`` answered "Each line
    must have 'qty', 'quantity', 'qty_received', or 'qty_shipped'" — four key
    names the client never sent, about a body that did carry a quantity — and
    ``{"qty": "abc"}`` reached ``Decimal("abc")``, which the route has no
    handler for: 500.  The four spellings stay (the shipped frontend and
    tests/test_full_api.py both use them); an undeclared key is now refused by
    name.  Zero is a legal received quantity: a line the carrier short-shipped
    is recorded as zero, not rejected.
    """

    sku: str | None = Field(default=None, max_length=64)
    qty: Decimal = Field(..., ge=Decimal("0"), validation_alias=AliasChoices(
        "qty", "quantity", "qty_received", "qty_shipped",
    ))
    batch_no: str | None = Field(default=None, max_length=64)
    lot_no: str | None = Field(default=None, max_length=64)
    # The column is a DateTime and the route passed the raw string to it, so a
    # value the client invented failed at COMMIT — inside the transaction.
    expiry_date: datetime | None = None

    model_config = {"extra": "forbid", "populate_by_name": True}


class StockInCreate(_DocumentBody):
    """Create a stock-in receipt.

    ``type`` is the ``StockInType`` vocabulary, and the value is stored
    verbatim, which is how ``frontend/src/views/stock/StockIn.vue`` ended up
    filing receipts as ``TRANSFER`` and ``MANUAL`` — strings that exist in no
    enum, no query and no report of this system.
    """

    warehouse_id: _uuid.UUID
    type: Literal["PURCHASE", "RETURN", "TRANSFER_IN", "ADJUSTMENT"] = "PURCHASE"
    ref_no: str | None = Field(default=None, max_length=100)
    reference_type: str | None = Field(default=None, max_length=64)
    supplier_id: _uuid.UUID | None = None
    # ``items`` is the key the frontend service sends for the line array.
    lines: list[StockLineCreate] = Field(
        min_length=1, validation_alias=AliasChoices("lines", "items"),
    )


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


class InventorySnapshotResponse(BaseModel):
    """单个 SKU 库存快照（stock_in / stock_out 返回）"""
    id: str
    warehouse_id: str
    location_id: str | None = None
    sku: str
    batch_no: str | None = None
    expiry_date: str | None = None
    manufacturing_date: str | None = None
    received_at: str | None = None
    quantity: float
    reserved_qty: float = 0.0
    available_qty: float = 0.0
    created_at: str
    updated_at: str

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


class StockInUpdate(_DocumentBody):
    """The fields a client may change on a stock-in — an allowlist.

    ``update_stock_in`` handed the request dict to ``update(...).values(data)``.
    ``{"data": {"is_deleted": true}}`` deleted the receipt,
    ``{"data": {"total_qty": 9999}}`` wrote a total the lines do not add up to,
    and ``{"data": {"warehouse_id": <other>}}`` moved the document to a
    warehouse the caller chose — all legal, all applied to the row behind the
    ORM object's back, so the JSON the client received was the row as it was
    before the update.
    """

    status: Literal["DRAFT", "CONFIRMED", "RECEIVED", "CANCELLED"] | None = None
    ref_no: str | None = Field(default=None, max_length=100)
    reference_type: str | None = Field(default=None, max_length=64)


class StockInLineResponse(BaseModel):
    id: str
    stock_in_id: str
    sku_id: str | None = None
    qty_received: float
    batch_no: str | None = None
    lot_no: str | None = None
    expiry_date: str | None = None

    model_config = {"from_attributes": True}


class StockInResponseWithLines(StockInResponse):
    lines: list[StockInLineResponse]


class StockOutCreate(_DocumentBody):
    """Create a stock-out shipment.  Same shape and same rules as StockInCreate.

    A stock-out created here is a document, not a movement: it does not touch a
    single ``Inventory`` row, and it writes no ``InventoryLog``.  Confirming and
    shipping it are status transitions on the document alone, so the shipment
    ledger and the shelf drift apart the moment one of these is created.
    """

    warehouse_id: _uuid.UUID
    type: Literal["SALE", "TRANSFER_OUT", "ADJUSTMENT"] = "SALE"
    ref_no: str | None = Field(default=None, max_length=100)
    reference_type: str | None = Field(default=None, max_length=64)
    lines: list[StockLineCreate] = Field(
        min_length=1, validation_alias=AliasChoices("lines", "items"),
    )


class StockOutUpdate(_DocumentBody):
    """The fields a client may change on a stock-out — same allowlist as StockInUpdate."""

    status: Literal["DRAFT", "CONFIRMED", "SHIPPED", "CANCELLED"] | None = None
    ref_no: str | None = Field(default=None, max_length=100)
    reference_type: str | None = Field(default=None, max_length=64)


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


class AdjustStockRequest(_DocumentBody):
    """Adjust stock up or down: positive quantity is 盘盈, negative is 盘亏.

    The direction is derived from the sign of ``quantity`` by the route, so the
    ``type`` field this schema used to carry was an input nothing read.

    ``operator_id`` is the field that names who made the adjustment, and it is
    the one the old route got wrong in both directions: it inserted
    ``data.get("operator_id")`` into a foreign key to ``users.id`` unchecked (a
    client that sent ``"admin"`` got a COMMIT failure), and its fallback —
    ``str(UUID(current_user["sub"]))`` — raised on every single request, because
    ``sub`` in this API's tokens is a username, not a user id, and the handler
    swallowed the error.  The operator column of an adjustment audit row was
    NULL always.  A key the route does not read (``operator``) is now refused by
    name rather than dropped, so a caller who believes they recorded an operator
    finds out at request time that they did not.
    """

    warehouse_id: _uuid.UUID
    sku_id: _uuid.UUID
    quantity: Decimal
    reason: Literal["DAMAGE", "EXPIRED", "LOST", "FOUND", "COUNT_ERROR"] | None = None
    remark: str | None = Field(default=None, max_length=500)
    operator_id: _uuid.UUID | None = None
