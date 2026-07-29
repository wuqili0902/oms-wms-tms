"""Admin Web UI router.

Jinja2-based admin panel for team operations.
All routes require authentication.
"""
import csv
import logging
from datetime import UTC, datetime
from io import StringIO

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics import service as analytics_service
from src.auth import service as auth_service
from src.barcode import service as barcode_service
from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.export import export_inventory, export_orders, stream_csv
from src.core.import_utils import import_inventory_from_csv, import_orders_from_csv
from src.models.base import model_to_dict
from src.oms import service as oms_service
from src.tms import service as tms_service
from src.wms import service as wms_service

router = APIRouter(prefix="/admin", tags=["admin"])

templates = Jinja2Templates(directory="src/admin/templates")

logger = logging.getLogger(__name__)


def _render(request: Request, template: str, context: dict) -> HTMLResponse:
    context["csrf_token"] = request.scope.get("csrf_token", request.cookies.get("csrf_token", ""))
    return templates.TemplateResponse(request, template, context)


def _get_flashes(request: Request) -> list[tuple[str, str]]:
    flashes = []
    for key in ("success", "error"):
        msg = request.query_params.get(f"flash_{key}")
        if msg:
            flashes.append((key, msg))
    return flashes


# ── Dashboard ─────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    from asyncio import gather
    stats_task = analytics_service.get_dashboard_stats(db)
    trends_task = analytics_service.get_order_trends(db, 30)
    status_task = analytics_service.get_status_distribution(db)
    low_stock_task = analytics_service.get_low_stock_items(db)
    recent_task = analytics_service.get_recent_orders(db, 10)
    import json
    stats, trends, status_dist, low_stock, recent_orders = await gather(
        stats_task, trends_task, status_task, low_stock_task, recent_task,
    )
    return _render(
        request,
        "admin/dashboard.html",
        {
            "active": "dashboard",
            "flashes": _get_flashes(request),
            "now": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "stats": stats,
            "order_trends_json": json.dumps([t["date"] for t in trends]),
            "order_counts_json": json.dumps([t["count"] for t in trends]),
            "status_labels_json": json.dumps([s["status"] for s in status_dist]),
            "status_counts_json": json.dumps([s["count"] for s in status_dist]),
            "low_stock": low_stock,
            "recent_orders": recent_orders,
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
    return _render(
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
        logger.exception("Failed to load order detail for %s", order_id)
        raise HTTPException(status_code=404, detail="Order not found")
    return _render(
        request,
        "admin/order_detail.html",
        {
            "active": "orders",
            "flashes": _get_flashes(request),
            "order": order,
            "history": history,
        },
    )


# ── Order CRUD (POST) ─────────────────────────────────────────────────────

@router.post("/orders", response_class=HTMLResponse)
async def create_order(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    form = await request.form()
    data = {
        "order_no": form.get("order_no"),
        "customer_id": form.get("customer_id"),
        "total_amount": form.get("total_amount"),
    }
    try:
        await oms_service.create_order(db, data)
    except Exception:
        logger.exception("Failed to create order")
        raise HTTPException(status_code=400, detail="Failed to create order")
    return RedirectResponse(url="/admin/orders", status_code=303)


@router.post("/orders/{order_id}/status", response_class=HTMLResponse)
async def update_order_status(
    request: Request,
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    form = await request.form()
    status = form.get("status")
    try:
        await oms_service.update_order_status(db, order_id, status, operator=current_user.get("username", "admin"))
    except Exception:
        logger.exception("Failed to update order status for %s", order_id)
        raise HTTPException(status_code=400, detail="Failed to update order status")
    return RedirectResponse(url=f"/admin/orders/{order_id}", status_code=303)


# ── User CRUD (POST) ──────────────────────────────────────────────────────

@router.post("/users", response_class=HTMLResponse)
async def create_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    form = await request.form()
    data = {
        "username": form.get("username"),
        "email": form.get("email"),
        "password": form.get("password"),
    }
    try:
        await auth_service.register_user(db, data)
    except Exception:
        logger.exception("Failed to create user")
        raise HTTPException(status_code=400, detail="Failed to create user")
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/toggle", response_class=HTMLResponse)
async def toggle_user_active(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    import uuid as _uuid

    from src.auth.models import User
    result = await db.execute(select(User).where(User.id == _uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = not user.is_active
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/delete", response_class=HTMLResponse)
async def delete_user(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    import uuid as _uuid

    from sqlalchemy import delete as sa_delete

    from src.auth.models import User
    await db.execute(sa_delete(User).where(User.id == _uuid.UUID(user_id)))
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


# ── Warehouse CRUD (API) ───────────────────────────────────────────────

@router.post("/warehouses", response_class=HTMLResponse)
async def create_warehouse(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    form = await request.form()
    data = {k: v for k, v in form.items()}
    wh = await wms_service.create_warehouse(db, data)
    return _render(
        request, "admin/warehouses.html", {"active": "warehouses", "flashes": [("success", f"Warehouse {wh['code']} created")]},
    )


@router.put("/warehouses/{wh_id}", response_class=HTMLResponse)
async def update_warehouse(
    wh_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    form = await request.form()
    data = {k: v for k, v in form.items() if k != "_method"}
    wh = await wms_service.update_warehouse(db, wh_id, data)
    wh_code = wh.code if wh else wh_id
    return _render(
        request, "admin/warehouses.html", {"active": "warehouses", "flashes": [("success", f"Warehouse {wh_code} updated")]},
    )


@router.delete("/warehouses/{wh_id}", response_class=HTMLResponse)
async def delete_warehouse(
    wh_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await wms_service.delete_warehouse(db, wh_id)
    return _render(request, "admin/warehouses.html", {"active": "warehouses", "flashes": [("success", f"Warehouse {wh_id} deleted")]},
    )


# ── Warehouse list (GET) ───────────────────────────────────────────────

@router.get("/warehouses/{wh_id}/edit", response_class=HTMLResponse)
async def edit_warehouse(
    request: Request, wh_id: str, db: AsyncSession = Depends(get_db),
):
    wh = await wms_service.get_warehouse(db, wh_id)
    return _render(request, "admin/warehouses.html", {
        "active": "warehouses", "flashes": _get_flashes(request), "wh": wh,
    })


@router.get("/warehouses", response_class=HTMLResponse)
async def list_warehouses(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    warehouses = await wms_service.list_warehouses(db)
    return _render(
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
    return _render(
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
    return _render(
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
    return _render(
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
    return _render(
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
    rows = await export_orders(db)
    columns = ["order_no", "status", "customer_id", "total_amount", "created_at", "updated_at"]
    return StreamingResponse(
        stream_csv(rows, columns),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders.csv"},
    )


@router.get("/export/inventory")
async def export_inventory_csv(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    rows = await export_inventory(db)
    columns = ["sku_id", "warehouse_id", "quantity", "locked_qty", "min_qty", "updated_at"]
    return StreamingResponse(
        stream_csv(rows, columns),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=inventory.csv"},
    )


@router.get("/import", response_class=HTMLResponse)
async def import_page(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    return _render(request, "admin/import.html", {
        "active": "import", "flashes": _get_flashes(request),
    })


@router.post("/import/orders")
async def import_orders(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    form = await request.form()
    file = form.get("file")
    if not file or not file.filename:
        return RedirectResponse(url="/admin/import?flash_error=No file uploaded", status_code=303)
    content = (await file.read()).decode("utf-8")
    result = await import_orders_from_csv(content, db)
    msg = f"Imported {result['success']} orders"
    if result["errors"]:
        msg += f", {len(result['errors'])} errors"
    return RedirectResponse(url=f"/admin/import?flash_success={msg}", status_code=303)


@router.post("/import/inventory")
async def import_inventory(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    form = await request.form()
    file = form.get("file")
    if not file or not file.filename:
        return RedirectResponse(url="/admin/import?flash_error=No file uploaded", status_code=303)
    content = (await file.read()).decode("utf-8")
    result = await import_inventory_from_csv(content, db)
    msg = f"Imported {result['success']} inventory items"
    if result["errors"]:
        msg += f", {len(result['errors'])} errors"
    return RedirectResponse(url=f"/admin/import?flash_success={msg}", status_code=303)


# ── Webhooks ──────────────────────────────────────────────────────────────

@router.get("/webhooks", response_class=HTMLResponse)
async def list_webhooks(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    from src.webhooks.models import WebhookTarget
    result = await db.execute(select(WebhookTarget).order_by(WebhookTarget.created_at.desc()))
    targets = []
    for t in result.scalars().all():
        import json
        events = json.loads(t.events) if t.events else []
        targets.append({
            "id": t.id,
            "name": t.name,
            "url": t.url,
            "events": events,
            "events_display": ", ".join(events),
            "status": t.status.value,
            "created_at": t.created_at.isoformat() if t.created_at else "",
        })
    return _render(request, "admin/webhooks.html", {
        "active": "webhooks", "flashes": _get_flashes(request), "targets": targets,
    })


@router.post("/webhooks")
async def create_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    import json

    from src.webhooks.models import WebhookStatus, WebhookTarget
    form = await request.form()
    events = form.getlist("events") if hasattr(form, "getlist") else [form.get("events", "")]
    target = WebhookTarget(
        name=form.get("name", ""),
        url=form.get("url", ""),
        secret=form.get("secret") or None,
        events=json.dumps(events),
        status=WebhookStatus(form.get("status", "active")),
    )
    db.add(target)
    await db.commit()
    return RedirectResponse(url="/admin/webhooks?flash_success=Webhook created", status_code=303)


@router.post("/webhooks/{target_id}/delete")
async def delete_webhook(
    target_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    from sqlalchemy import delete as sa_delete

    from src.webhooks.models import WebhookTarget
    await db.execute(sa_delete(WebhookTarget).where(WebhookTarget.id == target_id))
    await db.commit()
    return RedirectResponse(url="/admin/webhooks?flash_success=Webhook deleted", status_code=303)


# ═══════════════════════════════════════════════════════════════════════
# TMS Admin Pages
# ═══════════════════════════════════════════════════════════════════════

@router.get("/transport-orders", response_class=HTMLResponse)
async def list_transport_orders(
    request: Request, db: AsyncSession = Depends(get_db),
):
    orders, total = await tms_service.list_transport_orders(db, page=1, page_size=100)
    return _render(request, "admin/transport_orders.html",
        {"active": "transport_orders", "flashes": _get_flashes(request), "transport_orders": orders})


@router.get("/route-plans", response_class=HTMLResponse)
async def list_route_plans(
    request: Request, db: AsyncSession = Depends(get_db),
):
    from src.tms.models import RoutePlan
    plans_result = await db.execute(select(RoutePlan).order_by(RoutePlan.created_at.desc()).limit(100))
    plans = [model_to_dict(p) for p in plans_result.scalars().all()]
    return _render(request, "admin/route_plans.html",
        {"active": "route_plans", "flashes": _get_flashes(request), "route_plans": plans})


@router.get("/returns", response_class=HTMLResponse)
async def list_returns(
    request: Request, db: AsyncSession = Depends(get_db),
):
    orders, total = await tms_service.list_return_orders(db)
    return _render(request, "admin/returns.html",
        {"active": "returns", "flashes": _get_flashes(request), "return_orders": orders})


@router.get("/exceptions", response_class=HTMLResponse)
async def list_exceptions(
    request: Request, db: AsyncSession = Depends(get_db),
):
    excs = await tms_service.list_exceptions(db, status="open")
    return _render(request, "admin/exceptions.html",
        {"active": "exceptions", "flashes": _get_flashes(request), "exceptions": excs})


@router.get("/forecast", response_class=HTMLResponse)
async def forecast_page(
    request: Request, origin_city: str = Query(None), destination_city: str = Query(None), days: int = 7,
    db: AsyncSession = Depends(get_db),
):
    from src.tms.ml.forecast import forecaster as fc
    key = f"{origin_city or ''}-{destination_city or ''}"
    points = fc.forecast(key, days)
    return _render(request, "admin/forecast.html", {
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
    return _render(request, "admin/ml_forecast.html", {
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
    from src.tms.models import RoutePlan
    plans_result = await db.execute(select(RoutePlan).order_by(RoutePlan.created_at.desc()))
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
    return _render(request, "admin/ml_forecast.html", {
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
    return _render(request, "admin/forecast.html", {
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
