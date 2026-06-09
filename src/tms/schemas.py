"""TMS schemas — device registration, sessions, and sync logs."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Device ──────────────────────────────────────────────────────────────────

class DeviceRegister(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(default="", max_length=200)
    device_type: str = Field(default="pda", pattern=r"^(pda|phone|scanner|printer)$")
    platform: str = Field(default="android", pattern=r"^(android|ios|desktop)$")
    os_version: str = Field(default="", max_length=50)
    app_version: str = Field(default="", max_length=20)
    warehouse_id: Optional[str] = None
    config: Optional[dict] = None
    push_token: Optional[str] = None


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    os_version: Optional[str] = None
    app_version: Optional[str] = None
    warehouse_id: Optional[str] = None
    config: Optional[dict] = None
    push_token: Optional[str] = None
    status: Optional[str] = None


class DeviceResponse(BaseModel):
    id: str
    code: str
    name: str
    device_type: str
    platform: str
    os_version: str
    app_version: str
    status: str
    warehouse_id: Optional[str] = None
    last_sync_at: Optional[str] = None
    last_heartbeat_at: Optional[str] = None
    config: Optional[dict] = None
    push_token: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ── Heartbeat ───────────────────────────────────────────────────────────────

class HeartbeatResponse(BaseModel):
    id: str
    status: str
    last_heartbeat_at: str
    message: str


# ── Sync Log ────────────────────────────────────────────────────────────────

class SyncLogCreate(BaseModel):
    sync_type: str = Field(default="download", pattern=r"^(upload|download)$")
    status: str = Field(default="pending", pattern=r"^(pending|running|completed|failed|partial)$")
    records_count: int = Field(default=0, ge=0, alias="data_count")
    error_message: Optional[str] = None

    model_config = {"populate_by_name": True}


class SyncLogResponse(BaseModel):
    id: str
    device_id: str
    sync_type: str
    status: str
    records_count: int
    error_message: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Session ─────────────────────────────────────────────────────────────────

class SessionResponse(BaseModel):
    id: str
    device_id: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    login_at: str
    logout_at: Optional[str] = None

    model_config = {"from_attributes": True}
