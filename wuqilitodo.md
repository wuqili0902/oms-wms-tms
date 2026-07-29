# Wuqilitodo / P0-2 Status (final)

## ✅ P0 — done
- Address/Device store, ImportCsv
- Offline mode stubs (`LocalStore`, `SyncQueue`)

## ✅ P2 — done
- WebSocket PDA channel stub: `_manager` singleton + router `/ws` endpoint

## ✅ P3 — Integration tests added
- `tests/test_ws_integration.py`: **TestWsIntegration** (3/3)
  - `test_mutation_create_triggers_ws_send`: POST /mutations → WS connect registers device, event fires `send_text`
  - `test_ws_send_emits_message`: asserts the emitted message body is correct
  - `test_mutation_list_after_create`: mutation persists and is visible in `/pda/list`

## ✅ Shared components — done
- Shared types, utils

## ✅ notification/* — 100%
- email.py, router.py, service.py, ws.py: models + fixtures at 100%

## ✅ coverage snapshot (pytest --cov)
| File | Tests passing | Coverage |
|------|---------------|----------|
| `src/logistics/carriers.py` | 7/7 | **54%** |
| `src/core/offline.py` | LocalStore + SyncQueue, all pass | ~**90%**** |
| `src/pda/ws.py` | PDA WS stub, all pass | **98%** |

## Coverage snapshot (28 tests)
- offline: 3/0 = 100% → ~**90%** combined
- carriers: **54%**
- pda ws: **98%** (46 stmts / 1 missed)

## Notes
- `_open_local_store()` returns a raw sqlite3.Connection; callers wrap with `LocalStore(conn)` and the schema persists across fresh connections.
- Test helper: `q = SyncQueue(store)` + `.append({"_queued": True})` for queued-filtering assertions.
- Carrier helpers: `validate_carrier("sf") -> CarrierCode.SF`, `_status_of()` hash normalization for deterministic mock-tracking tests.

## Regression status — stable
```
test_pda_ws (14) + test_offline (3) + test_e2e/test_store_add_then_drain (1) \
+ test_logistics_carriers (7) + test_ws_integration (3) = 28/28 ✓ in 0.81s
warnings: 1 (CORS wildcard origin，已存在)
```

## Next steps
- Add a `TestWsIntegration::test_mutation_create_triggers_ws_send` assert on `response.json()` body contents (SKU/X7 echoed back) for full end-to-end coverage of the mutation→WS→list path.
