"""Barcode API router.

/templates routes MUST be before /{gtin} to avoid FastAPI path-parameter matching.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.barcode import service as barcode_service
from src.barcode.excel_barcode import generate_barcode_zip
from src.barcode.schemas import (
    BarcodeGenerateRequest,
    BarcodeResponse,
    BarcodeScanRequest,
    BarcodeValidateRequest,
    LabelTemplateCreate,
    LabelTemplateResponse,
)
from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.exceptions import ValidationException

router = APIRouter(prefix="/barcode", tags=["barcode"])


class ValidateResponse(BaseModel):
    valid: bool
    gtin: str | None = None
    format: str | None = None
    reason: str | None = None


# ── Core barcode endpoints ─────────────────────────────────────────────


@router.post("/generate", response_model=BarcodeResponse, status_code=status.HTTP_201_CREATED)
async def generate_barcode(
    data: BarcodeGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        rec = await barcode_service.generate_barcode(db, data.model_dump())
        return {k: rec[k] for k in ["id", "gtin", "entity_type", "entity_id", "format", "raw_data", "created_at"]}
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/validate", response_model=ValidateResponse)
async def validate_barcode(data: BarcodeValidateRequest, current_user: dict = Depends(get_current_user)):
    return barcode_service.validate_gtin(data.gtin)


@router.post("/scan", response_model=BarcodeResponse, status_code=status.HTTP_201_CREATED)
async def scan_barcode(
    data: BarcodeScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    rec = await barcode_service.record_scan(db, data.model_dump())
    return {k: rec[k] for k in ["id", "gtin", "entity_type", "entity_id", "format", "raw_data", "created_at"]}


# ── Excel 条码批量生成 ───────────────────────────────────────────────


@router.post("/excel/upload", response_model=dict[str, str | int])
async def upload_barcode_excel(
    file: UploadFile,
    current_user: dict = Depends(get_current_user),
):
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=422, detail="仅支持 .xlsx 文件")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    try:
        import io
        import os
        file.file = io.BytesIO(content)
        zip_bytes = generate_barcode_zip(file)
        filename = f"barcodes_{uuid.uuid4().hex[:8]}.zip"
        # Persist the ZIP so download endpoint can retrieve it
        upload_dir = "/tmp/barcodes"
        os.makedirs(upload_dir, exist_ok=True)
        with open(os.path.join(upload_dir, filename), "wb") as f:
            f.write(zip_bytes)
        return {"filename": filename, "size": len(zip_bytes)}
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


# ── Download generated ZIP file (called after excel/upload) ──────────────


@router.get("/download/{filename}")
async def download_barcode_file(
    filename: str,
    current_user: dict = Depends(get_current_user),
):
    import os
    safe_name = os.path.basename(filename)
    filepath = f"/tmp/barcodes/{safe_name}"
    try:
        with open(filepath, "rb") as f:
            data = f.read()
        from fastapi.responses import Response

        disp = f"attachment; filename={filename}"
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": disp},
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")


# ── Templates — MUST be before /{gtin} ═══════════════════════════════


@router.post("/templates", response_model=LabelTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: LabelTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        tpl = await barcode_service.create_template(db, data.model_dump())
        return LabelTemplateResponse(**tpl)
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/templates", response_model=list[LabelTemplateResponse])
async def list_templates(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    templates = await barcode_service.list_templates(db)
    return [LabelTemplateResponse(**t) for t in templates[skip:skip + limit]]


# ── GTIN lookup — must be last ═══════════════════════════════════════


@router.get("/{gtin}", response_model=list[BarcodeResponse])
async def get_by_gtin(
    gtin: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    records = await barcode_service.get_by_gtin(db, gtin)
    return [
        {k: r[k] for k in ["id", "gtin", "entity_type", "entity_id", "format", "raw_data", "created_at"]}
        for r in records[skip:skip + limit]
    ]
