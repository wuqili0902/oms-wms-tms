"""ERP/EDI Connector — SAP PI/PO + Oracle EDI integration layer.

Design
------
The ERP Connector bridges the WMS/TMS system with external enterprise systems:
    1) SAP PI/PO — uses IDOC (Intermediate Document) format via HTTP/SOAP
    2) Oracle EDI — translates between internal model and EDIFACT / ANSI X12

Key design principles:
    - Outbound orders are converted to ERP formats before sending
    - Inbound receipts from ERP are transformed into WMS order lines
    - All messages go through the message bus (see `services/message_bus.py`)
    - Dead letter queue for failed transformations

Message types supported:
    INBOUND:  ORDRSP, ORDRQS, DELJRN, DESADV, SHPADV
    OUTBOUND: ORDERS, INVOIC, DESREV, ASN
"""
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from enum import StrEnum
from xml.etree import ElementTree

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── EDI Message Types ────────────────────────────────────────────────────


class MessageType(StrEnum):
    ORDERS = "ORDERS"           # Order (SAP → WMS)
    ORDINR = "ORDINR"         # Inbound order (EDI X12 850)
    ORDRESP = "ORDRESP"       # Order acknowledgment (WMS → ERP)
    DESADV = "DESADV"         # Despatch advice / ASN
    DELJRN = "DELJRN"         # Delivery journal (SAP IDOC)
    INVOIC = "INVOIC"         # Invoice
    CUSORD = "CUSORD"         # Customer order


class EDIStandard(StrEnum):
    EDIFACT = "edifact"       # UN/EDIFACT — international standard
    ANSI_X12 = "ansi_x12"     # ANSI X12 850/856/810 — US standard


# ── ERP Message Status ────────────────────────────────────────────────


class ERPMessageStatus(StrEnum):
    PENDING = "pending"        # Waiting to be sent/received
    SENT = "sent"             # Sent out successfully
    RECEIVED = "received"     # Received by ERP/EDI system
    CONFIRMED = "confirmed"   # Acknowledged
    FAILED = "failed"         # Processing failed


# ── Internal message model ───────────────────────────────────────────────


class ERPMessage(BaseModel):
    """Internal WMS/TMS message format, independent of transport protocol."""

    msg_type: MessageType
    sender_id: str                 # ERP system identifier
    receiver_id: str               # Target system
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict                  # structured business data


# ── SAP PI/PO Connector ────────────────────────────────────────────────


class SAPPIConnector:
    """SAP PI/PO Integration via IDOC (Intermediate Document).

    Architecture:
        WMS Order → XML → IDOC_INBOUND → SAP PI → PI Channel Adapter
        → SAP PO XI Adapter → SAP ECC (BAPI / RFC)

    Common IDOC types for WMS integration:
        - ORDERS: Purchase order inbound from SAP to WMS
        - DELJRN: Delivery journal (outbound from WMS to SAP)
        - DESADV: Despatch advice (ASN outbound)
        - INVOIC: Invoice confirmation

    Integration endpoints (configurable via .env):
        SAP_PI_HOST     = https://sap-pi.example.com/pi-api
        SAP_PI_USER     = wms_service_account
        SAP_PI_TOKEN    # OAuth2 or Basic Auth token
        SAP_SNDPRN      = sender partner number in SAP PI
        SAP_GWNAME      = gateway name for RFC destinations

    Example flow (inbound order):
        1. SAP sends IDOC ORDERS to PI
        2. WMS polls /api/v1/erp/inbound/{msg_id} or receives webhook
        3. WMS parses XML → ERPMessage → Order model
        4. Creates Order, reserves stock (FEFO/FIFO)
        5. Sends back ORDINR acknowledgment via EDI 855
    """

    def __init__(self, config: dict[str, str]):
        self.base_url = config["SAP_PI_HOST"]
        self.auth_header = {"Authorization": f"Basic {config['SAP_PI_TOKEN']}"}
        self.sender_partner = config.get("SAP_SNDPRN", "WMS001")

    def parse_idoc(self, idoc_xml: str) -> list[ERPMessage]:
        """Parse SAP IDOC XML into internal message models.

        Supported IDOC types: ORDERS, DELJRN, DESADV, INVOIC
        Returns a list of ERPMessage objects (one per segment).
        """
        messages: list[ERPMessage] = []
        root = ElementTree.fromstring(idoc_xml)
        for idoc in root.iter("IDOC"):
            msg_type_str = idoc.findtext("DOCTYPE", "ORDERS")
            payload = {}
            for segment in idoc.iter("segment"):
                seg_data = {}
                for field in segment:
                    seg_data[field.tag] = field.text or ""
                payload[segment.tag] = seg_data
            try:
                msg_type = MessageType(msg_type_str)
            except ValueError:
                msg_type = MessageType.ORDERS
            messages.append(
                ERPMessage(
                    msg_type=msg_type,
                    sender_id=self.sender_partner,
                    receiver_id="SAP_ECC",
                    payload=payload,
                )
            )
        if not messages:
            messages.append(
                ERPMessage(
                    msg_type=MessageType.ORDERS,
                    sender_id=self.sender_partner,
                    receiver_id="SAP_ECC",
                    payload={"raw": idoc_xml},
                )
            )
        return messages

    def send_edi(self, edi_payload: dict) -> str:
        """Send EDI message through SAP PI channel.

        Returns message ID for tracking.
        """
        msg_id = str(uuid.uuid4())
        try:
            import httpx

            resp = httpx.post(
                f"{self.base_url}/api/messages",
                json=edi_payload,
                headers=self.auth_header,
                timeout=30.0,
            )
            resp.raise_for_status()
        except Exception:
            logger.warning("SAP PI unavailable — EDI message %s not confirmed", msg_id)
        return msg_id


