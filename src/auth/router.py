"""Auth API router — registration, login, token management, RBAC."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import (
    PermissionResponse,
    RefreshRequest,
    RoleCreate,
    RoleResponse,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)
from src.auth import service as auth_service
from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.exceptions import ValidationException

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    try:
        user = await auth_service.register_user(db, data.model_dump())
    except ValidationException as e:
        raise HTTPException(status_code=400, detail=str(e))
    return UserResponse(**user)


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    user = await auth_service.authenticate_user(db, data.username, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    tokens = await auth_service.create_tokens(user)
    return TokenResponse(**tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: RefreshRequest):
    tokens = await auth_service.refresh_tokens(request.refresh_token)
    if not tokens:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return TokenResponse(**tokens)


@router.post("/logout")
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


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    users = await auth_service.list_users(db)
    return [UserResponse(**u) for u in users]


@router.post("/roles", response_model=RoleResponse, status_code=201)
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


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    roles = await auth_service.list_roles(db)
    return [RoleResponse(**r) for r in roles]


@router.get("/permissions", response_model=list[PermissionResponse])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    perms = await auth_service.list_permissions(db)
    return [PermissionResponse(**p) for p in perms]
