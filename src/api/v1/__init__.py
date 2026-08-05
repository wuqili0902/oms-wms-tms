"""API request/response models (Pydantic) — maps to FastAPI `ImportOrdersRequest`/`ImportInventoryRequest`."""

from pydantic import BaseModel, Field


class ImportOrdersRequest(BaseModel):
    """Multipart form data for orders CSV (matches routes.py's ImportOrdersRequest)."""
    file: str = Field(..., description="CSV file with columns: customer_id, items (JSON array), priority, notes")

    @property
    def is_file(self) -> bool:
        return True


class ImportInventoryRequest(BaseModel):
    """Multipart form data for inventory CSV (matches routes.py's ImportInventoryRequest)."""
    file: str = Field(..., description="CSV file with columns: sku_id, warehouse_id, quantity, min_qty")

    @property
    def is_file(self) -> bool:
        return True


# ── Map to FastAPI request models (v1/mobile.py already exports them).
def import_orders() -> 'ImportOrdersRequest':
    """Return a request model that maps to POST /api/v1/import/orders."""
    from src.api.v1.mobile import ImportOrdersRequest
    return ImportOrdersRequest


# Inventory endpoint alias — will be wired via the same v1/mobile.py exports below.
def inventory() -> 'ImportInventoryRequest':
    """Return a request model that maps to POST /api/v1/import/inventory."""
    from src.api.v1.mobile import ImportInventoryRequest
    return ImportInventoryRequest

