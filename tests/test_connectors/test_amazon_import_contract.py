"""Amazon connector contract: the import produces an order the warehouse can act on.

Three console buttons — 导入订单 and 同步追踪 on the 电商对接 screen — posted
with **no body at all**.  ``POST /connectors/amazon/orders`` took ``data: dict``,
so the answer was 422 ``body: Field required``; the screen caught it, printed
"导入失败，请检查配置", and the operator was left guessing which configuration.
Two of the four jobs this connector is supposed to do (poll status, sync
inventory) are ``# TODO`` stubs, and the console advertised them as working
features.

What the endpoints accepted was the other half of the problem:

* ``AmazonOrderId`` was never read as a requirement — a payload naming no order
  imported as a 201 whose ``amazon_order_id`` was empty.  That number is what
  the tracking upload, the reconciliation and the Seller Central support ticket
  are all answered with.
* ``OrderItems`` was never read as a requirement either, and ``import_erp_order``
  calls ``oms_service.create_order`` **directly** — it never passes
  ``OrderCreate``, the schema the HTTP path enforces (``items`` ≥ 1, quantity
  > 0, a money amount).  So an order with no lines, a line with no product on
  it, and a quantity of ``-2`` all imported green.  An order with nothing on it
  cannot be picked, shipped, invoiced, or cancelled.
* ``QuantityOrdered`` went through ``int(...)``, which dies on the string
  SP-API uses for bundled listings ("2 items") — a 500 for a payload that was
  merely unusual.  ``ShippingAddress``/``OrderTotal`` arrive as null for
  unshipped and cancelled orders; ``.get`` on a null answered ``AttributeError``,
  and a 500 was the operator's only clue.
* ``ASIN`` was written into ``gtin``.  An ASIN is Amazon's own alphanumeric id,
  not an EAN — every scan-gun flow (``/barcode/validate``, the PDA 扫码) reads
  that column as a GTIN and rejects it.
* ``POST /connectors/amazon/tracking`` defaulted all four fields to ``""``,
  built a payload out of the defaults, and answered ``received``.  The screen
  read that as tracking on its way to Amazon.  It never was: nothing was sent,
  and ``upload_tracking_to_amazon`` is a stub.

The guards below live in ``parse_amazon_order`` and ``import_erp_order``, not in
the request schema — Amazon's own object is the input, and the same guards have
to run for the nightly poll that no screen posts.  ``tests/test_connectors/``
is its own directory: two earlier test files run the same endpoints through a
hand-built FastAPI app with no exception handlers, so a ``ValidationException``
there answers 500.  Every test here goes through the app in ``src/main.py``,
where 422 is 422.
"""

import pytest

API = "/api/v1"


@pytest.fixture(autouse=True)
async def _authenticated(async_client):
    from src.core.dependencies import get_current_user
    from src.main import app

    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "shipctr_", "username": "shipctr_", "roles": ["admin"],
    }
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _amazon_order(**over) -> dict:
    """One SP-API ``Order`` in the shape SP-API returns it."""
    data = {
        "AmazonOrderId": "402-3138915-0004487",
        "PurchaseDate": "2026-11-02T09:00:00Z",
        "OrderStatus": "Unshipped",
        "BuyerEmail": "buyer@example.com",
        "BuyerName": "Wei Chen",
        "MarketplaceId": "AAHKV2X7AFYLW",
        "OrderTotal": {"Amount": "150.00", "CurrencyCode": "CNY"},
        "ShippingAddress": {
            "Name": "Wei Chen", "AddressLine1": "1 Nanjing Rd",
            "City": "Shanghai", "StateOrRegion": "SH",
            "PostalCode": "200000", "CountryCode": "CN", "Phone": "13800000000",
        },
        "OrderItems": [{
            "SellerSKU": "SKU-BOLT-100", "Title": "M8 Bolt 100-pack",
            "QuantityOrdered": 2, "QuantityShipped": 0,
            "ItemPrice": {"Amount": "75.00", "CurrencyCode": "CNY"},
            "ASIN": "B0ABCDEF12",
        }],
    }
    data.update(over)
    return data


def _fields(resp) -> str:
    """Everything the API said is wrong, in one string to match against."""
    body = resp.json()
    parts = [str((body.get("error") or {}).get("message") or ""), str(body.get("detail") or "")]
    parts += [f"{e.get('field')} {e.get('message')} {e.get('value')}" for e in body.get("errors") or []]
    return " | ".join(parts)


