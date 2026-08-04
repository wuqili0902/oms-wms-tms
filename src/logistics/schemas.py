from typing import Any

from pydantic import BaseModel


class CreateWaybillRequest(BaseModel):
    order_id: str
    recipient_name: str
    recipient_phone: str
    recipient_address: str
    items: list[dict[str, Any]]
    carrier_code: str = "zto"


class WaybillResponse(BaseModel):
    id: str
    tracking_number: str
    order_id: str
    carrier_code: str
    carrier_name: str
    recipient_name: str
    recipient_phone: str
    recipient_address: str
    items: list[dict[str, Any]]
    status: str
    print_count: int
    last_printed_at: str | None = None
    label_url: str | None = None
    created_at: str
    updated_at: str | None = None


class WaybillListResponse(BaseModel):
    items: list[WaybillResponse]
    total: int
