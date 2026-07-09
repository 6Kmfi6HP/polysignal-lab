<verdict>PASS</verdict>

<context>
Re-checked active `src/`, `scripts/`, and `tests/` surfaces for the two forbidden settlement/persistence defaults after the latest `_settlement_check.py` fix:
- missing position side defaulting to `UP`
- missing `opened_at` defaulting to `closed_at`
</context>

<sources_searched>
- `src/polysignal_lab/app/_settlement_check.py`
- `src/polysignal_lab/publish/telegram_bot.py`
- `src/polysignal_lab/dashboard/app.py`
- `scripts/repair_settlement_results.py`
- active `tests/` matching the above flows
</sources_searched>

<findings>
- `src/polysignal_lab/app/_settlement_check.py:203-247` now requires a resolvable side from the projection or market token and returns `None` if `opened_at` cannot be parsed. It does not synthesize `UP` or reuse `closed_at` for persistence.
- `scripts/repair_settlement_results.py:124-147` and `:203-256` behave the same way for offline repair: side comes from the stored side field, and `opened_at` must exist from `opened_at`/`ts`/`created_at`; `closed_at` is generated separately with `utc_now()`.
- `src/polysignal_lab/dashboard/app.py:362-394` fills dashboard display rows from `opened_at`/`ts`/`created_at` for projection only, then validates `side` via `_resolve_side`; this is a read-side fallback, not a settlement persistence fallback.
- `src/polysignal_lab/dashboard/app.py:390-393` uses `opened_at` only as the open-position timestamp and keeps `closed_at` separate.
- `src/polysignal_lab/publish/telegram_bot.py` had no active settlement/result persistence path that defaults missing side to `UP` or missing `opened_at` to `closed_at`.
</findings>

<classification>
- Active business-logic defaults such as `return Side.UP` in domain/alpha helpers are not position-persistence fallbacks and were excluded.
- Test-only references to `Side.UP`, `opened_at`, and `closed_at` are expected fixtures and assertions.
- The dashboard fallback from missing `opened_at` to `ts`/`created_at` is valid for display/projection and is not the invalid `opened_at or closed_at` pattern.
</classification>

<blocking_issues>
None found in active source paths for the requested regression class.
</blocking_issues>
