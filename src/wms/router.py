"""WMS API router.

IMPORTANT: /inventory and /picking-waves routes MUST be defined before /{wh_id}
to avoid FastAPI path parameter matching.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.exceptions import NotFoundException, ValidationException
from src.models.base import model_to_dict
from src.wms import service as wms_service
from src.wms.schemas import (
    AddressCreate,
    AddressResponse,
    CreditMemoCreate,
    CreditMemoResponse,
    InventoryAdjust,
    InventoryResponse,
    InvoiceCreate,
    InvoiceResponse,
    LocationCreate,
    LocationListResponse,
    LocationResponse,
    LocationUpdate,
    PickingWaveCreate,
    PickingWaveResponse,
    PurchaseOrderCreate,
    PurchaseOrderListResponse,
    PurchaseOrderResponse,
    ShipmentResponse,
    StockInItemCreate,
    StockInResponseWithItems,
    StockMovementResponse,
    VendorCreate,
    VendorListResponse,
    VendorResponse,
    WarehouseCreate,
    WarehouseResponse,
)

router = APIRouter(prefix="/warehouses", tags=["wms"])


# ══════════════════════════════════════════════════════════════════════════════
# Inventory & Picking-wave routes — MUST be before /{wh_id} to avoid param
# matching
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/inventory", response_model=list[InventoryResponse])
async def query_inventory(
    warehouse_id: str = Query(None),
    location_id: str = Query(None),
    sku: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.query_inventory(db, wh_id=warehouse_id, location_id=location_id, sku=sku)


@router.post("/inventory/adjust", response_model=InventoryResponse)
async def adjust_inventory(
    data: InventoryAdjust,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.adjust_inventory(db, data.model_dump())
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/inventory/items", response_model=StockInResponseWithItems, status_code=status.HTTP_201_CREATED)
async def stock_in(
    warehouse_id: str,
    data: StockInItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """录入商品到仓库（SKU、数量、批次号），返回操作后的实时库存快照"""
    try:
        result = await wms_service.stock_in(db, warehouse_id, data.model_dump(), current_user)
        return result
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/inventory/movements", response_model=list[StockMovementResponse])
async def list_movements(
    warehouse_id: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.list_movements(db, wh_id=warehouse_id)


@router.post("/picking-waves", response_model=PickingWaveResponse, status_code=status.HTTP_201_CREATED)
async def create_picking_wave(
    data: PickingWaveCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.create_picking_wave(db, data.model_dump())
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/picking-waves", response_model=list[PickingWaveResponse])
async def list_picking_waves(
    warehouse_id: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.list_picking_waves(db, wh_id=warehouse_id)


# ══════════════════════════════════════════════════════════════════════════════
# Warehouse CRUD
# ══════════════════════════════════════════════════════════════════════════════

@router.post("", response_model=WarehouseResponse, status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    data: WarehouseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.create_warehouse(db, data.model_dump())
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


# ═══ Picking Wave Execution ═══════════════════════════════════════════════════

@router.post("/picking-waves/{wave_id}/start")
async def start_picking_wave(
    wave_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.start_picking(db, wave_id, current_user.get("sub", ""))
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/picking-waves/{wave_id}/complete")
async def complete_picking_wave(
    wave_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.complete_picking(db, wave_id)
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


# ═══ Packing ═══════════════════════════════════════════════════════════════════

@router.post("/packing", status_code=status.HTTP_201_CREATED)
async def create_packing(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.create_packing(db, data)
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


# ═══ Shipping ══════════════════════════════════════════════════════════════════

@router.post("/shipments", status_code=status.HTTP_201_CREATED)
async def create_shipment(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.create_shipment(db, data)
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/shipments/{shipment_id}/ship")
async def ship_package(
    shipment_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.mark_shipped(
            db, shipment_id,
            tracking_number=data.get("tracking_number", ""),
            carrier=data.get("carrier", ""),
        )
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/shipments", response_model=list[ShipmentResponse])
async def list_shipments(
    warehouse_id: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.list_shipments(db, warehouse_id=warehouse_id)


@router.get("")
async def list_warehouses(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.list_warehouses(db, page=page, page_size=page_size)


# ═══ Vendor CRUD ════════════════════════════════════════════════════════

@router.post("/vendors", status_code=status.HTTP_201_CREATED)
async def create_vendor(
    data: VendorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.create_vendor(db, data.model_dump())
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/vendors", response_model=VendorListResponse)
async def list_vendors(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.list_vendors(db, page=page, page_size=page_size)


@router.get("/vendors/{vendor_id}", response_model=VendorResponse)
async def get_vendor(
    vendor_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.get_vendor(db, vendor_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══ Address CRUD ═══════════════════════════════════════════════════════

@router.post("/addresses", status_code=status.HTTP_201_CREATED)
async def create_address(
    data: AddressCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.create_address(db, data.model_dump())


@router.get("/addresses", response_model=list[AddressResponse])
async def list_addresses(
    entity_type: str | None = None,
    entity_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.list_addresses(db, entity_type=entity_type, entity_id=entity_id)


# ═══ Purchase Order CRUD ════════════════════════════════════════════════

@router.post("/purchase-orders", status_code=status.HTTP_201_CREATED, response_model=PurchaseOrderResponse)
async def create_purchase_order(
    data: PurchaseOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.create_purchase_order(db, data.model_dump())


@router.get("/purchase-orders", response_model=PurchaseOrderListResponse)
async def list_purchase_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.list_purchase_orders(db, page=page, page_size=page_size)


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderResponse)
async def get_purchase_order(
    po_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.get_purchase_order(db, po_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/purchase-orders/{po_id}/approve", response_model=PurchaseOrderResponse)
async def approve_purchase_order(
    po_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.approve_purchase_order(db, po_id)
    except (NotFoundException, ValidationException) as e:
        status_code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=status_code, detail=str(e))


@router.post("/purchase-orders/{po_id}/receive", response_model=PurchaseOrderResponse)
async def receive_goods(
    po_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.receive_goods(db, po_id)
    except (NotFoundException, ValidationException) as e:
        status_code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=status_code, detail=str(e))


# ═══ Invoice CRUD ═══════════════════════════════════════════════════════

@router.post("/invoices", status_code=status.HTTP_201_CREATED, response_model=InvoiceResponse)
async def create_invoice(
    data: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.create_invoice(db, data.model_dump())


@router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.list_invoices(db)


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.get_invoice(db, invoice_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══ CreditMemo CRUD ════════════════════════════════════════════════════

@router.post("/credit-memos", status_code=status.HTTP_201_CREATED, response_model=CreditMemoResponse)
async def create_credit_memo(
    data: CreditMemoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.create_credit_memo(db, data.model_dump())


@router.get("/credit-memos", response_model=list[CreditMemoResponse])
async def list_credit_memos(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.list_credit_memos(db)


@router.get("/credit-memos/{cm_id}", response_model=CreditMemoResponse)
async def get_credit_memo(
    cm_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.get_credit_memo(db, cm_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# Warehouse-specific routes — MUST be after /inventory, /picking-waves
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/{wh_id}", response_model=WarehouseResponse)
async def get_warehouse(
    wh_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.get_warehouse(db, wh_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{wh_id}", response_model=WarehouseResponse)
async def update_warehouse(
    wh_id: str,
    data: WarehouseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        wh = await wms_service.update_warehouse(db, wh_id, data.model_dump())
        d = model_to_dict(wh)
        d["type"] = d.pop("warehouse_type", "standard")
        d["is_active"] = d.get("status") == "active"
        return d
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{wh_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_warehouse(
    wh_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        await wms_service.delete_warehouse(db, wh_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{wh_id}/locations", response_model=LocationResponse, status_code=status.HTTP_201_CREATED)
async def create_location(
    wh_id: str,
    data: LocationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        body = data.model_dump()
        body["warehouse_id"] = wh_id
        return await wms_service.create_location(db, wh_id, body)
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/{wh_id}/locations", response_model=LocationListResponse)
async def list_locations(
    wh_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.list_locations(db, wh_id=wh_id, page=page, page_size=page_size)


@router.put("/{wh_id}/locations/{loc_id}", response_model=LocationResponse)
async def update_location(
    wh_id: str,
    loc_id: str,
    data: LocationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await wms_service.update_location(db, wh_id, loc_id, data.model_dump())
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{wh_id}/locations/{loc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_location(
    wh_id: str,
    loc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        await wms_service.delete_location(db, wh_id, loc_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
