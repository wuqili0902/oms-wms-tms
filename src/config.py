import json

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "oms-wms-tms"
    app_version: str = "0.1.0"
    debug: bool = False
    secret_key: str = ""

    def model_post_init(self, __context) -> None:
        if not self.secret_key:
            raise ValueError(
                "SECRET_KEY must be set via environment variable or .env file. "
                "Generate a strong random key with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if not self.debug and self.secret_key in (
            "dev-secret-key-change-in-production",
        ):
            import warnings
            warnings.warn(
                "SECRET_KEY is set to a known default. Set a strong random value in production."
            )
        if self.cors_origins == '["*"]' and not self.debug:
            import warnings
            warnings.warn(
                "CORS is configured with wildcard origin ['*'] in production. "
                "Set CORS_ORIGINS to explicit frontend domain(s) for security."
            )

    # CORS
    cors_origins: str = '["*"]'

    @property
    def cors_origins_list(self) -> list[str]:
        return json.loads(self.cors_origins)

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/oms_wms_tms"
    database_sync_url: str = "postgresql://postgres:postgres@localhost:5432/oms_wms_tms"
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_pre_ping: bool = True

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4

    # Rate limiting
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    # Logging
    log_level: str = "info"
    log_format: str = "json"

    # Sentry (error capture & alerting)
    sentry_dsn: str | None = None
    environment: str = "development"

    # OpenTelemetry OTLP endpoint
    otlp_endpoint: str | None = None  # defaults to http://localhost:4318/v1/traces in tracing.py

    # PDA Offline mode (SQLite local DB path)
    pda_local_db_path: str = "wms_pda.db"  # relative to CWD or absolute path

    # SMTP (email notifications)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_from: str = "noreply@oms-wms-tms.local"

    # Outbox dispatch target (internal webhook endpoint)
    outbox_dispatch_url: str = "http://localhost:8000/api/v1/events/ingest"

    # Firebase Cloud Messaging (push notifications)
    firebase_credentials_path: str = ""
    firebase_enabled: bool = False

    # Carrier API endpoints (JSON dict: {"carrier_code": "https://api.carrier.com/..."})
    carrier_api_endpoints: str = "{}"

    @property
    def carrier_api_endpoints_dict(self) -> dict[str, str]:
        return json.loads(self.carrier_api_endpoints)


settings = Settings()