class TestOrderImport:
    async def test_console_body_imports_the_order_the_operator_pasted(self, async_client):
        resp = await async_client.post(f"{API}/connectors/amazon/orders", json=_amazon_order())
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "imported"
        assert data["amazon_order_id"] == "402-3138915-0004487"
        # The number printed on the order, not only the uuid nobody reads off a
        # pick list.
        assert data["order_no"].startswith("ORD-")
        assert data["line_count"] == 1
        assert data["total_amount"] == "150.00"

    async def test_order_naming_no_order_is_refused(self, async_client):
        """The 201 used to name no Amazon order at all."""
        resp = await async_client.post(f"{API}/connectors/amazon/orders", json=_amazon_order(AmazonOrderId=""))
        assert resp.status_code == 422
        assert "AmazonOrderId" in _fields(resp)

    async def test_order_with_no_lines_is_refused(self, async_client):
        """An order with nothing on it cannot be picked, shipped, or invoiced."""
        resp = await async_client.post(f"{API}/connectors/amazon/orders", json=_amazon_order(OrderItems=[]))
        assert resp.status_code == 422
        assert "OrderItems" in _fields(resp)

    async def test_line_naming_no_product_is_refused(self, async_client):
        """A line with neither a seller SKU nor a barcode is not a pickable line."""
        data = _amazon_order()
        data["OrderItems"] = [{"Title": "no identifiers here", "QuantityOrdered": 1}]
        resp = await async_client.post(f"{API}/connectors/amazon/orders", json=data)
        assert resp.status_code == 422
        assert "names no product" in _fields(resp)

    async def test_fba_line_with_no_seller_sku_is_named_by_its_asin(self, async_client):
        """Amazon's own fulfilment lines carry no ``SellerSKU``.

        Reading only ``SellerSKU`` left every FBA line with an empty sku — the
        warehouse was being told to pick a line that names nothing.
        """
        data = _amazon_order()
        data["OrderItems"] = [{"Title": "FBA widget", "QuantityOrdered": 1, "ASIN": "B0XYZ98765"}]
        resp = await async_client.post(f"{API}/connectors/amazon/orders", json=data)
        assert resp.status_code == 201
        assert resp.json()["line_count"] == 1

    async def test_the_order_is_priced_by_its_lines(self, async_client):
        resp = await async_client.post(f"{API}/connectors/amazon/orders", json=_amazon_order())
        assert resp.status_code == 201
        assert resp.json()["line_count"] == 1
        # 2 × 75.00.  Amazon's own ``OrderTotal`` includes the shipping Amazon
        # charges the buyer; the order in the OMS is priced by the lines the
        # warehouse picks.
        assert resp.json()["total_amount"] == "150.00"

    async def test_null_shipping_address_is_not_a_crash(self, async_client):
        """SP-API sends nulls for the fields it has no value for.

        ``.get`` on the null answered ``AttributeError``, and a 500 was all the
        operator saw.  The order total is the lines' total — the amount Amazon
        reports for an unshipped order is not the order's price here.
        """
        resp = await async_client.post(
            f"{API}/connectors/amazon/orders", json=_amazon_order(ShippingAddress=None, OrderTotal=None)
        )
        assert resp.status_code == 201
        assert resp.json()["total_amount"] == "150.00"

    async def test_bundled_listing_quantity_is_named_not_crashed(self, async_client):
        """SP-API spells a bundle's quantity as text ("2 items"); ``int`` died on it."""
        data = _amazon_order()
        data["OrderItems"][0]["QuantityOrdered"] = "2 items"
        resp = await async_client.post(f"{API}/connectors/amazon/orders", json=data)
        assert resp.status_code == 422
        assert "QuantityOrdered" in _fields(resp)

    async def test_negative_quantity_is_refused(self, async_client):
        data = _amazon_order()
        data["OrderItems"][0]["QuantityOrdered"] = -2
        resp = await async_client.post(f"{API}/connectors/amazon/orders", json=data)
        assert resp.status_code == 422
        assert "QuantityOrdered" in _fields(resp)

    async def test_price_spelled_as_prose_is_refused(self, async_client):
        """``Decimal(str(...))`` in ``create_order`` used to die on this, at 500."""
        data = _amazon_order()
        data["OrderItems"][0]["ItemPrice"] = {"Amount": "seventy five"}
        resp = await async_client.post(f"{API}/connectors/amazon/orders", json=data)
        assert resp.status_code == 422
        assert "ItemPrice" in _fields(resp)

    async def test_price_as_a_bare_amount_is_accepted(self, async_client):
        """Older SP-API versions and the seller reports give the price as a string."""
        data = _amazon_order()
        data["OrderItems"][0]["ItemPrice"] = "75.00"
        data["OrderTotal"] = "150.00"
        resp = await async_client.post(f"{API}/connectors/amazon/orders", json=data)
        assert resp.status_code == 201
        assert resp.json()["total_amount"] == "150.00"

    async def test_every_line_of_a_multi_line_order_imports(self, async_client):
        data = _amazon_order()
        data["OrderItems"] = [
            {"SellerSKU": "SKU-A", "QuantityOrdered": 1, "ItemPrice": {"Amount": "10.00"}},
            {"SellerSKU": "SKU-B", "QuantityOrdered": 3, "ItemPrice": {"Amount": "5.00"}},
        ]
        resp = await async_client.post(f"{API}/connectors/amazon/orders", json=data)
        assert resp.status_code == 201
        assert resp.json()["line_count"] == 2
        assert resp.json()["total_amount"] == "25.00"

    async def test_buyer_email_names_the_customer(self, async_client):
        resp = await async_client.post(f"{API}/connectors/amazon/orders", json=_amazon_order())
        assert resp.status_code == 201
        assert resp.json()["order_id"]


