"""Tests for TMS seed data module."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_seed_main_with_db():
    from src.tms.seed import main
    mock_db = AsyncMock()
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
    await main(db=mock_db)
    assert mock_db.add.call_count >= 10
    assert mock_db.commit.await_count >= 4


@pytest.mark.asyncio
async def test_seed_main_no_db():
    from src.tms.seed import main
    mock_session = AsyncMock()
    mock_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
    mock_factory = AsyncMock()
    mock_factory.__aenter__.return_value = mock_session
    with patch("src.tms.seed.async_session_factory", return_value=mock_factory):
        await main()
    assert mock_session.add.call_count >= 10
    assert mock_session.commit.await_count >= 4


@pytest.mark.asyncio
async def test_seed_hubs_skip_existing():
    from src.tms.models import TransferHub, TransferHubType
    from src.tms.seed import seed_hubs
    mock_db = AsyncMock()
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=TransferHub(
        id="existing", code="WUHAN_HUB", name="x", hub_type=TransferHubType.PRIMARY, city="x"
    ))
    await seed_hubs(mock_db)
    mock_db.add.assert_not_called()
