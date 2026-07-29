"""Tests for webhook dispatch service."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from src.webhooks.models import WebhookEvent, WebhookTarget, WebhookStatus
from src.webhooks.service import dispatch_event


class FakeResponse:
    """Lightweight response stub (avoids MagicMock attribute pitfalls)."""
    def __init__(self, is_success=True, status_code=200, text="OK"):
        self.is_success = is_success
        self.status_code = status_code
        self.text = text


class TestWebhookDispatch:
    @pytest.mark.asyncio
    async def test_no_active_targets(self, db_session):
        await dispatch_event(WebhookEvent.ORDER_CREATED, {"order_id": "123"}, db=db_session)

    @pytest.mark.asyncio
    async def test_no_matching_event(self, db_session):
        db_session.add(WebhookTarget(
            name="NoMatch", url="http://ex.com/hook",
            events='["delivery.confirmed"]', status=WebhookStatus.ACTIVE,
        ))
        await db_session.flush()
        await dispatch_event(WebhookEvent.ORDER_CREATED, {"id": "1"}, db=db_session)

    @pytest.mark.asyncio
    async def test_dispatch_success(self, db_session):
        db_session.add(WebhookTarget(
            name="Hooky", url="http://example.com/wh",
            events='["order.created"]', secret="test-secret",
            status=WebhookStatus.ACTIVE,
        ))
        await db_session.flush()

        mock_post = AsyncMock(return_value=FakeResponse())

        with patch("httpx.AsyncClient") as mc:
            mc.return_value.__aenter__.return_value.post = mock_post
            await dispatch_event(WebhookEvent.ORDER_CREATED, {"id": "1"}, db=db_session)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "http://example.com/wh"
        assert kwargs["headers"]["X-Webhook-Event"] == "order.created"
        assert "X-Webhook-Signature" in kwargs["headers"]
        assert json.loads(kwargs["content"]) == {"id": "1"}

    @pytest.mark.asyncio
    async def test_http_failure(self, db_session):
        db_session.add(WebhookTarget(
            name="Faily", url="http://ex.com/fail",
            events='["order.created"]', status=WebhookStatus.ACTIVE,
        ))
        await db_session.flush()

        with patch("httpx.AsyncClient") as mc:
            mc.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("Timeout")
            )
            await dispatch_event(WebhookEvent.ORDER_CREATED, {"id": "1"}, db=db_session)

    @pytest.mark.asyncio
    async def test_multiple_targets(self, db_session):
        for name in ("Alpha", "Beta"):
            db_session.add(WebhookTarget(
                name=name, url=f"http://{name.lower()}.com/wh",
                events='["order.created"]', status=WebhookStatus.ACTIVE,
            ))
        await db_session.flush()

        mock_post = AsyncMock(return_value=FakeResponse())
        with patch("httpx.AsyncClient") as mc:
            mc.return_value.__aenter__.return_value.post = mock_post
            await dispatch_event(WebhookEvent.ORDER_CREATED, {"id": "1"}, db=db_session)

        assert mock_post.call_count >= 2
        urls = [call.args[0] for call in mock_post.call_args_list]
        assert any("alpha.com" in u for u in urls)
        assert any("beta.com" in u for u in urls)
