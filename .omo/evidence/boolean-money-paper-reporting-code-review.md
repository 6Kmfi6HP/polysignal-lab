# Boolean Money And Paper Reporting Code Review

Verdict: FAIL
codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: `.omo/evidence/boolean-money-paper-reporting-code-review.md`
blockers:
- HIGH: paper reporting still accepts a JSON boolean as a numeric USD depth metric through `float(True)`, producing `average_executable_depth_usdc == 1.0`.

## Skill Perspective Check

- `omo:programming`: consulted `SKILL.md` and `references/python/README.md`. The scoped storage parser change follows the boundary-parse/fail-closed intent for trade rows and position events. The report metric path violates the same perspective because `optional_float` validates with `float(value)` at a reporting boundary and does not reject `bool`.
- `omo:remove-ai-slops`: consulted `SKILL.md`. The two named boolean-money tests are adversarial, behavior-level SQLite tests, not deletion-only/tautological tests. The report metric path violates this perspective because the new report tests cover normal floats but do not include the adversarial boolean case for `paper_available_depth_usdc`.

## CRITICAL

None.

## HIGH

### Boolean USD depth metrics are still coerced to numeric report values

`src/polysignal_lab/paper/report.py:159-164` feeds `metrics["paper_available_depth_usdc"]` into `_optional_float`, and `src/polysignal_lab/paper/report_aggregates.py:70-75` calls `float(value)` without rejecting `bool`. Python accepts `float(True) == 1.0`, so a malformed JSON boolean still corrupts paper reporting metrics.

Exact probe:

```bash
.venv/bin/python - <<'PY'
from datetime import date
from polysignal_lab.paper.report import PaperReportService
report = PaperReportService().build_daily_report(
    report_date=date(2026, 6, 22),
    starting_equity=1000.0,
    ending_equity=1000.0,
    total_signals=1,
    paper_orders=1,
    paper_fills=0,
    rejected_paper_orders=0,
    open_positions=0,
    results=[],
    paper_order_payloads=[{"paper_order_id": "po-bool-depth", "status": "FILLED", "metrics": {"paper_available_depth_usdc": True}}],
)
print(report.average_executable_depth_usdc)
PY
```

Observed output:

```text
1.0
```

Why this blocks approval: the prior failure mode was JSON booleans becoming money/size values through `float(True)`. The latest fix closes that for `paper_trade_results` and restored open positions, but not for this paper reporting USD depth metric.

## MEDIUM

### Non-string reject reasons can crash report generation after the split

`src/polysignal_lab/paper/report_rejections.py:39-44` assumes `reason` is `str | None` and calls `reason.startswith("PAPER_")`. The caller at `src/polysignal_lab/paper/report.py:168-172` passes values from JSON-backed `metrics` or `reject_reason` without a runtime type check.

Exact probe:

```bash
.venv/bin/python - <<'PY'
from datetime import date
from polysignal_lab.paper.report import PaperReportService
try:
    PaperReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=1,
        paper_orders=1,
        paper_fills=0,
        rejected_paper_orders=1,
        open_positions=0,
        results=[],
        paper_order_payloads=[{"status": "REJECTED", "metrics": {"paper_normalized_reason": True}}],
    )
except Exception as exc:
    print(type(exc).__name__, str(exc))
PY
```

Observed output:

```text
AttributeError 'bool' object has no attribute 'startswith'
```

This is not a money corruption path, but it is malformed JSON behavior that does not fail closed.

### Full project typecheck is not currently a clean gate

The scoped changed-file typecheck passed, but the full project command does not. If `paper-final-basedpyright.txt` is intended as whole-repo evidence, it is not reproduced by the actual whole-repo command.

Exact evidence:

```text
$ .venv/bin/basedpyright
327 errors, 6752 warnings, 0 notes
```

Scoped check:

```text
$ .venv/bin/basedpyright src/polysignal_lab/domain/paper_result.py src/polysignal_lab/storage/sqlite_store.py src/polysignal_lab/paper/report.py src/polysignal_lab/paper/report_rejections.py tests/test_storage_restore.py tests/test_reporting.py
0 errors, 290 warnings, 0 notes
```

## LOW

None.

## Passing Evidence

- `src/polysignal_lab/domain/paper_result.py:193-205` rejects booleans before numeric coercion in `_finite_float`, and also rejects non-finite, negative where disallowed, and zero where disallowed.
- `src/polysignal_lab/storage/sqlite_store.py:104-115` rejects booleans before numeric coercion in `_row_finite_float`.
- `src/polysignal_lab/storage/sqlite_store.py:72-101` applies positive/finite/timestamp checks to restored position events, so boolean and zero money fields are excluded from open-position restores.
- `src/polysignal_lab/storage/sqlite_store.py:403-424` skips malformed `paper_trade_results`, `system_events`, and `daily_reports` payload JSON on restore/query surfaces.
- `tests/test_storage_restore.py:204-237` covers zero-money paper trade rows.
- `tests/test_storage_restore.py:240-273` covers boolean-money paper trade rows for both API insert and hostile persisted rows.
- `tests/test_storage_restore.py:276-382` covers malformed JSON/timestamp payloads for trade rows, system events, and daily reports.
- `tests/test_storage_restore.py:588-655` covers zero and boolean money fields in restored open position events.
- `tests/test_reporting.py:251-308` covers legacy raw reject reason normalization and cancelled reject reason counting.

Commands run during review:

```text
$ .venv/bin/python -m pytest tests/test_storage_restore.py::test_sqlite_store_rejects_boolean_money_paper_trade_rows tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_with_boolean_money tests/test_storage_restore.py::test_sqlite_store_rejects_zero_money_paper_trade_rows tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_with_zero_money tests/test_storage_restore.py::test_sqlite_store_skips_malformed_payload_paper_trade_rows tests/test_storage_restore.py::test_sqlite_store_skips_malformed_system_events tests/test_storage_restore.py::test_sqlite_store_skips_malformed_daily_reports -q
.......                                                                  [100%]

$ .venv/bin/python -m pytest tests/test_reporting.py::test_daily_report_normalizes_legacy_raw_paper_reject_reason tests/test_reporting.py::test_daily_report_counts_cancelled_rejects_with_reasons -q
..                                                                       [100%]

$ .venv/bin/python -m pytest -q
[100%], warnings only

$ git diff --check
exit 0, no output
```

Inspected supplied artifacts:

- `.omo/ulw-loop/evidence/paper-bool-money-red.txt`: both adversarial tests failed before the fix (`DID NOT RAISE InvalidPaperTradeResultRow`; boolean open positions restored).
- `.omo/ulw-loop/evidence/paper-bool-money-green.txt`: the two named adversarial tests passed.
- `.omo/ulw-loop/evidence/paper-final-focused-pytest.txt`: 14 focused tests passed.
- `.omo/ulw-loop/evidence/paper-final-full-pytest.txt`: full pytest completed at 100% with warnings only.
- `.omo/ulw-loop/evidence/paper-final-basedpyright.txt`: scoped output ended with `0 errors, 443 warnings, 0 notes`.
- `.omo/ulw-loop/evidence/paper-final-refs-check.txt`: `PASS no protected refs/docs/nautilus_reference changes`.

Protected path status verified:

```text
$ git diff --name-only -- refs @refs docs/nautilus_reference
<no output>

$ git diff -- docs/nautilus_reference | wc -c
0
```

Dirty worktree note: the checkout has many unrelated modified/untracked files. I did not edit production or test files; this report artifact is the only file I created.
