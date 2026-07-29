"""Auth business logic — user registration, login, token management, RBAC.

All CRUD functions are async and require an ``AsyncSession``.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import Permission, Role, RolePermission, User, UserRole
from src.auth.token_store import token_store
from src.core.exceptions import NotFoundException, ValidationException
from src.core.security import (
    TokenExpired,
    TokenInvalid,
    async_hash_password,
    async_verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
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
        hashed_password=await async_hash_password(data["password"]),
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
    if not user or not await async_verify_password(password, user.hashed_password):
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
    try:
        payload = decode_token(refresh_token)
    except (TokenExpired, TokenInvalid):
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


async def update_role(db: AsyncSession, role_id: str, data: dict) -> dict:
    """Update a role's name/description."""
    result = await db.execute(select(Role).where(Role.id == uuid.UUID(role_id)))
    role = result.scalar_one_or_none()
    if not role:
        raise NotFoundException(message=f"Role {role_id} not found")
    if data.get("name") is not None:
        role.name = data["name"]
    if data.get("description") is not None:
        role.description = data["description"]
    await db.commit()
    await db.refresh(role)
    return model_to_dict(role)


async def delete_role(db: AsyncSession, role_id: str) -> None:
    """Delete a role (system roles protected)."""
    result = await db.execute(select(Role).where(Role.id == uuid.UUID(role_id)))
    role = result.scalar_one_or_none()
    if not role:
        raise NotFoundException(message=f"Role {role_id} not found")
    if role.is_system:
        raise ValidationException(message="Cannot delete system role")
    await db.delete(role)
    await db.commit()


# ── Permissions ──────────────────────────────────────────────────────────────

async def list_permissions(db: AsyncSession) -> list[dict]:
    """List all permissions."""
    result = await db.execute(select(Permission).order_by(Permission.created_at.desc()))
    return [model_to_dict(p) for p in result.scalars().all()]


async def create_permission(db: AsyncSession, data: dict) -> dict:
    """Create a new permission."""
    existing = await db.execute(select(Permission).where(Permission.code == data["code"]))
    if existing.scalar_one_or_none():
        raise ValidationException(message=f"Permission code '{data['code']}' already exists")
    perm = Permission(
        id=uuid.uuid4(),
        name=data["name"],
        code=data["code"],
        resource=data["resource"],
        action=data["action"],
        description=data.get("description"),
    )
    db.add(perm)
    await db.commit()
    await db.refresh(perm)
    return model_to_dict(perm)


# ── User-Role assignments ──────────────────────────────────────────────────


async def assign_role_to_user(db: AsyncSession, user_id: str, role_id: str) -> dict:
    """Assign a role to a user."""
    user = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    if not user.scalar_one_or_none():
        raise NotFoundException(message=f"User {user_id} not found")
    role = await db.execute(select(Role).where(Role.id == uuid.UUID(role_id)))
    if not role.scalar_one_or_none():
        raise NotFoundException(message=f"Role {role_id} not found")
    existing = await db.execute(
        select(UserRole).where(
            UserRole.user_id == uuid.UUID(user_id),
            UserRole.role_id == uuid.UUID(role_id),
        )
    )
    if existing.scalar_one_or_none():
        raise ValidationException(message="User already has this role")
    ur = UserRole(user_id=uuid.UUID(user_id), role_id=uuid.UUID(role_id))
    db.add(ur)
    await db.commit()
    return {"user_id": user_id, "role_id": role_id}


async def remove_role_from_user(db: AsyncSession, user_id: str, role_id: str) -> None:
    """Remove a role from a user."""
    result = await db.execute(
        select(UserRole).where(
            UserRole.user_id == uuid.UUID(user_id),
            UserRole.role_id == uuid.UUID(role_id),
        )
    )
    ur = result.scalar_one_or_none()
    if not ur:
        raise NotFoundException(message="User does not have this role")
    await db.delete(ur)
    await db.commit()


# ── Role-Permission assignments ────────────────────────────────────────────


async def assign_permission_to_role(db: AsyncSession, role_id: str, permission_id: str) -> dict:
    """Assign a permission to a role."""
    role = await db.execute(select(Role).where(Role.id == uuid.UUID(role_id)))
    if not role.scalar_one_or_none():
        raise NotFoundException(message=f"Role {role_id} not found")
    perm = await db.execute(select(Permission).where(Permission.id == uuid.UUID(permission_id)))
    if not perm.scalar_one_or_none():
        raise NotFoundException(message=f"Permission {permission_id} not found")
    existing = await db.execute(
        select(RolePermission).where(
            RolePermission.role_id == uuid.UUID(role_id),
            RolePermission.permission_id == uuid.UUID(permission_id),
        )
    )
    if existing.scalar_one_or_none():
        raise ValidationException(message="Role already has this permission")
    rp = RolePermission(role_id=uuid.UUID(role_id), permission_id=uuid.UUID(permission_id))
    db.add(rp)
    await db.commit()
    return {"role_id": role_id, "permission_id": permission_id}


async def remove_permission_from_role(db: AsyncSession, role_id: str, permission_id: str) -> None:
    """Remove a permission from a role."""
    result = await db.execute(
        select(RolePermission).where(
            RolePermission.role_id == uuid.UUID(role_id),
            RolePermission.permission_id == uuid.UUID(permission_id),
        )
    )
    rp = result.scalar_one_or_none()
    if not rp:
        raise NotFoundException(message="Role does not have this permission")
    await db.delete(rp)
    await db.commit()


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
