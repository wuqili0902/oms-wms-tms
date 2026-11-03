"""Tests for TMS route planning — TransferHub, CarrierRoute, HubConnection, RoutePlan."""
import uuid
from decimal import Decimal

import pytest

from src.core.exceptions import NotFoundException, ValidationException
from src.tms import service as tms_service


def _uniq(prefix: str = "") -> str:
    """Return a unique string for test data isolation."""
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


# ═══════════════════════════════════════════════════════════════════════════════
# TransferHub CRUD
# ═══════════════════════════════════════════════════════════════════════════════


class TestTransferHubCRUD:
    """Transfer hub create / read / update / list."""

    @pytest.mark.asyncio
    async def test_create_hub(self, db_session):
        code = _uniq("HUB")
        hub = await tms_service.create_hub(db_session, {
            "code": code,
            "name": "Test Hub",
            "type": "primary",
            "city": "武汉",
        })
        assert hub["code"] == code
        assert hub["city"] == "武汉"
        assert hub["status"] == "open"

    @pytest.mark.asyncio
    async def test_create_duplicate_hub_code(self, db_session):
        code = _uniq("DUP")
        await tms_service.create_hub(db_session, {
            "code": code, "name": "First", "city": "武汉",
        })
        with pytest.raises(ValidationException, match="already exists"):
            await tms_service.create_hub(db_session, {
                "code": code, "name": "Second", "city": "武汉",
            })

    @pytest.mark.asyncio
    async def test_get_hub(self, db_session):
        code = _uniq("GET")
        created = await tms_service.create_hub(db_session, {
            "code": code, "name": "长沙", "city": "长沙",
        })
        fetched = await tms_service.get_hub(db_session, created["id"])
        assert fetched["id"] == created["id"]
        assert fetched["name"] == "长沙"

    @pytest.mark.asyncio
    async def test_get_hub_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.get_hub(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_list_hubs_by_city(self, db_session):
        unique_city = _uniq("CITY")
        await tms_service.create_hub(db_session, {"code": _uniq("WH"), "name": "CityA", "city": unique_city})
        await tms_service.create_hub(db_session, {"code": _uniq("CS"), "name": "CityB", "city": _uniq("OTHER")})
        hubs = await tms_service.list_hubs(db_session, city=unique_city)
        assert len(hubs) == 1
        assert hubs[0]["city"] == unique_city

    @pytest.mark.asyncio
    async def test_list_hubs_by_type(self, db_session):
        await tms_service.create_hub(
            db_session, {"code": _uniq("WH"), "name": "武汉", "city": "武汉", "type": "primary"}
        )
        await tms_service.create_hub(
            db_session, {"code": _uniq("LZ"), "name": "柳州", "city": "柳州", "type": "secondary"}
        )
        hubs = await tms_service.list_hubs(db_session, hub_type="secondary")
        assert len(hubs) == 1
        assert hubs[0]["hub_type"] == "secondary"

    @pytest.mark.asyncio
    async def test_update_hub(self, db_session):
        hub = await tms_service.create_hub(db_session, {
            "code": "HUB", "name": "Original", "city": "武汉",
        })
        updated = await tms_service.update_hub(db_session, hub["id"], {
            "name": "Updated Hub",
            "contact_name": "张三",
        })
        assert updated["name"] == "Updated Hub"
        assert updated["contact_name"] == "张三"

    @pytest.mark.asyncio
    async def test_update_hub_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.update_hub(db_session, str(uuid.uuid4()), {"name": "X"})


# ═══════════════════════════════════════════════════════════════════════════════
# CarrierRoute CRUD
# ═══════════════════════════════════════════════════════════════════════════════


class TestCarrierRouteCRUD:
    """Carrier route create / list."""

    @pytest.mark.asyncio
    async def test_add_carrier_route(self, db_session):
        oc = _uniq("OC")
        dc = _uniq("DC")
        route = await tms_service.add_carrier_route(db_session, {
            "carrier_code": "sf_express",
            "origin_city": oc,
            "dest_city": dc,
            "distance_km": 300,
            "transit_hours": 4,
            "base_price_per_kg": Decimal("8.0"),
        })
        assert route["origin_city"] == oc
        assert route["dest_city"] == dc
        assert route["carrier_code"] == "sf_express"

    @pytest.mark.asyncio
    async def test_list_carrier_routes_filter(self, db_session):
        oc = _uniq("OC")
        dc1 = _uniq("DC")
        dc2 = _uniq("DC")
        await tms_service.add_carrier_route(db_session, {
            "carrier_code": "sf_express", "origin_city": oc, "dest_city": dc1,
            "distance_km": 300, "transit_hours": 4, "base_price_per_kg": Decimal("8"),
        })
        await tms_service.add_carrier_route(db_session, {
            "carrier_code": "zto", "origin_city": oc, "dest_city": dc2,
            "distance_km": 800, "transit_hours": 12, "base_price_per_kg": Decimal("6"),
        })
        routes = await tms_service.list_carrier_routes(db_session, origin_city=oc)
        assert len(routes) == 2
        routes_cs = await tms_service.list_carrier_routes(db_session, dest_city=dc1)
        assert len(routes_cs) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# HubConnection CRUD
# ═══════════════════════════════════════════════════════════════════════════════


class TestHubConnectionCRUD:
    """Hub connection create / list."""

    @pytest.mark.asyncio
    async def test_add_hub_connection(self, db_session):
        frm = _uniq("F")
        to = _uniq("T")
        conn = await tms_service.add_hub_connection(db_session, {
            "from_hub_code": frm,
            "to_hub_code": to,
            "distance_km": 300,
            "transit_hours": 4,
        })
        assert conn["from_hub_code"] == frm
        assert conn["to_hub_code"] == to

    @pytest.mark.asyncio
    async def test_add_duplicate_connection(self, db_session):
        frm = _uniq("A")
        to = _uniq("B")
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": frm, "to_hub_code": to, "distance_km": 100, "transit_hours": 2,
        })
        with pytest.raises(ValidationException, match="already exists"):
            await tms_service.add_hub_connection(db_session, {
                "from_hub_code": frm, "to_hub_code": to, "distance_km": 200, "transit_hours": 3,
            })

    @pytest.mark.asyncio
    async def test_list_hub_connections(self, db_session):
        a, b = _uniq("A"), _uniq("B")
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": a, "to_hub_code": b, "distance_km": 300, "transit_hours": 4,
        })
        c, d = _uniq("C"), _uniq("D")
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": c, "to_hub_code": d, "distance_km": 500, "transit_hours": 6,
        })
        all_conns = await tms_service.list_hub_connections(db_session)
        # At minimum our 2 connections exist — account for any prior data
        assert len(all_conns) >= 2

    @pytest.mark.asyncio
    async def test_list_hub_connections_filter(self, db_session):
        frm = _uniq("X")
        to = _uniq("Y")
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": frm, "to_hub_code": to, "distance_km": 300, "transit_hours": 4,
        })
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": to, "to_hub_code": frm, "distance_km": 300, "transit_hours": 4,
        })
        conns = await tms_service.list_hub_connections(db_session, hub_code=frm)
        assert len(conns) == 2  # both directions involve frm


