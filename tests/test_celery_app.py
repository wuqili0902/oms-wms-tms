"""Tests for Celery application configuration."""
import importlib.util
import sys

import pytest


@pytest.fixture
def celery_mod():
    spec = importlib.util.spec_from_file_location(
        "celery_app_test", "src/celery_app.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["celery_app_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestCeleryApp:
    def test_app_created(self, celery_mod):
        assert celery_mod.app is not None
        assert celery_mod.celery is not None
        assert celery_mod.celery is celery_mod.app

    def test_broker_url(self, celery_mod):
        assert celery_mod.app.conf.task_serializer == "json"
        assert celery_mod.app.conf.task_time_limit == 3600
        assert celery_mod.app.conf.task_soft_time_limit == 3000
        assert celery_mod.app.conf.worker_prefetch_count == 1

    def test_start_celery_worker(self, celery_mod, monkeypatch):
        args_called = []
        monkeypatch.setattr(celery_mod.app, "worker_main", lambda args: args_called.extend(args))
        celery_mod.start_celery_worker()
        assert "worker" in args_called
        assert "--loglevel=INFO" in args_called

    def test_start_celery_beat(self, celery_mod, monkeypatch):
        args_called = []
        celery_mod.app.beat_main = lambda args: args_called.extend(args)
        celery_mod.start_celery_beat()
        assert "beat" in args_called
        assert "--loglevel=INFO" in args_called


