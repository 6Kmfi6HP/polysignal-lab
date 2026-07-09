# Paper Context Rerun 4

<verdict>PASS</verdict>

## Sources searched

- `docs/architecture-nautilus-alignment.md`
- `docs/design/2026-07-07-dashboard-data-source-unification.md`
- `src/polysignal_lab/storage/sqlite_store.py`
- `src/polysignal_lab/storage/sqlite_schema.py`
- `src/polysignal_lab/dashboard/app.py`
- `src/polysignal_lab/publish/telegram_bot.py`
- `src/polysignal_lab/app/_settlement_check.py`
- `tests/test_dashboard.py`
- `tests/test_nautilus_observability.py`
- `git log -S'restore_open_positions'`
- `git log -S'paper_positions'`

## Discovered context

- Open-position restore is now fail-closed on malformed rows: `_valid_position_event()` requires `opened_at`, `ts`, or `created_at` for OPEN rows, plus numeric `shares` / `entry_price` / `stake_usdc` fields before the row can participate in restore logic. See `src/polysignal_lab/storage/sqlite_store.py:62-88`.
- `restore_open_positions()` no longer reads a legacy `paper_positions` table. It reconstructs the latest `nautilus_position` event per `paper_position_id` from `system_events`, then returns only OPEN rows. See `src/polysignal_lab/storage/sqlite_store.py:406-429`.
- Dashboard position rendering already normalizes `nautilus_position` payloads through `_paper_position_payload()`, filling `paper_position_id`, `asset`, `timeframe`, `market_id`, `market_slug`, `token_id`, `entry_price`, `shares`, `stake_usdc`, `opened_at`, and derived `is_closed`. See `src/polysignal_lab/dashboard/app.py:294-374` and `src/polysignal_lab/dashboard/app.py:449-470`.
- Telegram position summaries consume the same restored open-position path and use `opened_at | ts | created_at` fallbacks only for display timing. See `src/polysignal_lab/publish/telegram_bot.py:337` and `src/polysignal_lab/publish/telegram_bot.py:615`.
- Settlement logic also reads projected Nautilus positions, rejects closed rows, and requires `paper_position_id` / `position_id`, `market_id`, and `token_id` before settling. See `src/polysignal_lab/app/_settlement_check.py:24-28` and `src/polysignal_lab/app/_settlement_check.py:75-113`.
- The architecture doc still treats `paper_orders` / `paper_fills` / `paper_positions` as legacy-only fallback surfaces in the reporting transition plan, but not as the runtime source of truth. See `docs/design/2026-07-07-dashboard-data-source-unification.md:33-56` and `docs/design/2026-07-07-dashboard-data-source-unification.md:180-182`.
- The alignment doc explicitly says `PaperPosition` should be retained only for dashboard/report serialization, while Nautilus-boundary code should use Nautilus `Position` semantics. See `docs/architecture-nautilus-alignment.md:334-340` and `docs/architecture-nautilus-alignment.md:344-362`.

## Missed requirements

- None found in the scoped surfaces.
- I did not find a remaining `paper_positions` table dependency in source code.
- I did not find a remaining open-position restore path that bypasses the new timestamp validation.

## Blocking issues

- None.

