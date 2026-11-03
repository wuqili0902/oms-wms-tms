"""Auth business logic — user registration, login, token management, RBAC.

All CRUD functions are async and require an ``AsyncSession``.
"""
import logging
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import Permission, Role, RolePermission, User, UserRole
from src.auth.token_store import token_store
from src.config import settings
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


def _as_id(value: object, *, field: str) -> uuid.UUID:
    """Read an id the caller sent, naming the field when it is not an id.

    ``uuid.UUID(role_id)`` inside these functions raised ``ValueError`` on a
    truncated or mistyped id — an id in an old bookmark, an id a scanner mis-read —
    and the caller was told the server broke.  A value that is not an id is a
    request error about that value, and it names the field that carried it.
    """
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValidationException(
            message=f"{field} {value!r} is not an id (expected a UUID)",
            detail={field: str(value)},
        ) from None


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

    # Lazy-seed default admin if this is the first user (before commit)
    await _ensure_admin(db)

    await db.commit()
    await db.refresh(user)

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
    result = await db.execute(select(User).where(User.id == _as_id(user_id, field="user_id")))
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


async def toggle_user_active(db: AsyncSession, user_id: str) -> dict:
    """Flip a user's active flag and return the new state.

    The route did ``uuid.UUID(user_id)`` inline: the admin panel links users by
    id, so a stale bookmark or a half-copied id is the ordinary input, and it
    raised ``ValueError`` inside the route — reported to the operator as a server
    failure.  The id goes through :func:`_as_id`, like the RBAC writes.
    """
    uid = _as_id(user_id, field="user_id")
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException(message=f"User {user_id} not found")
    user.is_active = not user.is_active
    await db.commit()
    return {"is_active": user.is_active}


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
    # Decode BEFORE popping — if decode fails, token stays valid
    try:
        payload = decode_token(refresh_token)
    except (TokenExpired, TokenInvalid):
        return None
    username = await token_store.pop(refresh_token)
    if not username:
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
    result = await db.execute(select(Role).where(Role.id == _as_id(role_id, field="role_id")))
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
    result = await db.execute(select(Role).where(Role.id == _as_id(role_id, field="role_id")))
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
    """Assign a role to a user.

    Both ids are read through :func:`_as_id`: a request whose ``role_id`` is not a
    UUID used to reach ``uuid.UUID(role_id)`` and raise inside this function, so a
    typed-wrong id in the admin panel was reported as a server failure.
    """
    uid = _as_id(user_id, field="user_id")
    rid = _as_id(role_id, field="role_id")
    user = await db.execute(select(User).where(User.id == uid))
    if not user.scalar_one_or_none():
        raise NotFoundException(message=f"User {user_id} not found")
    role = await db.execute(select(Role).where(Role.id == rid))
    if not role.scalar_one_or_none():
        raise NotFoundException(message=f"Role {role_id} not found")
    existing = await db.execute(
        select(UserRole).where(
            UserRole.user_id == uid,
            UserRole.role_id == rid,
        )
    )
    if existing.scalar_one_or_none():
        raise ValidationException(message="User already has this role")
    ur = UserRole(user_id=uid, role_id=rid)
    db.add(ur)
    await db.commit()
    return {"user_id": user_id, "role_id": role_id}


async def remove_role_from_user(db: AsyncSession, user_id: str, role_id: str) -> None:
    """Remove a role from a user."""
    result = await db.execute(
        select(UserRole).where(
            UserRole.user_id == _as_id(user_id, field="user_id"),
            UserRole.role_id == _as_id(role_id, field="role_id"),
        )
    )
    ur = result.scalar_one_or_none()
    if not ur:
        raise NotFoundException(message="User does not have this role")
    await db.delete(ur)
    await db.commit()


# ── Role-Permission assignments ────────────────────────────────────────────


