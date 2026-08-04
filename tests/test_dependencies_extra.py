"""Tests for core dependency functions."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


@pytest.fixture
def mock_celery_app(monkeypatch):
    class MockCeleryApp:
        tasks = {}

        def _get_current_object(self):
            return self

    import celery
    monkeypatch.setattr(celery, "current_app", MockCeleryApp())
    return MockCeleryApp


class TestGetCurrentUser:
    async def test_valid_token_returns_payload(self):
        from src.core.dependencies import get_current_user

        mock_creds = MagicMock()
        mock_creds.credentials = "valid.token"

        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.return_value = {"sub": "testuser", "uid": "u1"}
            result = await get_current_user(mock_creds)
            assert result["sub"] == "testuser"

    async def test_no_credentials_raises_401(self):
        from src.core.dependencies import get_current_user

        with pytest.raises(HTTPException) as exc:
            await get_current_user(None)
        assert exc.value.status_code == 401

    async def test_empty_credentials_raises_401(self):
        from src.core.dependencies import get_current_user

        mock_creds = MagicMock()
        mock_creds.credentials = ""

        with pytest.raises(HTTPException) as exc:
            await get_current_user(mock_creds)
        assert exc.value.status_code == 401

    async def test_expired_token_raises_401(self):
        from src.core.dependencies import get_current_user
        from src.core.security import TokenExpired

        mock_creds = MagicMock()
        mock_creds.credentials = "expired.token"

        with patch("src.core.security.decode_token", side_effect=TokenExpired()):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(mock_creds)
            assert exc.value.status_code == 401

    async def test_invalid_token_raises_401(self):
        from src.core.dependencies import get_current_user
        from src.core.security import TokenInvalid

        mock_creds = MagicMock()
        mock_creds.credentials = "bad.token"

        with patch("src.core.security.decode_token", side_effect=TokenInvalid()):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(mock_creds)
            assert exc.value.status_code == 401

    async def test_missing_sub_raises_401(self):
        from src.core.dependencies import get_current_user

        mock_creds = MagicMock()
        mock_creds.credentials = "no.sub"

        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.return_value = {"uid": "u1"}
            with pytest.raises(HTTPException) as exc:
                await get_current_user(mock_creds)
            assert exc.value.status_code == 401


class TestGetOptionalCurrentUser:
    async def test_no_credentials_returns_empty(self):
        from src.core.dependencies import get_optional_current_user

        result = await get_optional_current_user(None)
        assert result == {}

    async def test_empty_credentials_returns_empty(self):
        from src.core.dependencies import get_optional_current_user

        mock_creds = MagicMock()
        mock_creds.credentials = ""

        result = await get_optional_current_user(mock_creds)
        assert result == {}

    async def test_valid_token_returns_payload(self):
        from src.core.dependencies import get_optional_current_user

        mock_creds = MagicMock()
        mock_creds.credentials = "valid.token"

        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.return_value = {"sub": "testuser"}
            result = await get_optional_current_user(mock_creds)
            assert result["sub"] == "testuser"

    async def test_expired_token_returns_empty(self):
        from src.core.dependencies import get_optional_current_user
        from src.core.security import TokenExpired

        mock_creds = MagicMock()
        mock_creds.credentials = "expired.token"

        with patch("src.core.security.decode_token", side_effect=TokenExpired()):
            result = await get_optional_current_user(mock_creds)
        assert result == {}

    async def test_missing_sub_returns_empty(self):
        from src.core.dependencies import get_optional_current_user

        mock_creds = MagicMock()
        mock_creds.credentials = "no.sub"

        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.return_value = {"uid": "u1"}
            result = await get_optional_current_user(mock_creds)
        assert result == {}


class TestGetRequiredCurrentUser:
    async def test_valid_token_returns_payload(self):
        from src.core.dependencies import get_required_current_user

        mock_creds = MagicMock()
        mock_creds.credentials = "valid.token"

        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.return_value = {"sub": "testuser"}
            result = await get_required_current_user(mock_creds)
            assert result["sub"] == "testuser"

    async def test_expired_token_raises_401(self):
        from src.core.dependencies import get_required_current_user
        from src.core.security import TokenExpired

        mock_creds = MagicMock()
        mock_creds.credentials = "expired.token"

        with patch("src.core.security.decode_token", side_effect=TokenExpired()):
            with pytest.raises(HTTPException) as exc:
                await get_required_current_user(mock_creds)
            assert exc.value.status_code == 401

    async def test_missing_sub_raises_401(self):
        from src.core.dependencies import get_required_current_user

        mock_creds = MagicMock()
        mock_creds.credentials = "no.sub"

        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.return_value = {"uid": "u1"}
            with pytest.raises(HTTPException) as exc:
                await get_required_current_user(mock_creds)
            assert exc.value.status_code == 401


class TestGetRedis:
    def test_get_redis_returns_client(self):
        from src.core.dependencies import get_redis

        mock_redis = MagicMock()
        with patch("src.cache.redis_client.get_redis") as mock_get:
            mock_get.return_value = mock_redis
            result = get_redis()
        assert result is mock_redis


class TestGetCeleryTask:
    def test_get_celery_task_found(self, mock_celery_app):
        from src.core.dependencies import get_celery_task

        mock_task = object()
        mock_celery_app.tasks["test_task"] = mock_task

        result = get_celery_task("test_task")
        assert result is mock_task

    def test_get_celery_task_not_found(self, mock_celery_app):
        from src.core.dependencies import get_celery_task

        result = get_celery_task("nonexistent")
        assert result is None
