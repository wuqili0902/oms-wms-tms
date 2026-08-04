"""Tests for ERP/EDI connector models and services."""

import importlib.util
import sys
import uuid
from datetime import datetime

# Import directly via file to avoid src.models.__init__ bcrypt chain
_spec = importlib.util.spec_from_file_location(
    "erp_connector", "src/models/erp_connector.py"
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["erp_connector"] = _mod
_spec.loader.exec_module(_mod)

DeadLetterQueue = _mod.DeadLetterQueue
EDITranslator = _mod.EDITranslator
EDIStandard = _mod.EDIStandard
ERPMessage = _mod.ERPMessage
ERPMessageStatus = _mod.ERPMessageStatus
MessageType = _mod.MessageType
OracleEDIConnector = _mod.OracleEDIConnector
SAPPIConnector = _mod.SAPPIConnector


class TestMessageType:
    def test_values(self):
        assert MessageType("ORDERS") == MessageType.ORDERS
        assert MessageType("ORDINR") == MessageType.ORDINR
        assert MessageType("ORDRESP") == MessageType.ORDRESP
        assert MessageType("DESADV") == MessageType.DESADV
        assert MessageType("INVOIC") == MessageType.INVOIC
        assert MessageType("DELJRN") == MessageType.DELJRN
        assert MessageType("CUSORD") == MessageType.CUSORD


class TestEDIStandard:
    def test_values(self):
        assert EDIStandard("edifact") == EDIStandard.EDIFACT
        assert EDIStandard("ansi_x12") == EDIStandard.ANSI_X12


class TestERPMessageStatus:
    def test_values(self):
        assert ERPMessageStatus("pending") == ERPMessageStatus.PENDING
        assert ERPMessageStatus("sent") == ERPMessageStatus.SENT
        assert ERPMessageStatus("received") == ERPMessageStatus.RECEIVED
        assert ERPMessageStatus("confirmed") == ERPMessageStatus.CONFIRMED
        assert ERPMessageStatus("failed") == ERPMessageStatus.FAILED


class TestERPMessage:
    def test_create(self):
        msg = ERPMessage(
            msg_type=MessageType.ORDERS,
            sender_id="SAP",
            receiver_id="WMS",
            payload={"order_id": "ORD-001"},
        )
        assert msg.msg_type == MessageType.ORDERS
        assert msg.sender_id == "SAP"
        assert msg.receiver_id == "WMS"
        assert msg.payload == {"order_id": "ORD-001"}
        assert isinstance(msg.created_at, datetime)

    def test_model_dump(self):
        msg = ERPMessage(
            msg_type=MessageType.DESADV,
            sender_id="WMS",
            receiver_id="ERP",
            payload={"shipment_id": "SHP-001"},
        )
        data = msg.model_dump()
        assert data["msg_type"] == "DESADV"
        assert data["sender_id"] == "WMS"
        assert data["receiver_id"] == "ERP"
        assert data["payload"] == {"shipment_id": "SHP-001"}


class TestSAPPIConnector:
    def test_init(self):
        config = {
            "SAP_PI_HOST": "https://sap-pi.example.com",
            "SAP_PI_TOKEN": "dG9rZW4=",
        }
        conn = SAPPIConnector(config)
        assert conn.base_url == "https://sap-pi.example.com"
        assert conn.auth_header == {"Authorization": "Basic dG9rZW4="}
        assert conn.sender_partner == "WMS001"

    def test_init_custom_sender(self):
        config = {
            "SAP_PI_HOST": "https://sap-pi.example.com",
            "SAP_PI_TOKEN": "dG9rZW4=",
            "SAP_SNDPRN": "CUSTOM_WH",
        }
        conn = SAPPIConnector(config)
        assert conn.sender_partner == "CUSTOM_WH"

    def test_parse_idoc_single(self):
        xml = """<?xml version="1.0"?>
<EDI_DC40>
  <IDOC>
    <DOCTYPE>ORDERS</DOCTYPE>
    <segment>
      <E1EDK01><BELNR>4500012345</BELNR></E1EDK01>
    </segment>
  </IDOC>
</EDI_DC40>"""
        config = {"SAP_PI_HOST": "x", "SAP_PI_TOKEN": "x"}
        conn = SAPPIConnector(config)
        msgs = conn.parse_idoc(xml)
        assert len(msgs) == 1
        assert msgs[0].msg_type == MessageType.ORDERS
        assert msgs[0].sender_id == "WMS001"
        assert msgs[0].receiver_id == "SAP_ECC"
        assert "segment" in msgs[0].payload
        assert "E1EDK01" in msgs[0].payload["segment"]

    def test_parse_idoc_multiple(self):
        xml = """<?xml version="1.0"?>
<EDI_DC40>
  <IDOC>
    <DOCTYPE>DESADV</DOCTYPE>
    <segment><E1EDK01><BELNR>DES-001</BELNR></E1EDK01></segment>
  </IDOC>
  <IDOC>
    <DOCTYPE>INVOIC</DOCTYPE>
    <segment><E1EDK01><BELNR>INV-001</BELNR></E1EDK01></segment>
  </IDOC>
</EDI_DC40>"""
        config = {"SAP_PI_HOST": "x", "SAP_PI_TOKEN": "x"}
        conn = SAPPIConnector(config)
        msgs = conn.parse_idoc(xml)
        assert len(msgs) == 2
        assert msgs[0].msg_type == MessageType.DESADV
        assert msgs[1].msg_type == MessageType.INVOIC

    def test_parse_idoc_unknown_doc_type(self):
        xml = """<?xml version="1.0"?>
<EDI_DC40>
  <IDOC>
    <DOCTYPE>UNKNOWN_TYPE</DOCTYPE>
    <segment><E1EDK01><BELNR>001</BELNR></E1EDK01></segment>
  </IDOC>
</EDI_DC40>"""
        config = {"SAP_PI_HOST": "x", "SAP_PI_TOKEN": "x"}
        conn = SAPPIConnector(config)
        msgs = conn.parse_idoc(xml)
        assert len(msgs) == 1
        assert msgs[0].msg_type == MessageType.ORDERS

    def test_parse_idoc_empty(self):
        xml = """<?xml version="1.0"?>
<EDI_DC40/>"""
        config = {"SAP_PI_HOST": "x", "SAP_PI_TOKEN": "x"}
        conn = SAPPIConnector(config)
        msgs = conn.parse_idoc(xml)
        assert len(msgs) == 1
        assert msgs[0].msg_type == MessageType.ORDERS
        assert "raw" in msgs[0].payload

    def test_send_edi_success(self, monkeypatch):
        config = {"SAP_PI_HOST": "https://sap-pi.example.com", "SAP_PI_TOKEN": "dG9rZW4="}
        conn = SAPPIConnector(config)
        import httpx
        def mock_post(url, **kwargs):
            class MockResp:
                def raise_for_status(self): pass
            return MockResp()
        monkeypatch.setattr(httpx, "post", mock_post)
        msg_id = conn.send_edi({"order_id": "ORD-001"})
        assert uuid.UUID(msg_id)

    def test_send_edi_failure_logs_warning(self, monkeypatch):
        config = {"SAP_PI_HOST": "https://sap-pi.example.com", "SAP_PI_TOKEN": "dG9rZW4="}
        conn = SAPPIConnector(config)
        import httpx
        def mock_post_fail(url, **kwargs):
            raise RuntimeError("Connection refused")
        monkeypatch.setattr(httpx, "post", mock_post_fail)
        msg_id = conn.send_edi({"order_id": "ORD-001"})
        assert uuid.UUID(msg_id)


class TestOracleEDIConnector:
    def test_init_defaults(self):
        conn = OracleEDIConnector()
        assert conn.standard == EDIStandard.EDIFACT
        assert conn.trading_partner_id is None

    def test_init_custom(self):
        conn = OracleEDIConnector(
            standard=EDIStandard.ANSI_X12,
            trading_partner_id="TP001",
        )
        assert conn.standard == EDIStandard.ANSI_X12
        assert conn.trading_partner_id == "TP001"

    def test_parse_edifact_orders(self):
        raw = "UNH+1+ORDERS:D:2.1:UN:EDIFACT'LIN+1++SKU001:SU:47++100'UNT+2+1'"
        conn = OracleEDIConnector(trading_partner_id="TP001")
        msg = conn.parse(raw)
        assert msg.msg_type == MessageType.ORDERS
        assert msg.sender_id == "TP001"
        assert msg.receiver_id == "WMS"
        assert len(msg.payload["segments"]) == 3

    def test_parse_edifact_desadv(self):
        raw = "UNH+1+DESADV:D:2.1:UN:EDIFACT'LIN+1++SKU002:SU:47++50'UNT+2+1'"
        conn = OracleEDIConnector()
        msg = conn.parse(raw)
        assert msg.msg_type == MessageType.DESADV

    def test_parse_edifact_unknown_type(self):
        raw = "UNH+1+UNKNOWN_TYPE:D:2.1:UN:EDIFACT'LIN+1++SKU003:SU:47++25'UNT+2+1'"
        conn = OracleEDIConnector()
        msg = conn.parse(raw)
        assert msg.msg_type == MessageType.ORDERS

    def test_serialize(self):
        conn = OracleEDIConnector(trading_partner_id="TP001")
        msg = ERPMessage(
            msg_type=MessageType.ORDERS,
            sender_id="WMS",
            receiver_id="TP001",
            payload={"order_ref": "PO-001"},
        )
        result = conn.serialize(msg)
        assert "UNB+UNOA:2+WMS+TP001" in result
        assert "UNH+1+ORDERS:D:2.1:UN:EDIFACT" in result
        assert "order_ref+PO-001" in result
        assert result.endswith("'")

    def test_serialize_with_segments(self):
        conn = OracleEDIConnector()
        msg = ERPMessage(
            msg_type=MessageType.DESADV,
            sender_id="WMS",
            receiver_id="ERP",
            payload={
                "order_ref": "PO-002",
                "segments": [{"tag": "LIN", "elements": ["1", "SKU001"]}],
            },
        )
        result = conn.serialize(msg)
        assert "DESADV" in result
        assert "order_ref+PO-002" in result
        assert "segments" not in result


class TestDeadLetterQueue:
    def test_enqueue(self, monkeypatch):
        monkeypatch.setattr("json.dumps", lambda x: "{}")
        dlq = DeadLetterQueue()
        msg = ERPMessage(
            msg_type=MessageType.ORDERS,
            sender_id="SAP",
            receiver_id="WMS",
            payload={"order_id": "ORD-001"},
        )
        entry = dlq.enqueue(msg, "EDI_PARSE_ERROR")
        assert entry.msg_type == MessageType.ORDERS
        assert entry.error_code == "EDI_PARSE_ERROR"
        assert not entry.resolved
        assert entry.id is not None
        assert len(dlq._entries) == 1

    def test_enqueue_multiple(self, monkeypatch):
        monkeypatch.setattr("json.dumps", lambda x: "{}")
        dlq = DeadLetterQueue()
        msg1 = ERPMessage(
            msg_type=MessageType.ORDERS, sender_id="SAP", receiver_id="WMS",
            payload={"id": "1"},
        )
        msg2 = ERPMessage(
            msg_type=MessageType.DESADV, sender_id="WMS", receiver_id="ERP",
            payload={"id": "2"},
        )
        e1 = dlq.enqueue(msg1, "ERR_1")
        e2 = dlq.enqueue(msg2, "ERR_2")
        assert len(dlq._entries) == 2
        assert e1.id != e2.id

    def test_retry_success(self, monkeypatch):
        monkeypatch.setattr("json.dumps", lambda x: "{}")
        dlq = DeadLetterQueue()
        msg = ERPMessage(
            msg_type=MessageType.ORDERS, sender_id="SAP", receiver_id="WMS",
            payload={"id": "1"},
        )
        entry = dlq.enqueue(msg, "SAP_COMM_FAILURE")
        assert dlq.retry(entry.id) is True
        assert entry.resolved
        assert entry.resolved_at is not None

    def test_retry_already_resolved(self, monkeypatch):
        monkeypatch.setattr("json.dumps", lambda x: "{}")
        dlq = DeadLetterQueue()
        msg = ERPMessage(
            msg_type=MessageType.ORDERS, sender_id="SAP", receiver_id="WMS",
            payload={"id": "1"},
        )
        entry = dlq.enqueue(msg, "SAP_COMM_FAILURE")
        dlq.retry(entry.id)
        assert dlq.retry(entry.id) is False

    def test_retry_not_found(self):
        dlq = DeadLetterQueue()
        assert dlq.retry("nonexistent") is False


class TestOrderSyncService:
    def test_init_defaults(self):
        svc = _mod.OrderSyncService()
        assert svc.sap_connector is None
        assert svc.edifact_conn is None

    def test_init_with_connectors(self):
        config = {"SAP_PI_HOST": "x", "SAP_PI_TOKEN": "x"}
        sap = SAPPIConnector(config)
        edi = OracleEDIConnector()
        svc = _mod.OrderSyncService(sap_connector=sap, edifact_conn=edi)
        assert svc.sap_connector is sap
        assert svc.edifact_conn is edi

    async def test_sync_order_with_sap(self, monkeypatch):
        config = {"SAP_PI_HOST": "x", "SAP_PI_TOKEN": "x"}
        sap = SAPPIConnector(config)
        svc = _mod.OrderSyncService(sap_connector=sap)

        import httpx
        def mock_post(url, **kwargs):
            class MockResp:
                def raise_for_status(self): pass
            return MockResp()
        monkeypatch.setattr(httpx, "post", mock_post)

        msg_id = await svc.sync_order("ORD-001")
        assert uuid.UUID(msg_id)

    async def test_sync_order_with_edi(self):
        edi = OracleEDIConnector(trading_partner_id="TP001")
        svc = _mod.OrderSyncService(edifact_conn=edi)
        msg_id = await svc.sync_order("ORD-002")
        assert isinstance(msg_id, str)
        assert len(msg_id) == 32

    async def test_sync_order_without_connector(self):
        svc = _mod.OrderSyncService()
        msg_id = await svc.sync_order("ORD-003")
        assert isinstance(msg_id, str)
        assert len(msg_id) == 36

    async def test_handle_ack_without_order_id(self):
        svc = _mod.OrderSyncService()
        msg = ERPMessage(msg_type=MessageType.ORDRESP, sender_id="ERP", receiver_id="WMS", payload={})
        await svc.handle_ack(msg)

    async def test_handle_ack_non_dict_payload(self):
        svc = _mod.OrderSyncService()
        msg = ERPMessage(msg_type=MessageType.ORDRESP, sender_id="ERP", receiver_id="WMS", payload={"order_id": None})
        await svc.handle_ack(msg)

    async def test_handle_ack_with_order(self, monkeypatch):
        svc = _mod.OrderSyncService()

        class FakeOrder:
            def __init__(self):
                self.status = None

        fake_order = FakeOrder()

        class FakeAsyncSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def get(self, model, id_):
                if id_ == "ORD-001":
                    return fake_order
                return None
            async def commit(self):
                pass

        def fake_factory():
            return FakeAsyncSession()

        monkeypatch.setattr("src.core.database.async_session_factory", fake_factory)

        msg = ERPMessage(
            msg_type=MessageType.ORDRESP,
            sender_id="ERP",
            receiver_id="WMS",
            payload={"order_id": "ORD-001"},
        )
        await svc.handle_ack(msg)
        assert fake_order.status is not None


class TestEDITranslator:
    def test_translate_order_edifact(self):
        t = _mod.EDITranslator(standard=_mod.EDIStandard.EDIFACT)
        msg = ERPMessage(msg_type=MessageType.ORDERS, sender_id="WMS", receiver_id="ERP", payload={"id": "1"})
        result = t.translate_order(msg)
        assert isinstance(result, str)
        assert result == "ORDERS+1"

    def test_translate_order_ansi_x12(self):
        t = _mod.EDITranslator(standard=_mod.EDIStandard.ANSI_X12)
        msg = ERPMessage(msg_type=MessageType.ORDERS, sender_id="WMS", receiver_id="ERP", payload={"id": "2"})
        result = t.translate_order(msg)
        assert result == "ST*850*2"
