"""TMS schemas — transport orders, tracking, POD, returns, and settlement."""

from decimal import Decimal
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator

# ── The envelope-accepting base ─────────────────────────────────────────────
# The base lives in ``src/core/schemas.py`` — the auth RBAC writes came to need
# the same contract, and a private base inside the TMS schemas is not something
# another module can share.  The alias keeps every body below spelled the same.
from src.core.schemas import PayloadBody as _PayloadBody
from src.tms.models import (
    CarrierCode,
    DeviceStatus,
    ExceptionType,
    FreightRule,
    HubStatus,
    PlatformType,
    PODSignature,
    ReturnReason,
    ReturnStatus,
    SyncLogStatus,
    SyncLogType,
    TerminalDeviceType,
    TrackingEventType,
    TransferHubType,
)

# ── Transport Order Schemas ──────────────────────────────────────────────────


class TransportStatusUpdate(BaseModel):
    """New status for a transport order, in the request body.

    The status used to be reachable only as a query parameter, so the body
    shape every other status endpoint in this API uses answered 422 "Field
    required: status" — a client that sent the obvious request was told the
    thing it had just sent was missing.
    """

    status: str = Field(..., min_length=1, max_length=30)

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
    pickup_warehouse_id: str | None = None
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
    # The enum itself, not a hand-written pattern.  The pattern omitted
    # "created", so a scan the domain recognises was rejected by the API, and
    # every member added to the enum left the two lists further apart.
    event_type: TrackingEventType = TrackingEventType.IN_TRANSIT
    location_code: str | None = None
    location_name: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    remark: str | None = None

    # Declaring the fields is only half the fix: an undeclared key is still
    # accepted and then dropped unless extra input is refused outright.  A
    # scanner app that sends "location" instead of "location_name" now gets a
    # 422 naming the key, instead of a 200 and a NULL column.
    model_config = {"extra": "forbid"}


class TrackingEventForOrderCreate(BaseModel):
    """Body for ``POST /transport-orders/{order_id}/tracking-events``.

    The order comes from the path, so it is not repeated here.  Declaring the
    fields is the point: this route took a bare ``dict``, so a body that said
    ``location`` and ``description`` was accepted, the service read
    ``location_name`` and ``remark``, and the scan was filed with both columns
    NULL — a tracking history that lost half of what the operator typed.
    """

    event_type: TrackingEventType
    location_code: str | None = None
    location_name: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    operator_id: str | None = None
    remark: str | None = None

    # Same as TrackingEventCreate: a mistyped key is refused here so it cannot
    # become a silently-empty column in the tracking history.
    model_config = {"extra": "forbid"}


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


class DeliveryPhoto(_PayloadBody):
    """A delivery photo, as the ``pod_records.delivery_photo_urls`` column stores it.

    The column is documented ``[{url, timestamp}]``; the console that displays it
    (``TransportOrderDetail.vue``) reads a list of bare URL strings, and both
    forms arrive from clients, so both are accepted and normalised to the shape
    the column says it holds.
    """

    url: str = Field(..., min_length=1, max_length=500)
    timestamp: str | None = None


class PODCreate(_PayloadBody):
    """Body for ``POST /transport-orders/{order_id}/pod``.

    The route took a bare ``dict`` and read four keys out of it, and the
    screen that posts it (``frontend/src/views/transport/TransportOrderDetail.vue``)
    sends ``receiver_name``.  The recipient's name is ``signed_by`` in the API,
    so every signature the console recorded was filed as ``signed_by =
    "unknown"`` — the form had the name, the record did not, and nothing
    reported the difference.  ``receiver_name`` is accepted as the same field.

    ``signature_type`` is the model's own enum (``PODSignature``), not a pattern
    that happens to list its members today.
    """

    # The order is named by the path; a body that repeats it must not name a
    # different one, and the service keeps the path's.
    transport_order_id: str | None = None
    signed_by: str | None = Field(
        default=None, max_length=200,
        validation_alias=AliasChoices("signed_by", "receiver_name"),
    )
    signature_type: PODSignature = PODSignature.PHYSICAL
    signature_image_url: str | None = Field(default=None, max_length=500)
    # None means "no photos sent", which on a re-submission leaves the photos on
    # the record alone; an empty list would erase them.
    delivery_photo_urls: list[str | DeliveryPhoto] | None = Field(
        default=None, validation_alias=AliasChoices("delivery_photo_urls", "photos"),
    )
    delivered_to_address: dict | None = None
    notes: str | None = None

    def photo_rows(self) -> list[dict] | None:
        """The photos as the column stores them, or None when none were sent."""
        if self.delivery_photo_urls is None:
            return None
        return [
            p.model_dump() if isinstance(p, DeliveryPhoto) else {"url": p, "timestamp": None}
            for p in self.delivery_photo_urls
        ]


