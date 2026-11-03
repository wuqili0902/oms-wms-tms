"""Auth API router — registration, login, token management, RBAC."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import service as auth_service
from src.auth.schemas import (
    PermissionCreate,
    PermissionResponse,
    RefreshRequest,
    RoleCreate,
    RolePermissionAssign,
    RoleResponse,
    RoleUpdate,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserRoleAssign,
)
from src.core.database import get_db
from src.core.dependencies import get_current_user, require_permission
from src.core.exceptions import NotFoundException, ValidationException
from src.core.rate_limiter import rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])


class MessageResponse(BaseModel):
    message: str


class UserRoleResponse(BaseModel):
    user_id: str
    role_id: str


class RolePermissionResponse(BaseModel):
    role_id: str
    permission_id: str


class ToggleActiveResponse(BaseModel):
    is_active: bool


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@rate_limit(requests=3, window=3600)
async def register(request: Request, data: UserCreate, db: AsyncSession = Depends(get_db)):
    try:
        user = await auth_service.register_user(db, data.model_dump())
    except ValidationException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Register failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Registration failed: {e}")
    return UserResponse(**user)


@router.post("/login", response_model=TokenResponse)
@rate_limit(requests=5, window=60)
async def login(request: Request, data: UserLogin, db: AsyncSession = Depends(get_db)):
    user = await auth_service.authenticate_user(db, data.username, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    tokens = await auth_service.create_tokens(user)
    return TokenResponse(**tokens)


# @rate_limit has to sit **under** @router.post.  router.post registers the function
# it is applied to, so decorating from above attaches the limiter to a local name and
# the route stays unlimited — which is how /auth/refresh shipped: a stolen refresh
# token could be replayed without limit.  ``request: Request`` is what gives the
# limiter an address to key on; a body model alone would not.
@router.post("/refresh", response_model=TokenResponse)
@rate_limit(requests=10, window=60)
async def refresh(request: Request, body: RefreshRequest):
    tokens = await auth_service.refresh_tokens(body.refresh_token)
    if not tokens:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return TokenResponse(**tokens)


@router.post("/logout", response_model=MessageResponse)
async def logout(request: RefreshRequest):
    await auth_service.revoke_refresh_token(request.refresh_token)
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    username = current_user.get("sub")
    user = await auth_service.get_user_by_username(db, username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**user)


@router.get("/users", response_model=list[UserResponse],
             dependencies=[Depends(require_permission("admin.rbac.manage"))])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    users = await auth_service.list_users(db)
    return [UserResponse(**u) for u in users]


@router.post("/roles", response_model=RoleResponse, status_code=201,
             dependencies=[Depends(require_permission("admin.rbac.manage"))])
async def create_role(
    role: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        r = await auth_service.create_role(db, role.model_dump())
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))
    return RoleResponse(**r)


@router.get("/roles", response_model=list[RoleResponse],
             dependencies=[Depends(require_permission("admin.rbac.manage"))])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    roles = await auth_service.list_roles(db)
    return [RoleResponse(**r) for r in roles]


@router.get("/permissions", response_model=list[PermissionResponse],
             dependencies=[Depends(require_permission("admin.rbac.manage"))])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    perms = await auth_service.list_permissions(db)
    return [PermissionResponse(**p) for p in perms]


@router.put("/roles/{role_id}", response_model=RoleResponse,
            dependencies=[Depends(require_permission("admin.rbac.manage"))])
async def update_role(
    role_id: str,
    data: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        r = await auth_service.update_role(db, role_id, data.model_dump())
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    return RoleResponse(**r)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_permission("admin.rbac.manage"))])
async def delete_role(
    role_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        await auth_service.delete_role(db, role_id)
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/permissions", response_model=PermissionResponse, status_code=201,
             dependencies=[Depends(require_permission("admin.rbac.manage"))])
async def create_permission(
    data: PermissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        p = await auth_service.create_permission(db, data.model_dump())
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))
    return PermissionResponse(**p)


@router.post(
    "/users/{user_id}/roles",
    response_model=UserRoleResponse,
    dependencies=[Depends(require_permission("admin.rbac.manage"))],
)
async def assign_role_to_user(
    user_id: str,
    data: UserRoleAssign,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Attach a role to a user.

    ``UserRoleAssign``: the handler read ``data["role_id"]`` from a bare ``dict``,
    so a request without that key was a ``KeyError`` inside the handler — a 500.
    """
    try:
        return await auth_service.assign_role_to_user(db, user_id, str(data.role_id))
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


@router.delete("/users/{user_id}/roles/{role_id}",
               status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_permission("admin.rbac.manage"))])
async def remove_role_from_user(
    user_id: str,
    role_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        await auth_service.remove_role_from_user(db, user_id, role_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/roles/{role_id}/permissions",
    response_model=RolePermissionResponse,
    dependencies=[Depends(require_permission("admin.rbac.manage"))],
)
async def assign_permission_to_role(
    role_id: str,
    data: RolePermissionAssign,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Grant a permission to a role (``RolePermissionAssign`` — see
    :func:`assign_role_to_user` for why the key has to be a field, not a dict lookup)."""
    try:
        return await auth_service.assign_permission_to_role(db, role_id, str(data.permission_id))
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


@router.delete("/roles/{role_id}/permissions/{perm_id}",
               status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_permission("admin.rbac.manage"))])
async def remove_permission_from_role(
    role_id: str,
    perm_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        await auth_service.remove_permission_from_role(db, role_id, perm_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/users/{user_id}/toggle",
    response_model=ToggleActiveResponse,
    dependencies=[Depends(require_permission("admin.user.manage"))],
)
async def toggle_user_active_state(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Flip a user's active flag.

    The id is checked in the service (:func:`auth_service.toggle_user_active`):
    this route built ``uuid.UUID(user_id)`` itself, so an id that is not one was a
    ``ValueError`` here — a 500 about the server in answer to a typed-wrong id.
    """
    try:
        return await auth_service.toggle_user_active(db, user_id)
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))
