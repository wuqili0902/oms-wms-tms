import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException, ValidationException
from src.logistics.carriers import CARRIER_NAMES, generate_tracking_number
from src.logistics.kdniao import get_tracking_url, validate_carrier
from src.logistics.models import Waybill
from src.logistics.schemas import CreateWaybillRequest
from src.models.base import model_to_dict


async def create_waybill(db: AsyncSession, req: CreateWaybillRequest) -> dict:
    code = validate_carrier(req.carrier_code) or "zto"
    tracking = generate_tracking_number(code, req.order_id)
    carrier_name = CARRIER_NAMES.get(code, "")

    now = datetime.now(UTC)
    waybill = Waybill(
        id=uuid.uuid4(),
        tracking_number=tracking,
        order_id=req.order_id,
        carrier_code=code,
        carrier_name=carrier_name,
        recipient_name=req.recipient_name,
        recipient_phone=req.recipient_phone,
        recipient_address=req.recipient_address,
        items=req.items,
        status="created",
        print_count=0,
        label_url=get_tracking_url(code, tracking),
        created_at=now,
        updated_at=now,
    )
    db.add(waybill)
    await db.commit()
    await db.refresh(waybill)
    return model_to_dict(waybill)


async def get_waybill(db: AsyncSession, tracking: str) -> dict:
    result = await db.execute(
        select(Waybill).where(
            Waybill.tracking_number == tracking,
            Waybill.is_deleted.is_(False),
        )
    )
    wb = result.scalar_one_or_none()
    if not wb:
        raise NotFoundException(message=f"运单 {tracking} 不存在")
    return model_to_dict(wb)


async def list_waybills(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    carrier: str | None = None,
    q: str | None = None,
) -> dict:
    query = select(Waybill).where(Waybill.is_deleted.is_(False))
    count_query = select(func.count(Waybill.id)).where(Waybill.is_deleted.is_(False))

    if status:
        query = query.where(Waybill.status == status)
        count_query = count_query.where(Waybill.status == status)
    if carrier:
        query = query.where(Waybill.carrier_code == carrier)
        count_query = count_query.where(Waybill.carrier_code == carrier)
    if q:
        like = f"%{q}%"
        query = query.where(
            Waybill.tracking_number.ilike(like)
            | Waybill.order_id.ilike(like)
            | Waybill.recipient_name.ilike(like)
        )
        count_query = count_query.where(
            Waybill.tracking_number.ilike(like)
            | Waybill.order_id.ilike(like)
            | Waybill.recipient_name.ilike(like)
        )

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(Waybill.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = [model_to_dict(row) for row in result.scalars().all()]

    return {"items": items, "total": total}


async def void_waybill(db: AsyncSession, tracking: str) -> dict:
    result = await db.execute(
        select(Waybill).where(
            Waybill.tracking_number == tracking,
            Waybill.is_deleted.is_(False),
        )
    )
    wb = result.scalar_one_or_none()
    if not wb:
        raise NotFoundException(message=f"运单 {tracking} 不存在")
    if wb.status == "voided":
        raise ValidationException(message=f"运单 {tracking} 已作废")

    wb.status = "voided"
    wb.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(wb)
    return model_to_dict(wb)


async def mark_printed(db: AsyncSession, tracking: str) -> dict:
    result = await db.execute(
        select(Waybill).where(
            Waybill.tracking_number == tracking,
            Waybill.is_deleted.is_(False),
        )
    )
    wb = result.scalar_one_or_none()
    if not wb:
        raise NotFoundException(message=f"运单 {tracking} 不存在")

    wb.print_count = (wb.print_count or 0) + 1
    wb.last_printed_at = datetime.now(UTC)
    wb.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(wb)
    return model_to_dict(wb)
