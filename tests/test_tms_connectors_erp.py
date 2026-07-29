"""Tests for src.tms.connectors.erp — TMSSyncService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.erp_connector import ERPMessage, MessageType


@pytest.fixture
def sap_mock():
    mock = MagicMock()
    mock.send_edi.return_value = "sap-msg-id-001"
    return mock


@pytest.fixture
def edi_mock():
    mock = MagicMock()
    mock.serialize.return_value = "EDI_RAW_STRING"
    return mock


@pytest.fixture
def order_sync_mock():
    return MagicMock()


class TestTMSSyncServiceInit:
    def test_init_with_sap(self, sap_mock):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService(sap_connector=sap_mock)
        assert svc.sap is sap_mock
        assert svc.edi is None
        assert svc._order_sync is None

    def test_init_with_edi(self, edi_mock):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService(edi_connector=edi_mock)
        assert svc.sap is None
        assert svc.edi is edi_mock
        assert svc._order_sync is None

    def test_init_with_both(self, sap_mock, edi_mock):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService(sap_connector=sap_mock, edi_connector=edi_mock)
        assert svc.sap is sap_mock
        assert svc.edi is edi_mock

    def test_init_with_order_sync(self, order_sync_mock):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService(order_sync=order_sync_mock)
        assert svc._order_sync is order_sync_mock


class TestTMSSyncServiceOrderSync:
    def test_order_sync_property_returns_existing(self, order_sync_mock):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService(order_sync=order_sync_mock)
        result = svc.order_sync
        assert result is order_sync_mock

    def test_order_sync_property_creates_lazy(self, sap_mock):
        from src.tms.connectors.erp import TMSSyncService

        with patch("src.tms.connectors.erp.OrderSyncService") as MockOS:
            mock_instance = MagicMock()
            MockOS.return_value = mock_instance
            svc = TMSSyncService(sap_connector=sap_mock)
            result = svc.order_sync
            assert result is mock_instance
            MockOS.assert_called_once_with(sap_connector=sap_mock, edifact_conn=None)


class TestSyncTransportOrder:
    async def test_with_sap(self, sap_mock):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService(sap_connector=sap_mock)
        result = await svc.sync_transport_order("TO-001")
        assert result == "sap-msg-id-001"
        sap_mock.send_edi.assert_called_once()
        args = sap_mock.send_edi.call_args[0][0]
        assert "TO-001" in args["raw"]

    async def test_with_edi(self, edi_mock):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService(edi_connector=edi_mock)
        result = await svc.sync_transport_order("TO-002")
        assert isinstance(result, str)
        assert len(result) == 32
        edi_mock.serialize.assert_called_once()

    async def test_without_connector(self):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService()
        result = await svc.sync_transport_order("TO-003")
        assert isinstance(result, str)
        assert len(result) == 36


class TestSyncTrackingEvent:
    async def test_with_sap(self, sap_mock):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService(sap_connector=sap_mock)
        result = await svc.sync_tracking_event("TO-001", "POD", {"signed_by": "John"})
        assert result == "sap-msg-id-001"
        sap_mock.send_edi.assert_called_once()

    async def test_with_edi(self, edi_mock):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService(edi_connector=edi_mock)
        result = await svc.sync_tracking_event("TO-002", "EXCEPTION", {"code": "DAMAGED"})
        assert isinstance(result, str)
        assert len(result) == 32
        edi_mock.serialize.assert_called_once()

    async def test_without_details(self, sap_mock):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService(sap_connector=sap_mock)
        result = await svc.sync_tracking_event("TO-004", "POD")
        assert result == "sap-msg-id-001"

    async def test_without_connector(self):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService()
        result = await svc.sync_tracking_event("TO-005", "EXCEPTION")
        assert isinstance(result, str)
        assert len(result) == 36


class TestHandleInboundRateUpdate:
    async def test_non_dict_payload_returns_0(self):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService()
        msg = ERPMessage.model_construct(
            msg_type=MessageType.ORDERS, sender_id="ERP", receiver_id="TMS", payload="raw-string",
        )
        result = await svc.handle_inbound_rate_update(msg)
        assert result == 0

    async def test_missing_carrier_code_returns_0(self):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService()
        msg = ERPMessage(msg_type=MessageType.ORDERS, sender_id="ERP", receiver_id="TMS", payload={"rate_data": {}})
        result = await svc.handle_inbound_rate_update(msg)
        assert result == 0

    async def test_missing_rate_data_returns_0(self):
        from src.tms.connectors.erp import TMSSyncService

        svc = TMSSyncService()
        msg = ERPMessage(msg_type=MessageType.ORDERS, sender_id="ERP", receiver_id="TMS", payload={"carrier_code": "UPS"})
        result = await svc.handle_inbound_rate_update(msg)
        assert result == 0

    async def test_success_calls_update_carrier_rate(self):
        from src.tms.connectors.erp import TMSSyncService

        rate_data = {"zone": "A2", "rate_per_kg": 1.25}
        msg = ERPMessage(
            msg_type=MessageType.ORDERS,
            sender_id="ERP",
            receiver_id="TMS",
            payload={"carrier_code": "FEDEX", "rate_data": rate_data},
        )

        svc = TMSSyncService()
        with patch("src.tms.service.update_carrier_rate", new_callable=AsyncMock, create=True) as mock_update:
            mock_update.return_value = 3
            result = await svc.handle_inbound_rate_update(msg)
            assert result == 3
            mock_update.assert_awaited_once_with("FEDEX", rate_data)
