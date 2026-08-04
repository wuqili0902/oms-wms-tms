"""Inventory CSV import handler."""
import csv
import io
import logging

from src.core._import import ImportResult

logger = logging.getLogger(__name__)


async def handle_inventory_import(csv_text: str) -> tuple[ImportResult, Exception | None]:
    """Parse inventory CSV and upsert stock records.

    Expected columns (order-dependent):
        sku_id       -- required UUID string
        warehouse_id -- required UUID string
        quantity     -- integer >= 0
        min_qty      -- optional safety stock threshold (integer)

    Returns:
        Tuple[ImportResult, Exception | None]
    """
    results = ImportResult()
    reader = csv.DictReader(io.StringIO(csv_text))

    for row_num, row in enumerate(reader, start=2):
        try:
            sku_id = row.get("sku_id", "").strip()
            warehouse_id = row.get("warehouse_id", "").strip()

            if not sku_id or not warehouse_id:
                raise ValueError("Missing required fields: sku_id and/or warehouse_id")

            _quantity = int(row.get("quantity", 0))
            _min_qty = int(row.get("min_qty", 0) or 0)

            # TODO: call wms_service.upsert_inventory(db, ...) here
            results.success += 1
        except ValueError as e:
            logger.warning("Row %d failed: %s", row_num, e)
            results.errors.append({"row": row_num, "error": str(e)})

    return (results, None)
