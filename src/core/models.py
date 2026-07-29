"""Core shared models — Address Master for cross-subsystem reuse."""
import uuid

from sqlalchemy import Column, String, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.base import Base, TimestampMixin, UUIDMixin


class AddressMaster(Base, UUIDMixin, TimestampMixin):
    """Central address book shared across OMS, WMS, and TMS.

    Stores normalized address data with deduplication support.
    """

    __tablename__ = "address_master"

    label: str = Column(String(100), index=True)
    entity_type: str = Column(String(20), nullable=False, index=True)
    entity_id: UUID | None = Column(UUID(as_uuid=True), nullable=True, index=True)
    address_type: str = Column(String(20), nullable=False)
    contact_name: str = Column(String(100))
    phone: str = Column(String(30))
    email: str = Column(String(255))
    address_line_1: str = Column(String(255))
    address_line_2: str = Column(String(255))
    city: str = Column(String(100))
    state: str = Column(String(100))
    postal_code: str = Column(String(20))
    country: str = Column(String(100), default="中国")

    def __repr__(self):
        return f"<AddressMaster {self.label}: {self.city}>"


async def resolve_address(
    db: AsyncSession,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    address_type: str | None = None,
) -> list[dict]:
    """Look up addresses for a given entity, returning all matches."""
    stmt = select(AddressMaster).where(AddressMaster.entity_type == entity_type)
    if entity_id:
        eid = uuid.UUID(str(entity_id)) if isinstance(entity_id, str) else entity_id
        stmt = stmt.where(AddressMaster.entity_id == eid)
    if address_type:
        stmt = stmt.where(AddressMaster.address_type == address_type)
    stmt = stmt.order_by(AddressMaster.created_at.desc())
    result = await db.execute(stmt)
    return [
        {
            "id": str(a.id),
            "label": a.label,
            "address_type": a.address_type,
            "contact_name": a.contact_name,
            "phone": a.phone,
            "email": a.email,
            "address_line_1": a.address_line_1,
            "address_line_2": a.address_line_2,
            "city": a.city,
            "state": a.state,
            "postal_code": a.postal_code,
            "country": a.country,
        }
        for a in result.scalars().all()
    ]
