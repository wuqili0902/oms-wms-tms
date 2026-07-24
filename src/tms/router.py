"""TMS API router — transport order management, tracking, POD, returns, exceptions."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.exceptions import NotFoundException, ValidationException
from src.tms import service as tms_service
from src.tms.schemas import (
    TransportOrderCreate,
    TransportOrderResponse,
    TransportOrderListResponse,
    TrackingEventCreate,
    TrackingEventResponse,
    PODCreate,
    TransferHubCreate,
    TransferHubResponse,
    CarrierRouteCreate,
    CarrierRouteResponse,
    HubConnectionCreate,
    HubConnectionResponse,
    RoutePlanCreate,
    RoutePlanResponse,
    TransportSegmentCreate,
    TransportSegmentResponse,
)

router = APIRouter(tags=["transport"])


# ── Transport Order Endpoints ────────────────────────────────────────────────

@router.post("/transport-orders", response_model=TransportOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_transport_order(
    data: TransportOrderCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new transport order (draft)."""
    payload = data.model_dump()
    try:
        return await tms_service.create_transport_order(db, payload)
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/transport-orders/{order_id}", response_model=dict)
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


@router.put("/transport-orders/{order_id}/status", response_model=dict)
async def update_transport_order_status(
    order_id: str,
    status: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Change transport order status (with state machine validation)."""
    try:
        return await tms_service.change_transport_status(db, order_id, status)
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


# ── Tracking Event Endpoints ────────────────────────────────────────────────

@router.post("/tracking-events", response_model=TrackingEventResponse, status_code=status.HTTP_201_CREATED)
async def record_tracking_event(
    data: TrackingEventCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a tracking scan event."""
    try:
        return await tms_service.record_tracking_event(db, data.model_dump())
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/transport-orders/{order_id}/tracking", response_model=list[TrackingEventResponse])
async def get_tracking_events(
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get all tracking events for a transport order."""
    try:
        return await tms_service.get_tracking_events(db, order_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── POD (Proof of Delivery) Endpoints ────────────────────────────────────────

@router.post("/transport-orders/{order_id}/pod", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_pod(
    order_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Record proof of delivery."""
    try:
        return await tms_service.create_pod(db, order_id, data)
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


# ── Return Order Endpoints (Reverse Logistics) ───────────────────────────────

@router.post("/return-orders", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_return_order(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Create a return / reverse logistics order."""
    try:
        return await tms_service.create_return_order(db, data)
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


# ── Exception Endpoints ──────────────────────────────────────────────────────

@router.post("/exceptions", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_exception(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Report a transport exception."""
    try:
        return await tms_service.create_exception(db, data)
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.patch("/exceptions/{exception_id}/resolve", response_model=dict)
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

@router.post("/freight-estimate", response_model=dict)
async def estimate_freight(
    carrier_code: str = Query(...),
    service_type: str = Query(default="standard"),
    distance_km: float = Query(..., gt=0),
    weight_kg: float = Query(..., ge=0),
):
    """Estimate freight cost for a route."""
    return await tms_service.estimate_freight(
        carrier_code=carrier_code,
        service_type=service_type,
        distance_km=distance_km,
        weight_kg=int(weight_kg),
    )


# ── Legacy Device Endpoints (Terminal Management) ────────────────────────────

@router.post("/devices", response_model=dict, status_code=status.HTTP_201_CREATED)
async def register_device(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Register a terminal device (legacy TMS)."""
    try:
        return await tms_service.register_device(db, data)
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/devices/{dev_id}", response_model=dict)
async def get_device(
    dev_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get a terminal device."""
    try:
        return await tms_service.get_device(db, dev_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/devices/{dev_id}", response_model=dict)
async def update_device(
    dev_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Update device fields."""
    try:
        return await tms_service.update_device(db, dev_id, data)
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/devices/{dev_id}/heartbeat", response_model=dict)
async def heartbeat(
    dev_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Record device heartbeat."""
    try:
        return await tms_service.record_heartbeat(db, dev_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/devices", response_model=list[dict])
async def list_devices(
    warehouse_id: str | None = Query(None),
    status: str | None = Query(None),
    device_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List terminal devices."""
    return await tms_service.list_devices(db, warehouse_id=warehouse_id, status=status, device_type=device_type)


@router.post("/devices/{dev_id}/sessions", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_session(
    dev_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create a device session."""
    try:
        return await tms_service.create_session(db, dev_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/devices/{dev_id}/sessions/{session_id}", response_model=dict)
async def end_session(
    dev_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """End a device session."""
    try:
        return await tms_service.end_session(db, dev_id, session_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/devices/{dev_id}/sessions", response_model=list[dict])
async def list_sessions(
    dev_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List sessions for a device."""
    try:
        return await tms_service.list_sessions(db, dev_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/devices/{dev_id}/sync", response_model=dict, status_code=status.HTTP_201_CREATED)
async def record_sync(
    dev_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Record a sync operation."""
    try:
        return await tms_service.record_sync(db, dev_id, data)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/devices/{dev_id}/sync", response_model=list[dict])
async def list_sync_logs(
    dev_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List sync logs for a device."""
    try:
        return await tms_service.list_sync_logs(db, dev_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# ══  Phase C — Route Planning Endpoints (TransferHub / CarrierRoute / RoutePlan)
# ═══════════════════════════════════════════════════════════════════════════════

# ── TransferHub Endpoints ──────────────────────────────────────────────────────

@router.post("/transfer-hubs", response_model=TransferHubResponse, status_code=status.HTTP_201_CREATED)
async def create_hub(
    data: TransferHubCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new transfer hub."""
    try:
        return await tms_service.create_hub(db, data.model_dump())
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


@router.get("/transfer-hubs", response_model=list[TransferHubResponse])
async def list_hubs(
    city: str | None = Query(None),
    hub_type: str | None = Query(None, alias="type"),
    db: AsyncSession = Depends(get_db),
):
    """List transfer hubs with optional city/type filters."""
    return await tms_service.list_hubs(db, city=city, hub_type=hub_type)


@router.patch("/transfer-hubs/{hub_id}", response_model=TransferHubResponse)
async def update_hub(
    hub_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Update transfer hub fields."""
    try:
        return await tms_service.update_hub(db, hub_id, data)
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
    try:
        return await tms_service.add_carrier_route(db, data.model_dump())
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/carrier-routes", response_model=list[CarrierRouteResponse])
async def list_carrier_routes(
    origin_city: str | None = Query(None),
    dest_city: str | None = Query(None),
    carrier_code: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List carrier routes with optional filters."""
    return await tms_service.list_carrier_routes(
        db, origin_city=origin_city, dest_city=dest_city, carrier_code=carrier_code,
    )


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


@router.get("/hub-connections", response_model=list[HubConnectionResponse])
async def list_hub_connections(
    hub_code: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List hub connections, optionally filtered by hub code."""
    return await tms_service.list_hub_connections(db, hub_code=hub_code)


# ── RoutePlan Endpoints ───────────────────────────────────────────────────────

@router.post("/transport-orders/{order_id}/route-plans", response_model=RoutePlanResponse, status_code=status.HTTP_201_CREATED)
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
    try:
        return await tms_service.create_segment(db, data.model_dump())
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


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


@router.get("/segments", response_model=list[TransportSegmentResponse])
async def list_segments(
    transport_order_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """List all segments for a transport order."""
    return await tms_service.list_segments(db, transport_order_id)


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

@router.post("/transport-orders/{order_id}/tracking-events")
async def create_tracking_event(
    order_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await tms_service.create_tracking_event(db, {"transport_order_id": order_id, **data})
    except (NotFoundException, ValidationException) as e:
        raise HTTPException(status_code=404 if isinstance(e, NotFoundException) else 422, detail=str(e))


@router.get("/transport-orders/{order_id}/tracking-events")
async def list_tracking_events(
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    return await tms_service.list_tracking_events(db, transport_order_id=order_id)


@router.post("/transport-orders/{order_id}/pod", status_code=status.HTTP_201_CREATED)
async def create_pod(
    order_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await tms_service.create_pod(db, {"transport_order_id": order_id, **data})
    except (NotFoundException, ValidationException) as e:
        raise HTTPException(status_code=404 if isinstance(e, NotFoundException) else 422, detail=str(e))


@router.get("/transport-orders/{order_id}/pod")
async def get_pod(
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    pod = await tms_service.get_pod(db, transport_order_id=order_id)
    if not pod:
        raise HTTPException(status_code=404, detail="POD not found")
    return pod


@router.put("/transport-orders/{order_id}/pod")
async def update_pod(
    order_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await tms_service.update_pod(db, transport_order_id=order_id, data=data)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
# Return Order (Reverse Logistics)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/return-orders", status_code=status.HTTP_201_CREATED)
async def create_return_order(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await tms_service.create_return_order(db, data)
    except (NotFoundException, ValidationException) as e:
        raise HTTPException(status_code=404 if isinstance(e, NotFoundException) else 422, detail=str(e))


@router.get("/return-orders")
async def list_return_orders(
    db: AsyncSession = Depends(get_db),
    status: str = Query(None),
):
    return await tms_service.list_return_orders(db, status=status)


@router.get("/return-orders/{return_id}")
async def get_return_order(return_id: str, db: AsyncSession = Depends(get_db)):
    order = await tms_service.get_return_order(db, return_id=return_id)
    if not order:
        raise HTTPException(status_code=404, detail="ReturnOrder not found")
    return order


@router.patch("/return-orders/{return_id}/status", response_model=dict)
async def update_return_status(return_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    try:
        return await tms_service.update_return_status(db, return_id=return_id, target=data.get("target"))
    except (NotFoundException, ValidationException) as e:
        raise HTTPException(status_code=404 if isinstance(e, NotFoundException) else 422, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
# Transport Exception / Incident
# ═══════════════════════════════════════════════════════════════════════

@router.post("/transport-orders/{order_id}/exceptions", status_code=status.HTTP_201_CREATED)
async def create_exception(order_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    try:
        return await tms_service.create_exception(db, {"transport_order_id": order_id, **data})
    except (NotFoundException, ValidationException) as e:
        raise HTTPException(status_code=404 if isinstance(e, NotFoundException) else 422, detail=str(e))


@router.get("/exceptions", response_model=list[dict])
async def list_exceptions(
    db: AsyncSession = Depends(get_db),
    transport_order_id: str = Query(None),
    status: str = Query("open"),
):
    return await tms_service.list_exceptions(db, transport_order_id=transport_order_id, status=status)


@router.patch("/exceptions/{exc_id}", response_model=dict)
async def resolve_exception(exc_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    try:
        return await tms_service.resolve_exception(
            db, exc_id=exc_id, resolution_notes=data.get("resolution_notes"))
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
# FreightRule & FreightTier (Shipping Cost Calculation)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/freight-rules", status_code=status.HTTP_201_CREATED)
async def create_freight_rule(data: dict, db: AsyncSession = Depends(get_db)):
    return await tms_service.create_freight_rule(db, data)


@router.post("/freight-tiers", status_code=status.HTTP_201_CREATED)
async def create_freight_tier(data: dict, db: AsyncSession = Depends(get_db)):
    return await tms_service.create_freight_tier(db, data)


@router.post("/freight/calculate")
async def calculate_freight(data: dict, db: AsyncSession = Depends(get_db)):
    try:
        return await tms_service.calculate_freight(db, data)
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
# ML Forecast (Demand Prediction)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/forecast/observations")
async def record_forecast_observation(data: dict, db: AsyncSession = Depends(get_db)):
    return await tms_service.record_forecast_observation(db, data)


@router.get("/forecast", response_model=list[dict])
async def get_forecast(
    origin_city: str = Query(None),
    destination_city: str = Query(None),
    days: int = Query(7, ge=1, le=30),
):
    return await tms_service.get_forecast(db={}, data={"origin_city": origin_city or "", "destination_city": destination_city or "", "days": days})


@router.post("/forecast/training")
async def train_forecast(data: dict, db: AsyncSession = Depends(get_db)):
    """Train forecast model with historical data."""
    return await tms_service.record_forecast_observation(db, data)