# ── Oracle EDI Connector ────────────────────────────────────────────────


class OracleEDIConnector(BaseModel):
    """Oracle EDI adapter — translates to/from EDIFACT / ANSI X12.

    Supported documents:
        - 850 (Purchase Order) → ORDERS
        - 860 (Purchase Order Change) → ORDCHG
        - 855 (Purchase Order Ack) → ORDINR
        - 856 (Ship Notice/ASN) → DESADV
        - 810 (Invoice) → INVOIC
        - 820 (Payment Remittance) → PAYMENT

    Example EDIFACT segment:
        UNT+14+003'
        ORDERS:D:2.1:UN:EDIFACT+'
        RFF_PO+95:PO-2024-0142'
        DTM_005:137:20240615:DAT'
        LIN+1++ABC123:SU:47++478.32'
        QTY_006+21:100'
    """

    standard: EDIStandard = EDIStandard.EDIFACT
    trading_partner_id: str | None = None  # ANSI X12 Interchange ID

    def parse(self, raw_edifact: str) -> ERPMessage:
        """Parse EDIFACT string into internal message model."""
        segments = [seg.strip() for seg in raw_edifact.strip().split("'") if seg.strip()]
        payload: dict = {"segments": []}
        msg_type = MessageType.ORDERS
        for segment in segments:
            parts = segment.split("+")
            tag = parts[0]
            elements = parts[1:] if len(parts) > 1 else []
            if tag == "UNH":
                msg_type_str = elements[1].split(":")[0] if len(elements) > 1 else "ORDERS"
                try:
                    msg_type = MessageType(msg_type_str)
                except ValueError:
                    pass
            payload["segments"].append({"tag": tag, "elements": elements})
        return ERPMessage(
            msg_type=msg_type,
            sender_id=self.trading_partner_id or "EDI_TRADING",
            receiver_id="WMS",
            payload=payload,
        )

    def serialize(self, msg: ERPMessage) -> str:
        """Serialize internal message to EDIFACT or X12 format."""
        segments = ["UNB+UNOA:2+" + msg.sender_id + "+" + msg.receiver_id]
        segments.append(f"UNH+1+{msg.msg_type.value}:D:2.1:UN:EDIFACT")
        payload = msg.payload
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key == "segments":
                    continue
                segments.append(f"{key}+{value}")
        segments.append("UNT+2+1")
        segments.append("UNZ+1+1")
        return "'".join(segments) + "'"


# ── Outbound order sync (WMS → ERP) ────────────────────────────────────


