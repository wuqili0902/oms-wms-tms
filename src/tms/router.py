"""TMS API router — transport order management, tracking, POD, returns, exceptions."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.exceptions import NotFoundException, ValidationException
from src.tms import service as tms_service
from src.tms.schemas import (
    CarrierRouteCreate,
    CarrierRouteResponse,
    DeviceRegister,
    DeviceResponse,
    DeviceUpdate,
    ExceptionResolution,
    ForecastObservationCreate,
    ForecastObservationResponse,
    ForecastTrainingRequest,
    ForecastTrainingResponse,
    FreightCalculateRequest,
    FreightCalculateResponse,
    FreightTierCalculateResponse,
    FreightTierCreate,
    FreightTierResponse,
    HeartbeatResponse,
    HubConnectionCreate,
    HubConnectionResponse,
    HubUpdate,
    PODCreate,
    PODResponse,
    PODUpdate,
    ReturnOrderCreate,
    ReturnOrderResponse,
    ReturnStatusUpdate,
    RoutePlanResponse,
    SessionResponse,
    SyncLogCreate,
    SyncLogResponse,
    TrackingEventCreate,
    TrackingEventForOrderCreate,
    TrackingEventResponse,
    TransferHubCreate,
    TransferHubResponse,
    TransportExceptionCreate,
    TransportExceptionResponse,
    TransportOrderCreate,
    TransportOrderListResponse,
    TransportOrderResponse,
    TransportSegmentCreate,
    TransportSegmentResponse,
    TransportStatusUpdate,
)

router = APIRouter(tags=["transport"], dependencies=[Depends(get_current_user)])


# ── Transport Order Endpoints ────────────────────────────────────────────────

@router.post("/transport-orders", response_model=TransportOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_transport_order(
    data: TransportOrderCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new transport order (draft)."""
    return await tms_service.create_transport_order(db, data.model_dump())