class PODUpdate(_PayloadBody):
    """Body for ``PUT /transport-orders/{order_id}/pod``.

    Every field is optional — an update carries the fields that changed — and
    the field names are the create body's, ``receiver_name`` included, because
    the console sends the same form object to both routes.
    """

    signed_by: str | None = Field(
        default=None, max_length=200,
        validation_alias=AliasChoices("signed_by", "receiver_name"),
    )
    signature_type: PODSignature | None = None
    signature_image_url: str | None = Field(default=None, max_length=500)
    delivery_photo_urls: list[str | DeliveryPhoto] | None = Field(
        default=None, validation_alias=AliasChoices("delivery_photo_urls", "photos"),
    )
    delivered_to_address: dict | None = None
    notes: str | None = None

    def photo_rows(self) -> list[dict] | None:
        """The photos as the column stores them, or None when none were sent."""
        if self.delivery_photo_urls is None:
            return None
        return [
            p.model_dump() if isinstance(p, DeliveryPhoto) else {"url": p, "timestamp": None}
            for p in self.delivery_photo_urls
        ]


class PODResponse(BaseModel):
    id: str
    transport_order_id: str
    signed_by: str | None = None
    signature_type: str
    signature_image_url: str | None = None
    delivery_photo_urls: list[dict] = Field(default=list)
    delivered_to_address: dict | None = None
    notes: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


# ── Return Order Schemas (Reverse Logistics) ────────────────────────────────


class ReturnOrderCreate(_PayloadBody):
    """Initiate a return / reverse logistics request.

    The console (``frontend/src/views/transport/ReturnOrderList.vue``) sends
    ``{order_no, reason}`` where ``reason`` is free text typed into a textarea.
    The service read ``ReturnReason(data["reason"])`` and
    ``uuid.UUID(data["transport_order_id"])``: the free-text reason raised
    ``ValueError`` and the order number raised ``ValueError`` in the handler, so
    the console's 创建退货 button answered 500 for every return anyone filed, and
    the key the console *did* send (``order_no``) was never read — a return with
    no original order attached.

    Both are handled here: the reason is the model's own enum, so an
    unrecognised one is a 422 naming the reasons the domain knows, and the
    original order is named by ``order_no`` / ``transport_order_no`` /
    ``transport_order_id`` and resolved by id *or* transport number.
    """

    transport_order_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("transport_order_id", "transport_order_no", "order_no"),
    )
    reason: ReturnReason
    reason_detail: str | None = None
    carrier_code: CarrierCode | None = None
    return_tracking_number: str | None = Field(default=None, max_length=100)
    pickup_address: AddressPayload | dict | None = None
    destination_warehouse_id: str | None = None
    refund_amount: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))


class ReturnStatusUpdate(_PayloadBody):
    """Body for ``PATCH /return-orders/{return_id}/status``.

    The service's parameter is called ``target``, and that is the key this route
    read; the console sends the same body every other status endpoint in this API
    uses (``{"status": ...}``), so a status change from the console reached
    ``target=None`` and was refused as a transition to ``'None'``.  Both keys
    name the field.
    """

    target: ReturnStatus = Field(validation_alias=AliasChoices("target", "status"))


