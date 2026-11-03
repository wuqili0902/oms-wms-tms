"""Stock In/Out / Inventory Log / Adjust Stock API endpoints.

The routes themselves live in ``src/routes/stock.py``; this module is the name
``src/main.py`` mounts.  It re-exports the router instead of rebuilding it.

It used to loop over ``_s.router.routes`` and call ``add_api_route`` with
``path``, ``endpoint``, ``methods`` and ``status_code``.  Those are only part of
what an ``APIRoute`` carries, and the parts left out were not cosmetic:

* ``dependencies`` — ``src/routes/stock.py`` declares
  ``APIRouter(dependencies=[Depends(get_current_user)])``, so the whole stock API
  was authentication-required.  A copied route starts with an empty dependency
  list, so every stock-in, stock-out and inventory-log endpoint answered
  anonymous callers.  Only ``/adjust-stock`` survived, because it happens to name
  ``current_user`` in its own signature.
* ``tags`` — the endpoints vanished from the "Stock In/Out" group that generated
  clients and docs are built from.
* ``response_model`` — the response stops being validated and filtered, so
  whatever the endpoint happens to return goes out as-is.

Re-exporting keeps all of it, because there is nothing to copy.  New stock
endpoints belong in ``src/routes/stock.py``.
"""

from src.routes.stock import router  # noqa: F401  — re-export: the same router, metadata intact
