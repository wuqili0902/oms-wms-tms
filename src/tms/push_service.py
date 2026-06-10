"""Push notification service.

Provides a notification abstraction layer. In production, this would
integrate with Firebase Cloud Messaging (FCM) for Android and
Apple Push Notification Service (APNs) for iOS.

The TMS device model already stores push_token — this service uses it
to send notifications to registered devices.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class NotificationPriority(str, Enum):
    """Notification priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass
class PushMessage:
    """Structured push notification message."""

    title: str
    body: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    data: dict = field(default_factory=dict)
    topic: Optional[str] = None


class PushService:
    """Push notification service with FCM/APNs stubs.

    In production, use firebase-admin SDK for FCM:
        import firebase_admin
        from firebase_admin import messaging
    """

    def __init__(self):
        self._sent_count = 0
        self._failed_count = 0

    async def send_to_device(self, push_token: str, message: PushMessage) -> bool:
        """Send a push notification to a single device.

        Returns True if the notification was sent successfully.
        """
        try:
            # In production: messaging.send(messaging.Message(
            #     token=push_token,
            #     notification=messaging.Notification(title=message.title, body=message.body),
            #     data=message.data,
            # ))
            logger.info(
                "Push notification to device: title=%s body=%s priority=%s",
                message.title, message.body, message.priority.value,
            )
            self._sent_count += 1
            return True
        except Exception as e:
            logger.error("Push notification failed: %s", str(e))
            self._failed_count += 1
            return False

    async def send_to_topic(self, topic: str, message: PushMessage) -> bool:
        """Send a push notification to a topic (broadcast).

        Topics allow sending to groups of devices without knowing
        individual tokens. E.g., 'warehouse:WH-001' or 'all_users'.
        """
        try:
            logger.info(
                "Push notification to topic '%s': title=%s body=%s",
                topic, message.title, message.body,
            )
            self._sent_count += 1
            return True
        except Exception as e:
            logger.error("Topic push failed: %s", str(e))
            self._failed_count += 1
            return False

    async def send_order_status_update(
        self, push_token: str, order_no: str, status: str
    ) -> bool:
        """Send a standardized order status update notification."""
        status_labels = {
            "confirmed": "已确认",
            "processing": "处理中",
            "picking": "拣货中",
            "completed": "已完成",
            "cancelled": "已取消",
        }
        label = status_labels.get(status, status)
        return await self.send_to_device(
            push_token,
            PushMessage(
                title="订单状态更新",
                body=f"订单 {order_no} 状态更新为：{label}",
                priority=NotificationPriority.NORMAL,
                data={"order_no": order_no, "status": status, "timestamp": datetime.now(timezone.utc).isoformat()},
            ),
        )

    @property
    def stats(self) -> dict:
        """Get push notification statistics."""
        return {"sent": self._sent_count, "failed": self._failed_count}


# Singleton
push_service = PushService()
