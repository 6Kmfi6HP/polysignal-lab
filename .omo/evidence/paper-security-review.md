recommendation: REJECT
reviewResult: FAIL

# Paper Nautilus Alignment Security/Safety Review

## originalIntent
Audit the Nautilus alignment refactor from the user's perspective, focusing on data parsing/persistence changes, settlement publication paths, Telegram publish best-effort behavior, SQLite paper order/fill/position table removal or retention, and changed tests. Verify no secrets, no production writes, no refs/@refs changes, no commits, and no unsafe regressions around broad exception swallowing, SQL injection, destructive data loss, or malicious/untrusted JSON handling.

## desiredOutcome
A security/safety PASS only if the diff and evidence prove that the refactor preserves fail-closed parsing at trust boundaries, avoids SQL injection and secret leakage, limits destructive database operations to the intended table removal/retention behavior, keeps Telegram publishing best-effort without hiding unsafe failures beyond the existing boundary, and includes tests that are not deletion-only, tautological, or overfit.

## userOutcomeReview
FAIL. The diff is mostly aligned with the intended Nautilus-owned order/fill/position state model, and the supplied test evidence is green. However, the shipped artifact relaxes validation on persisted/projection paper position and trade-result data by deleting the Pydantic paper models and replacing them with raw `dict`/`Mapping` helpers that silently default missing or malformed numeric and enum fields. That is a safety regression for settlement repair/reporting/publication paths that process persisted JSON. The changed tests primarily assert happy-path normalized rows and deletion of legacy model imports; they do not cover malicious/malformed persisted `system_events` or `paper_trade_results` payloads.

## checkedArtifactPaths
- `.omo/ulw-loop/evidence/paper-full-pytest.txt`: `651 passed, 2 warnings in 9.77s`.
- `.omo/ulw-loop/evidence/paper-pyscn.txt`: health score `85/100`, with complexity and duplication warnings.
- `.omo/ulw-loop/evidence/paper-refs-check.txt`: `refs_check=pass no refs/@refs changed`.
- `.omo/ulw-loop/evidence/paper-models-rg.txt`: remaining `paper_order`/`paper_position` strings are platform-boundary fixtures plus enum parser references.
- Diff and current sources under `src/polysignal_lab/...`, `scripts/repair_settlement_results.py`, and changed `tests/...`.

## blockers
1. Untrusted/persisted JSON handling no longer fails closed for paper trade and position data.
   - Deleted validators: `src/polysignal_lab/domain/paper_order.py`, `src/polysignal_lab/domain/paper_position.py`, and `PaperTradeResult` in `src/polysignal_lab/domain/paper_result.py` were replaced with `TypedDict`/helper accessors.
   - Risky defaults: `src/polysignal_lab/app/_settlement_check.py:184`-`197` defaults quantity/entry/stake to `0.0`; `scripts/repair_settlement_results.py:174`-`176` defaults settlement math inputs to `0.0`; `src/polysignal_lab/dashboard/app.py:252`-`275` defaults unknown position/order statuses to `OPEN`/`PENDING`; `src/polysignal_lab/domain/paper_result.py:65`-`74` converts numeric fields without rejecting non-finite floats.
   - Why this blocks PASS: malformed or hostile persisted JSON can be converted into apparently valid settlement, report, dashboard, or Telegram data instead of being rejected or quarantined.

2. Tests are green but not adversarial enough for the relaxed parsing boundary.
   - Added/changed tests cover normalized Nautilus row happy paths, e.g. dashboard and Telegram projected-row tests, and deletion-oriented platform boundary checks.
   - Evidence gap: no test injects malformed persisted `system_events`/`paper_trade_results` with missing IDs, invalid status, invalid side, NaN/Infinity numeric strings, negative shares/stake, or malformed opened/closed timestamps and proves fail-closed behavior.
   - Per `remove-ai-slops`/`programming` criteria, this is overfit coverage around the refactor's shape, not sufficient behavior coverage for a safety-sensitive parser boundary.

## nonBlockingFindings
- Secret leakage: PASS. Targeted scan only found fake test tokens in `tests/test_telegram_validation.py`; no production secret was found.
- refs/@refs: PASS. `git diff/status -- refs @refs` was empty and supplied refs evidence says pass.
- SQL injection: PASS with caveat. User-facing filters in dashboard use bound params; dynamic `IN (...)` construction in `src/polysignal_lab/app/scheduler_reporting.py:111`-`119` generates only `?` placeholders; `SQLiteStore` restricts table names to `ALLOWED_TABLES`. Raw `where` strings remain an internal API risk but no user-controlled interpolation was found in this diff.
- SQLite destructive data loss: PASS for this audit. `paper_orders`, `paper_fills`, and `paper_positions` are removed from schema/count validation, but no `DROP TABLE` migration is present; existing rows are retained/orphaned rather than deleted. Repair script deletes `paper_trade_results`/`daily_reports` only through parameterized, explicit repair flows with backup required for apply.
- Telegram best-effort publish: PASS with residual risk. `_publish_paper_result_best_effort` still catches broad `Exception`, but that boundary existed before this diff and occurs after durable persistence, logs a warning, and records a redacted `paper_result_publish_failed` event. Residual risk: formatter/programmer errors still look like publish failures.

## exactEvidenceGaps
- Missing adversarial tests for persisted JSON parsing in:
  - `SQLiteStore.restore_open_positions()` / `restore_closed_positions()`
  - `check_settlements()` / `_store_paper_result()`
  - `repair_settlement_results.py` audit/backfill
  - `PaperReportService.build_daily_report()`
  - `MessageFormatter.result_message()` / dashboard paper endpoints
- Missing proof that non-finite numeric payloads (`NaN`, `Infinity`) are rejected or sanitized after replacing Pydantic models with raw mapping helpers.
- Missing proof that unknown order/position statuses fail closed instead of becoming `PENDING`/`OPEN`.

## finalVerdict
FAIL / REJECT. Do not approve until the paper position/result JSON boundary is reintroduced as an explicit parser or schema with adversarial tests proving malformed persisted rows are rejected, quarantined, or excluded without producing settlement/report/publication output.
