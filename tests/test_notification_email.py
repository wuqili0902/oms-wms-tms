from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.notification.email import EmailMessage, EmailService


class TestEmailMessage:
    def test_defaults(self):
        msg = EmailMessage(to=["a@b.com"], subject="Test")
        assert msg.body_text == ""
        assert msg.body_html == ""

    def test_full_message(self):
        msg = EmailMessage(to=["a@b.com"], subject="Test", body_text="Hello", body_html="<p>Hello</p>")
        assert msg.body_text == "Hello"
        assert msg.body_html == "<p>Hello</p>"


class TestEmailService:
    @pytest.fixture
    def service_disabled(self):
        svc = EmailService()
        svc._enabled = False
        return svc

    @pytest.fixture
    def service_enabled(self):
        svc = EmailService()
        svc._enabled = True
        svc.host = "smtp.example.com"
        svc.port = 587
        svc.username = "user"
        svc.password = "pass"
        svc.from_addr = "noreply@example.com"
        return svc

    async def test_send_disabled_returns_false(self, service_disabled):
        result = await service_disabled.send(EmailMessage(to=["a@b.com"], subject="Test"))
        assert result is False

    async def test_send_success(self, service_enabled):
        mock_smtp = AsyncMock()
        with patch("src.notification.email.aiosmtplib.SMTP", return_value=mock_smtp):
            result = await service_enabled.send(EmailMessage(to=["a@b.com"], subject="Hi", body_text="Hello"))
        assert result is True
        mock_smtp.connect.assert_awaited_once()
        mock_smtp.sendmail.assert_awaited_once()
        mock_smtp.quit.assert_awaited_once()

    async def test_send_with_tls(self, service_enabled):
        service_enabled.use_tls = True
        mock_smtp = AsyncMock()
        with patch("src.notification.email.aiosmtplib.SMTP", return_value=mock_smtp):
            result = await service_enabled.send(EmailMessage(to=["a@b.com"], subject="Hi"))
        assert result is True
        mock_smtp.starttls.assert_awaited_once()

    async def test_send_without_login(self, service_enabled):
        service_enabled.username = ""
        mock_smtp = AsyncMock()
        with patch("src.notification.email.aiosmtplib.SMTP", return_value=mock_smtp):
            result = await service_enabled.send(EmailMessage(to=["a@b.com"], subject="Hi"))
        assert result is True
        mock_smtp.login.assert_not_called()

    async def test_send_with_html(self, service_enabled):
        mock_smtp = AsyncMock()
        with patch("src.notification.email.aiosmtplib.SMTP", return_value=mock_smtp):
            result = await service_enabled.send(EmailMessage(to=["a@b.com"], subject="Hi", body_html="<p>Hi</p>"))
        assert result is True

    async def test_send_exception_returns_false(self, service_enabled):
        mock_smtp = AsyncMock()
        mock_smtp.connect.side_effect = Exception("Connection refused")
        with patch("src.notification.email.aiosmtplib.SMTP", return_value=mock_smtp):
            result = await service_enabled.send(EmailMessage(to=["a@b.com"], subject="Hi"))
        assert result is False

    async def test_send_template(self, service_enabled):
        mock_smtp = AsyncMock()
        with (
            patch("src.notification.email.aiosmtplib.SMTP", return_value=mock_smtp),
            patch.object(service_enabled, "send", wraps=service_enabled.send) as mock_send,
        ):
            result = await service_enabled.send_template(["a@b.com"], "Subject", "Hello {name}", name="World")
        assert result is True
        args, _ = mock_send.call_args
        assert args[0].body_text == "Hello World"


class TestEmailSingleton:
    def test_email_service_is_instance(self):
        from src.notification.email import email_service
        assert isinstance(email_service, EmailService)
