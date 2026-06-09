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
