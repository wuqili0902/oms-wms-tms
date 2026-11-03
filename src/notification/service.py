import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_session as get_db_session
from src.core.ws_fanout import publish_notify
from src.notification.email import EmailMessage, email_service
from src.notification.models import (
    Notification,
    NotificationChannel,
    NotificationPreference,
    NotificationType,
)
from src.notification.ws import ws_manager

logger = logging.getLogger(__name__)


class NotificationDeliveryError(Exception):
    """Raised when notification delivery fails after retry/logging."""
    pass


def _check_enabled(prefs: list[NotificationPreference], ntype: NotificationType, channel: NotificationChannel) -> bool:
    for p in prefs:
        if p.notification_type == ntype and p.channel == channel:
            return p.enabled
    return True  # default to enabled if no explicit preference found


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
            sent = await _do_send(session, user_id, ntype, channel, title, body, data, user_email)
            # Standalone session — nobody else is going to commit it.
            if sent:
                await session.commit()
            else:
                await session.rollback()
            return sent
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
    """Persist the notification on the caller's session, then deliver it.

    The record used to be written through a session taken from the global
    engine — so a notification describing a change made on an injected session
    (every test session, any Celery/bridge session, anything that swaps
    engines) landed in a database nobody could read back, and the pool behind
    that engine belonged to whatever event loop first touched it.

    Writing on the caller's session through a SAVEPOINT keeps the isolation the
    old comment promised — a failed notification write rolls back by itself and
    never takes the caller's transaction down — while putting the row in the
    same database as the change it reports.
    """
    try:
        prefs = await _get_preferences(db, user_id)
    except Exception as e:  # noqa: BLE001 — a broken preferences read must not 500 the caller
        logger.error("Notification preferences read failed: user=%s error=%s", user_id, e)
        return False

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

    try:
        async with db.begin_nested():  # SAVEPOINT: notification-only rollback
            db.add(notification)
            await db.flush()
    except Exception as e:  # noqa: BLE001 — reported to the caller as "not sent"
        logger.error("Notification failed: user=%s type=%s channel=%s error=%s", user_id, ntype, channel, e)
        return False

    if channel == NotificationChannel.WEBSOCKET:
        try:
            ws_payload = {
                "type": "notification",
                "notification_type": ntype.value,
                "title": title,
                "body": body,
                "data": data or {},
                "created_at": datetime.now(UTC).isoformat(),
            }
            # Fan out across API workers via Redis; if Redis is down fall back
            # to this process's sockets only.
            if not await publish_notify(user_id, ws_payload):
                await ws_manager.send_to_user(user_id, ws_payload)
        except Exception as e:  # noqa: BLE001 — the record is already saved
            logger.error(
                "WebSocket notification failed (DB saved): user=%s type=%s error=%s",
                user_id, ntype, e,
            )

    if channel == NotificationChannel.EMAIL:
        if user_email:
            try:
                email_text = f"[{ntype.value}] {title}\n\n{body}"
                await email_service.send(EmailMessage(to=[user_email], subject=title, body_text=email_text))
            except Exception as e:  # noqa: BLE001 — surfaced to callers that count failures
                logger.error(
                    "Email notification failed (DB saved): user=%s type=%s error=%s",
                    user_id, ntype, e,
                )
                raise NotificationDeliveryError(f"Email send failed: {e}") from e
        else:
            logger.debug("Email skipped (no email provided): user=%s type=%s", user_id, ntype)

    logger.info("Notification sent: user=%s type=%s channel=%s", user_id, ntype, channel)
    return True


async def notify_order_status_change(order_id: int, user_id: str, status: str, order_no: str, db: AsyncSession):
    status_labels = {
        "pending": "待处理", "confirmed": "已确认", "processing": "处理中",
        "shipped": "已发货", "delivered": "已签收", "cancelled": "已取消",
    }
    label = status_labels.get(status, status)
    try:
        await send_notification(
            user_id=user_id,
            ntype=NotificationType.ORDER_STATUS_CHANGE,
            channel=NotificationChannel.WEBSOCKET,
            title=f"订单 {order_no} 状态更新",
            body=f"订单 {order_no} 状态变更为：{label}",
            data={"order_id": order_id, "order_no": order_no, "status": status},
            db=db,
        )
    except NotificationDeliveryError:
        logger.warning("Failed to deliver order status notification: user=%s order=%s", user_id, order_no)


async def notify_low_stock(warehouse_id: str, sku: str, current_qty: int, db: AsyncSession):
    from src.auth.models import User as UserModel
    result = await db.execute(select(UserModel.id, UserModel.email).where(UserModel.is_active))
    users = result.all()

    if not users:
        return

    max_recipients = 500
    if len(users) > max_recipients:
        logger.warning(
            "Low stock alert for SKU %s exceeds max recipients (%d/%d), sending to first %d",
            sku, len(users), max_recipients, max_recipients,
        )

    failures = 0
    total_sent = 0
    for user_id, user_email in users[:max_recipients]:
        try:
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
            total_sent += 1
        except NotificationDeliveryError:
            failures += 1

    if failures > 0 or total_sent != len(users[:max_recipients]):
        remaining = max(0, len(users) - max_recipients)
        if remaining > 0:
            logger.warning(
                "Low stock notification sent to %d/%d users (SKU=%s), %d skipped due to batch limit",
                total_sent, len(users), sku, remaining,
            )
        else:
            logger.warning(
                "Low stock notification failed for %d/%d users (SKU=%s)",
                failures, len(users[:max_recipients]), sku,
            )


async def _get_preferences(db: AsyncSession, user_id: str) -> list[NotificationPreference]:
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    )
    return list(result.scalars().all())