# ═══════════════════════════════════════════════════════════════════════════════
# TransportSegment CRUD + State Machine
# ═══════════════════════════════════════════════════════════════════════════════


class TestTransportSegment:
    """Transport segment create, read, list, status transitions."""

    @pytest.fixture
    def _order_id(self, db_session):
        """Create a transport order and return its ID."""
        import asyncio
        order = asyncio.get_running_loop().run_until_complete(
            tms_service.create_transport_order(db_session, {
                "carrier_code": "sf_express",
                "pickup_warehouse_id": str(uuid.uuid4()),
                "delivery_name": "Test",
                "delivery_address": {"province": "Guangdong", "city": "Shenzhen"},
            })
        )
        return order["id"]

    @pytest.mark.asyncio
    async def _make_order(self, db_session):
        return await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Test",
            "delivery_address": {"province": "Guangdong", "city": "Shenzhen"},
        })

    @pytest.mark.asyncio
    async def test_create_segment(self, db_session):
        order = await self._make_order(db_session)
        seg = await tms_service.create_segment(db_session, {
            "transport_order_id": order["id"],
            "segment_no": 0,
            "origin_hub_code": "HUB_A",
            "dest_hub_code": "HUB_B",
            "carrier_code": "sf_express",
            "weight_kg": Decimal("10"),
        })
        assert seg["segment_no"] == 0
        assert seg["status"] == "draft"
        assert seg["origin_hub_code"] == "HUB_A"

    @pytest.mark.asyncio
    async def test_get_segment(self, db_session):
        order = await self._make_order(db_session)
        seg = await tms_service.create_segment(db_session, {
            "transport_order_id": order["id"],
            "segment_no": 1,
        })
        fetched = await tms_service.get_segment(db_session, seg["id"])
        assert fetched["id"] == seg["id"]
        assert fetched["segment_no"] == 1

    @pytest.mark.asyncio
    async def test_list_segments(self, db_session):
        order = await self._make_order(db_session)
        await tms_service.create_segment(db_session, {
            "transport_order_id": order["id"], "segment_no": 0,
        })
        await tms_service.create_segment(db_session, {
            "transport_order_id": order["id"], "segment_no": 1,
        })
        segs = await tms_service.list_segments(db_session, order["id"])
        assert len(segs) == 2

    @pytest.mark.asyncio
    async def test_segment_status_lifecycle(self, db_session):
        order = await self._make_order(db_session)
        seg = await tms_service.create_segment(db_session, {
            "transport_order_id": order["id"], "segment_no": 0,
        })
        s1 = await tms_service.update_segment_status(db_session, seg["id"], "dispatched")
        assert s1["status"] == "dispatched"
        s2 = await tms_service.update_segment_status(db_session, seg["id"], "pickup")
        assert s2["status"] == "pickup"
        s3 = await tms_service.update_segment_status(db_session, seg["id"], "in_transit")
        assert s3["status"] == "in_transit"
        s4 = await tms_service.update_segment_status(db_session, seg["id"], "out_for_delivery")
        assert s4["status"] == "out_for_delivery"
        s5 = await tms_service.update_segment_status(db_session, seg["id"], "completed")
        assert s5["status"] == "completed"

    @pytest.mark.asyncio
    async def test_segment_invalid_transition(self, db_session):
        order = await self._make_order(db_session)
        seg = await tms_service.create_segment(db_session, {
            "transport_order_id": order["id"], "segment_no": 0,
        })
        with pytest.raises(ValidationException, match="Cannot transition"):
            await tms_service.update_segment_status(db_session, seg["id"], "completed")


