"""Orders CSV import handler."""
import csv
import io
import json
import logging
from typing import Any

from src.core._import import ImportResult

logger = logging.getLogger(__name__)


async def handle_orders_import(csv_text: str, db: Any) -> tuple[ImportResult, Exception | None]:
    """Parse orders CSV and create order records.

    Expected columns (order-dependent):
        customer_id  -- required UUID string
        items        -- JSON array of {"sku": "...", "qty": N} objects
        priority     -- optional: low|medium|high|urgent (default medium)
        notes        -- optional text field

    Returns:
        Tuple[ImportResult, Exception | None]
    """
    from src.oms import service as oms_service

    results = ImportResult()
    reader = csv.DictReader(io.StringIO(csv_text))

    for row_num, row in enumerate(reader, start=2):
        try:
            customer_id = row.get("customer_id", "").strip()
            if not customer_id:
                raise ValueError("Missing required field: customer_id")

            items_raw = row.get("items", "[]").strip()
            items = json.loads(items_raw) if items_raw else []

            priority = row.get("priority", "medium").strip().lower() or "medium"
            notes = row.get("notes", "").strip()

            order_data = {
                "customer_id": customer_id,
                "items": items,
                "priority": priority,
                "notes": notes,
            }
            await oms_service.create_order(db, order_data)
            results.success += 1
        except Exception as e:
            logger.warning("Row %d failed: %s", row_num, e)
            results.errors.append({"row": row_num, "error": str(e)})

    return (results, None)