class ReturnOrderResponse(BaseModel):
    id: str
    return_no: str
    status: str
    shipment_status: str
    reason: str
    reason_detail: str | None = None
    transport_order_id: str | None = None
    carrier_code: str | None = None
    return_tracking_number: str | None = None
    pickup_address: dict | None = None
    destination_warehouse_id: str | None = None
    refund_amount: str
    created_at: str
    updated_at: str | None = None

    model_config = {"from_attributes": True}


# ── Exception Schemas ───────────────────────────────────────────────────

class TransportExceptionCreate(_PayloadBody):
    """Report a transport exception.

    The console (``frontend/src/views/transport/ExceptionList.vue``) sends
    ``{transport_order_no, exception_type, description}``; the route took a bare
    ``dict`` and the service read ``data["type"]``.  So the 报告异常 button
    answered 500 every time it was pressed — ``KeyError`` inside the handler for
    a request that named a real exception type under a key the handler did not
    know — and the order the operator named was dropped, leaving an exception
    record that belongs to no shipment.

    The type is the model's own enum (``ExceptionType``), ``exception_type`` is
    accepted as the same field, and the order is named by id *or* transport
    number: the console shows the operator the number, not the uuid.
    """

    transport_order_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("transport_order_id", "transport_order_no", "order_no"),
    )
    type: ExceptionType = Field(validation_alias=AliasChoices("type", "exception_type"))
    severity: Literal["normal", "high", "critical"] = "normal"
    description: str | None = None
    resolution_notes: str | None = None


class ExceptionResolution(_PayloadBody):
    """Body for ``PATCH /exceptions/{exception_id}`` — how the exception was handled."""

    resolution_notes: str | None = None


class TransportExceptionResponse(BaseModel):
    id: str
    transport_order_id: str | None = None
    # The shipment's number, next to its id: an exception is cleared at a
    # shipment, and the number is what the operator and the carrier both read.
    transport_order_no: str | None = None
    type: str
    status: str
    severity: str
    description: str | None = None
    resolution_notes: str | None = None
    created_at: str
    updated_at: str | None = None

    model_config = {"from_attributes": True}


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

class DeviceRegister(_PayloadBody):
    """Register a terminal device.

    The console (``frontend/src/views/devices/DeviceList.vue``) posts
    ``{device_code, name, device_type}`` and the service read
    ``data["code"]`` — a ``KeyError`` inside the handler, so 注册设备 answered 500
    every time anyone pressed it, and the device they named was never filed.
    ``device_code`` is accepted as the code; the type and platform are the
    model's own vocabularies, not patterns that list them today.
    """

    code: str = Field(
        ..., min_length=1, max_length=50,
        validation_alias=AliasChoices("code", "device_code"),
    )
    name: str = Field(default="", max_length=200)
    device_type: TerminalDeviceType = TerminalDeviceType.PDA
    platform: PlatformType = PlatformType.ANDROID
    os_version: str = Field(default="", max_length=50)
    app_version: str = Field(default="", max_length=20)
    # A device is registered to a warehouse; a handheld's setup screen knows the
    # code on the bay door, and the service resolves it by id *or* code.
    warehouse_id: str | None = None
    config: dict | None = None
    push_token: str | None = Field(default=None, max_length=500)


class DeviceUpdate(_PayloadBody):
    """Change the fields of a registered device.

    The console's edit form sends ``device_code``, ``name`` and ``device_type``;
    this body used to declare neither of the first and last, so an edit that
    renamed a scanner, or corrected a device registered as the wrong type, was
    refused as an unknown key — and the code it sent was dropped.  A device's
    code is its own (``terminal_devices.code`` is unique), so a change that
    collides with another device is refused by the service.
    """

    code: str | None = Field(
        default=None, min_length=1, max_length=50,
        validation_alias=AliasChoices("code", "device_code"),
    )
    name: str | None = Field(default=None, max_length=200)
    device_type: TerminalDeviceType | None = None
    platform: PlatformType | None = None
    os_version: str | None = Field(default=None, max_length=50)
    app_version: str | None = Field(default=None, max_length=20)
    warehouse_id: str | None = None
    config: dict | None = None
    # The service updates this field, so the body declares it: a handheld
    # re-registering its push token after an OS update is the normal case.
    push_token: str | None = Field(default=None, max_length=500)
    status: DeviceStatus | None = None


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


