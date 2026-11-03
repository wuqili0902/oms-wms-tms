# Bugfix Plan — Outbox retry, cache exception handling, push failures, stock validation

Read this fully before editing. Fixes are prioritized by severity. All backend (`src/`), logic-level, no schema/migration changes. Follow existing code style; do not add dependencies.

## BUG 1 [HIGH] Outbox retry never fires — failed events silently dropped
Files: `src/core/outbox.py`, `src/tasks/outbox.py`

Problem: `dispatch_pending_events()` selects only `status == 'pending'`. On delivery failure, `tasks/outbox.py` calls `mark_failed()`, which sets `status='failed'`, bumps `retry_count`, and sets `scheduled_at = now+60s`. Nothing ever requeues FAILED→PENDING, so the `scheduled_at` backoff is never consulted. Failed events are retried at most once, then stuck forever (the retry>=5 "dead-letter" path also just leaves them FAILED). The task docstring falsely claims "auto-retry in 60s".

Fix:
- In `dispatch_pending_events()` (`src/core/outbox.py`), broaden the WHERE to include due retries:
  ```python
  .where(
      or_(
          OutboxEvent.status == OutboxEventStatus.PENDING.value,
          and_(
              OutboxEvent.status == OutboxEventStatus.FAILED.value,
              OutboxEvent.scheduled_at <= func.now(),
              OutboxEvent.retry_count < 5,
          ),
      )
  )
  ```
  (import `or_`, `and_` from sqlalchemy). Keep `.order_by(created_at)`.
- Add a new status `DEAD_LETTERED = "dead_lettered"` to `OutboxEventStatus`. In `mark_failed()`, when an event has reached retry_count >= 5, set it to `DEAD_LETTERED` (with a clear error_message) instead of leaving it FAILED. This stops dead-lettered events from being re-selected by the broadened query.
- Note secondary gap: events are marked DISPATCHED on pickup before delivery; if the worker crashes after commit but before delivering, they stay DISPATCHED-and-never-delivered and won't be retried. Out of scope for this pass — flag only.

## BUG 2 [MEDIUM] `@cached` swallows exceptions + double-executes on failure
File: `src/cache/decorators.py` (lines ~37-39)

Problem: the wrapper's bare `except Exception:` catches ALL wrapped-function exceptions and re-runs `func()` once. The analytics service now re-raises on DB failure, so each failure triggers a second query execution; more generally any cached function's real error is masked behind "Redis unavailable".

Fix: only fall back to uncached when Redis itself is unavailable (catch the redis/connection error specifically — e.g. import and catch `redis.exceptions.RedisError` plus `OSError`/connection errors from `get_redis()`), and let genuine function exceptions propagate WITHOUT re-executing. Keep the same "execute without cache" fallback for real Redis outages.

## BUG 3 [MEDIUM] TMS push notifications fail completely silently
File: `src/tms/push_service.py` (`_send_fcm` ~85, `send_to_device` ~119, `send_to_topic` ~149)

Problem: all three catch every exception and return `False` (only an error log). When Firebase is configured but broken, callers can't tell delivered from failed. When Firebase is NOT configured (`_fcm_ready=False`), the code increments `_sent_count` and returns `True` — reporting success for a no-op.

Fix: surface delivery status clearly to callers (return/raise a distinguishable result) and stop counting unconfigured no-ops as successes. Keep logging at an observable level. Preserve existing return-type contract where callers depend on it — check callers before changing signatures; prefer returning a richer result object/tuple if needed rather than breaking the bool API.

## BUG 4 [LOW] `adjust-stock` returns 500 on malformed input
File: `src/routes/stock.py` (lines ~270-274)

Problem: direct `data["sku_id"]`, `data["warehouse_id"]`, `data["quantity"]` access with no `.get()`/validation → KeyError → HTTP 500 instead of a clean 422.

Fix: validate presence and parse defensively, raising `HTTPException(422, ...)` for missing/invalid fields (consistent with the rest of the router). Keep behavior identical for valid input.

## Verification
- `ruff check src/core/outbox.py src/cache/decorators.py src/tms/push_service.py src/routes/stock.py`
- `pytest tests/test_core/ tests/test_tms/ -q` (outbox + tms suites)
- Add a test asserting a FAILED outbox event with past `scheduled_at` and retry_count < 5 is re-selected by `dispatch_pending_events`.
- Confirm analytics endpoints still return 500 on DB failure but execute the query only once under Redis.
