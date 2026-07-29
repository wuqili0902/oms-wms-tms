from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.barcode import service as barcode_service
from src.core.exceptions import ValidationException


class TestCalcCheckDigit:
    def test_even_position(self):
        assert barcode_service._calc_check_digit("000000000000") == 0

    def test_known_check_digit(self):
        assert barcode_service._calc_check_digit("123456789012") == 8

    def test_all_nines(self):
        result = barcode_service._calc_check_digit("999999999999")
        assert 0 <= result <= 9


class TestGenerateGtin:
    def test_generates_valid_gtin(self):
        result = barcode_service.generate_gtin("12345678901")
        assert len(result) == 13
        assert result.isdigit()

    def test_short_prefix_raises(self):
        with pytest.raises(ValidationException):
            barcode_service.generate_gtin("123")

    def test_long_prefix_raises(self):
        with pytest.raises(ValidationException):
            barcode_service.generate_gtin("1" * 13)

    def test_strips_nondigits(self):
        result = barcode_service.generate_gtin("ABC-1234567")
        assert result[:7] == "1234567"
        assert len(result) == 13

    def test_minimum_prefix_ok(self):
        result = barcode_service.generate_gtin("1234567")
        assert len(result) == 13

    def test_check_digit_valid(self):
        result = barcode_service.generate_gtin("12345678901")
        prefix = result[:12]
        check = barcode_service._calc_check_digit(prefix)
        assert int(result[12]) == check


class TestValidateGtin:
    def test_valid_ean13(self):
        gtin = barcode_service.generate_gtin("12345678901")
        result = barcode_service.validate_gtin(gtin)
        assert result["valid"] is True
        assert result["format"] == "ean13"

    def test_invalid_length(self):
        result = barcode_service.validate_gtin("123")
        assert result["valid"] is False
        assert "length" in result["reason"]

    def test_check_digit_mismatch(self):
        result = barcode_service.validate_gtin("1234567890129")
        assert result["valid"] is False
        assert "Check digit" in result["reason"]

    def test_strips_nondigits(self):
        result = barcode_service.validate_gtin("GTIN-12345678")
        assert result["valid"] is True
        assert result["format"] == "other"

    def test_short_valid_formats(self):
        result = barcode_service.validate_gtin("12345678")
        assert result["valid"] is True
        assert result["format"] == "other"


class TestGenerateBarcode:
    async def test_creates_record(self):
        mock_db = AsyncMock(spec=AsyncSession)
        with (
            patch("src.barcode.service.model_to_dict", return_value={"id": "r1"}),
            patch("src.barcode.service.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = "2026-01-01"
            result = await barcode_service.generate_barcode(mock_db, {
                "gtin_prefix": "12345678901",
                "entity_type": "order",
                "entity_id": "00000000-0000-0000-0000-000000000001",
                "format": "ean13",
            })
        assert result == {"id": "r1"}
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()


class TestRecordScan:
    async def test_records_scan(self):
        mock_db = AsyncMock(spec=AsyncSession)
        with patch("src.barcode.service.model_to_dict", return_value={"id": "s1"}):
            result = await barcode_service.record_scan(mock_db, {"raw_data": "1234567890123"})
        assert result == {"id": "s1"}
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()


class TestGetByGtin:
    async def test_returns_records(self):
        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [MagicMock()]
        mock_db.execute.return_value = mock_result
        with patch("src.barcode.service.model_to_dict", return_value={"gtin": "1234567890123"}):
            result = await barcode_service.get_by_gtin(mock_db, "1234567890123")
        assert result == [{"gtin": "1234567890123"}]

    async def test_empty(self):
        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        result = await barcode_service.get_by_gtin(mock_db, "0000000000000")
        assert result == []


class TestCreateTemplate:
    async def test_creates_template(self):
        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        with (
            patch("src.barcode.service.model_to_dict", return_value={"id": "tpl-1", "code": "LBL"}),
            patch("src.barcode.service.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = "2026-01-01"
            result = await barcode_service.create_template(mock_db, {
                "name": "Label", "code": "LBL",
                "format": "zpl", "width_mm": 100, "height_mm": 50,
            })
        assert result["code"] == "LBL"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()

    async def test_raises_on_duplicate_code(self):
        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()
        mock_db.execute.return_value = mock_result
        with pytest.raises(ValidationException, match="already exists"):
            await barcode_service.create_template(mock_db, {"name": "L", "code": "DUP"})

    async def test_list_empty(self):
        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        result = await barcode_service.list_templates(mock_db)
        assert result == []

    async def test_list_returns_templates(self):
        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [MagicMock()]
        mock_db.execute.return_value = mock_result
        with patch("src.barcode.service.model_to_dict", return_value={"code": "T1"}):
            result = await barcode_service.list_templates(mock_db)
        assert result == [{"code": "T1"}]
