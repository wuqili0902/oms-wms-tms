"""Supplementary tests for remaining uncovered paths in wms/service.py."""
import uuid
from decimal import Decimal

import pytest

from src.core.exceptions import NotFoundException, ValidationException
from src.wms import service as wms_service

LOC_DATA = {"zone": "A", "aisle": "1", "shelf": "1", "bin": "1"}


class TestWarehousePaginatedList:
    @pytest.mark.asyncio
    async def test_list_paginated(self, db_session):
        for i in range(3):
            await wms_service.create_warehouse(db_session, {"code": f"WH-PG-{i}", "name": f"PG {i}"})
        result = await wms_service.list_warehouses(db_session, page=1, page_size=2)
        assert isinstance(result, dict)
        assert "items" in result
        assert result["total"] >= 3
        assert result["page"] == 1

    @pytest.mark.asyncio
    async def test_list_unpaginated(self, db_session):
        result = await wms_service.list_warehouses(db_session)
        assert isinstance(result, list)


class TestDeleteLocation:
    @pytest.mark.asyncio
    async def test_delete_location(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-DEL", "name": "Del"})
        loc = await wms_service.create_location(db_session, wh["id"], LOC_DATA)
        await wms_service.delete_location(db_session, wh["id"], loc["id"])
        with pytest.raises(NotFoundException):
            await wms_service.get_location(db_session, loc["id"])


class TestUpdateWarehouseNotFound:
    @pytest.mark.asyncio
    async def test_update_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.update_warehouse(db_session, str(uuid.uuid4()), {"name": "X"})


class TestApprovePurchaseOrder:
    @pytest.mark.asyncio
    async def test_approve(self, db_session):
        po = await wms_service.create_purchase_order(db_session, {"po_number": "PO-APR-1"})
        result = await wms_service.approve_purchase_order(db_session, po["id"])
        assert result["status"] == "approved"

    @pytest.mark.asyncio
    async def test_approve_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.approve_purchase_order(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_approve_wrong_status(self, db_session):
        po = await wms_service.create_purchase_order(db_session, {"po_number": "PO-APR-2"})
        await wms_service.approve_purchase_order(db_session, po["id"])
        with pytest.raises(ValidationException, match="Cannot approve"):
            await wms_service.approve_purchase_order(db_session, po["id"])


class TestReceiveGoods:
    @pytest.mark.asyncio
    async def test_receive(self, db_session):
        """A receipt books what arrived.

        This used to create a PO with no lines at all and expect "received".
        That was only possible because receive_goods() booked nothing: an order
        for nothing and a delivery of nothing both came out looking like a
        completed receipt.
        """
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-RCV", "name": "RCV"})
        loc = await wms_service.create_location(db_session, wh["id"], LOC_DATA)
        po = await wms_service.create_purchase_order(db_session, {
            "po_number": "PO-RCV-1",
            "lines": [{"sku": "SKU-RCV", "quantity": 8, "unit_price": "2.50"}],
        })
        await wms_service.approve_purchase_order(db_session, po["id"])

        result = await wms_service.receive_goods(
            db_session, po["id"], {"warehouse_id": wh["id"], "location_id": loc["id"]}
        )

        assert result["status"] == "received"
        assert Decimal(str(result["lines"][0]["received_qty"])) == Decimal("8")
        # ...and the eight units are actually on the shelf.
        stock = await wms_service.query_inventory(db_session, wh_id=wh["id"], sku="SKU-RCV")
        assert sum(Decimal(str(row["quantity"])) for row in stock) == Decimal("8")

    @pytest.mark.asyncio
    async def test_receive_of_an_empty_order_is_refused(self, db_session):
        po = await wms_service.create_purchase_order(db_session, {"po_number": "PO-RCV-EMPTY"})
        await wms_service.approve_purchase_order(db_session, po["id"])
        with pytest.raises(ValidationException, match="no lines"):
            await wms_service.receive_goods(db_session, po["id"])

    @pytest.mark.asyncio
    async def test_receive_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.receive_goods(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_receive_wrong_status(self, db_session):
        po = await wms_service.create_purchase_order(db_session, {"po_number": "PO-RCV-2"})
        with pytest.raises(ValidationException, match="Cannot receive"):
            await wms_service.receive_goods(db_session, po["id"])


class TestCreditMemoWithLines:
    @pytest.mark.asyncio
    async def test_create_with_lines(self, db_session):
        cm = await wms_service.create_credit_memo(db_session, {
            "credit_memo_number": "CM-1",
            "entity_type": "vendor",
            "lines": [{"description": "Return", "quantity": 2, "unit_price": "10.00"}],
        })
        assert float(cm["total_amount"]) == 20.0


class TestAdjustStockCountErrors:
    @pytest.mark.asyncio
    async def test_missing_warehouse_and_code(self, db_session):
        data = {
            "location_id": str(uuid.uuid4()),
            "count_results": [{"sku": "X", "actual_qty": 1}],
        }
        with pytest.raises(ValidationException, match="Missing warehouse_id"):
            await wms_service.adjust_stock_count(db_session, data)

    @pytest.mark.asyncio
    async def test_invalid_warehouse_code(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.adjust_stock_count(db_session, {
                "source_warehouse_code": "NONEXISTENT",
                "location_id": str(uuid.uuid4()),
                "count_results": [{"sku": "X", "actual_qty": 1}],
            })

    @pytest.mark.asyncio
    async def test_missing_location(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SC-1", "name": "SC"})
        with pytest.raises(ValidationException, match="Missing location_id"):
            await wms_service.adjust_stock_count(db_session, {
                "warehouse_id": wh["id"],
                "count_results": [{"sku": "X", "actual_qty": 1}],
            })

    @pytest.mark.asyncio
    async def test_invalid_location(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SC-2", "name": "SC"})
        with pytest.raises(NotFoundException):
            await wms_service.adjust_stock_count(db_session, {
                "warehouse_id": wh["id"],
                "location_id": str(uuid.uuid4()),
                "count_results": [{"sku": "X", "actual_qty": 1}],
            })

    @pytest.mark.asyncio
    async def test_no_count_results(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SC-3", "name": "SC"})
        loc = await wms_service.create_location(db_session, wh["id"], LOC_DATA)
        with pytest.raises(ValidationException, match="No count results"):
            await wms_service.adjust_stock_count(db_session, {
                "warehouse_id": wh["id"],
                "location_id": loc["id"],
                "count_results": [],
            })

    @pytest.mark.asyncio
    async def test_missing_qty_field(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SC-4", "name": "SC"})
        loc = await wms_service.create_location(db_session, wh["id"], LOC_DATA)
        with pytest.raises(ValidationException, match="Missing quantity"):
            await wms_service.adjust_stock_count(db_session, {
                "warehouse_id": wh["id"],
                "location_id": loc["id"],
                "count_results": [{"sku": "SKU-NO-QTY"}],
            })

    @pytest.mark.asyncio
    async def test_success_new_sku(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SC-5", "name": "SC"})
        loc = await wms_service.create_location(db_session, wh["id"], LOC_DATA)
        result = await wms_service.adjust_stock_count(db_session, {
            "warehouse_id": wh["id"],
            "location_id": loc["id"],
            "count_results": [{"sku": "NEW-SKU-1", "actual_qty": 10}],
        })
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_success_existing_sku_adjust_in(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SC-6", "name": "SC"})
        loc = await wms_service.create_location(db_session, wh["id"], LOC_DATA)
        await wms_service.adjust_stock_count(db_session, {
            "warehouse_id": wh["id"],
            "location_id": loc["id"],
            "count_results": [{"sku": "SKU-ADJ", "actual_qty": 5}],
        })
        result = await wms_service.adjust_stock_count(db_session, {
            "warehouse_id": wh["id"],
            "location_id": loc["id"],
            "count_results": [{"sku": "SKU-ADJ", "actual_qty": 10}],
        })
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_success_existing_sku_adjust_out(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SC-7", "name": "SC"})
        loc = await wms_service.create_location(db_session, wh["id"], LOC_DATA)
        await wms_service.adjust_stock_count(db_session, {
            "warehouse_id": wh["id"],
            "location_id": loc["id"],
            "count_results": [{"sku": "SKU-ADJ2", "actual_qty": 10}],
        })
        result = await wms_service.adjust_stock_count(db_session, {
            "warehouse_id": wh["id"],
            "location_id": loc["id"],
            "count_results": [{"sku": "SKU-ADJ2", "actual_qty": 3}],
        })
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_no_change_is_noop(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SC-9", "name": "SC"})
        loc = await wms_service.create_location(db_session, wh["id"], LOC_DATA)
        await wms_service.adjust_stock_count(db_session, {
            "warehouse_id": wh["id"],
            "location_id": loc["id"],
            "count_results": [{"sku": "SKU-NOOP", "actual_qty": 5}],
        })
        result = await wms_service.adjust_stock_count(db_session, {
            "warehouse_id": wh["id"],
            "location_id": loc["id"],
            "count_results": [{"sku": "SKU-NOOP", "actual_qty": 5}],
        })
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_source_warehouse_code_lookup(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SC-CODE", "name": "SC"})
        loc = await wms_service.create_location(db_session, wh["id"], LOC_DATA)
        result = await wms_service.adjust_stock_count(db_session, {
            "source_warehouse_code": "WH-SC-CODE",
            "location_id": loc["id"],
            "count_results": [{"sku": "SKU-CODE", "actual_qty": 7}],
        })
        assert result["success"] is True


class TestListMovementsWithFilter:
    @pytest.mark.asyncio
    async def test_list_movements_empty(self, db_session):
        result = await wms_service.list_movements(db_session)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_movements_with_wh_filter(self, db_session):
        result = await wms_service.list_movements(db_session, wh_id=str(uuid.uuid4()))
        assert isinstance(result, list)


class TestListPurchaseOrdersPaginated:
    @pytest.mark.asyncio
    async def test_list_paginated(self, db_session):
        await wms_service.create_purchase_order(db_session, {"po_number": "PO-PG-1"})
        result = await wms_service.list_purchase_orders(db_session, page=1, page_size=10)
        assert isinstance(result, dict)
        assert "items" in result

    @pytest.mark.asyncio
    async def test_list_unpaginated(self, db_session):
        result = await wms_service.list_purchase_orders(db_session)
        assert isinstance(result, list)


class TestCreditMemoGetNotFound:
    @pytest.mark.asyncio
    async def test_get_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.get_credit_memo(db_session, str(uuid.uuid4()))