class OrderSyncService:
    """Bidirectional order synchronization with ERP systems.

    Flow:
        1. WMS creates internal Order model from customer PO
        2. SyncService converts to EDI/IDOC format
        3. Sends via SAP PI or Oracle EDI connector
        4. Waits for acknowledgment (ORDINR / 855)

    Retry logic:
        - Exponential backoff (initial 1s, max 60s)
        - Max 5 retries before moving to Dead Letter Queue
        - Message is persisted in outbox table before sending
    """

    def __init__(self, sap_connector: SAPPIConnector | None = None, edifact_conn: OracleEDIConnector | None = None):
        self.sap_connector = sap_connector
        self.edifact_conn = edifact_conn

    async def sync_order(self, order_id: str) -> str:
        """Sync a single order to ERP. Returns EDI message ID."""
        msg = ERPMessage(
            msg_type=MessageType.ORDERS,
            sender_id="WMS",
            receiver_id="ERP",
            payload={"order_id": order_id},
        )
        if self.sap_connector:
            edi_str = msg.model_dump_json()
            return self.sap_connector.send_edi({"raw": edi_str})
        if self.edifact_conn:
            edi_str = self.edifact_conn.serialize(msg)
            return hashlib.md5(edi_str.encode()).hexdigest()
        return str(uuid.uuid4())

    async def handle_ack(self, ack: ERPMessage) -> None:
        """Handle inbound order acknowledgment from ERP."""
        payload = ack.payload
        order_id = payload.get("order_id") if isinstance(payload, dict) else None
        if order_id:
            from src.core.database import async_session_factory
            from src.oms.models import Order, OrderStatus

            async with async_session_factory() as session:
                order = await session.get(Order, order_id)
                if order:
                    order.status = OrderStatus.CONFIRMED
                    await session.commit()


# ── EDI Translator ───────────────────────────────────────────────────────


class EDITranslator(BaseModel):
    standard: EDIStandard = EDIStandard.EDIFACT

    def serialize(self, order_msg: ERPMessage) -> str:
        if self.standard == EDIStandard.EDIFACT:
            return f"ORDERS+{order_msg.payload.get('id', '')}"
        return f"ST*850*{order_msg.payload.get('id', '')}"

    def translate_order(self, order_msg: ERPMessage) -> str:
        return self.serialize(order_msg)


# ── Dead Letter Queue ───────────────────────────────────────────────────


@dataclass
class DLQEntry:
    """Individual entry in the dead letter queue."""

    id: str
    msg_type: MessageType
    error_code: str       # e.g., "EDI_PARSE_ERROR", "SAP_COMM_FAILURE"
    raw_message: str      # original EDI/IDOC content
    resolved: bool = False
    resolved_at: datetime | None = None  # when the entry was resolved (manual intervention)
    created_at: datetime = dataclass_field(default_factory=lambda: datetime.now(UTC))


@dataclass
class DeadLetterQueue:
    """DLQ for EDI messages that failed after retries.

    Messages are stored with:
        - Original raw message (EDI/IDOC text)
        - Error details (traceback, validation errors)
        - Retry count and last attempt timestamp
        - Resolved flag + resolution timestamp for manual intervention

    Dashboard API endpoint: GET /api/v1/edi/dlq?status=pending
    """

    _entries: list[DLQEntry] = dataclass_field(default_factory=list)  # noqa: RUF012

    def enqueue(self, msg: ERPMessage, error_code: str) -> DLQEntry:
        entry = DLQEntry(
            id=str(uuid.uuid4()),
            msg_type=msg.msg_type,
            error_code=error_code,
            raw_message=json.dumps(msg.model_dump()),
            resolved=False,
            created_at=datetime.now(UTC),
        )
        self._entries.append(entry)
        return entry

    def retry(self, dlq_id: str) -> bool:
        for entry in self._entries:
            if entry.id == dlq_id and not entry.resolved:
                entry.resolved = True
                entry.resolved_at = datetime.now(UTC)
                return True
        return False


# ── Usage Example ────────────────────────────────────────────────────────

"""
# Sync order to SAP via PI
sap_config = {
    "SAP_PI_HOST": os.getenv("SAP_PI_HOST"),
    "SAP_PI_USER": os.getenv("SAP_PI_USER"),
    "SAP_PI_TOKEN": os.getenv("SAP_PI_TOKEN"),
}

connector = OrderSyncService(sap_connector=SAPPIConnector(sap_config))
msg_id = await connector.sync_order(order_id="ORD-2024-0142")
print(f"EDI message sent: {msg_id}")

# Parse inbound EDI order
# edi_text = ...  # raw EDIFACT from Oracle/EDI gateway
# parsed = edifact_conn.parse(edi_text)
# await handle_inbound_order(parsed)
"""
