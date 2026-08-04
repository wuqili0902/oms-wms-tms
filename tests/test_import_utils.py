"""Tests for src.core.import_utils — import_orders_from_csv, import_inventory_from_csv."""

from unittest.mock import AsyncMock, MagicMock, patch


class TestImportOrdersFromCsv:
    async def test_success(self):
        from src.core.import_utils import import_orders_from_csv

        mock_db = AsyncMock()

        with patch("src.oms.service.create_order", AsyncMock(return_value=None)):
            result = await import_orders_from_csv(
                "customer_id,items,priority,notes\nc1,\"[]\",high,note1\nc2,\"[{}]\",low,",
                mock_db,
            )
        assert result["success"] == 2
        assert result["errors"] == []

    async def test_missing_customer_id(self):
        from src.core.import_utils import import_orders_from_csv

        mock_db = AsyncMock()

        result = await import_orders_from_csv(
            "customer_id,items\n,\"[]\"",
            mock_db,
        )
        assert result["success"] == 0
        assert len(result["errors"]) == 1
        assert "customer_id is required" in result["errors"][0]["error"]

    async def test_invalid_json_items(self):
        from src.core.import_utils import import_orders_from_csv

        mock_db = AsyncMock()

        result = await import_orders_from_csv(
            "customer_id,items\nc1,not-json",
            mock_db,
        )
        assert result["success"] == 0
        assert len(result["errors"]) == 1

    async def test_create_order_exception(self):
        from src.core.import_utils import import_orders_from_csv

        mock_db = AsyncMock()

        with patch("src.oms.service.create_order", side_effect=ValueError("db error")):
            result = await import_orders_from_csv(
                "customer_id,items\nc1,\"[]\"",
                mock_db,
            )
            assert result["success"] == 0
            assert "db error" in result["errors"][0]["error"]

    async def test_empty_csv_yields_zero(self):
        from src.core.import_utils import import_orders_from_csv

        mock_db = AsyncMock()
        result = await import_orders_from_csv("customer_id,items\n", mock_db)
        assert result["success"] == 0
        assert result["errors"] == []


class TestImportInventoryFromCsv:
    async def test_existing_inventory_updated(self):
        from src.core.import_utils import import_inventory_from_csv

        mock_db = AsyncMock()
        mock_inv = MagicMock()
        mock_inv.quantity = 0
        mock_inv.min_qty = 0
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_inv
        mock_db.execute.return_value = mock_result

        result = await import_inventory_from_csv(
            "sku_id,warehouse_id,quantity,min_qty\n"
            "550e8400-e29b-41d4-a716-446655440000,550e8400-e29b-41d4-a716-446655440001,100,10",
            mock_db,
        )
        assert result["success"] == 1
        assert mock_inv.quantity == 100
        assert mock_inv.min_qty == 10

    async def test_new_inventory_created(self):
        from src.core.import_utils import import_inventory_from_csv

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await import_inventory_from_csv(
            "sku_id,warehouse_id,quantity,min_qty\n"
            "550e8400-e29b-41d4-a716-446655440002,550e8400-e29b-41d4-a716-446655440003,50,5",
            mock_db,
        )
        assert result["success"] == 1
        mock_db.add.assert_called_once()

    async def test_invalid_uuid_sku(self):
        from src.core.import_utils import import_inventory_from_csv

        mock_db = AsyncMock()

        result = await import_inventory_from_csv(
            "sku_id,warehouse_id,quantity,min_qty\nnot-a-uuid,550e8400-e29b-41d4-a716-446655440003,50,5",
            mock_db,
        )
        assert result["success"] == 0
        assert len(result["errors"]) == 1
