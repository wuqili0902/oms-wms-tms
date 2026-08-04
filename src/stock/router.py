"""Stock In/Out / Inventory Log / Adjust Stock API endpoints."""
from fastapi import APIRouter

router = APIRouter()


# ── re-export the stock routes from routes.stock ────────────────────
from src.routes import stock as _s  # noqa: E402

for ep in _s.router.routes:
    methods = getattr(ep, "methods", ["GET"])
    router.add_api_route(
        path=ep.path.lstrip("/"),
        endpoint=ep.endpoint,
        methods=list(methods),
    )