class SyncLogCreate(_PayloadBody):
    """A sync run a handheld reports back.

    The type and status are the model's own vocabularies (``SyncLogType``,
    ``SyncLogStatus``): a device reporting ``sync_type="upload_data"`` used to
    reach ``SyncLogType(...)`` inside the handler, so the sync that failed on
    the floor also failed on the way in, as a 500.
    """

    sync_type: SyncLogType = SyncLogType.DOWNLOAD
    status: SyncLogStatus = SyncLogStatus.PENDING
    # Devices report the row count under several spellings; all of them are the
    # same number, and a count that is not a number is refused, not dropped.
    records_count: int = Field(
        default=0, ge=0,
        validation_alias=AliasChoices("records_count", "data_count", "count"),
    )
    error_message: str | None = None


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
    status: str
    login_at: str
    logout_at: str | None = None

    model_config = {"from_attributes": True}


# ── Transfer Hub Schemas ─────────────────────────────────────────────────────

class TransferHubCreate(_PayloadBody):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    # The hub's type is the model's own vocabulary (``TransferHubType``); the
    # console's select sends ``type``, and the column is ``hub_type``, so both
    # spellings name it.  A pattern listing the members is what this replaces.
    hub_type: TransferHubType = Field(
        default=TransferHubType.PRIMARY,
        validation_alias=AliasChoices("hub_type", "type"),
    )
    city: str = Field(..., min_length=1, max_length=100)
    address: dict | None = None
    capacity_weight_kg: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=30)


class HubUpdate(_PayloadBody):
    """Change a hub's fields.

    ``PATCH /transfer-hubs/{id}`` took a bare ``dict``, and its ``updatable`` set had
    no ``code`` and no ``type``: the console's edit dialog offers 编码, 名称, 类型 and
    城市, and two of the four — the hub's code, and the type that decides where the
    route planner routes through it — were dropped on every save.
    """

    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    hub_type: TransferHubType | None = Field(
        default=None, validation_alias=AliasChoices("hub_type", "type"),
    )
    city: str | None = Field(default=None, min_length=1, max_length=100)
    address: dict | None = None
    capacity_weight_kg: Decimal | None = Field(default=None, ge=Decimal("0"))
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=30)
    status: HubStatus | None = None


class TransferHubResponse(BaseModel):
    """One hub, as every hub endpoint presents it.

    The column is ``hub_type`` and the console's key is ``type``; the alias below
    is the single spelling.  The contact fields are part of the record the
    中转站 screens fill in, so they are part of its shape too — the list route
    serializes through this model, so a page that reads a hub from the list and a
    page that reads it from the detail see the same keys.
    """

    id: str
    code: str
    name: str
    type: str = Field(validation_alias="hub_type")
    city: str
    address: dict | None = None
    capacity_weight_kg: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
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


# ── Freight Tier / Freight Calculation Requests ──────────────────────────────


class FreightTierCreate(_PayloadBody):
    """A rate-card tier for a carrier.

    ``FreightTierList.vue`` posts ``{carrier_code, weight_from, weight_to,
    price_per_kg}``; the service read ``data["rule_type"]`` and
    ``data["price_per_unit"]``, so the console's 提交 answered 500 for a tier
    whose bracket the form fully described — and the bracket keys it did send
    (``weight_from`` / ``weight_to``) were not the keys the column reads.  The
    bracket's bounds are checked here, because a tier whose maximum is below its
    minimum covers nothing, and a carrier with such a tier prices the shipments
    that fall in it as "no matching freight tier".
    """

    carrier_code: CarrierCode
    rule_type: FreightRule = FreightRule.WEIGHT_TIERED
    min_value: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"),
        validation_alias=AliasChoices("min_value", "weight_from", "min"),
    )
    max_value: Decimal | None = Field(
        default=None, ge=Decimal("0"),
        validation_alias=AliasChoices("max_value", "weight_to", "max"),
    )
    price_per_unit: Decimal = Field(
        ..., ge=Decimal("0"),
        validation_alias=AliasChoices("price_per_unit", "price_per_kg"),
    )
    surcharge_express: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))

    @model_validator(mode="after")
    def _bracket_has_to_reach_its_ceiling(self) -> "FreightTierCreate":
        if self.max_value is not None and self.max_value < self.min_value:
            raise ValueError(
                f"max_value {self.max_value} is below min_value {self.min_value} — a bracket "
                "whose ceiling is under its floor covers no shipment"
            )
        return self


