"""Tests for src.core.models — AddressMaster and resolve_address."""

from unittest.mock import AsyncMock, MagicMock


class TestAddressMaster:
    def test_repr(self):
        from src.core.models import AddressMaster

        obj = AddressMaster(label="Home", city="Beijing")
        obj.id = "uuid-1"
        assert repr(obj) == "<AddressMaster Home: Beijing>"


class TestResolveAddress:
    async def test_with_entity_type_only(self):
        from src.core.models import resolve_address

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_a = MagicMock()
        mock_a.id = "id-1"
        mock_a.label = "Main"
        mock_a.address_type = "shipping"
        mock_a.contact_name = "Alice"
        mock_a.phone = "123"
        mock_a.email = "a@b.com"
        mock_a.address_line_1 = "123 St"
        mock_a.address_line_2 = "Apt 1"
        mock_a.city = "Beijing"
        mock_a.state = "BJ"
        mock_a.postal_code = "100000"
        mock_a.country = "China"
        mock_result.scalars.return_value.all.return_value = [mock_a]
        mock_db.execute.return_value = mock_result

        result = await resolve_address(mock_db, entity_type="customer")
        assert len(result) == 1
        assert result[0]["label"] == "Main"
        assert result[0]["city"] == "Beijing"

    async def test_with_entity_id_and_address_type(self):
        from src.core.models import resolve_address

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await resolve_address(
            mock_db, entity_type="order", entity_id="550e8400-e29b-41d4-a716-446655440000", address_type="billing"
        )
        assert result == []
