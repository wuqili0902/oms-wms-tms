from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "oms-wms-tms"}


@router.get("/ready")
async def readiness_check():
    return {"status": "ready", "service": "oms-wms-tms"}