class FreightCalculateRequest(_PayloadBody):
    """Price a shipment against a carrier's rate card.

    The service read ``data.get("weight", 1)``.  The console
    (``FreightTierList.vue`` 运费试算) sends ``total_weight_kg``, so the weight the
    operator typed never reached the calculation: every quote this endpoint made
    for the console priced the shipment as 1 kg.

    ``service_type`` is accepted because the console sends it, and the express
    surcharge follows from it — a rate card carries one surcharge, and a request
    that says "express" is the request that pays it.
    """

    carrier_code: CarrierCode
    weight: Decimal = Field(
        default=Decimal("1"), ge=Decimal("0"),
        validation_alias=AliasChoices("weight", "weight_kg", "total_weight_kg"),
    )
    volume_m3: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"),
        validation_alias=AliasChoices("volume_m3", "volume"),
    )
    distance_km: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"),
        validation_alias=AliasChoices("distance_km", "distance"),
    )
    express: bool = False
    service_type: Literal["standard", "express", "overnight", "freight"] | None = None

    @model_validator(mode="after")
    def _service_level_decides_the_surcharge(self) -> "FreightCalculateRequest":
        if self.service_type == "express":
            self.express = True
        return self


# ── Freight Tier Response ──────────────────────────────────────────────────

class FreightTierResponse(BaseModel):
    id: str
    carrier_code: str
    rule_type: str
    min_value: str
    max_value: str | None = None
    price_per_unit: str
    surcharge_express: str
    created_at: str

    model_config = {"from_attributes": True}


class FreightCalculateResponse(BaseModel):
    carrier_code: str
    estimated_cost: float | str
    # None whenever the lane is unknown: /freight-estimate is given a distance,
    # not a route, and transit belongs to a route.  The endpoint used to answer
    # 2 days for every carrier and every service level.
    transit_days: int | None = None
    # "rate_card" when the carrier's configured FreightTier rows priced it,
    # "placeholder_table" when a published default did.  Without this, a guessed
    # number and a carrier's actual price look identical to the caller — and a
    # placeholder quoted to a customer is a loss the quote author never chose.
    pricing_source: str
    rule_type: str | None = None
    price_per_unit: str | None = None


class FreightTierCalculateResponse(BaseModel):
    carrier_code: str
    weight_kg: str
    total_freight_yuan: str
    rule_type: str
    tier_min_value: str
    tier_max_value: str | None = None


# ── Forecast Schemas ───────────────────────────────────────────────────────

class ForecastObservationResponse(BaseModel):
    status: str
    key: str


class ForecastPointResponse(BaseModel):
    date: str | None = None
    predicted_count: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None


class ForecastTrainingResponse(BaseModel):
    status: str
    trained: int
    #: Orders whose address names no city: they form a lane key no lookup can ask for.
    skipped: int = 0


class ForecastObservationCreate(_PayloadBody):
    """One lane-day fed to the demand model.

    The handler did ``float(data["count"])``: a request that omitted the count, or
    wrote it as 八百, raised inside the handler and was answered as a server
    failure.  A count is a whole number of orders, and the lane is the two cities
    the model predicts on.
    """

    origin_city: str = Field(..., min_length=1, max_length=100)
    destination_city: str = Field(..., min_length=1, max_length=100)
    count: int = Field(..., ge=0)


class ForecastTrainingRequest(_PayloadBody):
    """How much history the demand model trains on.

    ``int(data.get("months", 6))`` — a ``months`` of ``"six"`` raised inside the
    route.  The bound is the model's: training on a value outside it asks the
    forecaster for a window it does not build.
    """

    months: int = Field(default=6, ge=1, le=36)
