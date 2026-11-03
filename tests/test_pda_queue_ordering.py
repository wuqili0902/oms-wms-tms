"""The PDA mutation queue has to be ordered deterministically, and the tests that
read it have to start from a queue they own.

1. ``GET /pda/mutations`` pages with ``ORDER BY created_at DESC`` plus
   ``offset``/``limit``.  ``created_at`` is not unique — mutations written in the
   same batch carry the same timestamp — and SQLite then breaks the tie by rowid:
   measured on the unfixed query, five same-timestamp mutations came back oldest
   first, and the page contents shifted when the table churned.  A queue the PDA
   replays once per row needs a tiebreaker on a unique column.

2. ``_SharedSession`` opens ``connection.begin()`` then ``session.begin_nested()``,
   and a service reached through the API calls ``session.commit()``.  That commit
   bubbles past the savepoint into the outer transaction, so ``teardown()``'s
   rollback has nothing left to undo and the rows stay in the session-scoped
   database file.  ``tests/test_pda_service.py`` hit this as a
   ``data[0]["device_id"]`` mismatch against the previous test's row — a failure
   that appeared on some full runs and not others, because the row it tripped over
   was someone else's.  The fixture cannot clear tables at setup() (it wipes data
   that class-scoped seeding fixtures handed the test, and its DELETE deadlocks
   against those fixtures' connections — note at the end of this file), so each test
   that reads the queue deletes what it is about to read.
"""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete as sa_delete

from src.pda.models import PendingMutation, SyncOperation
from tests.conftest import _SharedSession

SAME_SECOND = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC).replace(tzinfo=None)


async def _clear_queue(session) -> None:
    """Start from an empty queue — same reason as tests/test_pda_service.py::_clear_queue.

    A commit made inside ``begin_nested()`` bubbles into the outer transaction, so
    the fixture's rollback cannot take a test's rows back; the queue is shared state
    for everything that reads it.
    """
    await session.execute(sa_delete(PendingMutation))
    await session.commit()


async def _seed_tied_rows(shared, count: int) -> list[int]:
    """Rows whose created_at is identical on purpose — the tie the ORDER BY must resolve."""
    ids = []
    for index in range(count):
        row = PendingMutation(
            device_id=f"pda-tie-{index}",
            entity_type="order",
            entity_id=f"tie-{index}",
            operation=SyncOperation.CREATE,
            payload="{}",
            created_at=SAME_SECOND,
        )
        shared.session.add(row)
        await shared.session.flush()
        ids.append(row.id)
    return ids


@pytest.mark.parametrize("page_size", [1, 2])
async def test_paging_a_tied_timestamp_neither_repeats_a_row_nor_drops_one(sqlite_engine, page_size):
    """Walking every page must return each mutation exactly once."""
    from src.core.database import get_db
    from src.core.dependencies import get_current_user
    from src.main import app

    shared = _SharedSession(sqlite_engine)
    await shared.setup()
    await _clear_queue(shared.session)
    ids = await _seed_tied_rows(shared, 5)

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[get_current_user] = lambda: {"sub": "ordering-test"}

    transport = ASGITransport(app=app)
    seen: list[int] = []
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for skip in range(0, len(ids), page_size):
            resp = await client.get(f"/pda/mutations?skip={skip}&limit={page_size}")
            assert resp.status_code == 200, resp.text
            seen += [row["id"] for row in resp.json()]

    app.dependency_overrides.clear()
    await shared.teardown()

    assert sorted(seen) == sorted(ids), f"pages of {page_size} lost or duplicated a mutation: {seen}"
    assert len(seen) == len(set(seen)) == len(ids), f"seen={seen}"


async def test_among_rows_sharing_a_timestamp_the_newest_comes_first(sqlite_engine):
    """``ORDER BY created_at DESC`` alone sorts a tie the wrong way round.

    Measured against the unfixed query, five mutations carrying the same
    ``created_at`` came back as ``[1, 2, 3, 4, 5]`` — SQLite broke the tie by rowid,
    so the *oldest* row of a same-batch group led the list, and the page contents
    moved when the table churned.  Only a unique column can make "newest first"
    mean anything.
    """
    from src.core.database import get_db
    from src.core.dependencies import get_current_user
    from src.main import app

    shared = _SharedSession(sqlite_engine)
    await shared.setup()
    await _clear_queue(shared.session)
    ids = await _seed_tied_rows(shared, 4)

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[get_current_user] = lambda: {"sub": "ordering-test"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/pda/mutations")

    app.dependency_overrides.clear()
    await shared.teardown()

    assert resp.status_code == 200, resp.text
    order = [row["id"] for row in resp.json()]
    assert order == sorted(ids, reverse=True), (
        f"rows sharing one created_at must come back newest-first (id DESC): got {order} for {ids}"
    )


# No test is pinned to the leak itself, and this says why.  A row written through
# _SharedSession and committed does survive teardown() — measured directly: setup(),
# add(), commit(), teardown(), and a fresh connection still counts it.  Reaching the
# same place through the API does not reproduce it once the test clears the queue
# first: that clearing commit leaves the fixture's outer transaction deassociated,
# and the row committed after it is dropped by teardown() instead of leaking (an
# xfail-stamped probe came back XPASS both ways it was written).  One direction is
# proven, neither is reproducible enough to pin, so what guards the queue here is the
# _clear_queue() each queue-reading test runs — not a test of the fixture.
#
# Clearing tables in _SharedSession.setup() is what the suite should want, and it is
# the change that was tried and rejected: class-scoped seeding fixtures instantiate
# before this fixture, so the wipe deletes data the test was handed (7
# tests/test_smoke.py cases answered 404), and the DELETE's write lock deadlocks
# against those fixtures' own connections (6 errors in
# tests/test_connectors/test_amazon_import_contract.py, "database is locked").