# ═══════════════════════════════════════════════════════════════════════════════
# Route Planning Algorithm (Dijkstra + generate_route_plan)
# ═══════════════════════════════════════════════════════════════════════════════


class TestRoutePlanningAlgorithm:
    """Core Dijkstra algorithm with hub network."""

    async def _setup_simple_network(self, db_session, origin_city="武汉", dest_city="柳州"):
        """Helper: create a simple direct hub network."""
        o_code = _uniq("ORIG")
        d_code = _uniq("DEST")
        await tms_service.create_hub(
            db_session, {"code": o_code, "name": origin_city, "city": origin_city, "type": "primary"}
        )
        await tms_service.create_hub(
            db_session, {"code": d_code, "name": dest_city, "city": dest_city, "type": "secondary"}
        )
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": o_code, "to_hub_code": d_code, "distance_km": 800, "transit_hours": 10,
        })
        await tms_service.add_carrier_route(db_session, {
            "carrier_code": "sf_express", "origin_city": origin_city, "dest_city": dest_city,
            "distance_km": 800, "transit_hours": 10, "base_price_per_kg": Decimal("12"),
        })
        return o_code, d_code

    @pytest.mark.asyncio
    async def test_find_best_route_plan_simple(self, db_session):
        """Direct route between two cities."""
        o_code, d_code = await self._setup_simple_network(db_session, "武汉", "柳州")
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "张三",
            "delivery_address": {"province": "广西", "city": "柳州"},
            "pickup_address": {"province": "湖北", "city": "武汉"},
            "total_weight_kg": 10,
        })
        route = await tms_service.find_best_route_plan(order["id"], db_session)
        assert route["origin_city"] == "武汉"
        assert route["destination_city"] == "柳州"
        assert len(route["segments"]) > 0

    @pytest.mark.asyncio
    async def test_find_best_route_plan_multi_segment(self, db_session):
        """Multi-segment through intermediate hub."""
        await tms_service.create_hub(
            db_session, {"code": _uniq("A"), "name": "武汉", "city": "武汉", "type": "primary"}
        )
        await tms_service.create_hub(
            db_session, {"code": _uniq("B"), "name": "长沙", "city": "长沙", "type": "secondary"}
        )
        await tms_service.create_hub(
            db_session, {"code": _uniq("C"), "name": "柳州", "city": "柳州", "type": "secondary"}
        )
        # get hub codes by city
        hubs = await tms_service.list_hubs(db_session, city="武汉")
        wh_code = hubs[0]["code"]
        hubs = await tms_service.list_hubs(db_session, city="长沙")
        cs_code = hubs[0]["code"]
        hubs = await tms_service.list_hubs(db_session, city="柳州")
        lz_code = hubs[0]["code"]

        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": wh_code, "to_hub_code": cs_code, "distance_km": 300, "transit_hours": 4,
        })
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": cs_code, "to_hub_code": lz_code, "distance_km": 500, "transit_hours": 6,
        })
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": wh_code, "to_hub_code": lz_code, "distance_km": 800, "transit_hours": 10,
        })
        for carrier in ["sf_express", "zto"]:
            await tms_service.add_carrier_route(db_session, {
                "carrier_code": carrier, "origin_city": "武汉", "dest_city": "长沙",
                "distance_km": 300, "transit_hours": 4, "base_price_per_kg": Decimal("8"),
            })
            await tms_service.add_carrier_route(db_session, {
                "carrier_code": carrier, "origin_city": "长沙", "dest_city": "柳州",
                "distance_km": 500, "transit_hours": 6, "base_price_per_kg": Decimal("10"),
            })
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "张三",
            "delivery_address": {"province": "广西", "city": "柳州"},
            "pickup_address": {"province": "湖北", "city": "武汉"},
            "total_weight_kg": 10,
        })
        route = await tms_service.find_best_route_plan(order["id"], db_session)
        assert route["origin_city"] == "武汉"
        assert route["destination_city"] == "柳州"

    @pytest.mark.asyncio
    async def test_no_route_found(self, db_session):
        """No hubs in destination city → should raise."""
        await tms_service.create_hub(db_session, {"code": _uniq("WH"), "name": "武汉", "city": "武汉"})
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Test",
            "delivery_address": {"province": "未知", "city": "未知城"},
            "pickup_address": {"province": "湖北", "city": "武汉"},
        })
        with pytest.raises(NotFoundException, match="No transfer hub found in destination city"):
            await tms_service.find_best_route_plan(order["id"], db_session)


