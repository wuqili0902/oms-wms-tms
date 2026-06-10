from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import Permission, Role, User
from src.core.database import get_db
from src.core.security import decode_token

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Validate JWT token and return current user."""
    token = credentials.credentials
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return payload


async def _get_user_permissions(db: AsyncSession, username: str) -> set[str]:
    """Query all permission codes for a user via their roles."""
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()
    if not user or not user.roles:
        return set()

    perm_codes: set[str] = set()
    for role in user.roles:
        for perm in role.permissions:
            perm_codes.add(perm.code)
    return perm_codes


def require_permission(*required_perms: str):
    """Dependency factory for RBAC permission checking.

    Usage:
        @router.get("/admin/users")
        async def admin_users(
            current_user: dict = Depends(require_permission("users.read")),
        ):
            ...
    """

    async def _check(
        current_user: dict = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        if not required_perms:
            return current_user

        username = current_user.get("sub", "")
        if not username:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User identity not found")

        user_perms = await _get_user_permissions(db, username)
        for perm in required_perms:
            if perm not in user_perms:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission '{perm}' required",
                )
        return current_user

    return _check
