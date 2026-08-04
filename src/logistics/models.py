import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, SoftDeleteMixin, TimestampMixin


class Waybill(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "waybills"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    tracking_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    order_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    carrier_code: Mapped[str] = mapped_column(String(10), nullable=False)
    carrier_name: Mapped[str] = mapped_column(String(50), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(100), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_address: Mapped[str] = mapped_column(Text, nullable=False)
    items: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="created", index=True
    )
    print_count: Mapped[int] = mapped_column(Integer, default=0)
    last_printed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    label_url: Mapped[str | None] = mapped_column(Text, nullable=True)
