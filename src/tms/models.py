"""TMS (Transport Management System) domain models.

Replaces the previous Terminal Management System with a full transportation
management system covering outbound shipment, carrier dispatch, route planning,
tracking, POD, and reverse logistics.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Optional

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin

# ───────────── Carrier Enums ────────────────────────────────────────────────

class CarrierCode(StrEnum):
    """Supported carrier codes."""

    SF_EXPRESS = "sf_express"
    ZTO = "zto"
    YUNDA = "yunda"
    JD_LOGISTICS = "jd_logistics"
    EMS = "ems"


CARRIER_NAMES: dict[str, str] = {
    CarrierCode.SF_EXPRESS.value: "顺丰速运",
    CarrierCode.ZTO.value: "中通快递",
    CarrierCode.YUNDA.value: "韵达速递",
    CarrierCode.JD_LOGISTICS.value: "京东物流",
    CarrierCode.EMS.value: "中国邮政 EMS",
}


class TransportStatus(StrEnum):
    """Transport order lifecycle."""

    DRAFT = "draft"
    DISPATCHED = "dispatched"
    PICKUP_COMPLETED = "pickup_completed"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    CANCELLED = "cancelled"


class CarrierServiceType(StrEnum):
    """Carrier service level."""

    STANDARD = "standard"      # 3-5 days
    EXPRESS = "express"        # next day
    OVERNIGHT = "overnight"
    FREIGHT = "freight"        # B2B heavy


class TransportType(StrEnum):
    """Transport method."""

    SELF_DELIVERY = "self_delivery"     # company own driver
    CARRIER_PICKUP = "carrier_pickup"   # carrier comes to warehouse
    DROP_OFF = "drop_off"               # warehouse drops at station


# ───────────── Transport Order Model ────────────────────────────────────────

class TransportOrder(Base, UUIDMixin, TimestampMixin):
    """Transport order representing a physical shipment contract with a carrier.

    Created from WMS Shipment records; each can carry one or more shipments.
    Supports pickup → in-transit → delivery lifecycle with full tracking events.
    """

    __tablename__ = "transport_orders"

    transport_no: str = Column(String(50), unique=True, index=True)  # e.g. TPL-20260718-0001
    status: TransportStatus = Column(SAEnum(TransportStatus), default=TransportStatus.DRAFT)
    carrier_code: CarrierCode = Column(SAEnum(CarrierCode))

    # Pickup / Delivery locations
    pickup_warehouse_id: UUID = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    pickup_address: dict = Column(JSON, nullable=False)       # formatted address
    delivery_name: str = Column(String(200), nullable=False)   # recipient name
    delivery_phone: str = Column(String(30))
    delivery_address: dict = Column(JSON, nullable=False)      # structured address

    # Shipment reference (links to WMS Shipment or PackingRecord)
    shipment_id: UUID | None = Column(UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=True)
    packing_record_id: UUID | None = Column(UUID(as_uuid=True), nullable=True)

    # Package details
    package_count: int = Column(Integer, default=1)
    total_weight_kg: Decimal = Column(Numeric(20, 4))
    total_volume_m3: Decimal = Column(Numeric(20, 6))

    # Carrier-assigned info
    tracking_number: str = Column(String(100), nullable=True)
    service_type: CarrierServiceType = Column(SAEnum(CarrierServiceType), default=CarrierServiceType.STANDARD)
    transport_type: TransportType = Column(SAEnum(TransportType), default=TransportType.CARRIER_PICKUP)

    # Estimates & actuals
    estimated_delivery_date: date | None = Column(Date, nullable=True)
    actual_pickup_time: datetime | None = Column(DateTime(timezone=True))
    actual_delivery_time: datetime | None = Column(DateTime(timezone=True))

    # Driver / Terminal assignment
    driver_terminal_id: UUID | None = Column(
        UUID(as_uuid=True), ForeignKey("terminal_devices.id"), nullable=True,
    )  # the PDA held by the delivery driver
    driver_name: str = Column(String(100), nullable=True)
    driver_phone: str = Column(String(30), nullable=True)

    # Settlement
    freight_amount: Decimal = Column(Numeric(18, 2), default=Decimal("0"))
    settlement_status: str = Column(String(20), default="pending")  # pending / settled / disputed

    notes: Text | None = Column(Text, nullable=True)
    carrier_config_id: UUID | None = Column(
        UUID(as_uuid=True), ForeignKey("carrier_configs.id"), nullable=True,
    )

    pickup_warehouse = relationship("Warehouse", foreign_keys=[pickup_warehouse_id])
    tracking_events: list["TrackingEvent"] = relationship(
        "TrackingEvent", back_populates="transport_order",
    )
    pod_record: Optional["ProofOfDelivery"] = relationship(
        "ProofOfDelivery", uselist=False, back_populates="transport_order"
    )
    carrier_config = relationship("CarrierConfig")

    __table_args__ = (
        Index("ix_transport_orders_status", "status"),
        Index("ix_transport_orders_carrier_code_created_at", "carrier_code", "created_at"),
    )



# ───────────── Tracking Event Model ─────────────────────────────────────────

class TrackingEventType(StrEnum):
    """Types of tracking scan events."""

    CREATED = "created"              # order created
    DISPATCHED = "dispatched"        # handed to carrier
    PICKUP_COMPLETED = "pickup_completed"  # carrier picked up at warehouse
    IN_TRANSIT = "in_transit"         # departed hub
    ARRIVED_HUB = "arrived_hub"       # arrived intermediate hub
    SORTING_CENTER = "sorting_center"
    OUT_FOR_DELIVERY = "out_for_delivery"  # dispatched to customer
    DELIVERED = "delivered"           # signed by recipient
    EXCEPTION_DELAY = "exception_delay"
    EXCEPTION_DAMAGED = "exception_damaged"
    CANCELLED = "cancelled"


class TrackingEvent(Base, UUIDMixin, TimestampMixin):
    """A single scan event in a transport order's tracking journey."""

    __tablename__ = "tracking_events"

    transport_order_id: UUID = Column(
        UUID(as_uuid=True), ForeignKey("transport_orders.id"), index=True
    )
    event_type: TrackingEventType = Column(SAEnum(TrackingEventType))
    location_code: str | None = Column(String(50))       # hub / station code
    location_name: str | None = Column(String(200))       # human-readable
    latitude: Decimal | None = Column(Numeric(10, 6))
    longitude: Decimal | None = Column(Numeric(10, 6))
    operator_id: UUID | None = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    remark: str | None = Column(Text)

    transport_order = relationship("TransportOrder", back_populates="tracking_events")
    operator = relationship("User")

    __table_args__ = (
        Index(
            "ix_tracking_events_transport_created",
            "transport_order_id",
            "created_at",
        ),
    )


