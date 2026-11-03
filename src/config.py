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
        if len(self.secret_key) < 32:
            import warnings
            warnings.warn(
                "SECRET_KEY is too short (minimum 32 characters for HMAC-SHA256). "
                "Generate a strong random key with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if not self.debug and self.secret_key in (
            "dev-secret-key-change-in-production",
        ):
            import warnings
            warnings.warn(
                "SECRET_KEY is set to a known default. Set a strong random value in production."
            )
        if not self.database_url and not self.testing:
            raise ValueError(
                "DATABASE_URL must be set via environment variable or .env file."
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

    # Database — MUST be set via DATABASE_URL env var in production
    database_url: str = ""
    database_sync_url: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 5
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

    # Bootstrap password for the seeded "admin" user.  Empty in production →
    # a random one-time password is generated at first startup (see
    # auth/service.py); test/debug mode falls back to the fixed dev credential.
    admin_init_password: str = ""

    # Kdniao (快递鸟) electronic waybill API.  Empty → 面单号 is generated locally
    # (a placeholder the carrier never issued) and the tracking query has nothing
    # to read.  With both set, logistics/kdniao.py calls the real
    # 电子面单下单/轨迹查询 endpoints.
    kdniao_ebusiness_id: str = ""
    kdniao_api_key: str = ""

    # Opt-in for the demo tracking data.  With no 快递鸟 credentials there is no
    # carrier data to read, and the demo generator picks a delivery state out of a
    # hash of the waybill number — "已签收" then is an invention, and dispatch
    # answers customers with it.  Off (the default), a tracking query with no
    # credentials answers 501; on, every event it returns is labelled source=mock.
    logistics_mock_enabled: bool = False

    # Amazon SP-API (LWA credentials, NOT AWS access keys).  Order import works
    # without them — the operator pastes SP-API's own Order object.  Set, they mark
    # the tracking handover as ready for upload (sync_status=queued); the outbound
    # SP-API calls themselves (status poll, tracking upload, inventory sync) are
    # not implemented in this build and say so.
    amazon_sp_api_client_id: str = ""
    amazon_sp_api_client_secret: str = ""
    amazon_sp_api_refresh_token: str = ""
    amazon_sp_api_region: str = "us"

    @property
    def amazon_sp_api_configured(self) -> bool:
        return bool(
            self.amazon_sp_api_client_id
            and self.amazon_sp_api_client_secret
            and self.amazon_sp_api_refresh_token
        )

    # Firebase Cloud Messaging (push notifications)
    firebase_credentials_path: str = ""
    firebase_enabled: bool = False

    # Testing mode (bypasses rate limiter, etc.)
    testing: bool = False

    # Carrier API endpoints (JSON dict: {"carrier_code": "https://api.carrier.com/..."})
    carrier_api_endpoints: str = "{}"

    @property
    def carrier_api_endpoints_dict(self) -> dict[str, str]:
        return json.loads(self.carrier_api_endpoints)


settings = Settings()
