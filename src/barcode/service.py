"""Barcode business logic — GTIN generation, validation, scan recording.

All CRUD functions are async and require an ``AsyncSession``.
Pure helpers (GTIN) remain synchronous.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.barcode.models import BarcodeRecord, LabelTemplate
from src.core.exceptions import ValidationException
from src.models.base import model_to_dict

# ── GTIN helpers (pure, no DB) ──────────────────────────────────────────────

def _calc_check_digit(digits: str) -> int:
    """Calculate EAN-13 check digit."""
    total = 0
    for i, ch in enumerate(digits):
        weight = 1 if i % 2 == 0 else 3
        total += int(ch) * weight
    return (10 - (total % 10)) % 10


def generate_gtin(prefix: str) -> str:
    """Generate a full GTIN from a prefix by appending a check digit."""
    cleaned = "".join(ch for ch in prefix if ch.isdigit())
    if len(cleaned) < 7 or len(cleaned) > 12:
        raise ValidationException(message=f"GTIN prefix must be 7-12 digits, got {len(cleaned)}")
    padded = cleaned.ljust(12, "0")
    check = _calc_check_digit(padded)
    return padded + str(check)


def validate_gtin(gtin: str) -> dict:
    """Validate a full GTIN string."""
    cleaned = "".join(ch for ch in gtin if ch.isdigit())
    if len(cleaned) not in (8, 12, 13, 14):
        return {"valid": False, "reason": f"Invalid length: {len(cleaned)} (expected 8, 12, 13, or 14)"}
    if len(cleaned) == 13:
        prefix = cleaned[:12]
        expected_check = _calc_check_digit(prefix)
        actual_check = int(cleaned[12])
        if actual_check != expected_check:
            return {"valid": False, "reason": f"Check digit mismatch: expected {expected_check}, got {actual_check}"}
    return {"valid": True, "gtin": cleaned, "format": "ean13" if len(cleaned) == 13 else "other"}


# ── Barcode records ─────────────────────────────────────────────────────────

async def generate_barcode(db: AsyncSession, data: dict) -> dict:
    """Generate a GTIN and persist the barcode record."""
    gtin = generate_gtin(data["gtin_prefix"])
    now = datetime.now(UTC)
    rec = BarcodeRecord(
        id=uuid.uuid4(),
        gtin=gtin,
        entity_type=data["entity_type"],
        entity_id=uuid.UUID(data["entity_id"]) if isinstance(data["entity_id"], str) else data["entity_id"],
        format=data.get("format", "ean13"),
        raw_data=gtin,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return model_to_dict(rec)


async def record_scan(db: AsyncSession, data: dict) -> dict:
    """Record a barcode scan event."""
    raw = data["raw_data"]
    now = datetime.now(UTC)
    rec = BarcodeRecord(
        id=uuid.uuid4(),
        gtin=raw.strip(),
        entity_type="scan",
        entity_id=uuid.uuid4(),
        format="code128",
        raw_data=raw,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return model_to_dict(rec)


async def get_by_gtin(db: AsyncSession, gtin: str) -> list[dict]:
    """Look up barcode records by GTIN."""
    result = await db.execute(select(BarcodeRecord).where(BarcodeRecord.gtin == gtin))
    return [model_to_dict(row) for row in result.scalars().all()]


# ── Label templates ─────────────────────────────────────────────────────────

async def create_template(db: AsyncSession, data: dict) -> dict:
    """Create a new label template."""
    existing = await db.execute(select(LabelTemplate).where(LabelTemplate.code == data["code"]))
    if existing.scalar_one_or_none():
        raise ValidationException(message=f"Template code '{data['code']}' already exists")

    now = datetime.now(UTC)
    tpl = LabelTemplate(
        id=uuid.uuid4(),
        name=data["name"],
        code=data["code"],
        format=data.get("format", "zpl"),
        width_mm=data.get("width_mm", 50),
        height_mm=data.get("height_mm", 30),
        content=data.get("content", {}),
        is_default=data.get("is_default", False),
        created_at=now,
        updated_at=now,
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return model_to_dict(tpl)


async def list_templates(db: AsyncSession) -> list[dict]:
    """List all label templates."""
    result = await db.execute(select(LabelTemplate).order_by(LabelTemplate.created_at.desc()))
    return [model_to_dict(row) for row in result.scalars().all()]
