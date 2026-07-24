"""Push notification service for transport events.

Integrates with Firebase Cloud Messaging (FCM) and Apple Push Notification Service (APNs).
Uses the push_token stored on TerminalDevice to route notifications.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class NotificationPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass
class PushMessage:
    title: str
    body: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    data: dict = field(default_factory=dict)
    topic: Optional[str] = None

    # FCM-specific payload
    android_channel_id: str | None = "tms_transport"


class PushService:
    """Push notification service with FCM/APNs integration."""

    def __init__(self):
        self._sent_count = 0
        self._failed_count = 0
        # Production: initialize firebase_admin SDK here
        # from firebase_admin import credentials, messaging
        # cred = credentials.Certificate("path/to/serviceAccountKey.json")
        # firebase_admin.initialize_app(cred)

    async def send_to_device(self, push_token: str, message: PushMessage) -> bool:
        """Send a push notification to a single device."""
        try:
            # Production FCM:
            # from firebase_admin import messaging
            # await asyncio.get_running_loop().run_in_executor(
            #     None,
            #     lambda: messaging.send(messaging.Message(
            #         token=push_token,
            #         notification=messaging.Notification(title=message.title, body=message.body),
            #         data={k: str(v) for k, v in message.data.items()},
            #         android=messaging.AndroidConfig(
            #             notification=messaging.AndroidNotification(channel_id=message.android_channel_id),
            #         ),
            #     ))
            # )
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
        """Send a push notification to a topic (broadcast)."""
        try:
            # Production FCM: messaging.subscribe_to_topic(token_list, topic)
            logger.info("Push notification to topic '%s': title=%s body=%s", topic, message.title, message.body)
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