@router.get("/transport-orders/{order_id}", response_model=TransportOrderResponse)
async def get_transport_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get transport order details."""
    try:
        return await tms_service.get_transport_order(db, order_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/transport-orders", response_model=TransportOrderListResponse)
async def list_transport_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    carrier_code: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List transport orders with pagination and filters."""
    items, total = await tms_service.list_transport_orders(
        db, page=page, page_size=page_size, status=status, carrier_code=carrier_code,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.put("/transport-orders/{order_id}/status", response_model=TransportOrderResponse)
async def update_transport_order_status(
    order_id: str,
    data: TransportStatusUpdate | None = None,
    status_param: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
):
    """Change transport order status (with state machine validation).

    The status now travels in the body, which is what every other status
    endpoint here expects and what a client writes naturally; the query form is
    still read because the clients written before this fix send it there.
    """
    new_status = (data.status if data else None) or status_param
    if not new_status:
        raise ValidationException(
            message="status is required — send it in the request body as {\"status\": \"dispatched\"}"
        )
    return await tms_service.change_transport_status(db, order_id, new_status)


# ── Tracking Event Endpoints ────────────────────────────────────────────────

@router.post("/tracking-events", response_model=TrackingEventResponse, status_code=status.HTTP_201_CREATED)
async def record_tracking_event(
    data: TrackingEventCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a tracking scan event."""
    return await tms_service.create_tracking_event(db, data.model_dump())


@router.get("/transport-orders/{order_id}/tracking", response_model=list[TrackingEventResponse])
async def get_tracking_events(
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get all tracking events for a transport order."""
    return await tms_service.list_tracking_events(db, order_id)


# ── POD (Proof of Delivery) Endpoints ────────────────────────────────────────

@router.post("/transport-orders/{order_id}/pod", response_model=PODResponse, status_code=status.HTTP_201_CREATED)
async def create_pod(
    order_id: str,
    data: PODCreate,
    db: AsyncSession = Depends(get_db),
):
    """Record proof of delivery.

    The body is typed (``PODCreate``): the console sends the recipient's name as
    ``receiver_name``, and the record stored it as ``signed_by = "unknown"``.
    Re-sending the POD for an order that already has one updates that record —
    it used to be accepted with 201 and written nowhere.
    """
    payload = data.model_dump(mode="json")
    payload.pop("transport_order_id", None)  # the path names the order
    return await tms_service.create_pod(db, order_id, payload)


# ── Return Order Endpoints (Reverse Logistics) ───────────────────────────────

@router.post("/return-orders", response_model=ReturnOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_return_order(
    data: ReturnOrderCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a return / reverse logistics order.

    ``ReturnOrderCreate``: the reason is one of the reason codes the domain
    knows, and the shipment it refers to is named by id *or* transport number.
    Both were constructors on the raw body, so every return the console filed
    was a 500.
    """
    return await tms_service.create_return_order(db, data.model_dump(mode="json"))


# ── Exception Endpoints ──────────────────────────────────────────────────────

@router.post("/exceptions", response_model=TransportExceptionResponse, status_code=status.HTTP_201_CREATED)
async def create_exception(
    data: TransportExceptionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Report a transport exception.

    ``TransportExceptionCreate``: the console's key is ``exception_type``, and
    the handler read ``data["type"]`` — a KeyError, reported as a server failure,
    for every exception anyone reported.
    """
    return await tms_service.create_exception(db, data.model_dump(mode="json"))


@router.patch("/exceptions/{exception_id}/resolve", response_model=TransportExceptionResponse)
async def resolve_exception(
    exception_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Resolve a transport exception."""
    try:
        return await tms_service.resolve_exception(db, exception_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Freight Estimate Endpoint ────────────────────────────────────────────────

@router.post("/freight-estimate", response_model=FreightCalculateResponse)
async def estimate_freight(
    carrier_code: str = Query(...),
    service_type: str = Query(default="standard"),
    distance_km: float = Query(..., gt=0),
    weight_kg: float = Query(..., ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Estimate freight cost for a route.

    ``weight_kg`` used to be passed on as ``int(weight_kg)``: a 5.5 kg shipment
    was quoted 5 kg, which is a discount nobody chose.  The service prices from
    Decimal, so the fraction goes through intact.
    """
    return await tms_service.estimate_freight(
        db,
        carrier_code=carrier_code,
        service_type=service_type,
        distance_km=distance_km,
        weight_kg=weight_kg,
    )


# ── Legacy Device Endpoints (Terminal Management) ────────────────────────────

@router.post("/devices", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def register_device(
    data: DeviceRegister,
    db: AsyncSession = Depends(get_db),
):
    """Register a terminal device (legacy TMS).

    ``DeviceRegister``: the console's key is ``device_code``, and the service read
    ``data["code"]`` — a KeyError, reported as a server failure, for every device
    anyone registered from the console.
    """
    try:
        return await tms_service.register_device(db, data.model_dump(mode="json"))
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/devices/{dev_id}", response_model=DeviceResponse)
async def get_device(
    dev_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a terminal device."""
    try:
        return await tms_service.get_device(db, dev_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/devices/{dev_id}", response_model=DeviceResponse)
async def update_device(
    dev_id: str,
    data: DeviceUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update device fields — the code, type, platform, warehouse and status
    included, which are the fields the console edits."""
    try:
        return await tms_service.update_device(db, dev_id, data.model_dump(mode="json"))
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/devices/{dev_id}/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    dev_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Record device heartbeat."""
    try:
        return await tms_service.record_heartbeat(db, dev_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/devices", response_model=dict)
async def list_devices(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    warehouse_id: str | None = Query(None),
    status: str | None = Query(None),
    device_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List terminal devices with pagination.

    The paging keys are ``page``/``page_size``, as every other list in this API
    names them; ``skip``/``limit`` are read too, because the callers written
    before this use them.  A caller that sent ``page`` and ``page_size`` used to
    have them ignored, so the console's pager showed page one at every page.
    """
    if page_size is not None:
        limit = page_size
        skip = (page - 1) * page_size
    all_items = await tms_service.list_devices(db, warehouse_id=warehouse_id, status=status, device_type=device_type)
    total = len(all_items)
    items = all_items[skip : skip + limit]
    return {"items": items, "total": total, "page": page, "page_size": limit, "skip": skip, "limit": limit}


@router.post("/devices/{dev_id}/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    dev_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Create a device session."""
    try:
        return await tms_service.create_session(db, dev_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete(
    "/devices/{dev_id}/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def end_session(
    dev_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """End a device session."""
    try:
        await tms_service.end_session(db, dev_id, session_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/devices/{dev_id}/sessions", response_model=dict)
async def list_sessions(
    dev_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List sessions for a device with pagination."""
    try:
        all_items = await tms_service.list_sessions(db, dev_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    total = len(all_items)
    items = all_items[skip : skip + limit]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("/devices/{dev_id}/sync", response_model=SyncLogResponse, status_code=status.HTTP_201_CREATED)
async def record_sync(
    dev_id: str,
    data: SyncLogCreate,
    db: AsyncSession = Depends(get_db),
):
    """Record a sync operation.

    ``SyncLogCreate``: the sync type and status are the device domain's own
    vocabularies, so a handheld reporting ``upload_data`` is refused by name
    instead of failing inside the handler as a 500.
    """
    try:
        return await tms_service.record_sync(db, dev_id, data.model_dump(mode="json"))
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/devices/{dev_id}/sync", response_model=dict)
async def list_sync_logs(
    dev_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List sync logs for a device with pagination."""
    try:
        all_items = await tms_service.list_sync_logs(db, dev_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    total = len(all_items)
    items = all_items[skip : skip + limit]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


# ═══════════════════════════════════════════════════════════════════════════════
# ══  Phase C — Route Planning Endpoints (TransferHub / CarrierRoute / RoutePlan)
# ═══════════════════════════════════════════════════════════════════════════════

# ── TransferHub Endpoints ──────────────────────────────────────────────────────

@router.post("/transfer-hubs", response_model=TransferHubResponse, status_code=status.HTTP_201_CREATED)
async def create_hub(
    data: TransferHubCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new transfer hub.

    ``TransferHubCreate``: the hub's type is the model's vocabulary (the console's
    select sends ``type``), and the capacity, contact name and phone are fields the
    hub record carries and this body used to drop without a word.
    """
    try:
        return await tms_service.create_hub(db, data.model_dump(mode="json"))
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/transfer-hubs/{hub_id}", response_model=TransferHubResponse)
async def get_hub(
    hub_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a transfer hub by ID."""
    try:
        return await tms_service.get_hub(db, hub_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/transfer-hubs", response_model=dict)
async def list_hubs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    city: str | None = Query(None),
    hub_type: str | None = Query(None, alias="type"),
    db: AsyncSession = Depends(get_db),
):
    """List transfer hubs with optional city/type filters and pagination.

    The page is serialized through ``TransferHubResponse``: the service hands
    back the record's column names, so this list spoke ``hub_type`` while every
    other hub endpoint spoke ``type`` — the console's 类型 column read a key the
    list never sent, and a screen that opened a hub from the list saw a different
    shape than one that opened it by id.
    """
    all_items = [
        TransferHubResponse.model_validate(hub).model_dump(mode="json")
        for hub in await tms_service.list_hubs(db, city=city, hub_type=hub_type)
    ]
    total = len(all_items)
    items = all_items[skip : skip + limit]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.patch("/transfer-hubs/{hub_id}", response_model=TransferHubResponse)
async def update_hub(
    hub_id: str,
    data: HubUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update transfer hub fields.

    ``HubUpdate``: the body used to be a bare ``dict`` and the service's update set
    had no ``code`` and no ``type``, so the console's edit dialog — which offers the
    code, the name, the type and the city — saved two of the four fields it sent.
    """
    try:
        return await tms_service.update_hub(db, hub_id, data.model_dump(mode="json"))
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


# ── CarrierRoute Endpoints ────────────────────────────────────────────────────

@router.post("/carrier-routes", response_model=CarrierRouteResponse, status_code=status.HTTP_201_CREATED)
async def add_carrier_route(
    data: CarrierRouteCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a new carrier route with pricing."""
    return await tms_service.add_carrier_route(db, data.model_dump())


@router.get("/carrier-routes", response_model=dict)
async def list_carrier_routes(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    origin_city: str | None = Query(None),
    dest_city: str | None = Query(None),
    carrier_code: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List carrier routes with optional filters and pagination."""
    all_items = await tms_service.list_carrier_routes(
        db, origin_city=origin_city, dest_city=dest_city, carrier_code=carrier_code,
    )
    total = len(all_items)
    items = all_items[skip : skip + limit]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


# ── HubConnection Endpoints ──────────────────────────────────────────────────

@router.post("/hub-connections", response_model=HubConnectionResponse, status_code=status.HTTP_201_CREATED)
async def add_hub_connection(
    data: HubConnectionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a directed hub connection (graph edge)."""
    try:
        return await tms_service.add_hub_connection(db, data.model_dump())
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/hub-connections", response_model=dict)
async def list_hub_connections(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    hub_code: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List hub connections, optionally filtered by hub code, with pagination."""
    all_items = await tms_service.list_hub_connections(db, hub_code=hub_code)
    total = len(all_items)
    items = all_items[skip : skip + limit]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


# ── RoutePlan Endpoints ───────────────────────────────────────────────────────

@router.post(
    "/transport-orders/{order_id}/route-plans",
    response_model=RoutePlanResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_route_plan(
    order_id: str,
    plan_type: str = Query(default="auto_gen", alias="type"),
    db: AsyncSession = Depends(get_db),
):
    """Generate a route plan for a transport order (auto_gen or manual)."""
    try:
        return await tms_service.generate_route_plan(order_id, db, plan_type=plan_type)
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/route-plans/{plan_id}", response_model=RoutePlanResponse)
async def get_route_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a route plan by ID, including segments."""
    try:
        return await tms_service.get_route_plan(db, plan_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── TransportSegment Endpoints ────────────────────────────────────────────────

@router.post("/segments", response_model=TransportSegmentResponse, status_code=status.HTTP_201_CREATED)
async def create_segment(
    data: TransportSegmentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a transport segment."""
    return await tms_service.create_segment(db, data.model_dump())


@router.get("/segments/{seg_id}", response_model=TransportSegmentResponse)
async def get_segment(
    seg_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a transport segment by ID."""
    try:
        return await tms_service.get_segment(db, seg_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/segments", response_model=dict)
async def list_segments(
    transport_order_id: str = Query(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all segments for a transport order with pagination."""
    all_items = await tms_service.list_segments(db, transport_order_id)
    total = len(all_items)
    items = all_items[skip : skip + limit]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.patch("/segments/{seg_id}/status", response_model=TransportSegmentResponse)
async def update_segment_status(
    seg_id: str,
    status: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Update transport segment status (with state machine validation)."""
    try:
        return await tms_service.update_segment_status(db, seg_id, status)
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Phase B — Tracking Events & POD (Proof of Delivery)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/transport-orders/{order_id}/tracking-events", response_model=TrackingEventResponse)
async def create_tracking_event(
    order_id: str,
    data: TrackingEventForOrderCreate,
    db: AsyncSession = Depends(get_db),
):
    # A bare ``dict`` here accepted anything: an unknown event_type reached the
    # enum constructor and raised (a 500 for a typo), while a body that used the
    # carrier's own field names was accepted and then silently dropped.
    return await tms_service.create_tracking_event(
        db, {"transport_order_id": order_id, **data.model_dump()}
    )


@router.get("/transport-orders/{order_id}/tracking-events", response_model=dict)
async def list_tracking_events(
    order_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    all_items = await tms_service.list_tracking_events(db, transport_order_id=order_id)
    total = len(all_items)
    items = all_items[skip : skip + limit]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/transport-orders/{order_id}/pod", response_model=PODResponse)
async def get_pod(
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    pod = await tms_service.get_pod(db, transport_order_id=order_id)
    if not pod:
        raise HTTPException(status_code=404, detail="POD not found")
    return pod


@router.put("/transport-orders/{order_id}/pod", response_model=PODResponse)
async def update_pod(
    order_id: str,
    data: PODUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing POD — only the fields the body carries change."""
    try:
        return await tms_service.update_pod(
            db, transport_order_id=order_id, data=data.model_dump(mode="json"),
        )
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
# Return Order (Reverse Logistics)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/return-orders", response_model=dict)
async def list_return_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    status: str = Query(None),
):
    items, total = await tms_service.list_return_orders(db, status=status)
    paginated = items[skip : skip + limit]
    return {"items": paginated, "total": total, "skip": skip, "limit": limit}


@router.get("/return-orders/{return_id}", response_model=ReturnOrderResponse)
async def get_return_order(return_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await tms_service.get_return_order(db, return_id=return_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/return-orders/{return_id}/status", response_model=ReturnOrderResponse)
async def update_return_status(return_id: str, data: ReturnStatusUpdate, db: AsyncSession = Depends(get_db)):
    """Move a return order along its lifecycle.

    The service's parameter is ``target`` and that is the only key this route
    used to read, so the ``{"status": ...}`` body the console sends reached
    ``target=None`` and was refused as a transition to ``'None'``.  The status is
    a return-status code (``ReturnStatus``), under either key.
    """
    try:
        return await tms_service.update_return_status(db, return_id=return_id, target=data.target)
    except (NotFoundException, ValidationException) as e:
        raise HTTPException(status_code=404 if isinstance(e, NotFoundException) else 422, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
# Transport Exception / Incident
# ═══════════════════════════════════════════════════════════════════════

@router.post("/transport-orders/{order_id}/exceptions", response_model=TransportExceptionResponse,
             status_code=status.HTTP_201_CREATED)
async def create_order_exception(order_id: str, data: TransportExceptionCreate, db: AsyncSession = Depends(get_db)):
    """Report an exception on the shipment named in the path."""
    payload = data.model_dump(mode="json")
    payload["transport_order_id"] = order_id  # the path names the order
    try:
        return await tms_service.create_exception(db, payload)
    except (NotFoundException, ValidationException) as e:
        raise HTTPException(status_code=404 if isinstance(e, NotFoundException) else 422, detail=str(e))


@router.get("/exceptions", response_model=dict)
async def list_exceptions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    transport_order_id: str = Query(None),
    status: str = Query("open"),
):
    all_items = await tms_service.list_exceptions(db, transport_order_id=transport_order_id, status=status)
    total = len(all_items)
    items = all_items[skip : skip + limit]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/exceptions/{exc_id}", response_model=TransportExceptionResponse)
async def get_exception(exc_id: str, db: AsyncSession = Depends(get_db)):
    """One exception, as recorded — including how it was resolved."""
    try:
        return await tms_service.get_exception(db, exc_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/exceptions/{exc_id}", response_model=TransportExceptionResponse)
async def resolve_exc(exc_id: str, data: ExceptionResolution, db: AsyncSession = Depends(get_db)):
    """Resolve a transport exception, recording how it was handled."""
    try:
        return await tms_service.resolve_exception(
            db, exc_id=exc_id, resolution_notes=data.resolution_notes)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
# FreightTier (Shipping Cost Calculation)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/freight-tiers", response_model=FreightTierResponse, status_code=status.HTTP_201_CREATED)
async def create_freight_tier(data: FreightTierCreate, db: AsyncSession = Depends(get_db)):
    """Add a bracket to a carrier's rate card.

    ``FreightTierCreate``: the screen's keys (``weight_from``, ``weight_to``,
    ``price_per_kg``) name the bracket's bounds and price, the rule defaults to
    the one those fields measure, and a bracket whose ceiling is below its floor
    is refused before it can silence the carrier that holds it.
    """
    return await tms_service.create_freight_tier(db, data.model_dump(mode="json"))


@router.post("/freight/calculate", response_model=FreightTierCalculateResponse)
async def calculate_freight(data: FreightCalculateRequest, db: AsyncSession = Depends(get_db)):
    """Price a shipment against a carrier's rate card.

    The weight the console types is ``total_weight_kg``; the calculation read
    ``data.get("weight", 1)``, so every quote from that screen priced a shipment
    as 1 kg.
    """
    try:
        return await tms_service.calculate_freight(db, data.model_dump(mode="json"))
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
# ML Forecast (Demand Prediction)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/forecast/observations", response_model=ForecastObservationResponse)
async def record_forecast_observation(data: ForecastObservationCreate, db: AsyncSession = Depends(get_db)):
    """Record one lane-day of order counts.

    ``ForecastObservationCreate``: the route did ``float(data["count"])``, so a
    request without the count, or with the count written as text, raised inside the
    handler and was reported as a server failure.
    """
    return await tms_service.record_forecast_observation(db, data.model_dump(mode="json"))


@router.get("/forecast", response_model=dict)
async def get_forecast(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    origin_city: str = Query(None),
    destination_city: str = Query(None),
    days: int = Query(7, ge=1, le=30),
):
    all_items = await tms_service.get_forecast(
        db=db,
        data={
            "origin_city": origin_city or "",
            "destination_city": destination_city or "",
            "days": days,
        },
    )
    total = len(all_items)
    items = all_items[skip : skip + limit]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("/forecast/training", response_model=ForecastTrainingResponse)
async def train_forecast(
    data: ForecastTrainingRequest,
    db: AsyncSession = Depends(get_db),
):
    """Train forecast model from historical transport orders.

    ``ForecastTrainingRequest``: ``int(data.get("months", 6))`` raised on a
    ``months`` that was not a number, and accepted 600, which the forecaster has no
    window for.
    """
    return await tms_service.train_forecast(db, months=data.months)
