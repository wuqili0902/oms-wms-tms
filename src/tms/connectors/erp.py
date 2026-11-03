"""TMS ERP/EDI Connector — Transport-specific ERP synchronization.

Wraps the shared ERP connector (src.models.erp_connector) with TMS-specific
workflows: transport order sync, carrier tracking updates, and ASN exchange.

Integration flows:
  1. Transport Order → ERP (SAP IDOC DELJRN / EDI 856)
  2. Carrier Tracking → ERP (POD, exception events)
  3. Inbound ERP messages → TMS (rate load, carrier assignment)
"""
import hashlib
import json
from datetime import UTC, datetime

from src.core.exceptions import NotImplementedActionException
from src.models.erp_connector import (
    ERPMessage,
    MessageType,
    OracleEDIConnector,
    OrderSyncService,
    SAPPIConnector,
)


class TMSSyncService:
    """Bidirectional TMS ↔ ERP sync for transport operations.

    Flow (outbound — transport order → ERP):
        1. TMS generates route plan / transport order
        2. TMSSyncService converts to DELJRN (SAP IDOC) or 856 (EDI)
        3. Sends via SAP PI or Oracle EDI connector
        4. ERP acknowledges

        Flow (inbound — ERP → TMS):
        1. ERP sends carrier assignment / rate change
        2. TMS receives and updates transport order

    The outbound flow needs a SAP PI host or an EDI gateway.  This deployment has
    neither (no config, no endpoint, no caller), so ``sync_transport_order`` and
    ``sync_tracking_event`` raise ``NotImplementedActionException`` when no
    connector was passed in — they no longer answer with ``uuid4``, which every
    screen reading it renders as an ERP acknowledgment that was never received.
    """

    def __init__(
        self,
        sap_connector: SAPPIConnector | None = None,
        edi_connector: OracleEDIConnector | None = None,
        order_sync: OrderSyncService | None = None,
    ):
        self.sap = sap_connector
        self.edi = edi_connector
        self._order_sync = order_sync

    @property
    def order_sync(self) -> OrderSyncService:
        if self._order_sync is None:
            self._order_sync = OrderSyncService(
                sap_connector=self.sap, edifact_conn=self.edi
            )
        return self._order_sync

    async def sync_transport_order(self, order_id: str) -> str:
        """Send transport order status to ERP as DELJRN / 856.

        Returns the ERP's message ID.  With no connector configured nothing was
        sent — and the ``uuid4`` this used to hand back reads, on every screen
        that shows it, as "ERP acknowledged this transport order".
        """
        msg = ERPMessage(
            msg_type=MessageType.DELJRN,
            sender_id="TMS",
            receiver_id="ERP",
            payload={
                "transport_order_id": order_id,
                "synced_at": datetime.now(UTC).isoformat(),
            },
        )
        if self.sap:
            return self.sap.send_edi({"raw": json.dumps(msg.model_dump(mode="json"))})
        if self.edi:
            raise self._built_not_sent("同步运输单", order_id, self._checksum(self.edi.serialize(msg)))
        raise self._no_transport("同步运输单", order_id)

    @staticmethod
    def _no_transport(action: str, identifier: str) -> NotImplementedActionException:
        return NotImplementedActionException(
            message=(
                f"{action}（{identifier}）未执行：本系统未配置 SAP PI / Oracle EDI 连接器，"
                "也没有对外传输端点——此处只有报文构造与序列化。"
            ),
            detail={"identifier": identifier, "configured": False},
        )

    @staticmethod
    def _built_not_sent(action: str, identifier: str, checksum: str) -> NotImplementedActionException:
        """A serialized 856 is a file on disk, not a delivery.

        The md5 of our own serialization is a checksum of what we built; the ERP
        side never saw it, so it is not an acknowledgment.
        """
        return NotImplementedActionException(
            message=(
                f"{action}（{identifier}）报文已构造、未发送：EDI 侧只做了序列化，"
                f"校验和 {checksum} 是本系统对自己生成的报文的哈希，不是 ERP 回执。"
            ),
            detail={"identifier": identifier, "checksum": checksum, "sent": False},
        )

    @staticmethod
    def _checksum(serialized: str) -> str:
        return hashlib.md5(serialized.encode()).hexdigest()

    async def sync_tracking_event(
        self,
        transport_order_id: str,
        event_type: str,
        details: dict | None = None,
    ) -> str:
        """Push a tracking / POD event to ERP. Returns the ERP's message ID."""
        msg = ERPMessage(
            msg_type=MessageType.DESADV,
            sender_id="TMS",
            receiver_id="ERP",
            payload={
                "transport_order_id": transport_order_id,
                "event_type": event_type,
                "details": details or {},
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        if self.sap:
            return self.sap.send_edi({"raw": json.dumps(msg.model_dump(mode="json"))})
        if self.edi:
            raise self._built_not_sent(
                "推送轨迹/POD 事件", transport_order_id, self._checksum(self.edi.serialize(msg))
            )
        raise self._no_transport("推送轨迹/POD 事件", transport_order_id)

    async def handle_inbound_rate_update(self, msg: ERPMessage) -> int:
        """Process incoming rate / carrier assignment from ERP.

        Returns number of transport orders updated.
        """
        payload = msg.payload
        if not isinstance(payload, dict):
            return 0
        carrier_code = payload.get("carrier_code")
        rate_data = payload.get("rate_data")
        if not carrier_code or not rate_data:
            return 0
        from src.tms.service import update_carrier_rate

        return await update_carrier_rate(carrier_code, rate_data)
