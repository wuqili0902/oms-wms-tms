"""Auth module - JWT authentication and RBAC permission system."""
from src.auth.router import router as auth_router

__all__ = ["auth_router"]
