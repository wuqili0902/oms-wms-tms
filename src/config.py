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
    secret_key: str = "change-this-to-a-secure-random-key"

    # CORS
    cors_origins: str = '["*"]'

    @property
    def cors_origins_list(self) -> list[str]:
        return json.loads(self.cors_origins)

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/oms_wms_tms"
    database_sync_url: str = "postgresql://postgres:postgres@localhost:5432/oms_wms_tms"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # RabbitMQ
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4

    # Logging
    log_level: str = "info"
    log_format: str = "json"


settings = Settings()
