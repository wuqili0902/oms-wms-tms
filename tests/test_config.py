"""Tests for src.config — Settings model."""

import json
import warnings

import pytest


class TestSettings:
    KNOWN_DEFAULT_KEY = "dev-secret-key-change-in-production"

    def test_defaults_from_env(self):
        from src.config import Settings

        s = Settings()
        assert s.app_name == "oms-wms-tms"
        assert s.app_version == "0.1.0"
        assert s.debug is False
        assert s.database_url.startswith("postgresql+asyncpg://")

    def test_raises_on_empty_secret(self):
        from src.config import Settings

        with pytest.raises(ValueError, match="SECRET_KEY must be set"):
            Settings(_env_file=None)

    def test_cors_origins_list(self):
        from src.config import Settings

        s = Settings(cors_origins='["http://localhost:3000"]', secret_key="test-secret")
        assert s.cors_origins_list == ["http://localhost:3000"]

    def test_cors_default(self):
        from src.config import Settings

        s = Settings(secret_key="test-secret")
        assert s.cors_origins_list == ["*"]

    def test_cors_invalid_json(self):
        from src.config import Settings

        s = Settings(cors_origins="not-json", secret_key="test-secret")
        with pytest.raises(json.JSONDecodeError):
            s.cors_origins_list

    def test_fields_from_env(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("APP_NAME", "my-app")
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
        from src.config import Settings

        s = Settings()
        assert s.app_name == "my-app"
        assert s.debug is True
        assert s.database_url == "sqlite:///test.db"

    def test_warning_on_known_dev_secret(self):
        from src.config import Settings

        with pytest.warns(UserWarning, match="SECRET_KEY is set to a known default"):
            Settings(secret_key=self.KNOWN_DEFAULT_KEY, cors_origins='["http://localhost:3000"]')

    def test_debug_suppresses_warning(self):
        from src.config import Settings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            Settings(secret_key=self.KNOWN_DEFAULT_KEY, debug=True, cors_origins='["http://localhost:3000"]')

    def test_custom_secret_no_warning(self):
        from src.config import Settings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            Settings(secret_key="a-strong-secret-value", cors_origins='["http://localhost:3000"]')

    def test_all_fields(self):
        from src.config import Settings

        s = Settings(
            app_name="x",
            app_version="2.0",
            debug=True,
            secret_key="sk-123",
            cors_origins='["a"]',
            database_url="postgresql://u:p@h:5432/d",
            redis_url="redis://r:6379/1",
            rabbitmq_url="amqp://u:p@h:5672/vh",
            host="127.0.0.1",
            port=9000,
            workers=2,
            log_level="debug",
            log_format="text",
            sentry_dsn="https://key@sentry.io/1",
            environment="staging",
            otlp_endpoint="http://otel:4318/v1/traces",
            pda_local_db_path="/data/pda.db",
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_user="user",
            smtp_password="pass",
            smtp_use_tls=False,
            smtp_from="alerts@example.com",
            outbox_dispatch_url="http://hook/api/ingest",
        )
        assert s.database_url == "postgresql://u:p@h:5432/d"
        assert s.sentry_dsn == "https://key@sentry.io/1"
        assert s.smtp_port == 465