# ───────────── Proof of Delivery Model ──────────────────────────────────────

class PODSignature(StrEnum):
    """POD signature type."""

    PHYSICAL = "physical"     # paper receipt photo
    DIGITAL = "digital"       # on-screen signature


class ProofOfDelivery(Base, UUIDMixin, TimestampMixin):
    """Electronic proof of delivery (ePOD)."""

    __tablename__ = "pod_records"

    transport_order_id: UUID = Column(
        UUID(as_uuid=True), ForeignKey("transport_orders.id"), unique=True, nullable=False
    )
    signed_by: str | None = Column(String(200))       # recipient name or driver name
    signature_type: PODSignature = Column(SAEnum(PODSignature), default=PODSignature.PHYSICAL)
    signature_image_url: str | None = Column(String(500))  # S3 / OSS URL
    delivery_photo_urls: list[dict] = Column(JSON, default=list)  # [{url, timestamp}]
    delivered_to_address: dict = Column(JSON, nullable=True)
    notes: str | None = Column(Text)

    transport_order = relationship("TransportOrder", back_populates="pod_record")


# ───────────── Carrier Configuration Model ──────────────────────────────────

class CarrierConfig(Base, UUIDMixin, TimestampMixin):
    """Carrier account configuration and SLA metrics."""

    __tablename__ = "carrier_configs"

    carrier_code: CarrierCode = Column(SAEnum(CarrierCode), unique=True, nullable=False)
    api_endpoint: str | None = Column(String(500))       # carrier API base URL
    api_key: str | None = Column(String(200))            # encrypted key
    account_number: str | None = Column(String(100))      # warehouse's account with carrier
    on_time_rate: Decimal = Column(Numeric(5, 2), default=Decimal("95.00"))  # SLA %
    avg_delivery_days: Decimal = Column(Numeric(4, 1), default=Decimal("3.0"))
    is_active: bool = True


