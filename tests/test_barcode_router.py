from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.main import app

API = "/api/v1/barcode"


@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_user():
    return {"uid": "u1", "sub": "admin"}


@pytest.fixture
def override_deps(mock_db, mock_user):
    async def _get_db():
        return mock_db

    async def _get_current_user():
        return mock_user

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_current_user
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(override_deps):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def make_record(**kw):
    return {
        "id": kw.get("id", "rec-1"),
        "gtin": kw.get("gtin", "1234567890123"),
        "entity_type": kw.get("entity_type", "order"),
        "entity_id": kw.get("entity_id", "e1"),
        "format": kw.get("format", "ean13"),
        "raw_data": kw.get("raw_data", "raw"),
        "created_at": kw.get("created_at", "2026-01-01T00:00:00"),
    }


class TestGenerateBarcode:
    async def test_generates_barcode(self, client):
        with patch("src.barcode.router.barcode_service.generate_barcode", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = make_record()
            resp = await client.post(f"{API}/generate", json={
                "gtin_prefix": "12345678901", "entity_type": "order",
                "entity_id": "e1", "format": "ean13",
            })
        assert resp.status_code == 201
        assert resp.json()["gtin"] == "1234567890123"

    async def test_validation_error(self, client):
        from src.core.exceptions import ValidationException
        with patch("src.barcode.router.barcode_service.generate_barcode", new_callable=AsyncMock) as mock_gen:
            mock_gen.side_effect = ValidationException("Invalid GTIN")
            resp = await client.post(f"{API}/generate", json={
                "gtin_prefix": "12345678901", "entity_type": "order",
                "entity_id": "e1", "format": "ean13",
            })
        assert resp.status_code == 422


class TestValidateBarcode:
    async def test_validates_gtin(self, client):
        with patch("src.barcode.router.barcode_service.validate_gtin") as mock_val:
            mock_val.return_value = {"valid": True, "format": "ean13"}
            resp = await client.post(f"{API}/validate", json={"gtin": "1234567890123"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True


class TestScanBarcode:
    async def test_records_scan(self, client):
        with patch("src.barcode.router.barcode_service.record_scan", new_callable=AsyncMock) as mock_scan:
            mock_scan.return_value = make_record()
            resp = await client.post(f"{API}/scan", json={
                "raw_data": "1234567890123",
            })
        assert resp.status_code == 201
        assert resp.json()["gtin"] == "1234567890123"


class TestExcelUpload:
    async def test_rejects_non_xlsx(self, client):
        resp = await client.post(f"{API}/excel/upload", files={"file": ("test.txt", b"data", "text/plain")})
        assert resp.status_code == 422

    async def test_accepts_xlsx(self, client):
        with patch("src.barcode.router.generate_barcode_zip") as mock_zip:
            mock_zip.return_value = b"zipdata"
            resp = await client.post(
                f"{API}/excel/upload",
                files={
                    "file": (
                        "test.xlsx",
                        b"data",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "filename" in data
        assert data["size"] == len(b"zipdata")

    async def test_handles_exception(self, client):
        with patch("src.barcode.router.generate_barcode_zip", side_effect=Exception("bad file")):
            resp = await client.post(
                f"{API}/excel/upload",
                files={
                    "file": (
                        "test.xlsx",
                        b"data",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
        assert resp.status_code == 422


class TestDownload:
    async def test_file_not_found(self, client):
        resp = await client.get(f"{API}/download/nonexistent.zip")
        assert resp.status_code == 404

    @patch("builtins.open", new_callable=MagicMock)
    async def test_downloads_file(self, mock_open, client):
        mock_open.return_value.__enter__.return_value.read.return_value = b"zipdata"
        resp = await client.get(f"{API}/download/test.zip")
        assert resp.status_code == 200


class TestTemplates:
    async def test_creates_template(self, client):
        with patch("src.barcode.router.barcode_service.create_template", new_callable=AsyncMock) as mock_ct:
            mock_ct.return_value = {
                "id": "tpl-1", "name": "Label", "code": "LBL",
                "format": "zpl", "width_mm": 100, "height_mm": 50,
                "content": {}, "is_default": False, "created_at": "2026-01-01T00:00:00",
            }
            resp = await client.post(f"{API}/templates", json={
                "name": "Label", "code": "LBL",
                "format": "zpl", "width_mm": 100, "height_mm": 50, "content": {},
            })
        assert resp.status_code == 201
        assert resp.json()["name"] == "Label"

    async def test_template_validation_error(self, client):
        from src.core.exceptions import ValidationException
        with patch("src.barcode.router.barcode_service.create_template", new_callable=AsyncMock) as mock_ct:
            mock_ct.side_effect = ValidationException("bad")
            resp = await client.post(f"{API}/templates", json={
                "name": "Bad", "code": "BAD",
                "format": "zpl", "width_mm": 100, "height_mm": 50, "content": {},
            })
        assert resp.status_code == 422

    async def test_lists_templates(self, client):
        with patch("src.barcode.router.barcode_service.list_templates", new_callable=AsyncMock) as mock_lt:
            mock_lt.return_value = [
                {
                    "id": "tpl-1",
                    "name": "L1",
                    "code": "L1",
                    "format": "zpl",
                    "width_mm": 100,
                    "height_mm": 50,
                    "content": {},
                    "is_default": False,
                    "created_at": "2026-01-01T00:00:00",
                }
            ]
            resp = await client.get(f"{API}/templates")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestGetByGtin:
    async def test_returns_records(self, client):
        with patch("src.barcode.router.barcode_service.get_by_gtin", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [make_record()]
            resp = await client.get(f"{API}/1234567890123")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["gtin"] == "1234567890123"
