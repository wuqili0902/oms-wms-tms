"""WMS API router.

IMPORTANT: /inventory and /picking-waves routes MUST be defined before /{wh_id}
to avoid FastAPI path parameter matching.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.exceptions import NotFoundException, ValidationException
from src.wms.schemas import (
    InventoryAdjust,
    InventoryResponse,
    LocationCreate,
    LocationResponse,
    PickingWaveCreate,
    PickingWaveResponse,
    StockMovementResponse,
    WarehouseCreate,
    WarehouseResponse,
)
from src.wms import service as wms_service

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


@router.get("", response_model=list[WarehouseResponse])
async def list_warehouses(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.list_warehouses(db)


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


@router.post("/{wh_id}/locations", response_model=LocationResponse, status_code=status.HTTP_201_CREATED)
async def create_location(
    wh_id: str,
    data: LocationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        # Inject wh_id from path into data dict
        body = data.model_dump()
        body["warehouse_id"] = wh_id
        return await wms_service.create_location(db, wh_id, body)
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/{wh_id}/locations", response_model=list[LocationResponse])
async def list_locations(
    wh_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await wms_service.list_locations(db, wh_id=wh_id)
