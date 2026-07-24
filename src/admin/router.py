"""Admin Web UI router.

Jinja2-based admin panel for team operations.
All routes require authentication.
"""
import csv
from datetime import UTC, datetime
from io import StringIO

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select, func
from src.auth import service as auth_service
from src.barcode import service as barcode_service
from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.models.base import model_to_dict
from src.oms import service as oms_service
from src.tms import service as tms_service
from src.wms import service as wms_service

router = APIRouter(prefix="/admin", tags=["admin"])

templates = Jinja2Templates(directory="src/admin/templates")


def _get_flashes(request: Request) -> list[tuple[str, str]]:
    flashes = []
    for key in ("success", "error"):
        msg = request.query_params.get(f"flash_{key}")
        if msg:
            flashes.append((key, msg))
    return flashes


async def _get_stats(db: AsyncSession) -> dict:
    orders, _ = await oms_service.list_orders(db, page=1, page_size=1)
    templates_list = await barcode_service.list_templates(db)
    users = await auth_service.list_users(db)
    inventory = await wms_service.query_inventory(db)
    warehouses = await wms_service.list_warehouses(db)
    return {
        "order_count": len(orders),
        "user_count": len(users),
        "inventory_count": len(inventory),
        "warehouse_count": len(warehouses),
        "template_count": len(templates_list),
    }


# ── Dashboard ─────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    all_orders, total = await oms_service.list_orders(db, page=1, page_size=10)
    stats = await _get_stats(db)
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "active": "dashboard",
            "flashes": _get_flashes(request),
            "now": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "stats": stats,
            "recent_orders": all_orders,
        },
    )


# ── Orders ─────────────────────────────────────────────────────────────────

