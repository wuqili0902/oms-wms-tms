import uuid
from pydantic import BaseModel, Field
from typing import Optional, List


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    email: str = Field(..., max_length=255, pattern=r'^[^@]+@[^@]+\.[^@]+$')
    password: str = Field(..., min_length=6, max_length=128)


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
    description: Optional[str] = None


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    description: Optional[str] = None
    is_system: bool

    model_config = {"from_attributes": True}


class PermissionCreate(BaseModel):
    name: str
    code: str
    resource: str
    action: str
    description: Optional[str] = None


class PermissionResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    resource: str
    action: str
    description: Optional[str] = None

    model_config = {"from_attributes": True}