# ───────────── Hub-and-Spoke Routing Models ──────────────────────────────────

class TransferHubType(StrEnum):
    """Types of transfer hubs."""

    PRIMARY = "primary"            # major hub (e.g., Wuhan)
    SECONDARY = "secondary"        # regional hub (e.g., Changsha)
    CARGO_STATION = "cargo_station"  # cargo station / sorting center


class HubStatus(StrEnum):
    """Hub operational status."""

    OPEN = "open"
    MAINTENANCE = "maintenance"
    CLOSED = "closed"


class TransferHub(Base, UUIDMixin, TimestampMixin):
    """A physical transfer hub / station in the hub-and-spoke network."""

    __tablename__ = "transfer_hubs"

    code: str = Column(String(50), unique=True, index=True, nullable=False)
    name: str = Column(String(200), nullable=False)
    hub_type: TransferHubType = Column(
        SAEnum(TransferHubType), default=TransferHubType.PRIMARY,
    )
    city: str = Column(String(100), nullable=False, index=True)
    address: dict | None = Column(JSON, nullable=True)
    capacity_weight_kg: Decimal = Column(Numeric(20, 4), default=Decimal("0"))
    contact_name: str | None = Column(String(100))
    contact_phone: str | None = Column(String(30))
    status: HubStatus = Column(SAEnum(HubStatus), default=HubStatus.OPEN)


# ───────────── Carrier Route Model ──────────────────────────────────────────

class CarrierRoute(Base, UUIDMixin, TimestampMixin):
    """Pre-defined carrier route between two cities or hub stations.

    Stores route pricing and timing for origin → destination pairs.
    Used by the route planner to compute multi-segment plans.
    """

    __tablename__ = "carrier_routes"

    carrier_code: CarrierCode = Column(SAEnum(CarrierCode), nullable=False, index=True)
    origin_city: str = Column(String(100), nullable=False, index=True)
    dest_city: str = Column(String(100), nullable=False, index=True)
    distance_km: Decimal = Column(Numeric(20, 4))                  # ~800 km
    transit_hours: Decimal = Column(Numeric(10, 1))                # ~12 h
    base_price_per_kg: Decimal = Column(Numeric(18, 4))            # ¥/kg
    express_surcharge: Decimal = Column(Numeric(18, 4), default=Decimal("0"))
    min_charge_weight: Decimal = Column(Numeric(20, 4), default=Decimal("1.0"))
    is_active: bool = True


# ───────────── Transport Segment Model ────────────────────────────────────────

class TransportSegmentStatus(StrEnum):
    """Lifecycle of an individual transport segment."""

    DRAFT = "draft"
    DISPATCHED = "dispatched"
    PICKUP = "pickup"
    IN_TRANSIT = "in_transit"
    TRANSIT_HUB_ARRIVED = "transit_hub_arrived"
    SORTING_CENTER = "sorting_center"
    OUT_FOR_DELIVERY = "out_for_delivery"
    COMPLETED = "completed"
    EXCEPTION = "exception"
    CANCELLED = "cancelled"


