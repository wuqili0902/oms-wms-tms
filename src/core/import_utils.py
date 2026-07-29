import csv
import io
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ValidationException


logger = logging.getLogger(__name__)


async def import_orders_from_csv(content: str, db: AsyncSession) -> dict:
    from src.oms.service import create_order
    reader = csv.DictReader(io.StringIO(content))
    results = {"success": 0, "errors": []}
    for row_num, row in enumerate(reader, start=2):
        try:
            customer_id = row.get("customer_id", "").strip()
            if not customer_id:
                raise ValidationException(message="customer_id is required")

            items_raw = row.get("items", "[]").strip()
            import json
            items = json.loads(items_raw) if items_raw else []

            priority = row.get("priority", "medium").strip()
            notes = row.get("notes", "").strip()

            await create_order(db, {
                "customer_id": customer_id,
                "items": items,
                "priority": priority,
                "notes": notes,
            })
            results["success"] += 1
        except Exception as e:
            results["errors"].append({"row": row_num, "error": str(e)})

    return results


async def import_inventory_from_csv(content: str, db: AsyncSession) -> dict:
    import uuid

    from sqlalchemy import select

    from src.wms.models import Inventory

    reader = csv.DictReader(io.StringIO(content))
    results = {"success": 0, "errors": []}
    for row_num, row in enumerate(reader, start=2):
        try:
            sku_id = row.get("sku_id", "").strip()
            warehouse_id = row.get("warehouse_id", "").strip()
            quantity = int(row.get("quantity", 0))
            min_qty = int(row.get("min_qty", 0))

            result = await db.execute(
                select(Inventory).where(
                    Inventory.sku_id == uuid.UUID(sku_id),
                    Inventory.warehouse_id == uuid.UUID(warehouse_id),
                )
            )
            inv = result.scalar_one_or_none()
            if inv:
                inv.quantity = quantity
                inv.min_qty = min_qty
            else:
                inv = Inventory(
                    id=uuid.uuid4(),
                    sku_id=uuid.UUID(sku_id),
                    warehouse_id=uuid.UUID(warehouse_id),
                    quantity=quantity,
                    min_qty=min_qty,
                )
                db.add(inv)
            results["success"] += 1
        except Exception as e:
            results["errors"].append({"row": row_num, "error": str(e)})
            continue

    await db.commit()
    return results
