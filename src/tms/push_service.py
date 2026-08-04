"""Push notification service for transport events.

Integrates with Firebase Cloud Messaging (FCM) and Apple Push Notification Service (APNs).
Uses the push_token stored on TerminalDevice to route notifications.

When Firebase is not configured, falls back to logging (safe no-op).
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

logger = logging.getLogger(__name__)


class NotificationPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass
class PushMessage:
    title: str
    body: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    data: dict = field(default_factory=dict)
    topic: str | None = None
    android_channel_id: str | None = "tms_transport"


_firebase_available = False
_firebase_app = None


def _init_firebase():
    """Initialize Firebase Admin SDK if configured."""
    global _firebase_available, _firebase_app
    if _firebase_available or _firebase_app is not None:
        return True
    try:
        from src.config import settings

        if not settings.firebase_credentials_path:
            logger.info("Firebase not configured — push notifications will be logged only")
            return False
        import firebase_admin
        from firebase_admin import credentials

        cred = credentials.Certificate(settings.firebase_credentials_path)
        _firebase_app = firebase_admin.initialize_app(cred)
        _firebase_available = True
        logger.info("Firebase initialized from %s", settings.firebase_credentials_path)
        return True
    except ImportError:
        logger.info("firebase_admin not installed — push notifications will be logged only")
        return False
    except Exception as e:
        logger.error("Firebase initialization failed: %s", str(e))
        return False


def _send_fcm(message: PushMessage, token: str) -> bool:
    """Send via Firebase Cloud Messaging."""
    try:
        from firebase_admin import messaging

        android_config = None
        if message.android_channel_id:
            android_config = messaging.AndroidConfig(
                notification=messaging.AndroidNotification(
                    channel_id=message.android_channel_id,
                    priority="high" if message.priority == NotificationPriority.HIGH else "normal",
                ),
            )

        fcm_message = messaging.Message(
            token=token,
            notification=messaging.Notification(title=message.title, body=message.body),
            data={k: str(v) for k, v in message.data.items()},
            android=android_config,
        )
        messaging.send(fcm_message)
        return True
    except Exception as e:
        logger.error("FCM send failed: %s", str(e))
        return False


class PushService:
    """Push notification service with FCM/APNs integration."""

    def __init__(self):
        self._sent_count = 0
        self._failed_count = 0
        self._fcm_ready = _init_firebase()

    async def send_to_device(self, push_token: str, message: PushMessage) -> bool:
        """Send a push notification to a single device."""
        try:
            if self._fcm_ready:
                import asyncio
                success = await asyncio.get_running_loop().run_in_executor(
                    None, _send_fcm, message, push_token
                )
                if success:
                    self._sent_count += 1
                    return True
                self._failed_count += 1
                return False

            logger.info(
                "Push notification (no-op): token=%s title=%s body=%s priority=%s",
                push_token[:16] + "..." if len(push_token) > 16 else push_token,
                message.title, message.body, message.priority.value,
            )
            self._sent_count += 1
            return True
        except Exception as e:
            logger.error("Push notification failed: %s", str(e))
            self._failed_count += 1
            return False

    async def send_to_topic(self, topic: str, message: PushMessage) -> bool:
        """Send a push notification to a topic (broadcast)."""
        try:
            if self._fcm_ready:
                import asyncio

                from firebase_admin import messaging

                success = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: messaging.send(messaging.Message(
                        topic=topic,
                        notification=messaging.Notification(title=message.title, body=message.body),
                        data={k: str(v) for k, v in message.data.items()},
                    )),
                )
                if success:
                    self._sent_count += 1
                    return True
                self._failed_count += 1
                return False

            logger.info("Topic push (no-op) to '%s': title=%s body=%s", topic, message.title, message.body)
            self._sent_count += 1
            return True
        except Exception as e:
            logger.error("Topic push failed: %s", str(e))
            self._failed_count += 1
            return False

    # ── Convenience methods for transport events ────────────────────────────────

    async def notify_status_update(self, device_id: str, order_no: str, status: str) -> bool:
        """Notify about transport order status change."""
        status_labels = {
            "dispatched": "已发车",
            "in_transit": "运输中",
            "out_for_delivery": "派送中",
            "delivered": "已签收",
            "exception": "异常处理中",
        }
        label = status_labels.get(status, status)
        return await self.send_to_device(
            device_id,
            PushMessage(
                title="物流状态更新",
                body=f"运单 {order_no} 状态更新为：{label}",
                data={"transport_order": order_no, "status": status},
                priority=NotificationPriority.HIGH if status in ("exception",) else NotificationPriority.NORMAL,
            ),
        )

    async def notify_delivery(self, device_id: str, tracking_number: str, eta: datetime | None = None) -> bool:
        """Notify about successful delivery."""
        return await self.send_to_device(
            device_id,
            PushMessage(
                title="包裹已签收",
                body=f"运单 {tracking_number} 已成功签收",
                data={"tracking": tracking_number},
                priority=NotificationPriority.HIGH,
            ),
        )

    async def notify_exception(self, device_id: str, transport_no: str, issue: str) -> bool:
        """Notify about transport exception."""
        return await self.send_to_device(
            device_id,
            PushMessage(
                title="运输异常通知",
                body=f"运单 {transport_no} 出现异常：{issue}",
                data={"transport_order": transport_no, "exception": issue},
                priority=NotificationPriority.HIGH,
            ),
        )

    async def send_order_status_update(self, push_token: str, order_id: str, status: str) -> bool:
        """Legacy alias for test compatibility."""
        return await self.notify_status_update(push_token, order_id, status)

    @property
    def stats(self) -> dict:
        return {"sent": self._sent_count, "failed": self._failed_count}


push_service = PushService()
