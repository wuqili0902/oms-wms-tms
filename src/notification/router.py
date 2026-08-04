import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.response import success_response
from src.notification.models import (
    Notification,
    NotificationChannel,
    NotificationPreference,
    NotificationType,
)
from src.notification.ws import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("/")
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.get("uid")
    query = select(Notification).where(Notification.user_id == uid).order_by(Notification.created_at.desc())
    if unread_only:
        query = query.where(~Notification.is_read)
    count_q = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0
    offset = (page - 1) * page_size
    result = await db.execute(query.offset(offset).limit(page_size))
    items = result.scalars().all()
    return success_response(data={
        "items": [
            {
                "id": n.id,
                "type": n.type.value,
                "channel": n.channel.value,
                "title": n.title,
                "body": n.body,
                "data": n.data,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.get("uid")
    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == uid)
        .values(is_read=True, read_at=datetime.now(UTC))
    )
    await db.commit()
    return success_response(message="Marked as read")


@router.post("/read-all")
async def mark_all_read(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.get("uid")
    await db.execute(
        update(Notification)
        .where(Notification.user_id == uid, ~Notification.is_read)
        .values(is_read=True, read_at=datetime.now(UTC))
    )
    await db.commit()
    return success_response(message="All marked as read")


@router.get("/preferences")
async def get_preferences(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.get("uid")
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == uid)
    )
    prefs = result.scalars().all()
    return success_response(data=[
        {
            "id": p.id,
            "notification_type": p.notification_type.value,
            "channel": p.channel.value,
            "enabled": p.enabled,
        }
        for p in prefs
    ])


@router.put("/preferences")
async def update_preferences(
    preferences: list[dict],
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.get("uid")
    await db.execute(delete(NotificationPreference).where(NotificationPreference.user_id == uid))
    for pref in preferences:
        db.add(NotificationPreference(
            user_id=uid,
            notification_type=NotificationType(pref["notification_type"]),
            channel=NotificationChannel(pref["channel"]),
            enabled=pref.get("enabled", True),
        ))
    await db.commit()
    return success_response(message="Preferences updated")


@router.websocket("/ws")
async def notification_websocket(websocket: WebSocket):
    user_id = None
    try:
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4001)
            return
        from src.core.security import decode_token
        payload = decode_token(token)
        uid = payload.get("uid")
        if not uid:
            await websocket.close(code=4001)
            return
        user_id = uid
    except (ValueError, json.JSONDecodeError, KeyError, WebSocketDisconnect):
        await websocket.close(code=4001)
        return

    await ws_manager.connect(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            logger.debug("WS message from user %s: %s", user_id, data)
    except WebSocketDisconnect:
        ws_manager.disconnect(user_id, websocket)
    except Exception as e:
        logger.warning("WS error user=%s: %s", user_id, e)
        ws_manager.disconnect(user_id, websocket)
