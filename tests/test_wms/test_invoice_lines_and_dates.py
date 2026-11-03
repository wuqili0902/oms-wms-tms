"""Invoice and credit-memo lines and dates.

Three defects sit in this corner of the WMS API, all of them the same shape as
the purchase-order ones: the request schema quietly drops what the service
already knows how to store.

* ``InvoiceCreate`` had no ``lines``, so every invoice created through the API
  arrived with no lines and — because the total is the sum of the lines — a
  total of zero.  An invoice with the wrong total is a billing document that
  contradicts itself.
* ``issue_date`` / ``due_date`` were absent from the responses, so nothing
  downstream could tell an overdue invoice from a paid one.
* Both dates were typed ``str`` and parsed with ``datetime.fromisoformat``, so
  "next friday" came back as a 500 rather than a 422.
"""

import uuid as uuid_mod

import pytest

from src.core.exceptions import ValidationException
from src.wms import service


@pytest.fixture
async def auth_headers(async_client):
    uname = f"invuser_{uuid_mod.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _create_invoice(async_client, auth_headers, **over):
    body = {"invoice_number": over.pop("invoice_number", "INV-LD-1"), "entity_type": "customer", **over}
    resp = await async_client.post("/api/v1/warehouses/invoices", json=body, headers=auth_headers)
    return resp


async def _create_credit_memo(async_client, auth_headers, **over):
    body = {
        "credit_memo_number": over.pop("credit_memo_number", "CM-LD-1"),
        "entity_type": "customer",
        **over,
    }
    resp = await async_client.post("/api/v1/warehouses/credit-memos", json=body, headers=auth_headers)
    return resp


class TestInvoiceLines:
    async def test_lines_survive_the_request(self, async_client, auth_headers):
        resp = await _create_invoice(
            async_client,
            auth_headers,
            invoice_number="INV-LINES-1",
            lines=[
                {"description": "Storage, October", "quantity": "2", "unit_price": "3.50"},
                {"description": "Pick & pack", "quantity": "1", "unit_price": "5.00"},
            ],
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert len(data["lines"]) == 2, (
            "InvoiceCreate dropped the lines: the invoice was filed with nothing on it"
        )
        # 2 × 3.50 + 1 × 5.00 — the total the customer is actually billed.
        assert data["total_amount"] == pytest.approx(12.0), data["total_amount"]

    async def test_the_total_is_the_lines_not_a_zero(self, async_client, auth_headers):
        """An invoice whose total is zero while it carries lines is a document
        that contradicts itself, so the total has to be derived here."""
        resp = await _create_invoice(
            async_client,
            auth_headers,
            invoice_number="INV-TOTAL-1",
            lines=[{"description": "Freight", "quantity": "3", "unit_price": "10.00"}],
        )
        assert resp.json()["total_amount"] == pytest.approx(30.0)

    async def test_lines_are_visible_on_get_and_on_list(self, async_client, auth_headers):
        created = (await _create_invoice(
            async_client,
            auth_headers,
            invoice_number="INV-GET-LINES",
            lines=[{"description": "Packing film", "quantity": "4", "unit_price": "2.00"}],
        )).json()
        inv_id = created["id"]

        one = await async_client.get(f"/api/v1/warehouses/invoices/{inv_id}", headers=auth_headers)
        assert [ln["description"] for ln in one.json()["lines"]] == ["Packing film"]

        many = await async_client.get("/api/v1/warehouses/invoices", headers=auth_headers)
        row = next(i for i in many.json() if i["id"] == inv_id)
        assert row["total_amount"] == pytest.approx(8.0), "the list view hid the invoice's amount"


class TestInvoiceDates:
    async def test_dates_are_returned(self, async_client, auth_headers):
        data = (await _create_invoice(
            async_client,
            auth_headers,
            invoice_number="INV-DATES-1",
            issue_date="2026-11-01",
            due_date="2026-11-15",
        )).json()
        assert data["issue_date"] == "2026-11-01", "an invoice with no issue date cannot be aged"
        assert data["due_date"] == "2026-11-15", "an invoice with no due date cannot be chased"

    async def test_a_missing_date_stays_missing(self, async_client, auth_headers):
        data = (await _create_invoice(
            async_client, auth_headers, invoice_number="INV-NODATE"
        )).json()
        assert data["issue_date"] is None
        assert data["due_date"] is None

    async def test_an_unparseable_date_is_rejected_not_a_500(self, async_client, auth_headers):
        """'next friday' is a human way of writing a date; a 500 is not an
        answer to it, and it is the answer the API used to give."""
        resp = await _create_invoice(
            async_client, auth_headers, invoice_number="INV-BADDATE", issue_date="next friday"
        )
        assert resp.status_code == 422, resp.text

    async def test_the_service_layer_rejects_a_bad_date_too(self, db_session):
        """The service is called directly (tasks, scripts) as well as through
        the router, so the guard cannot live only in the schema."""
        with pytest.raises(ValidationException) as exc:
            await service.create_invoice(db_session, {
                "invoice_number": "INV-SVC-BADDATE",
                "entity_type": "customer",
                "due_date": "tomorrow",
            })
        assert "due_date" in str(exc.value.message)

    async def test_a_service_caller_may_still_pass_an_iso_string(self, db_session):
        inv = await service.create_invoice(db_session, {
            "invoice_number": "INV-SVC-DATE",
            "entity_type": "customer",
            "issue_date": "2026-11-02",
        })
        assert str(inv["issue_date"]) == "2026-11-02"


class TestCreditMemoLinesAndDates:
    async def test_lines_and_issue_date_are_returned(self, async_client, auth_headers):
        data = (await _create_credit_memo(
            async_client,
            auth_headers,
            credit_memo_number="CM-LINES-1",
            issue_date="2026-11-03",
            reason="Damaged on arrival",
            lines=[
                {"description": "Returned carton", "quantity": "1", "unit_price": "12.00"},
                {"description": "Returned pallet", "quantity": "2", "unit_price": "4.00"},
            ],
        )).json()
        assert data["issue_date"] == "2026-11-03"
        assert len(data["lines"]) == 2, "CreditMemoCreate dropped the lines"
        assert data["total_amount"] == pytest.approx(20.0)

    async def test_a_credit_memo_can_point_at_the_it_corrects(self, async_client, auth_headers):
        invoice = (await _create_invoice(
            async_client,
            auth_headers,
            invoice_number="INV-CORRECTED",
            lines=[{"description": "Goods", "quantity": "2", "unit_price": "10.00"}],
        )).json()
        memo = (await _create_credit_memo(
            async_client,
            auth_headers,
            credit_memo_number="CM-AGAINST-1",
            invoice_id=invoice["id"],
            reason="Short shipment",
            lines=[{"description": "One carton not delivered", "quantity": "1", "unit_price": "10.00"}],
        )).json()
        assert memo["invoice_id"] == invoice["id"], (
            "a credit memo that does not name the invoice it corrects is just a second document"
        )


class TestNotFoundKeepsItsCode:
    async def test_a_missing_invoice_is_not_reported_as_a_generic_http_error(
        self, async_client, auth_headers
    ):
        resp = await async_client.get(
            f"/api/v1/warehouses/invoices/{uuid_mod.uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND", (
            "re-raising the service's NotFoundException as HTTPException relabelled "
            "a missing invoice 'HTTP_ERROR', which a client cannot branch on"
        )

    async def test_a_missing_credit_memo_is_not_reported_as_a_generic_http_error(
        self, async_client, auth_headers
    ):
        resp = await async_client.get(
            f"/api/v1/warehouses/credit-memos/{uuid_mod.uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"
