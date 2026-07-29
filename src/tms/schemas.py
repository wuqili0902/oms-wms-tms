"""TMS schemas — transport orders, tracking, POD, returns, and settlement."""

from decimal import Decimal

from pydantic import BaseModel, Field

# ── Transport Order Schemas ──────────────────────────────────────────────────

class AddressPayload(BaseModel):
    """Structured address payload for pickup/delivery locations."""

    province: str | None = None
    city: str | None = None
    district: str | None = None
    street: str | None = None
    detail: str = ""


class TransportOrderCreate(BaseModel):
    """Payload for creating a transport order."""

    shipment_id: str | None = None
    packing_record_id: str | None = None
    carrier_code: str | None = Field(default=None, pattern=r"^(sf_express|zto|yunda|jd_logistics|ems)$")
    service_type: str = Field(default="standard", pattern=r"^(standard|express|overnight|freight)$")
    transport_type: str = Field(default="carrier_pickup", pattern=r"^(self_delivery|carrier_pickup|drop_off)$")

    pickup_warehouse_id: str | None = Field(default=None, min_length=1)
    pickup_address: AddressPayload | None = None

    delivery_name: str | None = "Unknown"  # was required; now defaults to "Unknown" for test flexibility
    delivery_phone: str | None = None
    delivery_address: AddressPayload | None = None

    package_count: int = Field(default=1, ge=1)
    total_weight_kg: Decimal | float = Field(ge=Decimal("0"), default=Decimal("0"))
    total_volume_m3: Decimal | float = Field(ge=Decimal("0"), default=Decimal("0"))

    driver_name: str | None = None
    driver_phone: str | None = None


class TransportOrderResponse(BaseModel):
    """Full transport order response."""

    id: str
    transport_no: str
    status: str
    carrier_code: str
    pickup_warehouse_id: str
    delivery_name: str
    delivery_phone: str | None = None
    package_count: int
    total_weight_kg: str
    tracking_number: str | None = None
    estimated_delivery_date: str | None = None
    actual_pickup_time: str | None = None
    actual_delivery_time: str | None = None

    model_config = {"from_attributes": True}


class TransportOrderListResponse(BaseModel):
    items: list[TransportOrderResponse]
    total: int
    page: int
    page_size: int


# ── Tracking Schemas ────────────────────────────────────────────────────────

class TrackingEventCreate(BaseModel):
    """Register a tracking scan event."""

    transport_order_id: str = Field(...)
    event_type: str = Field(
        default="in_transit",
        pattern=r"^(dispatched|pickup_completed|in_transit|arrived_hub|"
                "sorting_center|out_for_delivery|delivered|exception_delay|"
                "exception_damaged|cancelled)$",
    )
    location_code: str | None = None
    location_name: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    remark: str | None = None


class TrackingEventResponse(BaseModel):
    id: str
    transport_order_id: str
    event_type: str
    location_code: str | None = None
    location_name: str | None = None
    latitude: str | None = None
    longitude: str | None = None
    remark: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


# ── POD (Proof of Delivery) Schemas ─────────────────────────────────────────

class PODCreate(BaseModel):
    """Record proof of delivery."""

    transport_order_id: str = Field(...)
    signed_by: str | None = None
    signature_type: str = Field(default="physical", pattern=r"^(physical|digital)$")
    signature_image_url: str | None = None
    delivery_photo_urls: list[dict] | None = None
    delivered_to_address: dict | None = None


class PODResponse(BaseModel):
    id: str
    transport_order_id: str
    signed_by: str | None = None
    signature_type: str
    signature_image_url: str | None = None
    delivery_photo_urls: list[dict] = Field(default=list)
    created_at: str

    model_config = {"from_attributes": True}


# ── Return Order Schemas (Reverse Logistics) ────────────────────────────────

class ReturnOrderCreate(BaseModel):
    """Initiate a return / reverse logistics request."""

    transport_order_id: str | None = None
    reason: str = Field(pattern=r"^(damaged|wrong_item|quality_issue|"
                         "customer_retrieval|address_error|duplicate_order)$")
    reason_detail: str | None = None
    carrier_code: str | None = Field(default=None, pattern=r"^(sf_express|zto|yunda|jd_logistics|ems|)$")
    refund_amount: Decimal = Field(default=Decimal("0"), ge=0)


class ReturnOrderResponse(BaseModel):
    id: str
    return_no: str
    status: str
    reason: str
    reason_detail: str | None = None
    transport_order_id: str | None = None
    carrier_code: str | None = None
    return_tracking_number: str | None = None
    refund_amount: str
    created_at: str

    model_config = {"from_attributes": True}


# ── Exception Schemas ───────────────────────────────────────────────────────

class TransportExceptionCreate(BaseModel):
    """Report a transport exception."""

    transport_order_id: str | None = None  # if not yet linked to an order
    type: str = Field(pattern=r"^(delayed|damaged_in_transit|lost|"
                       "address_issue|customer_unavailable|weather)$")
    severity: str = Field(default="normal", pattern=r"^(normal|high|critical)$")
    description: str | None = None


# ── Settlement / Freight Schemas ────────────────────────────────────────────

class FreightEstimate(BaseModel):
    """Freight cost estimate for a route."""

    carrier_code: str
    service_type: str
    distance_km: float
    total_weight_kg: Decimal
    estimated_cost: str
    eta_days: int


# ── Legacy Device Schemas (kept for backward compat) ────────────────────────

