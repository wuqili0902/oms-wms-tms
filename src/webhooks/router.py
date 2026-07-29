import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.response import success_response
from src.webhooks.models import WebhookEvent, WebhookStatus, WebhookTarget

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


class WebhookCreate(BaseModel):
    name: str
    url: str
    secret: str | None = None
    events: list[str]
    status: str = "active"


class WebhookUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    secret: str | None = None
    events: list[str] | None = None
    status: str | None = None


@router.get("/")
async def list_targets(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(WebhookTarget).order_by(WebhookTarget.created_at.desc()))
    items = result.scalars().all()
    return success_response(data=[
        {
            "id": t.id,
            "name": t.name,
            "url": t.url,
            "events": json.loads(t.events) if t.events else [],
            "status": t.status.value,
            "created_at": t.created_at.isoformat() if t.created_at else "",
        }
        for t in items
    ])


@router.post("/")
async def create_target(
    data: WebhookCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    for ev in data.events:
        if ev not in [e.value for e in WebhookEvent]:
            raise HTTPException(status_code=422, detail=f"Invalid event: {ev}")
    target = WebhookTarget(
        name=data.name,
        url=data.url,
        secret=data.secret,
        events=json.dumps(data.events),
        status=WebhookStatus(data.status),
    )
    db.add(target)
    await db.commit()
    await db.refresh(target)
    return success_response(data={"id": target.id}, message="Webhook target created")


@router.put("/{target_id}")
async def update_target(
    target_id: int,
    data: WebhookUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(WebhookTarget).where(WebhookTarget.id == target_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Webhook target not found")
    if data.name is not None:
        target.name = data.name
    if data.url is not None:
        target.url = data.url
    if data.secret is not None:
        target.secret = data.secret
    if data.events is not None:
        for ev in data.events:
            if ev not in [e.value for e in WebhookEvent]:
                raise HTTPException(status_code=422, detail=f"Invalid event: {ev}")
        target.events = json.dumps(data.events)
    if data.status is not None:
        target.status = WebhookStatus(data.status)
    await db.commit()
    return success_response(message="Webhook target updated")


@router.delete("/{target_id}")
async def delete_target(
    target_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(WebhookTarget).where(WebhookTarget.id == target_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Webhook target not found")
    await db.execute(delete(WebhookTarget).where(WebhookTarget.id == target_id))
    await db.commit()
    return success_response(message="Webhook target deleted")
