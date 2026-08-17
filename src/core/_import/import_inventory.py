"""Inventory CSV import handler."""
import csv
import io
import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from src.core._import import ImportResult

logger = logging.getLogger(__name__)


async def handle_inventory_import(csv_text: str, db: Any) -> tuple[ImportResult, Exception | None]:
    """Parse inventory CSV and upsert stock records.

    Expected columns (order-dependent):
        sku_id       -- required UUID string
        warehouse_id -- required UUID string
        quantity     -- integer >= 0
        min_qty      -- optional safety stock threshold (integer)

    Returns:
        Tuple[ImportResult, Exception | None]
    """
    from src.wms.models import Inventory, SKU, Warehouse  # noqa: I001

    results = ImportResult()
    reader = csv.DictReader(io.StringIO(csv_text))

    for row_num, row in enumerate(reader, start=2):
        try:
            sku_id_str = row.get("sku_id", "").strip()
            warehouse_id_str = row.get("warehouse_id", "").strip()

            if not sku_id_str or not warehouse_id_str:
                raise ValueError("Missing required fields: sku_id and/or warehouse_id")

            sku_id = uuid.UUID(sku_id_str)
            warehouse_id = uuid.UUID(warehouse_id_str)
            quantity = Decimal(str(int(row.get("quantity", 0))))
            min_qty = Decimal(str(int(row.get("min_qty", 0) or 0)))

            wh_result = await db.execute(select(Warehouse).where(Warehouse.id == warehouse_id))
            if not wh_result.scalar_one_or_none():
                raise ValueError(f"Warehouse {warehouse_id_str} not found")

            sku_result = await db.execute(select(SKU).where(SKU.id == sku_id))
            if not sku_result.scalar_one_or_none():
                raise ValueError(f"SKU {sku_id_str} not found")

            inv_result = await db.execute(
                select(Inventory).where(
                    Inventory.warehouse_id == warehouse_id,
                    Inventory.sku_id == sku_id,
                )
            )
            inv = inv_result.scalar_one_or_none()

            if inv:
                inv.quantity = quantity
                inv.min_qty = min_qty
            else:
                inv = Inventory(
                    id=uuid.uuid4(),
                    warehouse_id=warehouse_id,
                    sku_id=sku_id,
                    gtin="",
                    batch_no="IMPORT",
                    quantity=quantity,
                    locked_qty=Decimal(0),
                    min_qty=min_qty,
                    max_qty=Decimal(0),
                )
                db.add(inv)

            results.success += 1
        except (ValueError, Exception) as e:
            logger.warning("Row %d failed: %s", row_num, e)
            results.errors.append({"row": row_num, "error": str(e)})

    await db.commit()
    return (results, None)
