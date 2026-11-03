"""How the stock routes reach the application — and what the copy loop dropped.

``src/stock/router.py`` did not re-export ``src/routes/stock.py``'s router, it
rebuilt every route into a new APIRouter with
``router.add_api_route(path=…, endpoint=…, methods=…, status_code=…)``.  Those
four arguments are all a FastAPI route's *signature*; what it also carries —
tags, response_model, summary, and most importantly the router-level
``dependencies=[Depends(get_current_user)]`` — was not passed on.

So ``src/routes/stock.py`` line 24 declared the whole stock API as
authentication-required, and the copy silently un-declared it.  Every stock-in,
stock-out and inventory-log endpoint answered anonymous callers.
"""

from fastapi.routing import APIRoute

from src.core.dependencies import get_current_user
from src.main import app
from src.routes.stock import router as stock_source

# (path, method) pairs, not paths: GET and PUT share /api/v1/stock-in/{id}, and
# comparing route counts against path counts made that look like a dropped route.
_SOURCE_SIGNATURES = {
    (f"/api/v1{route.path}", method)
    for route in stock_source.routes
    if isinstance(route, APIRoute)
    for method in (route.methods or set())
}

_STOCK_PATHS = {path for path, _ in _SOURCE_SIGNATURES}


def _mounted_stock_routes() -> list[APIRoute]:
    return [
        route for route in app.routes
        if isinstance(route, APIRoute) and route.path in _STOCK_PATHS
    ]


def _requires_current_user(route: APIRoute) -> bool:
    return any(dep.dependency is get_current_user for dep in route.dependencies)


class TestStockMount:
    def test_the_stock_routes_are_mounted(self):
        mounted = _mounted_stock_routes()
        assert mounted, "no stock route reached the application"
        signatures = {(route.path, method) for route in mounted for method in route.methods}
        missing = sorted(_SOURCE_SIGNATURES - signatures)
        extra = sorted(signatures - _SOURCE_SIGNATURES)
        assert not missing, f"stock endpoints declared upstream but not mounted: {missing}"
        assert not extra, f"stock endpoints mounted without an upstream declaration: {extra}"

    def test_every_stock_route_still_requires_authentication(self):
        """Router-level dependencies have to survive the mount, or they vanish."""
        unprotected = sorted(
            f"{sorted(route.methods)} {route.path}"
            for route in _mounted_stock_routes()
            if not _requires_current_user(route)
        )
        assert not unprotected, (
            "these stock routes answer anonymous callers: " + "; ".join(unprotected)
        )

    async def test_anonymous_stock_out_query_is_rejected(self, async_client):
        resp = await async_client.get("/api/v1/stock-out")
        assert resp.status_code == 401, (
            "an unauthenticated caller was handed the stock-out ledger: "
            + resp.text[:200]
        )

    async def test_anonymous_stock_out_write_is_rejected(self, async_client):
        resp = await async_client.post(
            "/api/v1/stock-out", json={"data": {"warehouse_id": "0" * 32, "lines": []}}
        )
        assert resp.status_code == 401, (
            "an unauthenticated caller was allowed to write a stock-out record: "
            + resp.text[:200]
        )

    async def test_anonymous_inventory_log_is_rejected(self, async_client):
        resp = await async_client.get("/api/v1/inventory-log")
        assert resp.status_code == 401, resp.text[:200]

    def test_route_metadata_survives_the_mount(self):
        """Tags and the documented 201 are metadata, not decoration.

        Without tags the endpoints disappear from the "Stock In/Out" group a
        client generates its calls from; without status_code=201 a caller
        treats a created record as a plain 200.
        """
        routes = _mounted_stock_routes()
        untagged = sorted(
            f"{sorted(r.methods)} {r.path}" for r in routes if r.tags != ["Stock In/Out"]
        )
        assert not untagged, f"tags lost on: {untagged}"

        created = {r.path: r for r in routes if r.methods == {"POST"}}
        for path in ("/api/v1/stock-in", "/api/v1/stock-out"):
            assert created[path].status_code == 201, (
                f"{path} answers 200 where upstream declares 201"
            )
