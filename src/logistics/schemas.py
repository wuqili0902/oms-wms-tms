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
    # Where the tracking number came from: "kdniao" = the carrier issued it,
    # "local_placeholder" = we printed a number the carrier has never seen.  The
    # label is printed either way, so the operator has to be able to tell.
    tracking_source: str | None = None
    tracking_source_note: str | None = None


class WaybillListResponse(BaseModel):
    items: list[WaybillResponse]
    total: int


class TrackingInfoResponse(BaseModel):
    carrier: str
    tracking_number: str
    status: str
    status_detail: str
    estimated_delivery: str
    events: list[dict[str, Any]]
    # "kdniao" / "carrier_api" = the carrier answered; "mock" = demo data.  Every
    # caller that shows a delivery state shows this too, because the demo
    # generator's status is picked from a hash of the waybill number.
    source: str | None = None
    source_note: str | None = None


class PrintWaybillResponse(BaseModel):
    print_callback_url: str
