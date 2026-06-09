"""OMS schemas."""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class OrderItemSchema(BaseModel):
    gtin: str = Field(..., min_length=8, max_length=14)
    sku: str = Field(..., min_length=1, max_length=50)
    product_name: str = Field(default="", max_length=200)
    quantity: int = Field(..., gt=0, le=99999)
    unit_price: Decimal = Field(..., ge=0, max_digits=18, decimal_places=2)
    subtotal: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)


class OrderCreate(BaseModel):
    customer_id: str = Field(..., min_length=1)
    items: list[OrderItemSchema] = Field(..., min_length=1)
    priority: str = Field(default="medium", pattern=r"^(low|medium|high|urgent)$")
    notes: str = Field(default="", max_length=2000)


class OrderResponse(BaseModel):
    id: str
    order_no: str
    status: str
    customer_id: str
    items: list[dict]
    total_amount: str
    priority: str
    notes: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    total: int
    page: int
    page_size: int


class OrderStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(confirmed|processing|picking|completed|cancelled)$")


class OrderHistoryResponse(BaseModel):
    id: str
    order_id: str
    from_status: str
    to_status: str
    operator: str
    remark: str
    created_at: str
