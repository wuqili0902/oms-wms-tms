"""Orders CSV import handler."""
import csv
import io
import json
import logging

from src.core._import import ImportResult

logger = logging.getLogger(__name__)


async def handle_orders_import(csv_text: str) -> tuple[ImportResult, Exception | None]:
    """Parse orders CSV and create order records.

    Expected columns (order-dependent):
        customer_id  -- required UUID string
        items        -- JSON array of {"sku": "...", "qty": N} objects
        priority     -- optional: low|medium|high|urgent (default medium)
        notes        -- optional text field

    Returns:
        Tuple[ImportResult, Exception | None]
    """
    results = ImportResult()
    reader = csv.DictReader(io.StringIO(csv_text))

    for row_num, row in enumerate(reader, start=2):
        try:
            customer_id = row.get("customer_id", "").strip()
            if not customer_id:
                raise ValueError("Missing required field: customer_id")

            items_raw = row.get("items", "[]").strip()
            _items = json.loads(items_raw) if items_raw else []

            _priority = row.get("priority", "medium").strip().lower() or "medium"
            _notes = row.get("notes", "").strip()

            # TODO: call oms_service.create_order(db, ...) here
            results.success += 1
        except Exception as e:
            logger.warning("Row %d failed: %s", row_num, e)
            results.errors.append({"row": row_num, "error": str(e)})

    return (results, None)
