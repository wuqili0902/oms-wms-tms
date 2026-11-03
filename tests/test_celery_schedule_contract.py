"""A beat entry naming a task the worker never registered is a job that never runs.

The deployment starts ``celery -A src.celeryconf worker`` and ``… beat`` (see
deploy/docker-compose.prod.yml, deploy/helm/tms/templates/deployment.yaml,
docker/scripts/entrypoint-celery-*.sh), and src/celeryconf.py schedules eleven
jobs.  Two things used to make that story quietly untrue:

* ``src/celery_app.py`` registered a *hand-picked* list of task modules inside
  ``try: … except ImportError: pass``.  A task module that failed to import was
  therefore never registered, and beat fired its entry as
  ``Received unregistered task of type '…'`` — a scheduled job with a log line
  nobody reads, not an outage anyone sees.
* ``src/tasks/__init__.py`` listed ``check_low_stock_alerts`` and
  ``release_locked_inventory_for_cancelled_orders`` in ``__all__`` without
  importing them, so ``from src.tasks import *`` raised
  ``AttributeError: module 'src.tasks' has no attribute 'check_low_stock_alerts'``,
  and its docstring described an ``example.py`` that does not exist in the package.

The schedule also spells task names in two families — ``src/tasks/inventory.py``
declares explicit names (``tasks.inventory.*``, ``tasks.order.*``), the other
modules keep Celery's default ``src.tasks.<module>.<function>``.  A schedule entry
must match the name the decorator registered, so these tests read the names off
the registered tasks instead of restating them.
"""

import inspect

import src.celery_app as celery_app
import src.celeryconf as celeryconf
import src.tasks as tasks_pkg
import src.tasks.inventory as inventory_tasks
from src.tasks.base import BaseTask

SCHEDULE = celery_app.app.conf.beat_schedule


def _task_names() -> list[str]:
    return [entry["task"] for entry in SCHEDULE.values()]


def _local_tasks(module) -> list:
    """Celery task objects defined in a module (registered by importing it)."""
    found = []
    for _, obj in vars(module).items():
        if isinstance(obj, BaseTask) and getattr(obj, "name", None):
            found.append(obj)
    return found


class TestBeatScheduleIsRegistered:
    def test_schedule_is_applied_to_the_app(self):
        """Importing src.celery_app must carry the schedule, not just src.celeryconf."""
        assert SCHEDULE
        assert SCHEDULE == celeryconf.beat_schedule

    def test_every_scheduled_task_is_registered(self):
        registered = set(celery_app.app.tasks)
        unregistered = sorted({name for name in _task_names() if name not in registered})
        assert unregistered == [], f"beat 安排了未注册的任务：{unregistered}"

    def test_every_scheduled_task_runs_the_base_task(self):
        """A scheduled job that skips BaseTask skips its retry/logging bridge."""
        for entry in SCHEDULE.values():
            task = celery_app.app.tasks[entry["task"]]
            assert isinstance(task, BaseTask), f"{entry['task']} is not a BaseTask"

    def test_every_entry_is_a_named_job_with_a_schedule(self):
        for key, entry in SCHEDULE.items():
            assert isinstance(key, str) and key
            assert entry["task"].startswith(("tasks.", "src.tasks.")), key
            assert entry.get("schedule") is not None, key
            assert entry.get("options", {}).get("queue"), key

    def test_inventory_names_use_the_declared_names(self):
        """src/tasks/inventory.py declares explicit names; the schedule has to match them."""
        declared = {t.name for t in _local_tasks(inventory_tasks)}
        assert declared, "src/tasks/inventory.py registers no tasks"
        for name in declared:
            assert name in celery_app.app.tasks
        scheduled_inventory = {n for n in _task_names() if n.startswith("tasks.inventory.")}
        assert scheduled_inventory <= declared, scheduled_inventory - declared


class TestTasksPackageExports:
    def test_all_is_importable(self):
        """``from src.tasks import *`` used to raise: __all__ named names it never imported."""
        star = {name: getattr(tasks_pkg, name, None) for name in tasks_pkg.__all__}
        missing = sorted(name for name, obj in star.items() if obj is None)
        assert missing == [], f"src/tasks/__init__.py 声明了未导入的名字：{missing}"

    def test_every_task_in_the_package_is_exported(self):
        exported = {
            obj.name
            for name in tasks_pkg.__all__
            for obj in [getattr(tasks_pkg, name)]
            if isinstance(obj, BaseTask)
        }
        defined = set()
        for module_name, module in inspect.getmembers(tasks_pkg, inspect.ismodule):
            if module_name.startswith("_"):
                continue
            if module.__name__.startswith("src.tasks."):
                defined.update(t.name for t in _local_tasks(module))
        assert defined <= exported, f"任务未从 src.tasks 导出：{sorted(defined - exported)}"

    def test_no_module_is_advertised_that_is_not_there(self):
        """The docstring used to point at an example.py that does not exist."""
        doc = tasks_pkg.__doc__ or ""
        assert "example.py" not in doc

    def test_registration_is_not_swallowed(self):
        """The app registers by importing the package; a broken module must raise, not vanish."""
        source = inspect.getsource(celery_app)
        assert "except ImportError" not in source
        assert "import src.tasks" in source
