"""C10's dedup must not turn a legacy duplicate GTIN into a 500.

``record_scan()`` now looks for an existing row by GTIN instead of inserting a new
UUID per scan — the dedup the plan asked for.  But ``barcode_records.gtin`` is
indexed, **not unique** (src/barcode/models.py), so rows written before the dedup
existed can repeat a GTIN.  ``scalar_one_or_none()`` then raises
``MultipleResultsFound``, the scan endpoint has no handler for it, and
``POST /barcode/scan`` answers 500 for a barcode that scanned fine yesterday.

The dedup also has to be deterministic: with more than one legacy row, which row
gets the update cannot depend on whichever one the DB happened to return first.
"""

import uuid

from sqlalchemy import select

from src.barcode.models import BarcodeRecord
from src.barcode.service import record_scan

GTIN = "2350123456789"


async def _seed_scan_rows(db_session, *, gtin: str, entity_id: uuid.UUID | None, count: int) -> list[BarcodeRecord]:
    rows = []
    for _ in range(count):
        row = BarcodeRecord(
            id=uuid.uuid4(),
            gtin=gtin,
            entity_type="inventory",
            entity_id=entity_id,
            format="code128",
            raw_data=gtin,
        )
        db_session.add(row)
        rows.append(row)
    await db_session.flush()
    return rows


async def _scan(db_session, *, gtin: str, entity_id: uuid.UUID | None) -> dict:
    return await record_scan(
        db_session,
        {"raw_data": gtin, "entity_type": "inventory", "entity_id": str(entity_id) if entity_id else None},
    )


async def _rows_for(db_session, gtin: str) -> list[BarcodeRecord]:
    result = await db_session.execute(select(BarcodeRecord).where(BarcodeRecord.gtin == gtin))
    return list(result.scalars().all())


async def test_a_scan_survives_legacy_duplicate_rows(db_session):
    """Two pre-dedup rows with the same GTIN: the scan must answer, not raise."""
    entity_id = uuid.uuid4()
    await _seed_scan_rows(db_session, gtin=GTIN, entity_id=entity_id, count=2)

    result = await _scan(db_session, gtin=GTIN, entity_id=entity_id)

    assert isinstance(result, dict) and result["gtin"] == GTIN
    assert len(await _rows_for(db_session, GTIN)) == 2, "a scan must not add a third row"


async def test_a_scan_survives_legacy_duplicates_without_an_entity(db_session):
    """The entity_id-less lookup path has the same exposure."""
    await _seed_scan_rows(db_session, gtin=GTIN, entity_id=None, count=3)

    result = await _scan(db_session, gtin=GTIN, entity_id=None)

    assert result["gtin"] == GTIN
    assert len(await _rows_for(db_session, GTIN)) == 3


async def test_repeat_scan_updates_one_row_instead_of_adding_another(db_session):
    entity_id = uuid.uuid4()
    (original,) = await _seed_scan_rows(db_session, gtin=GTIN, entity_id=entity_id, count=1)

    result = await _scan(db_session, gtin=GTIN, entity_id=entity_id)

    rows = await _rows_for(db_session, GTIN)
    assert len(rows) == 1
    assert result["id"] == str(original.id), "the existing row should be the one that answers"


async def test_scan_of_an_unknown_gtin_creates_exactly_one_row(db_session):
    entity_id = uuid.uuid4()
    fresh = "9999000000014"

    result = await _scan(db_session, gtin=fresh, entity_id=entity_id)

    rows = await _rows_for(db_session, fresh)
    assert len(rows) == 1
    assert result["id"] == str(rows[0].id)


async def test_dedup_does_not_cross_entities(db_session):
    """Same GTIN on two different entities is not one scan."""
    entity_a = uuid.uuid4()
    entity_b = uuid.uuid4()
    await _seed_scan_rows(db_session, gtin=GTIN, entity_id=entity_a, count=1)

    await _scan(db_session, gtin=GTIN, entity_id=entity_b)

    rows = await _rows_for(db_session, GTIN)
    assert len(rows) == 2, "entity B's scan must not be folded into entity A's row"
    assert {row.entity_id for row in rows} == {entity_a, entity_b}
