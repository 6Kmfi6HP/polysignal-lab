<verdict>PASS</verdict>
severity: PASS
recommendation: PASS
reportPath: /home/debian/polysignal-lab/.omo/evidence/paper-security-rerun-6.md

# Paper Security Rerun 6

## Scope

Read-only security/data-integrity rerun after the latest paper safety fixes.

Reviewed surfaces:
- malformed persisted paper result / position JSON
- live settlement result persistence
- repair import and behavior
- dashboard position exposure
- Telegram open-position display exposure
- SQL/destructive repair paths
- debug artifacts, broad-exception drift, protected refs

## Severity Findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

- Syntactically invalid `payload_json` still raises `JSONDecodeError` through `SQLiteStore.query_json()` instead of skipping the row. Direct probe confirmed `restore_open_positions_exception=JSONDecodeError`. I am not classifying this HIGH because it fails closed for data integrity: no malformed row is converted into a position/trade result or exposed through Telegram/dashboard, and exploitation requires write access to the SQLite file. It remains availability hardening debt.
- Expanded programming/no-excuse probing over live settlement plus Telegram files reports existing non-security debt: oversized modules, object annotations, existing broad boundary handlers, and a pre-existing `except ValueError: pass` in side resolution. These are not new HIGH/CRITICAL security issues in the reviewed fixes.

### LOW

- Existing broad exception handlers remain in Telegram callback/rendering and best-effort publish paths. Direct diff scan found no newly added `except Exception`, debug breakpoints, `debugger`, `console.log`, or `print(...)` debug artifacts in the current diff.

## Blockers

None.

## User Outcome Review

- Live settlement now fail-closes missing/unresolvable side. `src/polysignal_lab/app/_settlement_check.py:271-274` rejects `None` from `_projection_side()`, and `_projection_side()` returns `None` when neither explicit `UP`/`DOWN` nor market-token mapping resolves a side at `src/polysignal_lab/app/_settlement_check.py:321-331`.
- Live settlement now fail-closes missing opened timestamp. `src/polysignal_lab/app/_settlement_check.py:283-291` requires a parseable `opened_at`, `ts`, or `created_at` before persisting.
- Repair remains fail-closed for missing side and malformed opened timestamp. `scripts/repair_settlement_results.py:124-147` parses side/timestamp to `None`, and `_settle_for_repair()` exits before result construction at `scripts/repair_settlement_results.py:203-206`.
- Dashboard remains fail-closed for invalid/missing side/timestamp and money fields. `src/polysignal_lab/dashboard/app.py:307-325` filters invalid projected positions before `/api/positions` returns rows at `src/polysignal_lab/dashboard/app.py:469-490`.
- Telegram display no longer fabricates `UP`. `_position_display_payload()` normalizes unresolved side to `""` at `src/polysignal_lab/publish/telegram_bot.py:686-693`, and `_format_positions()` skips rows without side at `src/polysignal_lab/publish/telegram_bot.py:341-344`.
- Persisted paper trade result rows are parsed before insert/query exposure. `src/polysignal_lab/domain/paper_result.py:88-136` requires key fields, valid side/result, finite numeric fields, and parseable timestamps; `src/polysignal_lab/storage/sqlite_store.py:381-394` drops invalid stored `paper_trade_results`.

## Slop / Overfit Pass

- `remove-ai-slops` criterion: focused tests are behavioral, not deletion-only or tautological. They exercise `check_settlements()`, SQLite restore/query, dashboard API output, repair result construction, publish validation, and Telegram rendered text.
- `programming` criterion: the security fix uses direct guards and existing parsers, with no new abstraction or dependency. Remaining `Any`/oversized-module/broad-handler debt is pre-existing or non-security-scoped and does not create false PASS evidence for the side/timestamp blockers.

## Checked Artifacts

- `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt`: focused paper blockers pass.
- `.omo/ulw-loop/evidence/paper-full-pytest.txt`: full pytest pass.
- `.omo/ulw-loop/evidence/paper-no-excuse-security-scope.txt`: no violations in the 6-file blocker scope.
- `.omo/ulw-loop/evidence/paper-debug-artifact-scan.txt`: debug artifact scan pass.
- `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`: `telegram_missing_side=pass`, `settlement_missing_side=pass`, `settlement_missing_timestamp=pass`, and zero settlement store calls.
- `.omo/ulw-loop/evidence/paper-refs-check.txt`: no refs/@refs/docs/nautilus_reference changes.
- `.omo/evidence/paper-security-rerun-5.md`: previous security PASS after the same side/timestamp fixes.
- `.omo/evidence/paper-code-review-rerun-4.md` and `.omo/evidence/paper-goal-verification-rerun-4.md`: prior FAILs identifying the live settlement/Telegram side fabrication now fixed in current source.

## Direct Commands / Probes

- `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_scheduler_settlement_resolution.py::test_settlement_skips_projection_without_resolvable_side tests/test_scheduler_settlement_resolution.py::test_settlement_skips_projection_without_opened_timestamp tests/test_telegram_bot_service.py::test_telegram_bot_positions_skips_rows_without_side tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_event_without_side tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_event_with_invalid_opened_at tests/test_dashboard.py::test_dashboard_excludes_open_position_without_resolvable_side tests/test_dashboard.py::test_dashboard_excludes_open_position_with_invalid_opened_at tests/test_repair_settlement_results.py::test_settle_for_repair_rejects_position_without_side` -> `8 passed`.
- `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_storage_restore.py::test_sqlite_store_rejects_invalid_paper_trade_rows tests/test_storage_restore.py::test_sqlite_store_rejects_incomplete_paper_trade_rows` -> `2 passed`.
- `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_publish_service.py::test_publish_paper_result_rejects_invalid_payload` -> `1 passed`.
- Manual probe: `live_missing_side_result=None`, `live_missing_side_store_calls=0`, `live_missing_timestamp_result=None`, `live_missing_timestamp_store_calls=0`, `repair_invalid_opened_at_result=None`, `telegram_missing_side_display_side=''`, `storage_missing_side_open_positions=[]`.
- Direct malformed JSON probe: invalid `system_events.payload_json` raises `JSONDecodeError` on restore/query, so it is not exposed as a valid position.
- `git diff -U0 -- . ':(exclude)refs' ':(exclude)docs/nautilus_reference' | rg ...` found no added broad exceptions/debug artifacts.
- `git diff --check` -> pass.
- `git status --short -- refs @refs docs/nautilus_reference && git diff --name-only -- refs @refs docs/nautilus_reference` -> no protected-path output.

## Evidence Gaps

- I did not count the expanded `basedpyright` run as a security gate: including the full `tests/test_telegram_bot_service.py` file reports existing test typing errors outside the side/timestamp security fixes. The stored blocker-scoped basedpyright artifact remains the relevant scoped static evidence.
- I did not run a live Telegram/API server. The reviewed surfaces are data-shaped fail-closed paths and were exercised through focused tests plus direct Python probes without spawning persistent processes.

## Final Verdict

PASS. No HIGH or CRITICAL security/data-integrity blocker remains in the reviewed malformed persisted row, live settlement persistence, repair, dashboard, Telegram display, SQL/destructive repair, debug artifact, or protected-ref scope.
