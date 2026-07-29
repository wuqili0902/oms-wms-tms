import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_session as get_db_session
from src.notification.email import EmailMessage, email_service
from src.notification.models import (
    Notification,
    NotificationChannel,
    NotificationPreference,
    NotificationType,
)
from src.notification.ws import ws_manager

logger = logging.getLogger(__name__)


def _check_enabled(prefs: list[NotificationPreference], ntype: NotificationType, channel: NotificationChannel) -> bool:
    for p in prefs:
        if p.notification_type == ntype and p.channel == channel:
            return p.enabled
    return True


async def send_notification(
    user_id: str,
    ntype: NotificationType,
    channel: NotificationChannel,
    title: str,
    body: str,
    data: dict | None = None,
    user_email: str | None = None,
    db: AsyncSession | None = None,
) -> bool:
    if db is None:
        async with get_db_session() as session:
            return await _do_send(session, user_id, ntype, channel, title, body, data, user_email)
    return await _do_send(db, user_id, ntype, channel, title, body, data, user_email)


async def _do_send(
    db: AsyncSession,
    user_id: str,
    ntype: NotificationType,
    channel: NotificationChannel,
    title: str,
    body: str,
    data: dict | None,
    user_email: str | None,
) -> bool:
    try:
        prefs = await _get_preferences(db, user_id)
        if not _check_enabled(prefs, ntype, channel):
            logger.debug("Notification skipped (preference): user=%s type=%s channel=%s", user_id, ntype, channel)
            return False

        notification = Notification(
            user_id=user_id,
            type=ntype,
            channel=channel,
            title=title,
            body=body,
            data=json.dumps(data, ensure_ascii=False) if data else None,
        )
        db.add(notification)
        await db.commit()

        if channel == NotificationChannel.WEBSOCKET:
            await ws_manager.send_to_user(user_id, {
                "type": "notification",
                "notification_type": ntype.value,
                "title": title,
                "body": body,
                "data": data or {},
                "created_at": datetime.now(UTC).isoformat(),
            })

        if channel == NotificationChannel.EMAIL and user_email:
            email_text = f"[{ntype.value}] {title}\n\n{body}"
            await email_service.send(EmailMessage(to=[user_email], subject=title, body_text=email_text))

        logger.info("Notification sent: user=%s type=%s channel=%s", user_id, ntype, channel)
        return True
    except Exception as e:
        logger.error("Notification failed: user=%s type=%s channel=%s error=%s", user_id, ntype, channel, e)
        return False


async def notify_order_status_change(order_id: int, user_id: str, status: str, order_no: str, db: AsyncSession):
    status_labels = {
        "pending": "待处理", "confirmed": "已确认", "processing": "处理中",
        "shipped": "已发货", "delivered": "已签收", "cancelled": "已取消",
    }
    label = status_labels.get(status, status)
    await send_notification(
        user_id=user_id,
        ntype=NotificationType.ORDER_STATUS_CHANGE,
        channel=NotificationChannel.WEBSOCKET,
        title=f"订单 {order_no} 状态更新",
        body=f"订单 {order_no} 状态变更为：{label}",
        data={"order_id": order_id, "order_no": order_no, "status": status},
        db=db,
    )


async def notify_low_stock(warehouse_id: str, sku: str, current_qty: int, db: AsyncSession):
    from src.auth.models import User as UserModel
    result = await db.execute(select(UserModel.id, UserModel.email).where(UserModel.is_active))
    users = result.all()
    for user_id, user_email in users:
        await send_notification(
            user_id=str(user_id),
            ntype=NotificationType.LOW_STOCK_ALERT,
            channel=NotificationChannel.EMAIL,
            title="库存预警",
            body=f"SKU {sku} 库存不足，当前库存：{current_qty}",
            data={"warehouse_id": warehouse_id, "sku": sku, "current_qty": current_qty},
            user_email=user_email,
            db=db,
        )


async def _get_preferences(db: AsyncSession, user_id: str) -> list[NotificationPreference]:
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    )
    return list(result.scalars().all())
