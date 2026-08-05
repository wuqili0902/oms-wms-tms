"""Seed data for TMS demo — hubs, carrier routes, freight rules."""
import asyncio
import uuid
from decimal import Decimal

from sqlalchemy import select

from src.core.database import async_session_factory
from src.tms.models import (
    CarrierCode,
    CarrierRoute,
    FreightRule,
    FreightTier,
    HubConnection,
    TransferHub,
    TransferHubType,
)


async def seed_hubs(db):
    hubs = [
        ("WUHAN_HUB", "武汉枢纽", TransferHubType.PRIMARY, "武汉"),
        ("CHANGSHA_HUB", "长沙枢纽", TransferHubType.SECONDARY, "长沙"),
        ("LIUZHOU_HUB", "柳州枢纽", TransferHubType.SECONDARY, "柳州"),
        ("BEIJING_HUB", "北京枢纽", TransferHubType.PRIMARY, "北京"),
        ("SHANGHAI_HUB", "上海枢纽", TransferHubType.PRIMARY, "上海"),
    ]
    for code, name, htype, city in hubs:
        ex = await db.execute(select(TransferHub).where(TransferHub.code == code))
        if not ex.scalar_one_or_none():
            t = TransferHub(id=uuid.uuid4(), code=code, name=name, hub_type=htype, city=city)
            db.add(t)
    await db.commit()


async def seed_hub_connections(db):
    """Connect hubs by approximate transit times."""
    conns = [
        ("WUHAN_HUB", "CHANGSHA_HUB", 350.0, Decimal("4.0")),
        ("CHANGSHA_HUB", "LIUZHOU_HUB", 500.0, Decimal("6.0")),
        ("BEIJING_HUB", "SHANGHAI_HUB", 1200.0, Decimal("12.0")),
    ]
    for frm, to, dist, hours in conns:
        ex = await db.execute(
            select(HubConnection).where(HubConnection.from_hub_code == frm, HubConnection.to_hub_code == to)
        )
        if not ex.scalar_one_or_none():
            c = HubConnection(id=uuid.uuid4(), from_hub_code=frm, to_hub_code=to,
                              distance_km=dist, transit_hours=hours)
            db.add(c)
    await db.commit()


async def seed_carrier_routes(db):
    routes = [
        ("WUHAN", "CHANGSHA", 350.0, Decimal("4.0"), Decimal("120.0")),
        ("CHANGSHA", "LIUZHOU", 500.0, Decimal("6.0"), Decimal("180.0")),
    ]
    for origin, dest, dist, hours, price in routes:
        r = CarrierRoute(id=uuid.uuid4(), carrier_code=CarrierCode.SF_EXPRESS,
                         origin_city=origin, dest_city=dest, distance_km=dist,
                         transit_hours=hours, base_price_per_kg=price)
        db.add(r)
    await db.commit()


async def seed_freight_rules(db):
    rules = [
        (CarrierCode.SF_EXPRESS, "weight_tiered", Decimal("0"), Decimal("10.0"), Decimal("8.5")),
        (CarrierCode.SF_EXPRESS, "weight_tiered", Decimal("10.0"), None, Decimal("7.2")),
    ]
    for carrier, rule_type, mn, mx, pp in rules:
        f = FreightTier(id=uuid.uuid4(), carrier_code=carrier, rule_type=FreightRule(rule_type),
                        min_value=mn, max_value=mx, price_per_unit=pp)
        db.add(f)
    await db.commit()


async def main(db=None):
    if db is None:
        async with async_session_factory() as session:
            await seed_hubs(session)
            await seed_hub_connections(session)
            await seed_carrier_routes(session)
            await seed_freight_rules(session)
    else:
        # Accept a session directly (for tests that pass db_session fixture)
        await seed_hubs(db)
        await seed_hub_connections(db)
        await seed_carrier_routes(db)
        await seed_freight_rules(db)

    print("Seed done.")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
