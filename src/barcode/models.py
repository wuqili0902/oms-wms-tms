import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Boolean, Float, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base, TimestampMixin


class BarcodeRecord(Base, TimestampMixin):
    __tablename__ = "barcode_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    gtin: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="order/inventory/location/device")
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False, comment="ean13/code128/qr/datamatrix")
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class LabelTemplate(Base, TimestampMixin):
    __tablename__ = "label_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(20), nullable=False, comment="zpl/ezpl")
    width_mm: Mapped[float] = mapped_column(Float, nullable=False)
    height_mm: Mapped[float] = mapped_column(Float, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
