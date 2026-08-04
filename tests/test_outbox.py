"""Tests for src.core.outbox — OutboxEvent, append_event, dispatch, mark."""

from unittest.mock import AsyncMock, MagicMock, patch


class TestAppendEvent:
    async def test_creates_and_flushes(self):
        from src.core.outbox import append_event

        mock_db = AsyncMock()

        result = await append_event(
            mock_db,
            aggregate_type="Order",
            aggregate_id="id-1",
            event_type="order.created",
            payload={"amount": 50},
        )
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()
        assert result.aggregate_type == "Order"


class TestDispatchPendingEvents:
    async def test_returns_events(self):
        from src.core.outbox import dispatch_pending_events

        mock_session = AsyncMock()
        mock_event = MagicMock()
        mock_event.event_type = "order.created"
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_event]
        mock_session.execute.return_value = mock_result

        mod = __import__("src.core.outbox", fromlist=["dispatch_pending_events"])
        with patch.object(mod, "get_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            events = await dispatch_pending_events(batch_size=50)
            assert len(events) == 1
            assert events[0].event_type == "order.created"


class TestMarkDispatched:
    async def test_updates_events(self):
        from src.core.outbox import mark_dispatched

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 2
        mock_session.execute.return_value = mock_result

        mod = __import__("src.core.outbox", fromlist=["mark_dispatched"])
        with patch.object(mod, "get_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            count = await mark_dispatched(["id-1", "id-2"])
            assert count == 2


class TestMarkFailed:
    async def test_updates_event(self):
        from src.core.outbox import mark_failed

        mock_session = AsyncMock()

        mod = __import__("src.core.outbox", fromlist=["mark_failed"])
        with patch.object(mod, "get_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            await mark_failed("id-1", "timeout error")
            mock_session.execute.assert_awaited_once()
            mock_session.commit.assert_awaited_once()


class TestOutboxEvent:
    def test_to_dict(self):
        from src.core.outbox import OutboxEvent, OutboxEventStatus

        e = OutboxEvent()
        e.id = "a1b2c3"
        e.aggregate_type = "Order"
        e.aggregate_id = "id-1"
        e.event_type = "order.created"
        e.payload = {"amount": 100}
        e.status = OutboxEventStatus.PENDING.value
        e.retry_count = 0
        e.error_message = None
        e.scheduled_at = None
        e.dispatched_at = None

        d = e.to_dict()
        assert d["event_type"] == "order.created"
        assert d["payload"] == {"amount": 100}
        assert d["scheduled_at"] is None
        assert d["dispatched_at"] is None

    def test_to_dict_with_dates(self):
        from datetime import UTC, datetime, timedelta

        from src.core.outbox import OutboxEvent, OutboxEventStatus

        now = datetime.now(UTC)
        e = OutboxEvent()
        e.id = "x"
        e.aggregate_type = "Inv"
        e.aggregate_id = "id-2"
        e.event_type = "inv.adjusted"
        e.payload = {}
        e.status = OutboxEventStatus.DISPATCHED.value
        e.retry_count = 1
        e.error_message = "prev fail"
        e.scheduled_at = now + timedelta(seconds=60)
        e.dispatched_at = now

        d = e.to_dict()
        assert d["dispatched_at"] == now.isoformat()
        assert d["scheduled_at"] == (now + timedelta(seconds=60)).isoformat()
