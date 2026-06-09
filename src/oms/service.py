"""OMS business logic layer with order state machine.

All CRUD functions are async and require an ``AsyncSession``.
Maps ORM model fields to Pydantic schema field names.
"""
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException, ValidationException
from src.oms.models import Customer, Order, OrderItem, OrderPriority, OrderStatus, OrderStatusLog
from src.wms.models import SKU

# ── State machine ──────────────────────────────────────────────────────────

ORDER_STATES: dict[str, set[str]] = {
    "draft": {"confirmed", "cancelled"},
    "confirmed": {"processing", "cancelled"},
    "processing": {"picking", "cancelled"},
    "picking": {"completed", "cancelled"},
    "completed": set(),      # terminal
    "cancelled": set(),      # terminal
    "failed": set(),         # terminal
}

# Map schema status strings to ORM OrderStatus enum values
STATUS_MAP: dict[str, OrderStatus] = {
    "draft": OrderStatus.PENDING,
    "confirmed": OrderStatus.CONFIRMED,
    "processing": OrderStatus.PROCESSING,
    "picking": OrderStatus.PICKING,
    "completed": OrderStatus.COMPLETED,
    "cancelled": OrderStatus.CANCELLED,
    "failed": OrderStatus.FAILED,
}
STATUS_REVERSE: dict[OrderStatus, str] = {v: k for k, v in STATUS_MAP.items()}

# Map schema priority strings to ORM enums
PRIORITY_MAP: dict[str, OrderPriority] = {
    "low": OrderPriority.LOW,
    "medium": OrderPriority.MEDIUM,
    "high": OrderPriority.HIGH,
    "urgent": OrderPriority.URGANIC,
}
PRIORITY_REVERSE: dict[OrderPriority, str] = {v: k for k, v in PRIORITY_MAP.items()}


def validate_transition(current: str, target: str) -> None:
    allowed = ORDER_STATES.get(current, set())
    if target not in allowed:
        transitions = ", ".join(sorted(allowed)) if allowed else "none (terminal state)"
        raise ValidationException(
            message=f"Cannot transition from '{current}' to '{target}'",
            detail=f"Allowed transitions from '{current}': {transitions}",
        )


# ── Helpers ─────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(UTC)


def _to_uuid(val: str | uuid.UUID | None) -> uuid.UUID | None:
    if val is None or isinstance(val, uuid.UUID):
        return val
    return uuid.UUID(val)


async def _get_or_create_customer(db: AsyncSession, customer_code: str) -> Customer:
    """Look up a Customer by code, creating one if not found."""
    result = await db.execute(select(Customer).where(Customer.code == customer_code))
    c = result.scalar_one_or_none()
    if not c:
        c = Customer(
            id=uuid.uuid4(),
            code=customer_code,
            name=customer_code,
            contact="",
            phone="",
            address={},
        )
        db.add(c)
        await db.flush()
    return c


async def _get_or_create_sku(db: AsyncSession, sku_str: str) -> SKU:
    """Look up a SKU by code, creating one if not found."""
    result = await db.execute(select(SKU).where(SKU.sku == sku_str))
    sku = result.scalar_one_or_none()
    if not sku:
        sku = SKU(id=uuid.uuid4(), sku=sku_str, name=sku_str)
        db.add(sku)
        await db.flush()
    return sku


async def _order_to_dict(db: AsyncSession, order: Order) -> dict:
    """Convert Order ORM row to schema dict."""
    # Fetch customer code for the response
    customer = await db.get(Customer, order.customer_id)
    customer_code = customer.code if customer else str(order.customer_id)

    # Fetch items from OrderItem table
    items_result = await db.execute(
        select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.created_at)
    )
    items = []
    for oi in items_result.scalars().all():
        sku_str = ""
        if oi.sku_id:
            sku_obj = await db.get(SKU, oi.sku_id)
            sku_str = sku_obj.sku if sku_obj else ""
        items.append({
            "gtin": oi.gtin or "",
            "sku": sku_str,
            "product_name": oi.name or "",
            "quantity": oi.quantity,
            "unit_price": str(oi.unit_price) if oi.unit_price else "0",
            "subtotal": str(Decimal(str(oi.unit_price or 0)) * int(oi.quantity or 0)),
        })

    return {
        "id": str(order.id),
        "order_no": order.order_no,
        "status": STATUS_REVERSE.get(order.status, "draft"),
        "customer_id": customer_code,
        "items": items,
        "total_amount": str(order.total_amount) if order.total_amount else "0",
        "priority": PRIORITY_REVERSE.get(order.priority, "medium"),
        "notes": order.notes or "",
        "created_at": order.created_at.isoformat() if order.created_at else "",
        "updated_at": order.updated_at.isoformat() if order.updated_at else "",
    }


# ── Service functions ──────────────────────────────────────────────────────