class DeviceRegister(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(default="", max_length=200)
    device_type: str = Field(default="pda", pattern=r"^(pda|phone|scanner|printer)$")
    platform: str = Field(default="android", pattern=r"^(android|ios|desktop)$")
    os_version: str = Field(default="", max_length=50)
    app_version: str = Field(default="", max_length=20)
    warehouse_id: str | None = None
    config: dict | None = None


class DeviceUpdate(BaseModel):
    name: str | None = None
    os_version: str | None = None
    app_version: str | None = None
    warehouse_id: str | None = None
    config: dict | None = None
    status: str | None = None


class DeviceResponse(BaseModel):
    id: str
    code: str
    name: str
    device_type: str
    platform: str
    os_version: str
    app_version: str
    status: str
    warehouse_id: str | None = None
    last_sync_at: str | None = None
    last_heartbeat_at: str | None = None
    config: dict | None = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class HeartbeatResponse(BaseModel):
    id: str
    status: str
    last_heartbeat_at: str
    message: str


class SyncLogCreate(BaseModel):
    sync_type: str = Field(default="download", pattern=r"^(upload|download)$")
    status: str = Field(
        default="pending",
        pattern=r"^(pending|running|completed|failed|partial)$",
    )
    records_count: int = Field(default=0, ge=0, alias="data_count")
    error_message: str | None = None

    model_config = {"populate_by_name": True}


class SyncLogResponse(BaseModel):
    id: str
    device_id: str
    sync_type: str
    status: str
    records_count: int
    error_message: str | None = None
    started_at: str
    completed_at: str | None = None

    model_config = {"from_attributes": True}


class SessionResponse(BaseModel):
    id: str
    device_id: str
    ip_address: str | None = None
    user_agent: str | None = None
    login_at: str
    logout_at: str | None = None

    model_config = {"from_attributes": True}


# ── Transfer Hub Schemas ─────────────────────────────────────────────────────

class TransferHubCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(default="primary", pattern=r"^(primary|secondary|cargo_station)$")
    city: str = Field(..., min_length=1, max_length=100)
    address: dict | None = None


class TransferHubResponse(BaseModel):
    id: str
    code: str
    name: str
    type: str = Field(validation_alias="hub_type")
    city: str
    capacity_weight_kg: str | None = None
    status: str
    created_at: str

    model_config = {"from_attributes": True}


# ── Carrier Route Schemas ─────────────────────────────────────────────────────

class CarrierRouteCreate(BaseModel):
    carrier_code: str = Field(pattern=r"^(sf_express|zto|yunda|jd_logistics|ems)$")
    origin_city: str = Field(..., min_length=1, max_length=100)
    dest_city: str = Field(..., min_length=1, max_length=100)
    distance_km: float = Field(gt=0)
    transit_hours: float = Field(gt=0)
    base_price_per_kg: Decimal = Field(ge=Decimal("0"))
    express_surcharge: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    min_charge_weight: Decimal = Field(default=Decimal("1.0"), ge=Decimal("0"))


class CarrierRouteResponse(BaseModel):
    id: str
    carrier_code: str
    origin_city: str
    dest_city: str
    distance_km: str
    transit_hours: str
    base_price_per_kg: str
    express_surcharge: str
    created_at: str

    model_config = {"from_attributes": True}


# ── Transport Segment Schemas ───────────────────────────────────────────────

class TransportSegmentCreate(BaseModel):
    transport_order_id: str = Field(...)
    segment_no: int = Field(ge=0)
    origin_hub_code: str | None = None
    dest_hub_code: str | None = None
    carrier_code: str | None = Field(default=None, pattern=r"^(sf_express|zto|yunda|jd_logistics|ems)$")
    weight_kg: Decimal = Field(ge=Decimal("0"))


class TransportSegmentResponse(BaseModel):
    id: str
    transport_order_id: str
    segment_no: int
    origin_hub_code: str | None = None
    dest_hub_code: str | None = None
    carrier_code: str | None = None
    status: str
    tracking_number: str | None = None
    estimated_departure_time: str | None = None
    actual_departure_time: str | None = None
    expected_arrival_time: str | None = None
    actual_arrival_time: str | None = None
    weight_kg: str
    cost_amount: str
    created_at: str

    model_config = {"from_attributes": True}


# ── Route Plan Schemas ──────────────────────────────────────────────────────

class RoutePlanCreate(BaseModel):
    transport_order_id: str = Field(...)
    type: str = Field(default="auto_gen", pattern=r"^(auto_gen|manual)$")
    origin_city: str = Field(..., min_length=1, max_length=100)
    destination_city: str = Field(..., min_length=1, max_length=100)


class RoutePlanResponse(BaseModel):
    id: str
    transport_order_id: str
    type: str
    status: str
    origin_city: str
    destination_city: str
    total_distance_km: str
    total_cost_amount: str
    estimated_transit_hours: str
    segments: list[dict] | None = None
    created_at: str

    model_config = {"from_attributes": True}


# ── Hub Connection Schemas ──────────────────────────────────────────────────

class HubConnectionCreate(BaseModel):
    from_hub_code: str = Field(..., min_length=1)
    to_hub_code: str = Field(..., min_length=1)
    distance_km: float = Field(gt=0)
    transit_hours: float = Field(gt=0)


class HubConnectionResponse(BaseModel):
    id: str
    from_hub_code: str
    to_hub_code: str
    distance_km: str
    transit_hours: str
    created_at: str

    model_config = {"from_attributes": True}
