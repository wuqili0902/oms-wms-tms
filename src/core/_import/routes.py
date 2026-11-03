"""REST API endpoints for CSV imports.

Both endpoints bulk-write arbitrary rows, so they require an authenticated
caller (previously they were fully public).
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.core._import import import_csv_handler
from src.core._import.import_inventory import handle_inventory_import
from src.core._import.import_orders import handle_orders_import
from src.core.database import get_db
from src.core.dependencies import get_current_user

router = APIRouter(prefix="/import", tags=["import"])

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/orders", response_model=dict)
async def import_orders_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Import orders from CSV file.

    Expected columns (order-dependent):
        customer_id  -- required UUID string
        items        -- JSON array of {"sku": "...", "qty": N} objects
        priority     -- optional: low|medium|high|urgent (default medium)
        notes        -- optional text field

    Returns:
        { "success": <count>, "errors": [...] }
    """
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")
    result = await import_csv_handler(content, db, handle_orders_import)
    return result


@router.post("/inventory", response_model=dict)
async def import_inventory_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Import inventory from CSV file.

    Expected columns (order-dependent):
        sku_id       -- required UUID string
        warehouse_id -- required UUID string
        quantity     -- integer >= 0
        min_qty      -- optional safety stock threshold (integer)

    Returns:
        { "success": <count>, "errors": [...] }
    """
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")
    result = await import_csv_handler(content, db, handle_inventory_import)
    return result