class TestGenerateRoutePlan:
    """generate_route_plan — full end-to-end."""

    async def _make_order(self, db_session, origin_city="武汉", dest_city="柳州"):
        return await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "张三",
            "delivery_address": {"province": "广西", "city": dest_city},
            "pickup_address": {"province": "湖北", "city": origin_city},
            "total_weight_kg": 10,
        })

    @pytest.mark.asyncio
    async def test_generate_route_plan_auto(self, db_session):
        """Full end-to-end: auto-generate a route plan + segments."""
        o_code = _uniq("ORIG")
        d_code = _uniq("DEST")
        await tms_service.create_hub(db_session, {"code": o_code, "name": "武汉", "city": "武汉", "type": "primary"})
        await tms_service.create_hub(db_session, {"code": d_code, "name": "柳州", "city": "柳州", "type": "secondary"})
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": o_code, "to_hub_code": d_code, "distance_km": 800, "transit_hours": 10,
        })
        await tms_service.add_carrier_route(db_session, {
            "carrier_code": "sf_express", "origin_city": "武汉", "dest_city": "柳州",
            "distance_km": 800, "transit_hours": 10, "base_price_per_kg": Decimal("12"),
        })
        order = await self._make_order(db_session)
        plan = await tms_service.generate_route_plan(order["id"], db_session, plan_type="auto_gen")
        assert plan["origin_city"] == "武汉"
        assert plan["destination_city"] == "柳州"
        assert plan["type"] == "auto_gen"
        assert plan["status"] == "route_active"
        assert len(plan.get("segments", [])) >= 1

    @pytest.mark.asyncio
    async def test_get_route_plan(self, db_session):
        """Get a route plan by ID."""
        o_code = _uniq("ORIG")
        d_code = _uniq("DEST")
        await tms_service.create_hub(db_session, {"code": o_code, "name": "武汉", "city": "武汉"})
        await tms_service.create_hub(db_session, {"code": d_code, "name": "柳州", "city": "柳州"})
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": o_code, "to_hub_code": d_code, "distance_km": 800, "transit_hours": 10,
        })
        await tms_service.add_carrier_route(db_session, {
            "carrier_code": "sf_express", "origin_city": "武汉", "dest_city": "柳州",
            "distance_km": 800, "transit_hours": 10, "base_price_per_kg": Decimal("12"),
        })
        order = await self._make_order(db_session)
        plan = await tms_service.generate_route_plan(order["id"], db_session)
        fetched = await tms_service.get_route_plan(db_session, plan["id"])
        assert fetched["id"] == plan["id"]
        assert "segments" in fetched


