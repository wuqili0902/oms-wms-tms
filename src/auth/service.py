"""Auth business logic — user registration, login, token management, RBAC.

All CRUD functions are async and require an ``AsyncSession``.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import Permission, Role, User
from src.auth.token_store import token_store
from src.core.exceptions import NotFoundException, ValidationException
from src.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from src.models.base import model_to_dict


# ── Users ────────────────────────────────────────────────────────────────────

async def register_user(db: AsyncSession, data: dict) -> dict:
    """Register a new user. Raises ValidationException if username/email taken."""
    existing = await db.execute(select(User).where(
        (User.username == data["username"]) | (User.email == data["email"])
    ))
    if existing.scalar_one_or_none():
        raise ValidationException(message="Username or email already exists")

    user = User(
        id=uuid.uuid4(),
        username=data["username"],
        email=data["email"],
        hashed_password=hash_password(data["password"]),
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Lazy-seed default admin if this is the first user
    await _ensure_admin(db)

    return model_to_dict(user)


async def authenticate_user(db: AsyncSession, username: str, password: str) -> dict | None:
    """Verify credentials, return user dict or None."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return model_to_dict(user)


async def get_user_by_id(db: AsyncSession, user_id: str) -> dict:
    """Get user by UUID string."""
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException(message="User not found")
    return model_to_dict(user)


async def get_user_by_username(db: AsyncSession, username: str) -> dict | None:
    """Get user by username."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    return model_to_dict(user) if user else None


async def list_users(db: AsyncSession) -> list[dict]:
    """List all users."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return [model_to_dict(u) for u in result.scalars().all()]


# ── Token management (Redis + in-memory fallback) ──────────────────────────

async def create_tokens(user: dict) -> dict:
    """Generate access + refresh token pair."""
    token_data = {"sub": user["username"], "uid": user["id"]}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)
    await token_store.store(refresh_token, user["username"])
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


async def refresh_tokens(refresh_token: str) -> dict | None:
    """Validate and rotate a refresh token."""
    username = await token_store.pop(refresh_token)
    if not username:
        return None
    payload = decode_token(refresh_token)
    if not payload:
        return None
    token_data = {"sub": username, "uid": payload.get("uid")}
    new_access = create_access_token(token_data)
    new_refresh = create_refresh_token(token_data)
    await token_store.store(new_refresh, username)
    return {"access_token": new_access, "refresh_token": new_refresh}


async def revoke_refresh_token(refresh_token: str) -> None:
    """Remove a refresh token."""
    await token_store.revoke(refresh_token)


# ── Roles ────────────────────────────────────────────────────────────────────

async def create_role(db: AsyncSession, data: dict) -> dict:
    """Create a new role. Raises ValidationException if code taken."""
    existing = await db.execute(select(Role).where(Role.code == data["code"]))
    if existing.scalar_one_or_none():
        raise ValidationException(message=f"Role code '{data['code']}' already exists")
    role = Role(
        id=uuid.uuid4(),
        name=data["name"],
        code=data["code"],
        description=data.get("description"),
        is_system=False,
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return model_to_dict(role)


async def list_roles(db: AsyncSession) -> list[dict]:
    """List all roles."""
    result = await db.execute(select(Role).order_by(Role.created_at.desc()))
    return [model_to_dict(r) for r in result.scalars().all()]


# ── Permissions ──────────────────────────────────────────────────────────────

async def list_permissions(db: AsyncSession) -> list[dict]:
    """List all permissions."""
    result = await db.execute(select(Permission).order_by(Permission.created_at.desc()))
    return [model_to_dict(p) for p in result.scalars().all()]


# ── Admin seeding ────────────────────────────────────────────────────────────

_admin_seeded = False


async def _ensure_admin(db: AsyncSession) -> None:
    """Lazy-seed the default admin user and admin role on first call."""
    global _admin_seeded
    if _admin_seeded:
        return
    count = await db.execute(select(User).limit(1))
    if count.scalar_one_or_none():
        _admin_seeded = True
        return

    # This function is called only during register — skip auto-seed for now.
    _admin_seeded = True
