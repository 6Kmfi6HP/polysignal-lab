recommendation: REJECT
verdict: FAIL
severity: HIGH

# Paper Security Rerun

## originalIntent
Security/safety review the paper blocker fixes in `/home/debian/polysignal-lab` without modifying code or committing. Compare `.omo/evidence/paper-security-review.md` against current code/evidence, focusing on fail-closed parsing of persisted `paper_trade_results`, malformed/incomplete rows, repair script backfill persistence, dashboard/publish filtering, SQL/destructive data risks, secrets, and protected refs mutation.

## desiredOutcome
PASS only if the current diff and evidence prove prior high/critical paper safety blockers are gone: malformed or incomplete persisted rows must not be converted into valid settlement/report/publish/dashboard output; repair backfill must persist schema-complete results without fabricating missing financial data; publish/dashboard surfaces must filter invalid rows; destructive SQL must be bounded/parameterized; no secrets or protected refs changes are introduced.

## userOutcomeReview
FAIL. The `paper_trade_results` parser and store/publish/dashboard tests are stronger than the previous blocker state: malformed result rows now reject or filter, publish parses before sending, and the supplied focused/full pytest artifacts are green. However, a prior high-risk class remains in the repair path: incomplete persisted open position events can still be restored as open positions, and `_settle_for_repair` still fabricates `0.0` money/share fields into a parseable winning settlement row. That is not fail-closed handling for malformed/incomplete persisted rows.

## checkedArtifactPaths
- `.omo/evidence/paper-security-review.md`
- `.omo/evidence/paper-code-review.md`
- `.omo/evidence/paper-goal-verification-review.md`
- `.omo/evidence/paper-qa-execution-review.md`
- `.omo/ulw-loop/evidence/paper-security-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-full-pytest.txt`
- `.omo/ulw-loop/evidence/paper-refs-check.txt`
- `src/polysignal_lab/domain/paper_result.py`
- `src/polysignal_lab/storage/sqlite_store.py`
- `scripts/repair_settlement_results.py`
- `src/polysignal_lab/app/services/publish_service.py`
- `src/polysignal_lab/dashboard/app.py`
- `tests/test_storage_restore.py`
- `tests/test_publish_service.py`
- `tests/test_dashboard.py`
- `tests/test_repair_settlement_results.py`

## blockers
1. HIGH: Repair backfill still fabricates valid settlements from incomplete persisted position rows.
   - Current code: `scripts/repair_settlement_results.py:174`-`176` defaults missing `entry_price`, `shares`, and `stake_usdc` to `0.0`.
   - Current code: `src/polysignal_lab/storage/sqlite_store.py:53`-`69` permits missing financial fields in `_valid_position_event`, so incomplete open position events can reach repair.
   - Direct evidence: a persisted `nautilus_position` event with no `shares`, `entry_price`, or `stake_usdc` restored as one open row: `{'open_rows': 1, ...}`.
   - Direct evidence: `_settle_for_repair` on a position missing those fields returned a parseable result: `{'returned': True, 'shares': 0.0, 'stake_usdc': 0.0, 'settlement_value': 0.0, 'result': 'WIN'}`.
   - Why this blocks PASS: malformed/incomplete persisted position state can become durable settlement output instead of being rejected or skipped.

2. HIGH: The new tests do not cover the remaining malformed repair input class.
   - Focused rerun passed: `uv run pytest -p no:cacheprovider --no-header tests/test_storage_restore.py::test_sqlite_store_rejects_invalid_paper_trade_rows tests/test_storage_restore.py::test_sqlite_store_rejects_incomplete_paper_trade_rows tests/test_publish_service.py::test_publish_paper_result_rejects_invalid_payload tests/test_dashboard.py::test_dashboard_excludes_invalid_nautilus_projection_rows tests/test_repair_settlement_results.py::test_settle_for_repair_returns_parseable_trade_result_row` -> `5 passed`.
   - Existing artifacts passed: `paper-security-focused-pytest.txt` -> `5 passed`; `paper-blockers-focused-pytest.txt` -> `44 passed`; `paper-full-pytest.txt` -> `659 passed`.
   - Coverage gap: `tests/test_repair_settlement_results.py` only proves a happy-path repair row is parseable; it does not inject an incomplete restored position and prove repair skips/rejects it.

## resolvedFindings
- `parse_paper_trade_result_row` now fails closed for required IDs/status/timestamps, unknown result/side, non-finite numeric values, and negative nonnegative fields.
- `SQLiteStore.insert_paper_trade_result` parses before insert, and `SQLiteStore.query_json("paper_trade_results")` excludes invalid persisted result payloads.
- `PublishService.publish_paper_result` parses before formatting/sending; invalid publish payload tests prove no publisher or persistence call.
- Dashboard invalid-row test covers unknown order status and invalid position status/non-finite shares; positions are filtered from `/api/positions`.
- SQL/destructive scan found bounded parameterized deletes for paper result/report/publish IDs. Repair apply requires `--backup`; no scoped `DROP`/`TRUNCATE` found.
- Protected refs/docs check passed: `git diff --name-only -- refs @refs docs/nautilus_reference` and `git status --short -- refs @refs docs/nautilus_reference` returned no output; `paper-refs-check.txt` says pass.
- Secret scan: local ignored `.env` contains credential-looking values, but `git check-ignore` confirms `.env`/`.env.*` are ignored and `git ls-files` found no tracked env secret files. No secret values are included here.

## slopAndProgrammingReview
- `.omo/evidence/paper-code-review.md` explicitly includes `programming` and `remove-ai-slops` perspectives, but its recommendation is `REQUEST_CHANGES`, not approval.
- Direct slop pass: the invalid `paper_trade_results`, publish, and dashboard tests are behavioral rather than deletion-only or tautological. The repair test is underfit for the adversarial class above, so it gives false confidence for the repair blocker.
- Direct programming pass: the remaining blocker is behavioral/safety-critical, not merely style. Existing report concerns around `Any`/`object`/`cast` remain maintenance risk but are secondary to the fail-open repair path.

## exactEvidenceGaps
- No test proves `SQLiteStore.restore_open_positions()` rejects persisted open position events missing financial settlement inputs.
- No test proves `_settle_for_repair()` rejects/skips incomplete position rows instead of defaulting money/share fields to zero.
- No end-to-end repair backfill test proves malformed restored positions cannot persist fabricated `paper_trade_results`.
- No updated unconditional code-review artifact supersedes the existing `REQUEST_CHANGES` paper code review.

## finalVerdict
FAIL / REJECT. High paper safety blockers are not gone.
