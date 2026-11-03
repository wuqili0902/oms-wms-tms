"""Wiring checks for the Celery periodic tasks.

The earlier version of this file tested nothing: both of its tests were skipped
with "Requires PostgreSQL (async_session_factory)", so the module loaded and no
behaviour was checked — which is how ``release_locked_inventory`` was able to
inflate on-hand stock on a daily schedule for as long as it existed.  The
behaviour the skip was standing in for now lives in
tests/test_tasks_inventory_release.py, which drives the release against the test
database.

What genuinely cannot run in a test process is the broker round-trip.  What *can*
be checked — and was not — is the spelling agreement between the beat schedule
and the task decorators.  A mismatch there fails silently in the loudest way:
beat starts, logs the schedule, sends a task name nobody registered, and the
work simply never happens.
"""

import pytest

import src.celeryconf  # noqa: F401  — applying app.conf.beat_schedule is its whole job
from src.celery_app import celery


def _beat_task_names() -> list[str]:
    schedule = celery.conf.beat_schedule
    assert schedule, "src.celeryconf did not apply a beat schedule"
    return [entry["task"] for entry in schedule.values()]


class TestBeatScheduleWiring:
    def test_beat_schedule_is_loaded(self):
        assert celery.conf.beat_schedule is not None, (
            "celery beat only schedules what conf.beat_schedule holds; src.celeryconf "
            "sets it, and the deployment commands (-A src.celeryconf) depend on that import"
        )

    def test_every_scheduled_task_is_registered(self):
        """A scheduled task name with no task behind it is dropped in silence."""
        registered = set(celery.tasks)
        missing = sorted(name for name in _beat_task_names() if name not in registered)
        assert not missing, (
            f"beat schedules {missing} but no worker will find them: "
            "rename the schedule entry or import the task module in src.celery_app"
        )

    def test_inventory_tasks_are_all_registered_by_their_declared_names(self):
        from src.tasks.inventory import (  # noqa: F401  — the decorators do the registering
            cancel_expired_orders,
            check_low_stock_alerts,
            process_pending_orders,
            release_locked_inventory_for_cancelled_orders,
            snapshot_inventory,
            sync_inventory,
        )

        for task in (
            sync_inventory,
            snapshot_inventory,
            check_low_stock_alerts,
            release_locked_inventory_for_cancelled_orders,
            cancel_expired_orders,
            process_pending_orders,
        ):
            assert task.name in celery.tasks, f"{task.name} is not registered"

    def test_release_task_name_matches_its_beat_entry(self):
        """The daily release is only daily because these two strings agree."""
        entries = {
            key: entry["task"] for key, entry in celery.conf.beat_schedule.items()
            if "inventory" in entry["task"]
        }
        assert "release-locked-inventory-daily" in entries
        assert entries["release-locked-inventory-daily"] == "tasks.inventory.release_locked"

    @pytest.mark.parametrize("name", [
        "tasks.inventory.check_low_stock",
        "tasks.inventory.release_locked",
    ])
    def test_inventory_schedule_entries_point_at_inventory_tasks(self, name):
        assert name in _beat_task_names()
        assert name in celery.tasks