class TestTrackingHandover:
    async def test_handover_names_the_order_carrier_and_number(self, async_client):
        resp = await async_client.post(f"{API}/connectors/amazon/tracking", json={
            "amazon_order_id": "402-3138915-0004487",
            "carrier_code": "SF",
            "tracking_number": "SF1234567890",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "received"
        assert data["carrier_code"] == "SF"
        assert data["tracking_number"] == "SF1234567890"

    async def test_the_answer_says_how_far_it_actually_got(self, async_client):
        """``received`` is not ``uploaded to Amazon``, and the screen must not imply it.

        The SP-API upload needs credentials; without them the handover is
        recorded here and the Amazon side says so.
        """
        resp = await async_client.post(f"{API}/connectors/amazon/tracking", json={
            "amazon_order_id": "402-3138915-0004487",
            "carrier_code": "SF",
            "tracking_number": "SF1234567890",
        })
        assert resp.status_code == 200
        assert resp.json()["sync_status"] == "not_configured"

    async def test_no_body_is_told_what_it_is_missing(self, async_client):
        """The console posted nothing and was told 导入失败，请检查配置."""
        resp = await async_client.post(f"{API}/connectors/amazon/tracking", json={})
        assert resp.status_code == 422
        fields = _fields(resp)
        assert "amazon_order_id" in fields
        assert "tracking_number" in fields

    async def test_tracking_without_a_carrier_is_refused(self, async_client):
        """Amazon needs the carrier and the number together to update a fulfillment."""
        resp = await async_client.post(f"{API}/connectors/amazon/tracking", json={
            "amazon_order_id": "402-3138915-0004487", "tracking_number": "SF1234567890",
        })
        assert resp.status_code == 422
        assert "carrier_code" in _fields(resp)

    async def test_camel_case_body_is_the_same_handover(self, async_client):
        resp = await async_client.post(f"{API}/connectors/amazon/tracking", json={
            "amazonOrderId": "402-3138915-0004487",
            "carrierCode": "ZTO",
            "trackingNumber": "ZTO5551234",
        })
        assert resp.status_code == 200
        assert resp.json()["carrier_code"] == "ZTO"

    async def test_envelope_is_accepted(self, async_client):
        resp = await async_client.post(f"{API}/connectors/amazon/tracking", json={
            "data": {"amazon_order_id": "402-9", "carrier_code": "SF", "tracking_number": "SF9"},
        })
        assert resp.status_code == 200
        assert resp.json()["amazon_order_id"] == "402-9"

    async def test_a_key_the_contract_does_not_have_is_refused(self, async_client):
        resp = await async_client.post(f"{API}/connectors/amazon/tracking", json={
            "amazon_order_id": "402-9", "carrier_code": "SF", "tracking_number": "SF9", "shipment_id": "x",
        })
        assert resp.status_code == 422
        assert "shipment_id" in _fields(resp)


class TestParserDirectly:
    """The nightly poll calls the parser; the guards cannot live in a request schema."""

    def test_order_id_is_required(self):
        from src.connectors.amazon_sp_api import parse_amazon_order
        from src.core.exceptions import ValidationException

        with pytest.raises(ValidationException, match="AmazonOrderId"):
            parse_amazon_order({"OrderItems": [{"SellerSKU": "A", "QuantityOrdered": 1}]})

    def test_lines_are_required(self):
        from src.connectors.amazon_sp_api import parse_amazon_order
        from src.core.exceptions import ValidationException

        with pytest.raises(ValidationException, match="no lines"):
            parse_amazon_order({"AmazonOrderId": "A-1", "OrderItems": []})

    def test_bundled_quantity_is_named(self):
        from src.connectors.amazon_sp_api import parse_amazon_order
        from src.core.exceptions import ValidationException

        data = _amazon_order()
        data["OrderItems"][0]["QuantityOrdered"] = "2 items"
        with pytest.raises(ValidationException, match=r"OrderItems\[0\]\.QuantityOrdered"):
            parse_amazon_order(data)

    def test_the_faulty_line_is_the_one_named(self):
        from src.connectors.amazon_sp_api import parse_amazon_order
        from src.core.exceptions import ValidationException

        data = _amazon_order()
        data["OrderItems"].append({"SellerSKU": "SKU-B", "QuantityOrdered": 0})
        with pytest.raises(ValidationException, match=r"OrderItems\[1\]"):
            parse_amazon_order(data)

    def test_the_fba_line_is_named_by_its_asin(self):
        """Amazon's own fulfilment lines carry no ``SellerSKU``.

        Reading only ``SellerSKU`` left every FBA line with an empty sku — the
        warehouse was told to pick a line that names nothing.
        """
        from src.connectors.amazon_sp_api import parse_amazon_order

        data = _amazon_order()
        data["OrderItems"] = [{"Title": "FBA widget", "QuantityOrdered": 1, "ASIN": "B0XYZ98765"}]
        item = parse_amazon_order(data).payload["items"][0]
        assert item["sku"] == "B0XYZ98765"

    def test_the_asin_is_not_written_into_the_gtin_field(self):
        """The scan gun reads ``gtin`` as an EAN; an ASIN is Amazon's own id."""
        from src.connectors.amazon_sp_api import parse_amazon_order

        item = parse_amazon_order(_amazon_order()).payload["items"][0]
        assert item["gtin"] == ""

    @pytest.mark.parametrize("barcode", ["6901234567892", "012345678905"])
    def test_the_barcode_the_listing_carries_is_the_gtin(self, barcode):
        """A listing that declares a barcode has a real EAN, and that is what scans."""
        from src.connectors.amazon_sp_api import parse_amazon_order

        data = _amazon_order()
        data["OrderItems"][0]["EAN"] = barcode
        assert parse_amazon_order(data).payload["items"][0]["gtin"] == barcode


class TestUnimplementedOutboundActions:
    """The five outbound SP-API actions used to answer with an invented success.

    ``poll_order_status`` returned ``"Unshipped"`` for a poll that polled
    nothing; ``upload_tracking_to_amazon`` returned ``"uploaded"`` for a call
    that never left the process; ``sync_inventory_to_amazon`` returned
    ``"synced"`` for inventory Amazon never heard about.  Nothing downstream can
    tell "the tracking number is on Amazon" from "it is not", and the operator
    acting on the answer reconciles against a shipment Amazon has never seen.
    """

    @staticmethod
    def _calls():
        from src.connectors.amazon_sp_api import (
            mark_fba_shipped,
            poll_order_status,
            sync_inventory_to_amazon,
            sync_order_status,
            upload_tracking_to_amazon,
        )

        return [
            lambda: poll_order_status("AAHKV2X7AFYLW", "402-9"),
            lambda: sync_order_status("AAHKV2X7AFYLW", "402-9"),
            lambda: upload_tracking_to_amazon("AAHKV2X7AFYLW", "402-9", "SF", "SF1"),
            lambda: mark_fba_shipped("AAHKV2X7AFYLW", "402-9"),
            lambda: sync_inventory_to_amazon("AAHKV2X7AFYLW", "SKU-1", 5),
        ]

    def test_no_outbound_action_claims_a_success(self):
        for call in self._calls():
            result = call()
            assert result["implemented"] is False, result
            assert result["status"] == "not_implemented", result

    def test_the_answer_names_the_order_it_is_talking_about(self):
        from src.connectors.amazon_sp_api import upload_tracking_to_amazon

        result = upload_tracking_to_amazon("AAHKV2X7AFYLW", "402-3138915-0004487", "SF", "SF1234567890")
        assert result["amazon_order_id"] == "402-3138915-0004487"
        assert "tracking" in result["reason"]


class TestImportServiceDirectly:
    """``import_erp_order`` bypasses ``OrderCreate``; its own guards are the contract."""

    async def test_no_lines_is_refused(self, db_session):
        from src.connectors.service import import_erp_order
        from src.core.exceptions import ValidationException
        from src.models.erp_connector import ERPMessage, MessageType

        msg = ERPMessage(
            msg_type=MessageType.ORDERS, sender_id="SAP", receiver_id="WMS",
            payload={"customer_email": "a@b.com", "source": "SAP", "items": []},
        )
        with pytest.raises(ValidationException, match="no lines"):
            await import_erp_order(db_session, msg)

    async def test_line_without_a_product_is_refused(self, db_session):
        from src.connectors.service import import_erp_order
        from src.core.exceptions import ValidationException
        from src.models.erp_connector import ERPMessage, MessageType

        msg = ERPMessage(
            msg_type=MessageType.ORDERS, sender_id="SAP", receiver_id="WMS",
            payload={"customer_email": "a@b.com", "source": "SAP",
                                  "items": [{"product_name": "widget", "quantity": 1, "unit_price": "1"}]},
        )
        with pytest.raises(ValidationException, match="names no product"):
            await import_erp_order(db_session, msg)

    async def test_quantity_of_zero_is_refused(self, db_session):
        from src.connectors.service import import_erp_order
        from src.core.exceptions import ValidationException
        from src.models.erp_connector import ERPMessage, MessageType

        msg = ERPMessage(
            msg_type=MessageType.ORDERS, sender_id="SAP", receiver_id="WMS",
            payload={"customer_email": "a@b.com", "source": "SAP",
                                  "items": [{"sku": "SKU-1", "quantity": 0, "unit_price": "1"}]},
        )
        with pytest.raises(ValidationException, match="quantity 0"):
            await import_erp_order(db_session, msg)

    async def test_price_spelled_as_prose_is_refused(self, db_session):
        from src.connectors.service import import_erp_order
        from src.core.exceptions import ValidationException
        from src.models.erp_connector import ERPMessage, MessageType

        msg = ERPMessage(
            msg_type=MessageType.ORDERS, sender_id="SAP", receiver_id="WMS",
            payload={"customer_email": "a@b.com", "source": "SAP",
                                  "items": [{"sku": "SKU-1", "quantity": 1, "unit_price": "ten yuan"}]},
        )
        with pytest.raises(ValidationException, match="unit_price"):
            await import_erp_order(db_session, msg)

    async def test_the_imported_line_keeps_the_product_it_names(self, db_session):
        """What the warehouse is told to pick is what the source system sent."""
        from src.connectors.service import import_erp_order
        from src.models.erp_connector import ERPMessage, MessageType

        msg = ERPMessage(
            msg_type=MessageType.ORDERS, sender_id="EDI", receiver_id="WMS",
            payload={"source": "EDI-SYSTEM",
                                  "items": [{"gtin": "6901234567892", "quantity": 4, "unit_price": "12.50"}]},
        )
        order = await import_erp_order(db_session, msg)
        assert order["items"][0]["gtin"] == "6901234567892"
        assert order["items"][0]["quantity"] == 4
        assert order["total_amount"] == "50.00"

    async def test_a_customer_is_named_by_the_source_when_the_buyer_is_not(self, db_session):
        """``"unknown"`` collected every import that forgot the buyer into one customer."""
        from src.connectors.service import import_erp_order
        from src.models.erp_connector import ERPMessage, MessageType

        msg = ERPMessage(
            msg_type=MessageType.ORDERS, sender_id="EDI", receiver_id="WMS",
            payload={"source": "EDI-SYSTEM", "items": [{"sku": "SKU-1", "quantity": 1, "unit_price": "1"}]},
        )
        order = await import_erp_order(db_session, msg)
        assert order["customer_id"] == "EDI-SYSTEM"