# ═══════════════════════════════════════════════════════════════════════════════
# Corrected segment-cost semantics + route cache invalidation
# ═══════════════════════════════════════════════════════════════════════════════


class TestRouteCostSemantics:
    """Lane prices are whole-lane per-kg — a priced multi-hop must not be
    penalised by charging the lane price once per segment."""

    async def _make_order(self, db_session, weight=10):
        return await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "张三",
            "delivery_address": {"province": "广西", "city": "柳州"},
            "pickup_address": {"province": "湖北", "city": "武汉"},
            "total_weight_kg": weight,
        })

    @pytest.mark.asyncio
    async def test_priced_multi_hop_beats_unpriced_direct(self, db_session):
        a = _uniq("WUHAN")
        b = _uniq("CHANGSHA")
        c = _uniq("LIUZHOU")
        for code, name in ((a, "武汉"), (b, "长沙"), (c, "柳州")):
            await tms_service.create_hub(db_session, {"code": code, "name": name, "city": name})
        # Direct express lane (no carrier prices this city pair → 0.5/km fallback)
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": a, "to_hub_code": c, "distance_km": 800, "transit_hours": 10,
        })
        # Two priced hops: 8/kg + 10/kg on 10kg = 180 total < 800×0.5 = 400
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": a, "to_hub_code": b, "distance_km": 300, "transit_hours": 4,
        })
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": b, "to_hub_code": c, "distance_km": 500, "transit_hours": 6,
        })
        await tms_service.add_carrier_route(db_session, {
            "carrier_code": "zto", "origin_city": "武汉", "dest_city": "长沙",
            "distance_km": 300, "transit_hours": 4, "base_price_per_kg": Decimal("8"),
        })
        await tms_service.add_carrier_route(db_session, {
            "carrier_code": "zto", "origin_city": "长沙", "dest_city": "柳州",
            "distance_km": 500, "transit_hours": 6, "base_price_per_kg": Decimal("10"),
        })
        order = await self._make_order(db_session)

        route = await tms_service.find_best_route_plan(order["id"], db_session)
        assert len(route["segments"]) == 2
        assert Decimal(route["total_cost_amount"]) == Decimal("180")
        # Segment metrics must be exactly one per hop, in path order.
        assert [Decimal(s["distance_km"]) for s in route["segments"]] == [Decimal("300"), Decimal("500")]
        assert [Decimal(s["transit_hours"]) for s in route["segments"]] == [Decimal("4"), Decimal("6")]

    @pytest.mark.asyncio
    async def test_direct_priced_lane_cost(self, db_session):
        a = _uniq("WUHAN")
        c = _uniq("LIUZHOU")
        for code, name in ((a, "武汉"), (c, "柳州")):
            await tms_service.create_hub(db_session, {"code": code, "name": name, "city": name})
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": a, "to_hub_code": c, "distance_km": 800, "transit_hours": 10,
        })
        await tms_service.add_carrier_route(db_session, {
            "carrier_code": "sf_express", "origin_city": "武汉", "dest_city": "柳州",
            "distance_km": 800, "transit_hours": 10, "base_price_per_kg": Decimal("12"),
        })
        order = await self._make_order(db_session)

        route = await tms_service.find_best_route_plan(order["id"], db_session)
        assert len(route["segments"]) == 1
        # 10 kg × 12/kg — charged once for the lane, not once per segment.
        assert Decimal(route["total_cost_amount"]) == Decimal("120")


