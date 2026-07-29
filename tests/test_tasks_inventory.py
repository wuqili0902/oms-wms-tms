"""Tests for inventory background tasks (P0 fixes).

These task functions use ``async_session_factory`` which connects to
PostgreSQL.  Full integration tests require a running PostgreSQL + Redis
environment.  Here we verify the module loads and task names are correct.
"""

import pytest

from src.tasks.inventory import (
    check_low_stock_alerts,
    release_locked_inventory_for_cancelled_orders,
)

pytestmark = pytest.mark.skip(reason="Requires PostgreSQL (async_session_factory)")


class TestInventoryTasks:
    async def test_check_low_stock_alerts(self):
        result = await check_low_stock_alerts()
        assert "low_stock_count" in result

    async def test_release_locked_inventory(self):
        result = await release_locked_inventory_for_cancelled_orders()
        assert "released_count" in result
