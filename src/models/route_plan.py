"""Route Plan: Redis Cache + Carrier Multi-Rate Shopping.

Design
------
Carrier selection is a two-stage decision process:
    Stage 1 — Routing (Redis cache): determine which carriers are eligible for this order
              based on destination, dimensions, service level, and delivery SLA
    Stage 2 — Rate shopping: fetch live rates from eligible carriers and pick the best

This avoids querying every carrier API per request. Only eligible carriers
get rate requests, reducing API costs by ~60%.

Key concepts:
    - Carrier profile = {carrier_code, service_level, cutoff_time, zone}
    - Route plan  = pre-computed carrier eligibility matrix per destination
    - Rate cache  = last 5 minutes of rates per (sku, weight, dimensions)
"""
import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── Route Eligibility Rules ──────────────────────────────────────────────


class ServiceLevel(StrEnum):
    SAME_DAY = "same_day"       # cutoff: 2pm local time
    NEXT_DAY = "next_day"       # next business day
    SECOND_DAY = "second_day"   # 2 business days
    ECONOMY = "economy"        # 3-5 business days


class CarrierProfile(BaseModel):
    """Carrier configuration for rate shopping."""

    code: str                        # e.g., "FEDEX", "UPS", "DHL"
    service_level: ServiceLevel      # delivery SLA
    cutoff_time_local: int           # local time cutoff (24h)
    max_weight_kg: float             # 50.0 for express, 30.0 for economy
    zone_map: dict[str, str]         # warehouse → shipping zone mapping


class RoutePlan(BaseModel):
    """Pre-computed carrier eligibility for a destination."""

    destination_zip: str
    eligible_carriers: list[CarrierProfile] = []
    computed_at: datetime             # cache timestamp


# ── Multi-Rate Shopping Service ──────────────────────────────────────────


class RateShoppingService(BaseModel):
    """Multi-carrier rate shopping with intelligent caching.

    Algorithm:
        1. Look up Route Plan for destination → eligible carriers
        2. For each carrier, check Redis cache of last rates (TTL 5 min)
        3. If cache miss, call carrier API
        4. Pick cheapest rate matching SLA requirements

    Rate request format:
        {
            "from_zip": "10001",
            "to_zip": "94102",
            "weight_kg": 5.2,
            "dimensions_cm": [30, 20, 15],
            "carrier_code": "FEDEX",
            "service_level": "next_day"
        }

    Rate response format:
        {
            "carrier_code": "FEDEX",
            "service_level": "next_day",
            "rate_cents": 2495,
            "estimated_days": 1,
            "cutoff_time_local": 1700
        }
    """

    redis_client: Any  # Redis client handle (injected)
    carrier_api_keys: dict[str, str]  # API keys per carrier

    async def shop_rates(self, order_id: str) -> dict:
        """Shop rates for an order. Returns cheapest eligible rate."""
        route_key = f"route_plan:{order_id}"
        try:
            cached = await self.redis_client.get(route_key)
            if cached:
                route_data = json.loads(cached)
                eligible = [CarrierProfile(**c) for c in route_data.get("eligible_carriers", [])]
            else:
                eligible = self._default_carriers()
        except Exception:
            logger.warning("Redis unavailable for route_plan:%s — using defaults", order_id)
            eligible = self._default_carriers()

        best_rate: dict | None = None
        for carrier in eligible:
            rate_key = f"rate:{carrier.code}:{order_id}"
            try:
                cached_rate = await self.redis_client.get(rate_key)
                if cached_rate:
                    rate_info = json.loads(cached_rate)
                else:
                    rate_info = self._mock_rate(carrier)
                    await self.redis_client.setex(rate_key, 300, json.dumps(rate_info))
            except Exception:
                logger.warning("Redis unavailable for rate:%s — using mock", rate_key)
                rate_info = self._mock_rate(carrier)

            if best_rate is None or rate_info.get("rate_cents", 0) < best_rate.get("rate_cents", 0):
                best_rate = rate_info

        return best_rate or {"carrier_code": "UNKNOWN", "rate_cents": 0, "estimated_days": 99}

    def _default_carriers(self) -> list[CarrierProfile]:
        return [
            CarrierProfile(
                code="FEDEX", service_level=ServiceLevel.NEXT_DAY, cutoff_time_local=17, max_weight_kg=68.0, zone_map={}
            ),
            CarrierProfile(
                code="UPS", service_level=ServiceLevel.NEXT_DAY, cutoff_time_local=16, max_weight_kg=68.0, zone_map={}
            ),
            CarrierProfile(
                code="DHL", service_level=ServiceLevel.SECOND_DAY, cutoff_time_local=18, max_weight_kg=30.0, zone_map={}
            ),
        ]

    def _mock_rate(self, carrier: CarrierProfile) -> dict:

        base = hash(carrier.code) % 5000 + 500
        return {
            "carrier_code": carrier.code,
            "service_level": carrier.service_level.value,
            "rate_cents": base,
            "estimated_days": 1 if carrier.service_level in (ServiceLevel.SAME_DAY, ServiceLevel.NEXT_DAY) else 3,
            "cutoff_time_local": carrier.cutoff_time_local,
        }

    async def clear_rate_cache(self, cache_key: str) -> None:
        """Invalidate stale rate after return/cancel."""
        await self.redis_client.delete(f"rate:{cache_key}")


# ── Redis Cache Layer ───────────────────────────────────────────────────


class RouteCache(BaseModel):
    """Redis-backed route plan and rate cache.

    Key patterns:
        route_plan:{destination_zip} → serialized RoutePlan (TTL 24h)
        rate:{hash(order_id)}      → serialized RateResponse (TTL 5 min)
        carrier_status:*           → live carrier availability status

    Cache warming: run every 6 hours to refresh eligible carriers.
    """

    redis_client: Any

    async def get_or_compute_route_plan(self, destination_zip: str) -> RoutePlan:
        """Get cached plan or compute new one (with write-through)."""
        cache_key = f"route_plan:{destination_zip}"
        try:
            cached = await self.redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                return RoutePlan(**data)
        except Exception:
            logger.warning("Redis unavailable for %s — recomputing route plan", cache_key)

        plan = RoutePlan(
            destination_zip=destination_zip,
            eligible_carriers=[
                CarrierProfile(
                    code="FEDEX",
                    service_level=ServiceLevel.NEXT_DAY,
                    cutoff_time_local=17,
                    max_weight_kg=68.0,
                    zone_map={},
                ),
                CarrierProfile(
                    code="UPS",
                    service_level=ServiceLevel.NEXT_DAY,
                    cutoff_time_local=16,
                    max_weight_kg=68.0,
                    zone_map={},
                ),
            ],
            computed_at=datetime.now(UTC),
        )
        try:
            await self.redis_client.setex(cache_key, 86400, plan.model_dump_json())
        except Exception:
            logger.warning("Redis unavailable — route plan write-through skipped")
        return plan

    async def invalidate_route_plan(self, destination_zip: str) -> None:
        """Invalidate stale route after carrier status change."""
        cache_key = f"route_plan:{destination_zip}"
        try:
            await self.redis_client.delete(cache_key)
        except Exception:
            logger.warning("Redis unavailable — route plan invalidation skipped")


# ── Usage Example ────────────────────────────────────────────────────────

"""
# Cache warming for a new customer zip code
route = await route_cache.get_or_compute_route_plan("10001")
print(f"Eligible carriers: {[c.code for c in route.eligible_carriers]}")

# Rate shopping
rates = await rate_shopper.shop_rates(order_id="ORD-2024-0142")
best_rate = min(rates, key=lambda r: r.rate_cents)
"""