class _FakeRedis:
    def __init__(self):
        self.store: dict = {}
        self.calls: list = []

    async def get(self, key):
        self.calls.append(("get", key))
        return self.store.get(key)

    async def set(self, key, value=None, ex=None, **kwargs):
        # redis-py 5 deprecates ``setex``, so the service writes the TTL as ``ex=``
        # on ``set``; the fake follows the client it stands in for.
        self.calls.append(("set", key))
        self.store[key] = value

    async def incr(self, key):
        self.calls.append(("incr", key))
        self.store[key] = int(self.store.get(key, 0)) + 1


class TestRouteCacheInvalidation:
    """Cached route plans must become unreachable when lane prices change."""

    @pytest.mark.asyncio
    async def test_lane_price_change_invalidates_cached_plan(self, db_session, monkeypatch):
        import json
        from contextlib import asynccontextmanager

        from src.cache import redis_client as rc

        fake = _FakeRedis()

        @asynccontextmanager
        async def _fake_get_redis():
            yield fake

        monkeypatch.setattr(rc, "get_redis", _fake_get_redis)

        a = _uniq("WUHAN")
        c = _uniq("LIUZHOU")
        for code, name in ((a, "武汉"), (c, "柳州")):
            await tms_service.create_hub(db_session, {"code": code, "name": name, "city": name})
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": a, "to_hub_code": c, "distance_km": 800, "transit_hours": 10,
        })
        await tms_service.add_carrier_route(db_session, {
            "carrier_code": "sf_express", "origin_city": "武汉", "dest_city": "柳州",
            "distance_km": 800, "transit_hours": 10, "base_price_per_kg": Decimal("12"),
        })
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "张三",
            "delivery_address": {"province": "广西", "city": "柳州"},
            "pickup_address": {"province": "湖北", "city": "武汉"},
            "total_weight_kg": 10,
        })

        r1 = await tms_service.find_best_route_plan(order["id"], db_session)
        assert Decimal(r1["total_cost_amount"]) == Decimal("120")

        # Poison the cached entry; a cache hit must now return the sentinel.
        # (Seeding bumps the version itself, so read the key back dynamically.)
        cached_keys = [k for op, k in fake.calls if op == "set"]
        assert cached_keys, f"expected a versioned cache write, calls={fake.calls}"
        original_key = cached_keys[-1]
        fake.store[original_key] = json.dumps({"marker": "sentinel"})
        r2 = await tms_service.find_best_route_plan(order["id"], db_session)
        assert r2.get("marker") == "sentinel"

        # A cheaper lane price must bump the cache version so the stale entry
        # is unreachable, and the recomputation must pick up the new price.
        await tms_service.add_carrier_route(db_session, {
            "carrier_code": "zto", "origin_city": "武汉", "dest_city": "柳州",
            "distance_km": 800, "transit_hours": 10, "base_price_per_kg": Decimal("5"),
        })
        assert any(op == "incr" for op, _ in fake.calls), "expected a version bump"

        r3 = await tms_service.find_best_route_plan(order["id"], db_session)
        assert r3.get("marker") is None
        assert Decimal(r3["total_cost_amount"]) == Decimal("50")
        new_keys = [k for op, k in fake.calls if op == "set" and k != original_key]
        assert new_keys, "expected a cache re-write under a bumped version"
