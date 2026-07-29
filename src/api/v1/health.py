"""Health check endpoints with DB and Redis probes."""
from fastapi import APIRouter

from src.config import settings
from src.core.database import check_db_health

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    db_ok = await check_db_health()
    return {
        "status": "ok" if db_ok else "degraded",
        "service": settings.app_name,
        "version": settings.app_version,
        "checks": {
            "database": "healthy" if db_ok else "unhealthy",
        },
    }


@router.get("/ready")
async def readiness_check():
    db_ok = await check_db_health()
    redis_ok = False
    try:
        from src.cache.redis_client import redis_health_check

        redis_ok = await redis_health_check()
    except Exception:
        pass

    all_healthy = db_ok and redis_ok
    return {
        "status": "ready" if all_healthy else "degraded",
        "service": settings.app_name,
        "checks": {
            "database": "healthy" if db_ok else "unhealthy",
            "redis": "healthy" if redis_ok else "unavailable",
        },
    }
