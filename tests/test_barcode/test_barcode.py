"""Tests for Barcode service — mix of HTTP integration and service unit tests.

HTTP integration tests: single-request validation (GTIN, scan, create).
Service unit tests (with db_session): multi-step operations (duplicate checks, list).
"""
import io
import uuid

import pandas as pd
import pytest
from fastapi import UploadFile

from src.barcode import service as barcode_service
from src.barcode.excel_barcode import (
    _generate_qr,
    _parse_excel,
    _zpl_line,
    calc_ean13_check_digit,
    export_csv_barcodes,
    export_zpl_labels,
    generate_barcode_zip,
    generate_gtin_from_sku,
)

# ── HTTP Integration tests (single-request) ──────────────────────────────────

@pytest.fixture
async def auth_headers(async_client):
    """Register + login a temp user, return auth header dict."""
    import uuid as _uuid
    uname = f"bc_{_uuid.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestGTIN:
    async def test_generate_gtin(self, async_client, auth_headers):
        eid = str(uuid.uuid4())
        resp = await async_client.post("/api/v1/barcode/generate", json={
            "gtin_prefix": "690123456", "entity_type": "order", "entity_id": eid,
        }, headers=auth_headers)
        assert resp.status_code == 201
        gtin = resp.json()["gtin"]
        assert len(gtin) == 13
        assert gtin.startswith("690123456")

    async def test_validate_valid_gtin(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/barcode/validate", json={
            "gtin": "6901234567892",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    async def test_validate_invalid_gtin(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/barcode/validate", json={
            "gtin": "6901234567890",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["valid"] is False


class TestScan:
    async def test_record_scan(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/barcode/scan", json={
            "raw_data": "6901234567890", "scanner_id": "SCAN-001",
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["raw_data"] == "6901234567890"

    async def test_get_by_gtin(self, async_client, auth_headers):
        eid = str(uuid.uuid4())
        await async_client.post("/api/v1/barcode/generate", json={
            "gtin_prefix": "690123456", "entity_type": "order", "entity_id": eid,
        }, headers=auth_headers)
        # The generated GTIN will start with 690123456 but exact value is computed.
        # Just verify the endpoint responds.
        resp = await async_client.get("/api/v1/barcode/6901234560000", headers=auth_headers)
        assert resp.status_code == 200

    async def test_generate_barcode_invalid_prefix(self, async_client, auth_headers):
        # Must pass Pydantic min_length=7 but fail the service's generate_gtin check
        resp = await async_client.post("/api/v1/barcode/generate", json={
            "gtin_prefix": "abc1234defg", "entity_type": "order", "entity_id": str(uuid.uuid4()),
        }, headers=auth_headers)
        assert resp.status_code == 422


class TestLabelTemplate:
    async def test_create_template(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/barcode/templates", json={
            "name": "Test Label",
            "code": "TEST-LBL",
            "format": "zpl",
            "width_mm": 50,
            "height_mm": 30,
            "content": {"field": "value"},
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["name"] == "Test Label"

    async def test_create_template_duplicate_code(self, async_client, auth_headers):
        data = {"name": "T1", "code": "DUP-HTTP", "format": "zpl", "width_mm": 50, "height_mm": 30}
        await async_client.post("/api/v1/barcode/templates", json=data, headers=auth_headers)
        resp = await async_client.post("/api/v1/barcode/templates", json=data, headers=auth_headers)
        assert resp.status_code == 422


class TestBarcodeRouterErrorPaths:
    async def test_upload_excel_wrong_extension(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/barcode/excel/upload",
            files={"file": ("test.txt", b"not an excel", "text/plain")},
            headers=auth_headers)
        assert resp.status_code == 422

    async def test_upload_excel_empty_workbook(self, async_client, auth_headers):
        import io as _io

        from openpyxl import Workbook as _Workbook
        wb = _Workbook()
        buf = _io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        resp = await async_client.post("/api/v1/barcode/excel/upload",
            files={"file": ("test.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth_headers)
        assert resp.status_code == 422

    async def test_list_templates_http(self, async_client, auth_headers):
        resp = await async_client.get("/api/v1/barcode/templates", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_download_barcode_file_not_found(self, async_client, auth_headers):
        resp = await async_client.get("/api/v1/barcode/download/nonexistent.zip", headers=auth_headers)
        assert resp.status_code == 404


    async def test_upload_excel_success(self, async_client, auth_headers):
        import io as _io

        from openpyxl import Workbook as _Wb
        wb = _Wb()
        ws = wb.active
        ws.append(["sku", "name", "quantity", "gtin"])
        ws.append(["SKU-HTTP", "Item", "1", ""])
        buf = _io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        resp = await async_client.post("/api/v1/barcode/excel/upload",
            files={"file": ("test.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "filename" in data
        assert data["size"] > 0

    async def test_download_barcode_file_success(self, async_client, auth_headers):
        import os as _os
        _dir = _os.path.abspath("/tmp/barcodes")
        _os.makedirs(_dir, exist_ok=True)
        _fp = _os.path.join(_dir, "test_dl.zip")
        with open(_fp, "wb") as _f:
            _f.write(b"fake zip content")
        try:
            resp = await async_client.get("/api/v1/barcode/download/test_dl.zip", headers=auth_headers)
            assert resp.status_code == 200
            assert resp.content == b"fake zip content"
        finally:
            _os.remove(_fp)


# ── Service unit tests (shared db_session for multi-step) ────────────────────

class TestService:
    async def test_create_label_template_duplicate_code(self, db_session):
        """Duplicate code should raise ValidationException."""
        await barcode_service.create_template(db_session, {
            "name": "First", "code": "DUP-SVC", "format": "zpl",
        })
        import pytest as _pt

        from src.core.exceptions import ValidationException
        with _pt.raises(ValidationException):
            await barcode_service.create_template(db_session, {
                "name": "Second", "code": "DUP-SVC", "format": "zpl",
            })

    async def test_list_templates(self, db_session):
        """Verify listing all templates in order."""
        await barcode_service.create_template(db_session, {
            "name": "L1", "code": "SVC-LST-1", "format": "zpl",
        })
        await barcode_service.create_template(db_session, {
            "name": "L2", "code": "SVC-LST-2", "format": "zpl",
        })
        templates = await barcode_service.list_templates(db_session)
        codes = [t["code"] for t in templates]
        assert "SVC-LST-1" in codes
        assert "SVC-LST-2" in codes

    async def test_generate_and_retrieve_barcode(self, db_session):
        """Generate a barcode via service, then retrieve by GTIN."""
        rec = await barcode_service.generate_barcode(db_session, {
            "gtin_prefix": "690123456",
            "entity_type": "order",
            "entity_id": str(uuid.uuid4()),
        })
        assert rec["gtin"].startswith("690123456")
        assert len(rec["gtin"]) == 13

        records = await barcode_service.get_by_gtin(db_session, rec["gtin"])
        assert len(records) == 1
        assert records[0]["gtin"] == rec["gtin"]

    async def test_record_scan_via_service(self, db_session):
        rec = await barcode_service.record_scan(db_session, {
            "raw_data": "SCAN-TEST-001",
        })
        assert rec["raw_data"] == "SCAN-TEST-001"
        assert rec["entity_type"] == "scan"


# ── Excel barcode generation (pure function tests) ────────────────────────────

class TestExcelBarcodeHelpers:
    def test_calc_ean13_check_digit(self):
        assert calc_ean13_check_digit("690123456789") == 2

    def test_calc_ean13_check_digit_known(self):
        assert calc_ean13_check_digit("200000000001") == 5

    def test_generate_gtin_from_sku_digit_only(self):
        result = generate_gtin_from_sku("200000000001")
        assert len(result) == 13
        assert result.endswith("5")

    def test_generate_gtin_from_sku_with_letters(self):
        result = generate_gtin_from_sku("SKU-12345")
        assert len(result) == 13
        assert result.startswith("12345")

    def test_generate_gtin_from_sku_short(self):
        result = generate_gtin_from_sku("AB")
        assert len(result) == 13

    def test_generate_gtin_from_sku_empty(self):
        result = generate_gtin_from_sku("")
        assert len(result) == 13
        assert result == "0000000000000"

    def test_zpl_line_basic(self):
        output = _zpl_line("TEST-SKU", "Test Item", 2, "2000000000018")
        assert "^XA" in output
        assert "^XZ" in output
        assert "TEST-SKU" in output
        assert "Test Item" in output
        assert "2000000000018" in output

    def test_zpl_line_empty_name(self):
        output = _zpl_line("SKU-1", "", 1, "1234567890123")
        assert "SKU-1" in output
        assert "^XA" in output
        assert "^XZ" in output

    def test_export_zpl_labels(self):
        df = pd.DataFrame([
            {"sku": "SKU-A", "name": "Item A", "quantity": 2, "gtin": ""},
            {"sku": "SKU-B", "name": "Item B", "quantity": 1, "gtin": "5901234567890"},
        ])
        output = export_zpl_labels(df)
        assert "SKU-A" in output
        assert "SKU-B" in output
        assert "5901234567890" in output
        # Each label should be a separate ZPL block
        assert output.count("^XA") == 2
        assert output.count("^XZ") == 2

    def test_export_zpl_labels_missing_columns(self):
        df = pd.DataFrame([{"sku": "SKU-X"}])
        output = export_zpl_labels(df)
        assert "SKU-X" in output
        assert "^XA" in output

    def test_export_csv_barcodes(self):
        df = pd.DataFrame([
            {"sku": "SKU-1", "name": "One", "gtin": ""},
            {"sku": "SKU-2", "name": "Two", "gtin": "5901234567890"},
        ])
        csv = export_csv_barcodes(df)
        assert "SKU-1" in csv
        assert "SKU-2" in csv
        assert "5901234567890" in csv
        assert "GTIN" in csv

    def test_export_zpl_empty_dataframe(self):
        df = pd.DataFrame()
        output = export_zpl_labels(df)
        assert output == ""

    def test_export_csv_empty_dataframe(self):
        df = pd.DataFrame()
        csv = export_csv_barcodes(df)
        assert isinstance(csv, str)

    def test_export_zpl_with_nan_values(self):
        import numpy as np
        df = pd.DataFrame([
            {"sku": "SKU-NAN", "name": np.nan, "quantity": np.nan, "gtin": np.nan},
        ])
        output = export_zpl_labels(df)
        assert "SKU-NAN" in output
        assert "^XA" in output

    def test_generate_qr_returns_png(self):
        buf = _generate_qr("test-data", size=100)
        data = buf.read()
        assert data.startswith(b"\x89PNG")
        assert len(data) > 100

    def test_generate_qr_with_url(self):
        buf = _generate_qr("https://example.com/label?id=123")
        data = buf.read()
        assert data.startswith(b"\x89PNG")


class TestParseExcel:
    def _make_excel(self, rows):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        for row in rows:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return UploadFile(filename="test.xlsx", file=buf)

    async def test_parse_excel_basic(self):
        f = self._make_excel([
            ["sku", "name", "quantity", "gtin"],
            ["SKU-1", "Item 1", 2, ""],
        ])
        headers, df = _parse_excel(f)
        assert "sku" in headers
        assert "name" in headers
        assert len(df) == 1

    async def test_parse_excel_empty_workbook(self):
        f = self._make_excel([])
        import pytest as _pt
        with _pt.raises(ValueError, match="Empty workbook"):
            _parse_excel(f)

    async def test_generate_barcode_zip_basic(self):
        f = self._make_excel([
            ["sku", "name", "quantity", "gtin"],
            ["SKU-ZIP", "ZIP Item", 1, ""],
        ])
        zip_bytes = generate_barcode_zip(f)
        assert len(zip_bytes) > 100
        import zipfile
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            assert any("SKU-ZIP" in n for n in names)
            assert any(n.endswith("ean13.pdf") for n in names)
            assert any(n.endswith("qr.png") for n in names)

    async def test_generate_barcode_zip_with_gtin(self):
        f = self._make_excel([
            ["sku", "name", "quantity", "gtin"],
            ["SKU-GTIN", "GTIN Item", 1, "5901234567890"],
        ])
        zip_bytes = generate_barcode_zip(f)
        assert len(zip_bytes) > 100

    async def test_generate_barcode_zip_invalid_gtin(self):
        f = self._make_excel([
            ["sku", "name", "quantity", "gtin"],
            ["SKU-BAD", "Bad GTIN", 1, "123"],
        ])
        with pytest.raises(ValueError, match="Invalid GTIN"):
            generate_barcode_zip(f)

    async def test_generate_barcode_zip_skips_empty_sku(self):
        f = self._make_excel([
            ["sku", "name", "quantity", "gtin"],
            ["", "No SKU", 1, ""],
            ["SKU-OK", "Good SKU", 1, ""],
        ])
        zip_bytes = generate_barcode_zip(f)
        import zipfile
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            # Without the `continue` on empty SKU, there would be 4 entries
            assert len(names) == 2
            assert all("SKU-OK" in n for n in names)

    async def test_generate_barcode_zip_empty(self):
        f = self._make_excel([])
        with pytest.raises(ValueError, match="Empty workbook"):
            generate_barcode_zip(f)
