"""Celery command entry point — ``celery -A src.celeryconf worker|beat``.

The deployment starts the worker and the scheduler with this module
(deploy/docker-compose.prod.yml, deploy/helm/tms/templates/deployment.yaml,
docker/scripts/entrypoint-celery-worker.sh / -beat.sh, docs/deployment-guide.md),
so Celery's app discovery needs to find the app here: it does, through the
``app``/``celery`` bindings below.

The schedule itself is **not** defined here.  It lives in src/celery_app.py and is
attached to the app there, so the periodic jobs exist no matter which module is
imported first — this module imports src.celery_app, and a schedule defined here
would be invisible to ``-A src.celery_app`` (and to the API process, and to the
tests) without a circular import.
"""
from src.celery_app import app, beat_schedule  # noqa: F401  (Celery app discovery binds these)

celery = app
