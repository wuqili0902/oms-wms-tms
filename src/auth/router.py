import uuid
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from src.auth.schemas import (
    UserCreate,
    UserLogin,
    TokenResponse,
    RefreshRequest,
    UserResponse,
    RoleCreate,
    RoleUpdate,
    RoleResponse,
    PermissionCreate,
    PermissionResponse,
)
from src.core.security import (
    verify_password,
    hash_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from src.core.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory storage (will be replaced with DB in Task 6+)
users_db: Dict[str, dict] = {}
roles_db: Dict[str, dict] = {}
permissions_db: Dict[str, dict] = {}
refresh_tokens_db: Dict[str, str] = {}  # token -> username
_admin_seeded = False


def _seed_admin():
    """Lazy-seed the default admin user."""
    global _admin_seeded
    if _admin_seeded:
        return
    _admin_id = str(uuid.uuid4())
    users_db["admin"] = {
        "id": _admin_id,
        "username": "admin",
        "email": "admin@oms.local",
        "hashed_password": hash_password("admin123"),
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _admin_seeded = True


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate):
    _seed_admin()
    if user_data.username in users_db:
        raise HTTPException(status_code=400, detail="Username already exists")
    user_id = str(uuid.uuid4())
    users_db[user_data.username] = {
        "id": user_id,
        "username": user_data.username,
        "email": user_data.email,
        "hashed_password": hash_password(user_data.password),
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return UserResponse(
        id=uuid.UUID(user_id),
        username=user_data.username,
        email=user_data.email,
        is_active=True,
    )


@router.post("/login", response_model=TokenResponse)
async def login(login_data: UserLogin):
    _seed_admin()
    user = users_db.get(login_data.username)
    if not user or not verify_password(login_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account is disabled")

    token_data = {"sub": login_data.username, "uid": user["id"]}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)
    refresh_tokens_db[refresh_token] = login_data.username

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: RefreshRequest):
    username = refresh_tokens_db.get(request.refresh_token)
    if not username or username not in users_db:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    payload = decode_token(request.refresh_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Refresh token expired or invalid")

    # Remove old refresh token
    del refresh_tokens_db[request.refresh_token]

    user = users_db[username]
    token_data = {"sub": username, "uid": user["id"]}
    new_access = create_access_token(token_data)
    new_refresh = create_refresh_token(token_data)
    refresh_tokens_db[new_refresh] = username

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout")
async def logout(request: RefreshRequest):
    refresh_tokens_db.pop(request.refresh_token, None)
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    username = current_user.get("sub")
    user = users_db.get(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(
        id=uuid.UUID(user["id"]),
        username=user["username"],
        email=user["email"],
        is_active=user["is_active"],
    )


@router.get("/users", response_model=List[UserResponse])
async def list_users(current_user: dict = Depends(get_current_user)):
    return [
        UserResponse(id=uuid.UUID(u["id"]), username=u["username"], email=u["email"], is_active=u["is_active"])
        for u in users_db.values()
    ]


@router.post("/roles", response_model=RoleResponse, status_code=201)
async def create_role(role: RoleCreate, current_user: dict = Depends(get_current_user)):
    role_id = str(uuid.uuid4())
    roles_db[role.code] = {
        "id": role_id,
        "name": role.name,
        "code": role.code,
        "description": role.description,
        "is_system": False,
    }
    return RoleResponse(id=uuid.UUID(role_id), name=role.name, code=role.code, description=role.description, is_system=False)


@router.get("/roles", response_model=List[RoleResponse])
async def list_roles(current_user: dict = Depends(get_current_user)):
    return [
        RoleResponse(id=uuid.UUID(r["id"]), name=r["name"], code=r["code"], description=r["description"], is_system=r.get("is_system", False))
        for r in roles_db.values()
    ]


@router.get("/permissions", response_model=List[PermissionResponse])
async def list_permissions(current_user: dict = Depends(get_current_user)):
    return [
        PermissionResponse(id=uuid.UUID(p["id"]), name=p["name"], code=p["code"], resource=p["resource"], action=p["action"], description=p.get("description"))
        for p in permissions_db.values()
    ]
