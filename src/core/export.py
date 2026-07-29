import csv
import io
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.oms.models import Order
from src.oms.service import STATUS_REVERSE
from src.wms.models import Inventory

logger = logging.getLogger(__name__)


async def stream_csv(rows: list[dict], columns: list[str]) -> AsyncGenerator[bytes, None]:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    yield buffer.getvalue().encode("utf-8-sig")
    buffer.seek(0)
    buffer.truncate(0)

    encode = "utf-8"
    for row in rows:
        writer.writerow({col: row.get(col, "") for col in columns})
        yield buffer.getvalue().encode(encode)
        buffer.seek(0)
        buffer.truncate(0)


async def export_orders(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(Order).order_by(Order.created_at.desc()))
    rows = []
    for o in result.scalars().all():
        rows.append({
            "order_no": o.order_no,
            "status": STATUS_REVERSE.get(o.status, "draft"),
            "customer_id": str(o.customer_id),
            "total_amount": str(o.total_amount) if o.total_amount else "0",
            "created_at": o.created_at.isoformat() if o.created_at else "",
            "updated_at": o.updated_at.isoformat() if o.updated_at else "",
        })
    return rows


async def export_inventory(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(Inventory))
    rows = []
    for inv in result.scalars().all():
        rows.append({
            "sku_id": str(inv.sku_id),
            "warehouse_id": str(inv.warehouse_id),
            "quantity": inv.quantity,
            "locked_qty": inv.locked_qty,
            "min_qty": inv.min_qty,
            "updated_at": inv.updated_at.isoformat() if inv.updated_at else "",
        })
    return rows
