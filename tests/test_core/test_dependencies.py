"""Tests for core dependencies — auth & permission utilities."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import Permission, Role, User, UserRole, RolePermission
from src.core.dependencies import (
    _get_user_permissions,
    get_current_user,
    get_optional_current_user,
    get_required_current_user,
    require_permission,
)
from src.core.security import TokenExpired, TokenInvalid


class TestGetUserPermissions:
    async def _setup_user_role_perms(self, db_session, username, suffix, perms):
        suffix = uuid.uuid4().hex[:6]
        user = User(id=uuid.uuid4(), username=username,
                    email=f"{suffix}@t.com", hashed_password="h")
        role = Role(id=uuid.uuid4(), name="R", code=f"r_{suffix}")
        db_session.add_all([user, role])
        db_session.add(UserRole(user_id=user.id, role_id=role.id))
        for code, name, res, action in perms:
            unique_code = f"{code}_{suffix}"
            p = Permission(id=uuid.uuid4(), name=name, code=unique_code,
                           resource=res, action=action)
            db_session.add(p)
            db_session.add(RolePermission(role_id=role.id, permission_id=p.id))
        await db_session.commit()
        return suffix

    async def test_returns_permissions(self, db_session: AsyncSession):
        suffix = await self._setup_user_role_perms(db_session, "puser", None, [
            ("r", "Read", "test", "read"),
        ])
        result = await _get_user_permissions(db_session, "puser")
        assert result == {f"r_{suffix}"}

    async def test_returns_multiple_permissions(self, db_session: AsyncSession):
        suffix = await self._setup_user_role_perms(db_session, "muser", None, [
            ("r", "Read", "test", "read"),
            ("w", "Write", "test", "write"),
        ])
        result = await _get_user_permissions(db_session, "muser")
        assert result == {f"r_{suffix}", f"w_{suffix}"}

    async def test_empty_for_unknown_user(self, db_session: AsyncSession):
        result = await _get_user_permissions(db_session, "nobody")
        assert result == set()

    async def test_empty_for_user_without_roles(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        user = User(id=uuid.uuid4(), username=f"norole-{suffix}",
                    email=f"norole-{suffix}@t.com", hashed_password="h")
        db_session.add(user)
        await db_session.commit()
        result = await _get_user_permissions(db_session, user.username)
        assert result == set()

    async def test_permissions_from_multiple_roles(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        user = User(id=uuid.uuid4(), username=f"multirole-{suffix}",
                    email=f"mr-{suffix}@t.com", hashed_password="h")
        r1 = Role(id=uuid.uuid4(), name="R1", code=f"r1_{suffix}")
        r2 = Role(id=uuid.uuid4(), name="R2", code=f"r2_{suffix}")
        p1 = Permission(id=uuid.uuid4(), name="P1", code=f"p1_read_{suffix}",
                        resource="p1", action="read")
        p2 = Permission(id=uuid.uuid4(), name="P2", code=f"p2_write_{suffix}",
                        resource="p2", action="write")
        db_session.add_all([user, r1, r2, p1, p2])
        db_session.add(UserRole(user_id=user.id, role_id=r1.id))
        db_session.add(UserRole(user_id=user.id, role_id=r2.id))
        db_session.add(RolePermission(role_id=r1.id, permission_id=p1.id))
        db_session.add(RolePermission(role_id=r2.id, permission_id=p2.id))
        await db_session.commit()
        result = await _get_user_permissions(db_session, user.username)
        assert result == {f"p1_read_{suffix}", f"p2_write_{suffix}"}


class TestRequirePermission:
    async def test_grants_access_when_permission_held(self):
        suffix = uuid.uuid4().hex[:6]
        user = User(id=uuid.uuid4(), username=f"ruser-{suffix}",
                    email=f"ru-{suffix}@t.com", hashed_password="h")
        mock_session = AsyncMock(spec=AsyncSession)

        with (patch("src.core.dependencies._get_user_permissions",
                     new_callable=AsyncMock) as mock_get_perms,
              patch("src.core.database.get_db") as mock_get_db):
            mock_get_db.return_value.__anext__ = AsyncMock(return_value=mock_session)
            mock_get_perms.return_value = {"test:access"}
            check = require_permission("test:access")
            result = await check({"sub": user.username})

        assert result == {"sub": user.username}

    async def test_raises_403_when_permission_missing(self):
        suffix = uuid.uuid4().hex[:6]
        user = User(id=uuid.uuid4(), username=f"denied-{suffix}",
                    email=f"denied-{suffix}@t.com", hashed_password="h")
        mock_session = AsyncMock(spec=AsyncSession)

        with (patch("src.core.dependencies._get_user_permissions",
                     new_callable=AsyncMock) as mock_get_perms,
              patch("src.core.database.get_db") as mock_get_db):
            mock_get_db.return_value.__anext__ = AsyncMock(return_value=mock_session)
            mock_get_perms.return_value = {"other:perm"}
            check = require_permission("test:access")
            with pytest.raises(HTTPException) as exc:
                await check({"sub": user.username})
            assert exc.value.status_code == 403
            assert "test:access" in exc.value.detail

    async def test_raises_403_when_no_username(self):
        mock_session = AsyncMock(spec=AsyncSession)

        with (patch("src.core.database.get_db") as mock_get_db):
            mock_get_db.return_value.__anext__ = AsyncMock(return_value=mock_session)
            check = require_permission("test:access")
            with pytest.raises(HTTPException) as exc:
                await check({"sub": ""})
            assert exc.value.status_code == 403
            assert "User identity not found" in exc.value.detail

    async def test_returns_user_when_no_permissions_required(self):
        check = require_permission()
        result = await check({"sub": "anyone"})
        assert result == {"sub": "anyone"}

    async def test_multiple_permissions_required_grants(self):
        mock_session = AsyncMock(spec=AsyncSession)

        with (patch("src.core.dependencies._get_user_permissions",
                     new_callable=AsyncMock) as mock_get_perms,
              patch("src.core.database.get_db") as mock_get_db):
            mock_get_db.return_value.__anext__ = AsyncMock(return_value=mock_session)
            mock_get_perms.return_value = {"a:r", "a:w", "a:x"}
            check = require_permission("a:r", "a:w")
            result = await check({"sub": "testuser"})
            assert result == {"sub": "testuser"}

    async def test_multiple_permissions_required_fails(self):
        mock_session = AsyncMock(spec=AsyncSession)

        with (patch("src.core.dependencies._get_user_permissions",
                     new_callable=AsyncMock) as mock_get_perms,
              patch("src.core.database.get_db") as mock_get_db):
            mock_get_db.return_value.__anext__ = AsyncMock(return_value=mock_session)
            mock_get_perms.return_value = {"a:r"}
            check = require_permission("a:r", "a:w")
            with pytest.raises(HTTPException) as exc:
                await check({"sub": "testuser"})
            assert exc.value.status_code == 403


class TestGetCurrentUser:
    def _creds(self, token: str = "test-token") -> HTTPAuthorizationCredentials:
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    async def test_valid_token(self):
        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.return_value = {"sub": "testuser", "role": "admin"}
            result = await get_current_user(self._creds())
        assert result == {"sub": "testuser", "role": "admin"}

    async def test_no_credentials(self):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(None)
        assert exc.value.status_code == 401

    async def test_empty_credentials(self):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(self._creds(""))
        assert exc.value.status_code == 401

    async def test_expired_token(self):
        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.side_effect = TokenExpired
            with pytest.raises(HTTPException) as exc:
                await get_current_user(self._creds())
            assert exc.value.status_code == 401

    async def test_invalid_token(self):
        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.side_effect = TokenInvalid
            with pytest.raises(HTTPException) as exc:
                await get_current_user(self._creds())
            assert exc.value.status_code == 401

    async def test_token_without_sub(self):
        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.return_value = {"role": "admin"}
            with pytest.raises(HTTPException) as exc:
                await get_current_user(self._creds())
            assert exc.value.status_code == 401


class TestGetOptionalCurrentUser:
    def _creds(self, token: str = "test-token") -> HTTPAuthorizationCredentials:
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    async def test_no_credentials(self):
        result = await get_optional_current_user(None)
        assert result == {}

    async def test_empty_credentials(self):
        result = await get_optional_current_user(self._creds(""))
        assert result == {}

    async def test_valid_token(self):
        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.return_value = {"sub": "testuser"}
            result = await get_optional_current_user(self._creds())
        assert result == {"sub": "testuser"}

    async def test_expired_token_returns_empty(self):
        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.side_effect = TokenExpired
            result = await get_optional_current_user(self._creds())
        assert result == {}

    async def test_invalid_token_returns_empty(self):
        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.side_effect = TokenInvalid
            result = await get_optional_current_user(self._creds())
        assert result == {}

    async def test_token_without_sub_returns_empty(self):
        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.return_value = {"role": "admin"}
            result = await get_optional_current_user(self._creds())
        assert result == {}


class TestGetRequiredCurrentUser:
    def _creds(self, token: str = "test-token") -> HTTPAuthorizationCredentials:
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    async def test_valid_token(self):
        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.return_value = {"sub": "testuser"}
            result = await get_required_current_user(self._creds())
        assert result == {"sub": "testuser"}

    async def test_no_credentials(self):
        with pytest.raises(HTTPException) as exc:
            await get_required_current_user(None)
        assert exc.value.status_code == 401

    async def test_expired_token(self):
        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.side_effect = TokenExpired
            with pytest.raises(HTTPException) as exc:
                await get_required_current_user(self._creds())
            assert exc.value.status_code == 401

    async def test_invalid_token(self):
        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.side_effect = TokenInvalid
            with pytest.raises(HTTPException) as exc:
                await get_required_current_user(self._creds())
            assert exc.value.status_code == 401

    async def test_token_without_sub(self):
        with patch("src.core.security.decode_token") as mock_decode:
            mock_decode.return_value = {"role": "admin"}
            with pytest.raises(HTTPException) as exc:
                await get_required_current_user(self._creds())
            assert exc.value.status_code == 401
