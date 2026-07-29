"""Order split and merge service functions.

Allows operations staff to:
  - **Split** a single order into multiple child orders
  - **Merge** multiple orders into a single fulfilment shipment
"""
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.exceptions import NotFoundException, ValidationException
from src.oms.models import (
    MergeGroup,
    Order,
    OrderItem,
    OrderStatus,
    SplitChildOrder,
)
from src.oms.service import _order_to_dict, _to_uuid


async def split_order(
    db: AsyncSession,
    order_id: str,
    splits: list[dict],
    reason: str = "",
) -> list[dict]:
    """Split an order into multiple child orders.

    ``splits`` is a list of dicts, each specifying items for a child order::

        [
            {"items": [{"sku": "SKU-001", "quantity": 2}], "note": "Split 1"},
            {"items": [{"sku": "SKU-001", "quantity": 1}], "note": "Split 2"},
        ]
    """
    result = await db.execute(
        select(Order).where(Order.id == _to_uuid(order_id))
        .options(selectinload(Order.items_list))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundException(message=f"Order {order_id} not found")

    child_orders = []
    for idx, split in enumerate(splits):
        child = Order(
            id=uuid.uuid4(),
            order_no=f"{order.order_no}-SP{idx + 1}",
            status=OrderStatus.PENDING,
            customer_id=order.customer_id,
            warehouse_id=order.warehouse_id,
            items={},
            total_amount=Decimal("0"),
            priority=order.priority,
            notes=split.get("note", f"Split from {order.order_no}"),
        )
        db.add(child)
        await db.flush()

        total = Decimal("0")
        for item_req in split.get("items", []):
            sku_str = item_req.get("sku", "")
            qty = int(item_req.get("quantity", 0))
            orig = None
            for oi in order.items_list:
                if str(oi.sku_id) == sku_str:
                    orig = oi
                    break
            unit_price = orig.unit_price if orig else Decimal("0")
            oi = OrderItem(
                id=uuid.uuid4(),
                order_id=child.id,
                sku_id=orig.sku_id if orig else None,
                gtin=orig.gtin if orig else "",
                name=item_req.get("product_name", orig.name if orig else ""),
                quantity=qty,
                unit_price=unit_price,
            )
            db.add(oi)
            total += unit_price * qty

        link = SplitChildOrder(
            id=uuid.uuid4(),
            parent_order_id=order.id,
            child_order_id=child.id,
            split_reason=reason or f"Manual split ({idx + 1})",
        )
        db.add(link)

        child.total_amount = total
        child_orders.append(await _order_to_dict(db, child))

    await db.commit()
    return child_orders


async def merge_orders(
    db: AsyncSession,
    order_ids: list[str],
    code: str | None = None,
    warehouse_id: str | None = None,
    note: str = "",
) -> dict:
    """Merge multiple orders into one MergeGroup for combined fulfilment.

    Creates a ``MergeGroup`` and links each order via ``SplitChildOrder``.
    Returns the merge group details including all child orders.
    """
    if len(order_ids) < 2:
        raise ValidationException(message="Need at least 2 orders to merge")

    orders = []
    total_amount = Decimal("0")
    total_items = 0

    for oid in order_ids:
        result = await db.execute(
            select(Order).where(Order.id == _to_uuid(oid))
            .options(selectinload(Order.items_list))
        )
        order = result.scalar_one_or_none()
        if not order:
            raise NotFoundException(message=f"Order {oid} not found")
        if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.FAILED):
            raise ValidationException(
                message=f"Cannot merge order {oid}: already in terminal state"
            )
        orders.append(order)
        total_amount += order.total_amount or Decimal("0")
        total_items += len(order.items_list)

    count = await db.execute(select(func.count()).select_from(MergeGroup))
    merge_code = code or f"MG-{count.scalar() + 1:04d}"

    group = MergeGroup(
        id=uuid.uuid4(),
        code=merge_code,
        warehouse_id=_to_uuid(warehouse_id) if warehouse_id else None,
        status="active",
        total_items=total_items,
        total_amount=total_amount,
        notes=note,
    )
    db.add(group)
    await db.flush()

    for order in orders:
        link = SplitChildOrder(
            id=uuid.uuid4(),
            child_order_id=order.id,
            merge_group_id=group.id,
            split_reason="merged",
        )
        db.add(link)

    await db.commit()
    await db.refresh(group)

    return {
        "id": str(group.id),
        "code": group.code,
        "status": group.status,
        "total_items": group.total_items,
        "total_amount": str(group.total_amount),
        "notes": group.notes or "",
        "order_ids": [str(o.id) for o in orders],
        "created_at": group.created_at.isoformat() if group.created_at else "",
    }


async def get_merge_group(db: AsyncSession, group_id: str) -> dict | None:
    """Get a merge group with its child orders."""
    result = await db.execute(
        select(MergeGroup).where(MergeGroup.id == _to_uuid(group_id))
    )
    group = result.scalar_one_or_none()
    if not group:
        return None

    child_links = await db.execute(
        select(SplitChildOrder).where(
            SplitChildOrder.merge_group_id == group.id,
            SplitChildOrder.is_deleted.is_(False),
        )
    )
    child_order_ids = [link.child_order_id for link in child_links.scalars().all()]

    return {
        "id": str(group.id),
        "code": group.code,
        "status": group.status,
        "total_items": group.total_items,
        "total_amount": str(group.total_amount),
        "notes": group.notes or "",
        "child_order_ids": [str(oid) for oid in child_order_ids],
        "created_at": group.created_at.isoformat() if group.created_at else "",
    }