class TransportSegment(Base, UUIDMixin, TimestampMixin):
    """A single leg (origin → destination) within a multi-segment route plan.

    Each segment is independently dispatched to a carrier and tracked via its
    own tracking events.  A TransportOrder can contain multiple segments chained
    through hub-and-spoke routing.
    """

    __tablename__ = "transport_segments"

    transport_order_id: UUID = Column(
        UUID(as_uuid=True), ForeignKey("transport_orders.id"), index=True,
    )
    segment_no: int = Column(Integer, default=1)                # 0-based position in plan
    origin_hub_code: str | None = Column(String(50))            # e.g. WUHAN_HUB
    dest_hub_code: str | None = Column(String(50))              # e.g. LIUZHOU_HUB or destination city

    carrier_code: CarrierCode | None = Column(SAEnum(CarrierCode), nullable=True)
    status: TransportSegmentStatus = Column(
        SAEnum(TransportSegmentStatus), default=TransportSegmentStatus.DRAFT,
    )
    tracking_number: str | None = Column(String(100))

    estimated_departure_time: datetime | None = Column(DateTime(timezone=True))
    actual_departure_time: datetime | None = Column(DateTime(timezone=True))
    expected_arrival_time: datetime | None = Column(DateTime(timezone=True))
    actual_arrival_time: datetime | None = Column(DateTime(timezone=True))

    weight_kg: Decimal = Column(Numeric(20, 4), default=Decimal("0"))
    cost_amount: Decimal = Column(Numeric(18, 2), default=Decimal("0"))

    notes: str | None = Column(String(500))


# ───────────── Hub Connection Model (graph edges) ────────────────────────────

class HubConnection(Base, UUIDMixin, TimestampMixin):
    """Connectivity between two hubs — the graph for route planning."""

    __tablename__ = "hub_connections"

    from_hub_code: str = Column(String(50), nullable=False, index=True)
    to_hub_code: str = Column(String(50), nullable=False, index=True)
    distance_km: Decimal = Column(Numeric(20, 4))              # edge weight
    transit_hours: Decimal = Column(Numeric(10, 1))             # travel time
    is_active: bool = True

    __table_args__ = (
        Index("uq_hub_connections", "from_hub_code", "to_hub_code", unique=True),
    )


# ───────────── Route Plan Model ──────────────────────────────────────────────

class RoutePlanType(StrEnum):
    """How the route plan was generated."""

    AUTO_GEN = "auto_gen"        # algorithm computed optimal multi-segment plan
    MANUAL = "manual"           # user manually selected a predefined plan


class RoutePlanStatus(StrEnum):
    ROUTE_ACTIVE = "route_active"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RoutePlan(Base, UUIDMixin, TimestampMixin):
    """A route plan tied to a TransportOrder — the multi-segment routing blueprint.

    Stores origin/destination cities, total distance, cost breakdown, and links
    back to individual TransportSegments.  Each plan is either auto-generated by
    Dijkstra shortest-path or manually assembled from available carrier routes.
    """

    __tablename__ = "route_plans"

    transport_order_id: UUID = Column(
        UUID(as_uuid=True), ForeignKey("transport_orders.id"), unique=True, nullable=False,
    )
    type: RoutePlanType = Column(SAEnum(RoutePlanType))
    status: RoutePlanStatus = Column(SAEnum(RoutePlanStatus), default=RoutePlanStatus.ROUTE_ACTIVE)

    origin_city: str = Column(String(100), nullable=False)
    destination_city: str = Column(String(100), nullable=False)

    total_distance_km: Decimal = Column(Numeric(20, 4))           # sum of segment distances
    total_cost_amount: Decimal = Column(Numeric(18, 2))           # freight cost for full order
    estimated_transit_hours: Decimal = Column(Numeric(10, 1))     # total ETA in hours

    plan_json: dict | None = Column(
        JSON, nullable=False
    )  # raw route tree for UI display


# ───────────── Reverse Logistics Model ────────────────────────────────────────