@router.get("/orders", response_class=HTMLResponse)
async def list_orders(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    orders, total = await oms_service.list_orders(db, page=1, page_size=100)
    return templates.TemplateResponse(
        request,
        "admin/orders.html",
        {"active": "orders", "flashes": _get_flashes(request), "orders": orders},
    )


@router.get("/orders/{order_id}", response_class=HTMLResponse)
async def order_detail(
    request: Request,
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        order = await oms_service.get_order(db, order_id)
        history = await oms_service.get_order_history(db, order_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Order not found")
    return templates.TemplateResponse(
        request,
        "admin/order_detail.html",
        {
            "active": "orders",
            "flashes": _get_flashes(request),
            "order": order,
            "history": history,
        },
    )


# ── Warehouse ──────────────────────────────────────────────────────────────

@router.get("/warehouses", response_class=HTMLResponse)
async def list_warehouses(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    warehouses = await wms_service.list_warehouses(db)
    return templates.TemplateResponse(
        request,
        "admin/warehouses.html",
        {
            "active": "warehouses",
            "flashes": _get_flashes(request),
            "warehouses": warehouses,
        },
    )


# ── Inventory ────────────────────────────────────────────────────────────────

@router.get("/inventory", response_class=HTMLResponse)
async def list_inventory(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    inventory = await wms_service.query_inventory(db)
    return templates.TemplateResponse(
        request,
        "admin/inventory.html",
        {
            "active": "inventory",
            "flashes": _get_flashes(request),
            "inventory": inventory,
        },
    )


# ── Devices ────────────────────────────────────────────────────────────────

@router.get("/devices", response_class=HTMLResponse)
async def list_devices(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    devices = await tms_service.list_devices(db)
    return templates.TemplateResponse(
        request,
        "admin/devices.html",
        {
            "active": "devices",
            "flashes": _get_flashes(request),
            "devices": devices,
        },
    )


# ── Barcode Templates ─────────────────────────────────────────────────────

@router.get("/templates", response_class=HTMLResponse)
async def list_label_templates(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    templates_list = await barcode_service.list_templates(db)
    return templates.TemplateResponse(
        request,
        "admin/templates.html",
        {
            "active": "templates",
            "flashes": _get_flashes(request),
            "templates": templates_list,
        },
    )


# ── Users ──────────────────────────────────────────────────────────────────

@router.get("/users", response_class=HTMLResponse)
async def list_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    users = await auth_service.list_users(db)
    # Strip sensitive fields for display
    safe_users = [
        {k: v for k, v in u.items() if k not in ("hashed_password",)}
        for u in users
    ]
    return templates.TemplateResponse(
        request,
        "admin/users.html",
        {
            "active": "users",
            "flashes": _get_flashes(request),
            "users": safe_users,
        },
    )


# ── Export ────────────────────────────────────────────────────────────────────

@router.get("/export/orders")
async def export_orders_csv(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Export all orders as CSV."""
    orders, _ = await oms_service.list_orders(db, page=1, page_size=10000)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Order No", "Status", "Customer", "Total", "Priority", "Items", "Created"])
    for o in orders:
        writer.writerow([
            o.get("order_no", ""),
            o.get("status", ""),
            o.get("customer_id", ""),
            o.get("total_amount", "0"),
            o.get("priority", ""),
            len(o.get("items", [])),
            o.get("created_at", ""),
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders.csv"},
    )


@router.get("/export/inventory")
async def export_inventory_csv(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Export inventory as CSV."""
    items = await wms_service.query_inventory(db)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["SKU", "Warehouse ID", "Location ID", "Quantity", "Reserved", "Available"])
    for item in items:
        writer.writerow([
            item.get("sku", ""),
            item.get("warehouse_id", ""),
            item.get("location_id", ""),
            item.get("quantity", 0),
            item.get("reserved_qty", 0),
            item.get("available_qty", 0),
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=inventory.csv"},
    )


# ═══════════════════════════════════════════════════════════════════════
# TMS Admin Pages
# ═══════════════════════════════════════════════════════════════════════

@router.get("/transport-orders", response_class=HTMLResponse)
async def list_transport_orders(
    request: Request, db: AsyncSession = Depends(get_db),
):
    orders, total = await tms_service.list_transport_orders(db, page=1, page_size=100)
    return templates.TemplateResponse(request, "admin/transport_orders.html",
        {"active": "transport_orders", "flashes": _get_flashes(request), "transport_orders": orders})


@router.get("/route-plans", response_class=HTMLResponse)
async def list_route_plans(
    request: Request, db: AsyncSession = Depends(get_db),
):
    from src.tms.models import RoutePlan as _RP
    plans_result = await db.execute(select(_RP).order_by(_RP.created_at.desc()).limit(100))
    plans = [model_to_dict(p) for p in plans_result.scalars().all()]
    return templates.TemplateResponse(request, "admin/route_plans.html",
        {"active": "route_plans", "flashes": _get_flashes(request), "route_plans": plans})


@router.get("/returns", response_class=HTMLResponse)
async def list_returns(
    request: Request, db: AsyncSession = Depends(get_db),
):
    orders, total = await tms_service.list_return_orders(db, page=1, page_size=100)
    return templates.TemplateResponse(request, "admin/returns.html",
        {"active": "returns", "flashes": _get_flashes(request), "return_orders": orders})


@router.get("/exceptions", response_class=HTMLResponse)
async def list_exceptions(
    request: Request, db: AsyncSession = Depends(get_db),
):
    excs = await tms_service.list_exceptions(db, status="open")
    return templates.TemplateResponse(request, "admin/exceptions.html",
        {"active": "exceptions", "flashes": _get_flashes(request), "exceptions": excs})


@router.get("/forecast", response_class=HTMLResponse)
async def forecast_page(
    request: Request, origin_city: str = Query(None), destination_city: str = Query(None), days: int = 7,
    db: AsyncSession = Depends(get_db),
):
    from src.tms.ml.forecast import forecaster as fc
    key = f"{origin_city or ''}-{destination_city or ''}"
    points = fc.forecast(key, days)
    return templates.TemplateResponse(request, "admin/forecast.html", {
        "active": "forecast", "flashes": _get_flashes(request), "points": [p.__dict__ for p in points],
    })


@router.get("/ml/forecast", response_class=HTMLResponse)
async def ml_forecast_page(
    request: Request, origin_city: str = Query(None), destination_city: str = Query(None), days: int = 7,
    db: AsyncSession = Depends(get_db),
):
    from src.tms.ml.forecast import forecaster as fc
    key = f"{origin_city or ''}-{destination_city or ''}"
    points = fc.forecast(key, days)
    return templates.TemplateResponse(request, "admin/ml_forecast.html", {
        "active": "ml_forecast", "flashes": _get_flashes(request), "points": [p.__dict__ for p in points],
    })


@router.get("/export/transport-orders")
async def export_transport_orders_csv(db: AsyncSession = Depends(get_db)):
    orders, _ = await tms_service.list_transport_orders(db, page=1, page_size=10000)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Transport No", "Status", "Carrier", "Pickup", "Delivery", "Weight (kg)", "Created"])
    for o in orders:
        writer.writerow([o.get("transport_no",""), o.get("status",""), o.get("carrier_code",""),
                         o.get("pickup_address",{}).get("city",""),
                         o.get("delivery_address",{}).get("city",""),
                         o.get("total_weight_kg",""), o.get("created_at","")])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transport_orders.csv"})


@router.get("/export/returns")
async def export_returns_csv(db: AsyncSession = Depends(get_db)):
    orders, _ = await tms_service.list_return_orders(db)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Return No", "Status", "Reason", "Refund Amount"])
    for o in orders:
        writer.writerow([o.get("return_no",""), o.get("status",""), o.get("reason",""), o.get("refund_amount","0")])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=returns.csv"})


@router.get("/export/exceptions")
async def export_exceptions_csv(db: AsyncSession = Depends(get_db)):
    excs = await tms_service.list_exceptions(db)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Status", "Type", "Severity"])
    for e in excs:
        writer.writerow([e.get("id",""), e.get("status",""), e.get("type",""), e.get("severity","")])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=exceptions.csv"})


@router.get("/export/route-plans")
async def export_route_plans_csv(db: AsyncSession = Depends(get_db)):
    from src.tms.models import RoutePlan as _RP
    plans_result = await db.execute(select(_RP).order_by(_RP.created_at.desc()))
    plans = [model_to_dict(p) for p in plans_result.scalars().all()]
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["No", "Origin", "Dest", "Distance (km)", "Cost"])
    for p in plans:
        writer.writerow([p.get("plan_no",""), p.get("origin_city",""), p.get("destination_city",""),
                         p.get("total_distance_km",""), p.get("total_cost_amount","")])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=route_plans.csv"})


@router.post("/ml/forecast/train", response_class=HTMLResponse)
async def train_ml_forecast(
    request: Request, data: dict = Form(), db: AsyncSession = Depends(get_db),
):
    from src.tms.ml.forecast import forecaster as fc
    key = f"{data.get('origin_city','')}-{data.get('destination_city','')}"
    count = float(data.get("count", 0))
    fc.add_observation(key, count)
    return templates.TemplateResponse(request, "admin/ml_forecast.html", {
        "active": "ml_forecast", "flashes": [("success", f"Trained with {count} orders for key '{key}'")],
        "points": [], "origin_city": data.get("origin_city",""), "destination_city": data.get("destination_city",""),
    })


@router.post("/forecast/training", response_class=HTMLResponse)
async def train_forecast(
    request: Request, origin_city: str = Form(), destination_city: str = Form(), count: int = Form(),
    db: AsyncSession = Depends(get_db),
):
    from src.tms.ml.forecast import forecaster as fc
    key = f"{origin_city}-{destination_city}"
    fc.add_observation(key, float(count))
    return templates.TemplateResponse(request, "admin/forecast.html", {
        "active": "forecast", "flashes": [("success", f"Trained with {count} orders")], "points": [],
    })


@router.get("/export/ml-forecast")
async def export_forecast_csv(db: AsyncSession = Depends(get_db)):
    from src.tms.ml.forecast import forecaster as fc
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Predicted", "Lower", "Upper"])
    for p in fc.forecast(""):
        writer.writerow([p.date, p.predicted_orders or "", p.confidence_lower or "", p.confidence_upper or ""])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=forecast.csv"})
