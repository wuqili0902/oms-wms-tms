"""Shared FastAPI dependencies — database, auth, permission checks."""

# NOTE: ALL imports that can cause circular deps are deferred inside functions.
# This module must NOT import from src.auth at top-level because that loads the router
# which imports back into this module (get_current_user), creating a cycle.


from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
):
    """Validate JWT token and return current user.

    Raises 401 when no token is present OR token is invalid/expired.
    For routes that want to allow anonymous access, check `credentials` first.
    """
    from src.core.security import TokenExpired, TokenInvalid, decode_token

    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    try:
        payload = decode_token(credentials.credentials)
    except (TokenExpired, TokenInvalid):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    if "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    return payload


async def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
):
    """Validate JWT token and return current user — but returns {} on missing/invalid token."""

    from src.core.security import TokenExpired, TokenInvalid, decode_token

    if not credentials or not credentials.credentials:
        return {}  # Anonymous access allowed

    try:
        payload = decode_token(credentials.credentials)
    except (TokenExpired, TokenInvalid):
        return {}
    if "sub" not in payload:
        return {}

    return payload


async def get_required_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
):
    """Strict version — raises 401 for missing/invalid tokens."""
    from src.core.security import TokenExpired, TokenInvalid, decode_token

    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        payload = decode_token(credentials.credentials)
    except (TokenExpired, TokenInvalid):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    if "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    return payload


async def _get_user_permissions(db, username):
    """Query all permission codes for a user via their roles."""
    from sqlalchemy import select

    # Lazy-import to avoid circular dep with auth.router which imports this module
    from sqlalchemy.orm import selectinload

    from src.auth.models import Role, User

    result = await db.execute(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.username == username)
    )
    user = result.scalar_one_or_none()
    if not user or not user.roles:
        return set()

    perm_codes = set()
    for role in user.roles:
        for perm in role.permissions:
            perm_codes.add(perm.code)
    return perm_codes


def require_permission(*required_perms: str):
    """Dependency factory for RBAC permission checking."""

    async def _check(
        current_user: dict = Depends(get_current_user),
        db = None,
    ):
        from src.core.database import get_db

        if not required_perms:
            return current_user

        username = current_user.get("sub", "")
        if not username:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User identity not found")

        async with get_db() as db_session:
            user_perms = await _get_user_permissions(db_session, username)
        for perm in required_perms:
            if perm not in user_perms:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission '{perm}' required",
                )
        return current_user

    return _check


def get_celery_task(task_name):  # type: ignore[misc]
    """Resolve a Celery task by name — lazy to avoid import cycles."""
    from celery import current_app

    app = getattr(current_app, "_get_current_object", lambda: None)() or current_app._get_current_object()  # noqa: SLF001
    return app.tasks.get(task_name)


def get_redis():  # type: ignore[misc]
    """Resolve Redis client — lazy to avoid import cycles."""
    from src.cache.redis_client import get_redis as _get_r

    return _get_r()