class ReturnReason(StrEnum):
    """Customer return reason codes."""

    DAMAGED = "damaged"
    WRONG_ITEM = "wrong_item"
    QUALITY_ISSUE = "quality_issue"
    CUSTOMER_RETRIEVAL = "customer_retrieval"  # customer changed mind
    ADDRESS_ERROR = "address_error"
    DUPLICATE_ORDER = "duplicate_order"


class ReturnStatus(StrEnum):
    """Return order lifecycle."""

    REQUESTED = "requested"
    PICKUP_SCHEDULED = "pickup_scheduled"
    IN_TRANSIT_RETURN = "in_transit_return"
    RETURNED_TO_WAREHOUSE = "returned_to_warehouse"
    REFUNDED = "refunded"
    CLOSED = "closed"


class ReturnShipmentStatus(StrEnum):
    """Physical shipment lifecycle for return orders."""

    PENDING = "pending"
    PICKUP_SCHEDULED = "pickup_scheduled"
    IN_TRANSIT_RETURN = "in_transit_return"
    RECEIVED_BY_CARRIER = "received_by_carrier"
    RETURNED_TO_WAREHOUSE = "returned_to_warehouse"


class ReturnOrder(Base, UUIDMixin, TimestampMixin):
    """Reverse logistics / return order."""

    __tablename__ = "return_orders"

    return_no: str = Column(String(50), unique=True, index=True)  # RTN-20260718-0001
    status: ReturnStatus = Column(SAEnum(ReturnStatus), default=ReturnStatus.REQUESTED)
    shipment_status: ReturnShipmentStatus = Column(
        SAEnum(ReturnShipmentStatus), default=ReturnShipmentStatus.PENDING,
    )
    reason: ReturnReason = Column(SAEnum(ReturnReason))
    reason_detail: str | None = Column(Text)

    # Link to original transport order (if any)
    transport_order_id: UUID | None = Column(
        UUID(as_uuid=True), ForeignKey("transport_orders.id"), nullable=True,
    )

    # Return logistics
    carrier_code: CarrierCode | None = Column(SAEnum(CarrierCode))
    return_tracking_number: str | None = Column(String(100))
    pickup_address: dict = Column(JSON)  # where customer ships from (return address)
    destination_warehouse_id: UUID | None = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"))

    # Settlement
    refund_amount: Decimal = Column(Numeric(18, 2), default=Decimal("0"))

    destination_warehouse = relationship("Warehouse", foreign_keys=[destination_warehouse_id])
    transport_order = relationship("TransportOrder")


# ───────────── Exception Model ──────────────────────────────────────────────

class ExceptionType(StrEnum):
    """Types of transport exceptions."""

    DELAYED = "delayed"
    DAMAGED_IN_TRANSIT = "damaged_in_transit"
    LOST = "lost"
    ADDRESS_ISSUE = "address_issue"
    CUSTOMER_UNAVAILABLE = "customer_unavailable"
    WEATHER = "weather"


class ExceptionStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class TransportException(Base, UUIDMixin, TimestampMixin):
    """Transport exception / incident."""

    __tablename__ = "transport_exceptions"

    transport_order_id: UUID | None = Column(
        UUID(as_uuid=True), ForeignKey("transport_orders.id"), index=True, nullable=True
    )
    type: ExceptionType = Column(SAEnum(ExceptionType))
    status: ExceptionStatus = Column(SAEnum(ExceptionStatus), default=ExceptionStatus.OPEN)
    severity: str = Column(String(20), default="normal")  # normal / high / critical
    description: str | None = Column(Text, nullable=True)
    resolution_notes: str | None = Column(Text, nullable=True)

    transport_order = relationship("TransportOrder")


# ───────────── Settlement Model ────────────────────────────────────────────

class FreightRule(StrEnum):
    """Freight calculation rule types."""

    WEIGHT_TIERED = "weight_tiered"      # tiered by weight bracket
    DISTANCE_TIERED = "distance_tiered"  # per km
    FLAT_RATE = "flat_rate"              # fixed price
    VOLUME_BASED = "volume_based"        # per cubic meter