async def create_order(db: AsyncSession, data: dict) -> dict:
    """Create a new order in draft status."""
    # Ensure customer exists
    customer = await _get_or_create_customer(db, data["customer_id"])

    # Generate order_no
    date_part = _now().strftime("%Y%m%d")
    count_result = await db.execute(select(func.count()).select_from(Order))
    count = count_result.scalar() or 0
    order_no = f"ORD-{date_part}-{count + 1:04d}"

    items = data.get("items", [])
    total = sum(
        Decimal(str(item.get("unit_price", 0))) * int(item.get("quantity", 0))
        for item in items
    )

    order = Order(
        id=uuid.uuid4(),
        order_no=order_no,
        status=OrderStatus.PENDING,
        customer_id=customer.id,
        items={},  # Placeholder — real items stored in OrderItem table
        total_amount=total,
        priority=PRIORITY_MAP.get(data.get("priority", "medium"), OrderPriority.MEDIUM),
        notes=data.get("notes", ""),
    )
    db.add(order)
    await db.flush()  # Get order.id before creating OrderItems

    # Create OrderItem records
    for item in items:
        # Look up or create SKU
        sku_str = item.get("sku", "")
        sku_obj = await _get_or_create_sku(db, sku_str) if sku_str else None
        unit_price = Decimal(str(item.get("unit_price", 0)))

        oi = OrderItem(
            id=uuid.uuid4(),
            order_id=order.id,
            sku_id=sku_obj.id if sku_obj else None,
            gtin=item.get("gtin", ""),
            name=item.get("product_name", ""),
            quantity=int(item.get("quantity", 0)),
            unit_price=unit_price,
        )
        db.add(oi)

    # Add history entry
    log = OrderStatusLog(
        id=uuid.uuid4(),
        order_id=order.id,
        from_status="",
        to_status="pending",
        operator_id=None,
        remark="Order created",
    )
    db.add(log)
    await db.commit()
    await db.refresh(order)
    return await _order_to_dict(db, order)


async def get_order(db: AsyncSession, order_id: str) -> dict:
    """Get an order by ID (excludes soft-deleted)."""
    result = await db.execute(
        select(Order).where(Order.id == _to_uuid(order_id), ~Order.is_deleted)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundException(message=f"Order {order_id} not found")
    return await _order_to_dict(db, order)


async def list_orders(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    customer_id: str | None = None,
) -> tuple[list[dict], int]:
    """List orders with pagination and optional filters."""
    stmt = select(Order)
    if status:
        enum_val = STATUS_MAP.get(status)
        if enum_val:
            stmt = stmt.where(Order.status == enum_val)
    if customer_id:
        stmt = stmt.where(Order.customer_id == _to_uuid(customer_id))
    stmt = stmt.order_by(Order.created_at.desc())

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)
    result = await db.execute(stmt)
    items = [await _order_to_dict(db, o) for o in result.scalars().all()]
    return items, total


async def update_order_status(db: AsyncSession, order_id: str, target: str, operator: str = "system") -> dict:
    """Update order status with state machine validation."""
    result = await db.execute(select(Order).where(Order.id == _to_uuid(order_id)))
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundException(message=f"Order {order_id} not found")

    current = STATUS_REVERSE.get(order.status, "draft")
    validate_transition(current, target)

    order.status = STATUS_MAP.get(target, OrderStatus.PENDING)
    order.updated_at = _now()

    log = OrderStatusLog(
        id=uuid.uuid4(),
        order_id=order.id,
        from_status=current,
        to_status=target,
        operator_id=None,
        remark=f"Status changed to {target}",
    )
    db.add(log)
    await db.commit()
    await db.refresh(order)
    return await _order_to_dict(db, order)


async def delete_order(db: AsyncSession, order_id: str) -> None:
    """Delete an order (soft delete)."""
    result = await db.execute(select(Order).where(Order.id == _to_uuid(order_id)))
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundException(message=f"Order {order_id} not found")

    current = STATUS_REVERSE.get(order.status, "draft")
    if current in ("completed", "cancelled", "failed"):
        raise ValidationException(message=f"Cannot delete order in '{current}' state")

    order.is_deleted = True
    order.deleted_at = _now()
    await db.commit()


async def get_order_history(db: AsyncSession, order_id: str) -> list[dict]:
    """Get status change history for an order."""
    # Verify order exists
    result = await db.execute(select(Order).where(Order.id == _to_uuid(order_id)))
    if not result.scalar_one_or_none():
        raise NotFoundException(message=f"Order {order_id} not found")

    stmt = (
        select(OrderStatusLog)
        .where(OrderStatusLog.order_id == _to_uuid(order_id))
        .order_by(OrderStatusLog.created_at.asc())
    )
    result = await db.execute(stmt)
    history = []
    for log in result.scalars().all():
        history.append({
            "id": str(log.id),
            "order_id": str(log.order_id),
            "from_status": log.from_status or "",
            "to_status": log.to_status or "",
            "operator": str(log.operator_id) if log.operator_id else "system",
            "remark": log.remark or "",
            "created_at": log.created_at.isoformat() if log.created_at else "",
        })
    return history