async def assign_permission_to_role(db: AsyncSession, role_id: str, permission_id: str) -> dict:
    """Assign a permission to a role.

    Ids go through :func:`_as_id` — see :func:`assign_role_to_user` for why a
    mistyped id has to be a 422 about that id and not a 500 about the server.
    """
    rid = _as_id(role_id, field="role_id")
    pid = _as_id(permission_id, field="permission_id")
    role = await db.execute(select(Role).where(Role.id == rid))
    if not role.scalar_one_or_none():
        raise NotFoundException(message=f"Role {role_id} not found")
    perm = await db.execute(select(Permission).where(Permission.id == pid))
    if not perm.scalar_one_or_none():
        raise NotFoundException(message=f"Permission {permission_id} not found")
    existing = await db.execute(
        select(RolePermission).where(
            RolePermission.role_id == rid,
            RolePermission.permission_id == pid,
        )
    )
    if existing.scalar_one_or_none():
        raise ValidationException(message="Role already has this permission")
    rp = RolePermission(role_id=rid, permission_id=pid)
    db.add(rp)
    await db.commit()
    return {"role_id": role_id, "permission_id": permission_id}


async def remove_permission_from_role(db: AsyncSession, role_id: str, permission_id: str) -> None:
    """Remove a permission from a role."""
    result = await db.execute(
        select(RolePermission).where(
            RolePermission.role_id == _as_id(role_id, field="role_id"),
            RolePermission.permission_id == _as_id(permission_id, field="permission_id"),
        )
    )
    rp = result.scalar_one_or_none()
    if not rp:
        raise NotFoundException(message="Role does not have this permission")
    await db.delete(rp)
    await db.commit()


# ── Admin seeding ────────────────────────────────────────────────────────────

_admin_seeded = False


_ADMIN_PERMISSIONS = [
    ("admin.rbac.manage", "admin", "rbac_manage"),
    ("admin.user.manage", "admin", "user_manage"),
    ("admin.webhook.manage", "admin", "webhook_manage"),
    ("admin.export.manage", "admin", "export_manage"),
]

logger = logging.getLogger(__name__)


def _initial_admin_password() -> str:
    """Bootstrap password for the seeded ``admin`` user.

    Priority: ``ADMIN_INIT_PASSWORD`` env var → fixed dev credential in
    test/debug mode → random one-time password in production (printed once so
    the operator can log in, then change it; set the env var to control it).
    """
    configured = settings.admin_init_password
    if configured:
        return configured
    if settings.testing or settings.debug:
        return "admin123456"
    generated = secrets.token_urlsafe(12)
    logger.warning(
        "ADMIN_INIT_PASSWORD is not set: generated one-time password %r for the "
        "seeded 'admin' user. Log in and change it immediately, or set "
        "ADMIN_INIT_PASSWORD before first startup.",
        generated,
    )
    return generated


async def _ensure_admin(db: AsyncSession) -> None:
    """Lazy-seed the default admin user, admin role, and permissions on first call."""
    global _admin_seeded
    if _admin_seeded:
        return

    # Check if admin user already exists
    admin_check = await db.execute(select(User).where(User.username == "admin"))
    if admin_check.scalar_one_or_none():
        _admin_seeded = True
        return

    # Seed permissions
    perm_map: dict[str, Permission] = {}
    for code, resource, action in _ADMIN_PERMISSIONS:
        existing = await db.execute(select(Permission).where(Permission.code == code))
        perm = existing.scalar_one_or_none()
        if not perm:
            perm = Permission(
                id=uuid.uuid4(),
                code=code,
                name=code.replace(".", " ").title(),
                resource=resource,
                action=action,
            )
            db.add(perm)
            await db.flush()
        perm_map[code] = perm

    # Seed admin role with all permissions
    admin_role_result = await db.execute(select(Role).where(Role.name == "admin"))
    admin_role = admin_role_result.scalar_one_or_none()
    if not admin_role:
        admin_role = Role(id=uuid.uuid4(), name="admin", code="admin", description="System administrator")
        db.add(admin_role)
        await db.flush()
        for perm in perm_map.values():
            db.add(RolePermission(role_id=admin_role.id, permission_id=perm.id))

    # Seed admin user — never with a hardcoded production credential.
    admin_user = User(
        id=uuid.uuid4(),
        username="admin",
        email="admin@example.com",
        hashed_password=await async_hash_password(_initial_admin_password()),
        is_active=True,
    )
    db.add(admin_user)
    await db.flush()
    db.add(UserRole(user_id=admin_user.id, role_id=admin_role.id))

    _admin_seeded = True
