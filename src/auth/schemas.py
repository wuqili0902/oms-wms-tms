import uuid

from pydantic import BaseModel, Field

from src.core.schemas import PayloadBody


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    email: str = Field(..., max_length=255, pattern=r"^[^@]+@[^@]+\.[^@]+$")
    password: str = Field(..., min_length=8, max_length=128)


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    is_active: bool

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    name: str = Field(..., max_length=100)
    code: str = Field(..., max_length=50)
    description: str | None = None


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    description: str | None = None
    is_system: bool

    model_config = {"from_attributes": True}


class PermissionCreate(BaseModel):
    name: str
    code: str
    resource: str
    action: str
    description: str | None = None


class PermissionResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    resource: str
    action: str
    description: str | None = None

    model_config = {"from_attributes": True}


# ── RBAC assignment bodies ───────────────────────────────────────────────────


class UserRoleAssign(PayloadBody):
    """The body that attaches a role to a user.

    The handler read ``data["role_id"]`` from a bare ``dict``: a request that did
    not carry that key raised ``KeyError`` inside the handler, which is reported as
    a server failure — an admin panel bug became a 500 in the API log.  The id is
    checked here as a UUID, so the value that reaches the service is one.
    """

    role_id: uuid.UUID


class RolePermissionAssign(PayloadBody):
    """The body that grants a permission to a role.  Same reason as above."""

    permission_id: uuid.UUID
