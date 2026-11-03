"""Tests for remaining uncovered paths in webhooks/service.py, analytics/service.py, auth/service.py."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.webhooks.models import WebhookEvent, WebhookStatus, WebhookTarget
from src.webhooks.service import _deliver_async, dispatch_event


class FakeResponse:
    def __init__(self, is_success=True, status_code=200, text="OK"):
        self.is_success = is_success
        self.status_code = status_code
        self.text = text


# ── Webhook: _deliver_async ────────────────────────────────────────────────


class TestDeliverAsync:
    @pytest.mark.asyncio
    async def test_success_no_secret(self):
        mock_post = AsyncMock(return_value=FakeResponse())
        with patch("httpx.AsyncClient") as mc:
            mc.return_value.__aenter__.return_value.post = mock_post
            result = await _deliver_async(
                target_id=1, url="http://example.com/hook",
                secret=None, event_value="order.created",
                payload_str='{"id": "1"}',
            )
        assert result["success"] is True
        assert result["status_code"] == 200
        headers = mock_post.call_args[1]["headers"]
        assert "X-Webhook-Signature" not in headers

    @pytest.mark.asyncio
    async def test_success_with_secret(self):
        mock_post = AsyncMock(return_value=FakeResponse())
        with patch("httpx.AsyncClient") as mc:
            mc.return_value.__aenter__.return_value.post = mock_post
            result = await _deliver_async(
                target_id=1, url="http://example.com/hook",
                secret="my-secret", event_value="order.created",
                payload_str='{"id": "1"}',
            )
        assert result["success"] is True
        headers = mock_post.call_args[1]["headers"]
        assert "X-Webhook-Signature" in headers
        assert "X-Webhook-Timestamp" in headers

    @pytest.mark.asyncio
    async def test_http_failure(self):
        mock_post = AsyncMock(side_effect=Exception("Connection refused"))
        with patch("httpx.AsyncClient") as mc:
            mc.return_value.__aenter__.return_value.post = mock_post
            result = await _deliver_async(
                target_id=1, url="http://example.com/hook",
                secret=None, event_value="order.created",
                payload_str='{"id": "1"}',
            )
        assert result["success"] is False
        assert result["status_code"] is None
        assert "Connection refused" in result["response_body"]


# ── Webhook: invalid JSON in target events ─────────────────────────────────


class TestWebhookInvalidJson:
    @pytest.mark.asyncio
    async def test_invalid_json_events_skipped(self, db_session):
        db_session.add(WebhookTarget(
            name="BadJSON", url="http://example.com/hook",
            events="not-valid-json", status=WebhookStatus.ACTIVE,
        ))
        await db_session.flush()
        result = await dispatch_event(WebhookEvent.ORDER_CREATED, {"id": "1"}, db=db_session)
        assert result is None or result == []

    @pytest.mark.asyncio
    async def test_empty_list_events_no_match(self, db_session):
        db_session.add(WebhookTarget(
            name="EmptyEvents", url="http://example.com/hook",
            events='[]', status=WebhookStatus.ACTIVE,
        ))
        await db_session.flush()
        result = await dispatch_event(WebhookEvent.ORDER_CREATED, {"id": "1"}, db=db_session)
        assert result is None or result == []


# ── Webhook: dispatch without db (creates own session) ─────────────────────


class TestDispatchNoDb:
    @pytest.mark.asyncio
    async def test_creates_session_when_db_none(self):
        with patch("src.core.database.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_cm = MagicMock()
            mock_cm.__aenter__.return_value = mock_session
            mock_cm.__aexit__.return_value = False
            mock_get_session.return_value = mock_cm

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute.return_value = mock_result

            await dispatch_event(WebhookEvent.ORDER_CREATED, {"id": "1"}, db=None)
            mock_session.commit.assert_awaited_once()


# ── Webhook: outbox failure gracefully handled ─────────────────────────────


class TestWebhookOutboxFailure:
    @pytest.mark.asyncio
    async def test_outbox_failure_does_not_crash(self, db_session):
        db_session.add(WebhookTarget(
            name="Hooky", url="http://example.com/wh",
            events='["order.created"]', status=WebhookStatus.ACTIVE,
        ))
        await db_session.flush()

        mock_post = AsyncMock(return_value=FakeResponse())
        with patch("httpx.AsyncClient") as mc, \
             patch("src.webhooks.service.append_event", side_effect=Exception("DB error")):
            mc.return_value.__aenter__.return_value.post = mock_post
            await dispatch_event(WebhookEvent.ORDER_CREATED, {"id": "1"}, db=db_session)
            assert mock_post.call_count == 1


# ── Webhook: delivery log with failed response ─────────────────────────────


class TestWebhookDeliveryLog:
    @pytest.mark.asyncio
    async def test_failed_delivery_logged(self, db_session):
        db_session.add(WebhookTarget(
            name="FailTarget", url="http://example.com/fail",
            events='["order.created"]', status=WebhookStatus.ACTIVE,
        ))
        await db_session.flush()

        mock_post = AsyncMock(return_value=FakeResponse(is_success=False, status_code=500, text="Server Error"))
        with patch("httpx.AsyncClient") as mc:
            mc.return_value.__aenter__.return_value.post = mock_post
            await dispatch_event(WebhookEvent.ORDER_CREATED, {"id": "1"}, db=db_session)
            assert mock_post.call_count == 1


# ── Analytics: exception paths ─────────────────────────────────────────────


class TestAnalyticsExceptionPaths:
    """A DB outage has to look like an outage.

    These used to assert a quiet fallback (zeros / empty lists).  An outage that
    renders as "0 orders today" is indistinguishable from a bad day, so the
    service re-raises and the caller turns it into a 5xx.
    """

    @pytest.fixture
    def mock_db(self):
        return AsyncMock(spec=AsyncSession)

    async def test_dashboard_stats_exception(self, mock_db):
        from src.analytics import service as analytics_service
        mock_db.execute = AsyncMock(side_effect=Exception("DB error"))
        with pytest.raises(Exception, match="DB error"):
            await analytics_service.get_dashboard_stats(mock_db)

    async def test_order_trends_exception(self, mock_db):
        from src.analytics import service as analytics_service
        mock_db.execute = AsyncMock(side_effect=Exception("DB error"))
        with pytest.raises(Exception, match="DB error"):
            await analytics_service.get_order_trends(mock_db)

    async def test_status_distribution_exception(self, mock_db):
        from src.analytics import service as analytics_service
        mock_db.execute = AsyncMock(side_effect=Exception("DB error"))
        with pytest.raises(Exception, match="DB error"):
            await analytics_service.get_status_distribution(mock_db)

    async def test_low_stock_items_exception(self, mock_db):
        from src.analytics import service as analytics_service
        mock_db.execute = AsyncMock(side_effect=Exception("DB error"))
        with pytest.raises(Exception, match="DB error"):
            await analytics_service.get_low_stock_items(mock_db)

    async def test_recent_orders_exception(self, mock_db):
        from src.analytics import service as analytics_service
        mock_db.execute = AsyncMock(side_effect=Exception("DB error"))
        with pytest.raises(Exception, match="DB error"):
            await analytics_service.get_recent_orders(mock_db)

    async def test_failure_is_not_cached(self, mock_db):
        """A failed call must not poison the cache for the next caller."""
        from src.analytics import service as analytics_service
        mock_db.execute = AsyncMock(side_effect=Exception("DB error"))
        for _ in range(2):
            with pytest.raises(Exception, match="DB error"):
                await analytics_service.get_dashboard_stats(mock_db)
        assert mock_db.execute.await_count >= 2  # the second call really ran again


# ── Auth: additional edge cases ────────────────────────────────────────────


class TestAuthEdgeCases:
    async def test_refresh_tokens_expired(self):
        from src.auth.service import TokenExpired, refresh_tokens
        with patch("src.auth.service.decode_token", side_effect=TokenExpired("expired")):
            result = await refresh_tokens("expired-token")
            assert result is None

    async def test_refresh_tokens_invalid(self):
        from src.auth.service import TokenInvalid, refresh_tokens
        with patch("src.auth.service.decode_token", side_effect=TokenInvalid("invalid")):
            result = await refresh_tokens("invalid-token")
            assert result is None

    async def test_revoke_idempotent(self):
        from src.auth.service import revoke_refresh_token
        await revoke_refresh_token("nonexistent-token-xyz")
