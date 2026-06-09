"""Tests for auth models — all skipped until DB is configured."""

import pytest


@pytest.mark.skip(reason="Database not configured for testing yet")
class TestUserModel:
    async def test_create_user_with_valid_data(self):
        pass

    async def test_user_has_required_fields(self):
        pass

    async def test_user_username_is_unique(self):
        pass

    async def test_user_email_is_unique(self):
        pass

    async def test_user_default_is_active(self):
        pass

    async def test_user_timestamps_are_set(self):
        pass
