from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Validate JWT token and return current user.
    Placeholder - will be fully implemented in Task 3 (Auth)."""
    token = credentials.credentials
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    return {"sub": "placeholder"}


async def require_permission(*permissions: str):
    """Dependency factory for RBAC permission checking.
    Placeholder - will be fully implemented in Task 3 (Auth)."""

    async def _check_permission(
        current_user: dict = Depends(get_current_user),
    ):
        return current_user

    return _check_permission