class FreightTier(Base, UUIDMixin, TimestampMixin):
    """Freight rate tier within a rule."""

    __tablename__ = "freight_tiers"

    carrier_code: CarrierCode = Column(SAEnum(CarrierCode), primary_key=True)
    rule_type: FreightRule = Column(SAEnum(FreightRule))
    min_value: Decimal = Column(Numeric(20, 4))   # min weight/volume/km
    max_value: Decimal | None = Column(Numeric(20, 4))
    price_per_unit: Decimal = Column(Numeric(18, 4))
    surcharge_express: Decimal = Column(Numeric(18, 4), default=Decimal("0"))


# ── Legacy Device Management Models (Terminal Management) — kept for backward compat ─

class TerminalDeviceType(StrEnum):
    PDA = "pda"
    PHONE = "phone"
    SCANNER = "scanner"
    PRINTER = "printer"


class PlatformType(StrEnum):
    ANDROID = "android"
    IOS = "ios"
    DESKTOP = "desktop"


class DeviceStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    DISABLED = "disabled"


class SyncLogType(StrEnum):
    UPLOAD = "upload"
    DOWNLOAD = "download"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"


class SyncLogStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class TerminalDevice(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Terminal device model — kept for backward compat."""

    __tablename__ = "terminal_devices"

    code: str = Column(String(50), unique=True, index=True)
    name: str | None = Column(String(200))
    device_type: TerminalDeviceType = Column(SAEnum(TerminalDeviceType))
    platform: PlatformType = Column(SAEnum(PlatformType))
    os_version: str | None = Column(String(50))
    app_version: str | None = Column(String(20))
    status: DeviceStatus = Column(SAEnum(DeviceStatus), default=DeviceStatus.OFFLINE)
    warehouse_id: UUID | None = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=True)
    last_sync_at: datetime | None = Column(DateTime(timezone=True), nullable=True, index=True)
    last_heartbeat_at: datetime | None = Column(DateTime(timezone=True), nullable=True, index=True)
    config: dict | None = Column(JSON, nullable=True)
    push_token: str | None = Column(String(500), nullable=True)

    device_sessions: list["DeviceSession"] = relationship("DeviceSession", back_populates="device")
    sync_logs: list["SyncLog"] = relationship("SyncLog", back_populates="device")

    __table_args__ = (Index("ix_terminal_devices_status", "status"),)


class DeviceSession(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Active device session — kept for backward compat."""

    __tablename__ = "device_sessions"

    device_id: UUID = Column(UUID(as_uuid=True), ForeignKey("terminal_devices.id"))
    token: str = Column(String(500), unique=True, index=True)
    login_at: datetime = Column(DateTime(timezone=True))
    status: SessionStatus = Column(SAEnum(SessionStatus), default=SessionStatus.ACTIVE)
    logout_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
    ip_address: str | None = Column(String(45))

    device: TerminalDevice = relationship("TerminalDevice", back_populates="device_sessions")

    __table_args__ = (Index("ix_device_sessions_device_id_active", "device_id", "logout_at"),)


class SyncLog(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Sync log — kept for backward compat."""

    __tablename__ = "sync_logs"

    device_id: UUID = Column(UUID(as_uuid=True), ForeignKey("terminal_devices.id"))
    sync_type: SyncLogType = Column(SAEnum(SyncLogType))
    status: SyncLogStatus = Column(SAEnum(SyncLogStatus), default=SyncLogStatus.PENDING)
    records_count: int = Column(Integer, default=0)
    error_message: str | None = Column(Text, nullable=True)
    started_at: datetime = Column(DateTime(timezone=True))
    completed_at: datetime | None = Column(DateTime(timezone=True), nullable=True)

    device: TerminalDevice = relationship("TerminalDevice", back_populates="sync_logs")

    __table_args__ = (
        Index("ix_sync_logs_device_id_status", "device_id", "status"),
    )
