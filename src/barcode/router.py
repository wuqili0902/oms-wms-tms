"""Barcode API router.

/templates routes MUST be before /{gtin} to avoid FastAPI path-parameter matching.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.barcode.schemas import (
    BarcodeGenerateRequest,
    BarcodeResponse,
    BarcodeScanRequest,
    BarcodeValidateRequest,
    LabelTemplateCreate,
    LabelTemplateResponse,
)
from src.barcode import service as barcode_service
from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.exceptions import ValidationException

router = APIRouter(prefix="/barcode", tags=["barcode"])


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


@router.post("/validate")
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


# ═══ Templates — MUST be before /{gtin} ═══════════════════════════════════════

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
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    templates = await barcode_service.list_templates(db)
    return [LabelTemplateResponse(**t) for t in templates]


# ═══ GTIN lookup — must be last ═══════════════════════════════════════════════

@router.get("/{gtin}", response_model=list[BarcodeResponse])
async def get_by_gtin(
    gtin: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    records = await barcode_service.get_by_gtin(db, gtin)
    return [
        {k: r[k] for k in ["id", "gtin", "entity_type", "entity_id", "format", "raw_data", "created_at"]}
        for r in records
    ]
