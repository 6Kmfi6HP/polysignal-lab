# paper-context-rerun-5

<verdict>FAIL</verdict>

## Discovered Context

- `SQLiteStore.restore_open_positions()` is fail-closed on malformed persisted position events via `_valid_position_event()`, including missing side, missing money fields, missing timestamp, and invalid `opened_at`.
- Remaining bypasses are in downstream presentation / repair code, not in the store restore gate itself.
- `dashboard/app.py` still fabricates or backfills position fields for display, including `side` defaulting to `UP` and `opened_at` falling back to `ts` / `created_at`.
- `app/_settlement_check.py` still fabricates a `Side.UP` fallback in the projection-to-result path.
- `publish/telegram_bot.py` still defaults missing position `side` to `UP` in `_position_display_payload()`.
- Documentation still describes `paper_positions` as an active projection/table and still prescribes `restore_open_positions()` as a live repair/reporting source, which conflicts with the Nautilus-alignment direction that removes legacy paper position objects and active `paper_positions` runtime usage.

## Sources Searched

- `src/polysignal_lab/storage/sqlite_store.py`
- `src/polysignal_lab/dashboard/app.py`
- `src/polysignal_lab/app/_settlement_check.py`
- `src/polysignal_lab/publish/telegram_bot.py`
- `src/polysignal_lab/app/services/persistence_service.py`
- `src/polysignal_lab/storage/sqlite_schema.py`
- `tests/test_storage_restore.py`
- `tests/test_dashboard.py`
- `docs/PRD.md`
- `docs/design/2026-07-07-dashboard-data-source-unification.md`
- `docs/architecture-nautilus-alignment.md`
- `docs/superpowers/plans/2026-07-05-settlement-db-repair-script.md`

## Missed Requirements

- No remaining bypass in `restore_open_positions()` itself, but there are still `Side.UP` fabrications in position-facing paths.
- `dashboard/app.py` still turns malformed / missing position inputs into displayable rows instead of keeping them absent in every path.
- `app/_settlement_check.py` still uses a `Side.UP` fallback for unresolved position side.
- Docs still conflict with the intended removal of legacy `paper_positions` runtime usage.

## Blocking Issues

- `src/polysignal_lab/dashboard/app.py:381-393` still resolves position side via `_resolve_side()` and `_fill_missing(..., "opened_at", ...)`, which allows fallback fabrication.
- `src/polysignal_lab/dashboard/app.py:680-692` still defaults missing `side` to `UP`.
- `src/polysignal_lab/app/_settlement_check.py:245-255` still returns `Side.UP` if the side cannot be inferred.
- `src/polysignal_lab/publish/telegram_bot.py:668-693` still defaults missing `side` to `UP`.
- `docs/PRD.md:685-693` still documents `paper_positions` as a current SQLite table.
- `docs/design/2026-07-07-dashboard-data-source-unification.md:182-250` still frames `paper_positions` as a legacy table to be handled rather than already removed.
