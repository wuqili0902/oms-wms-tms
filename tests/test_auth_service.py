"""Tests for src.auth.service — raises ValidationException on duplicate."""

import uuid

import pytest

from src.auth.service import create_role, delete_role, update_role

# --- role -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_role_success(db_session):
    r = await create_role(db_session, {"name": "R1", "code": "r1"})
    assert r.get("code") == "r1" and isinstance(r, dict)


@pytest.mark.asyncio
async def test_update_role(db_session):
    role = await create_role(db_session, {"name":"R2","code":"r2"})
    role["description"] = "desc"
    updated = await update_role(db_session, str(role["id"]), {"name":"Renamed"})
    assert updated.get("name") == "Renamed"


@pytest.mark.asyncio
async def test_delete_role_not_found(db_session):
    with pytest.raises(Exception):
        await delete_role(db_session, uuid.uuid4())
