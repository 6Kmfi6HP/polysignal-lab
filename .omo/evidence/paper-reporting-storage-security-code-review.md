# Paper Reporting/Storage Security Review

Verdict: FAIL

codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: .omo/evidence/paper-reporting-storage-security-code-review.md

## Skill-Perspective Check

- `remove-ai-slops`: ran by loading `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/remove-ai-slops/SKILL.md`. Violation found: adversarial invalid-money coverage misses JSON booleans, so green zero-money tests create false confidence for a still-accepted invalid numeric payload.
- `programming`: ran by loading `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/SKILL.md` and `references/python/README.md`. Violation found: boundary parsing accepts `bool` as numeric because Python `bool` is an `int` subclass.

## CRITICAL

None.

## HIGH

1. Invalid JSON boolean money values are accepted as real money/size values.

   Evidence:
   - `src/polysignal_lab/domain/paper_result.py:193-205` accepts `int | float | str`, then `float(value)`. In Python, `True` is an `int`, so `shares=True` parses as `1.0`.
   - `src/polysignal_lab/storage/sqlite_store.py:104-115` uses the same `int | float | str` check for restored position events, so `shares=True` is treated as a valid positive open-position size.
   - `tests/test_storage_restore.py:170-237` covers `NaN` and zero-money rows, but has no boolean numeric adversary.
   - Current focused tests still pass: `uv run pytest tests/test_storage_restore.py tests/test_reporting.py -q` -> `27 passed`.
   - Current zero-money tests still pass: `uv run pytest tests/test_storage_restore.py::test_sqlite_store_rejects_zero_money_paper_trade_rows tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_with_zero_money -q` -> `2 passed`.
   - Direct proof:

     ```text
     PYTHONPATH=tests uv run python - <<'PY'
     ...
     row["shares"] = True
     store.insert_paper_trade_result(row)
     print({"accepted": accepted, "err": err, "restored_shares": store.query_json("paper_trade_results")[0]["shares"]})
     PY
     {'accepted': True, 'err': '', 'restored_shares': 1.0}
     ```

   - Position restore proof:

     ```text
     uv run python - <<'PY'
     ...
     "shares": True,
     print({"restored_count": len(restored), "restored_shares": restored[0]["shares"] if restored else None})
     PY
     {'restored_count': 1, 'restored_shares': True}
     ```

   Impact: a hostile or corrupted JSON row can fabricate a non-zero share/money value using `true`, bypassing the zero-money fail-closed intent in both trade-result restore and open-position restore.

## MEDIUM

None.

## LOW

None.

## Non-Blocking Checks

- Malformed JSON syntax is not accepted on scoped restore paths: `sqlite_store.py:407-423` catches `json.JSONDecodeError` for `paper_trade_results`, `system_events`, and `daily_reports`; `tests/test_storage_restore.py:240-347` covers malformed payload skips.
- Existing duplicate rows with malformed payload JSON fail closed: `sqlite_store.py:517-524` raises `MalformedSQLitePayloadError`; `tests/test_storage_restore.py:349-375` covers it.
- Reject reason semantics appear preserved across the `report.py` split: `report_helpers.py:25-56` contains the same normalization map and fallback behavior, and `tests/test_reporting.py:251-308` covers legacy raw and cancelled reject reasons.
- Protected `refs` modifications were not observed: `git status --short refs`, `git diff -- refs`, and `git ls-files -o --exclude-standard refs` all produced no output.
- Evidence artifacts inspected:
  - `.omo/ulw-loop/evidence/paper-zero-money-red.txt` shows the prior zero-money red failure.
  - `.omo/ulw-loop/evidence/paper-zero-money-green.txt` shows `2 passed`.
  - `.omo/ulw-loop/evidence/paper-zero-money-focused-pytest.txt` shows `27 passed`.
  - `.omo/ulw-loop/evidence/paper-zero-money-full-pytest.txt` shows full pytest passing.
  - `.omo/ulw-loop/evidence/paper-zero-money-no-excuse.txt` shows `no violations in 10 file(s)`.
  - `.omo/ulw-loop/evidence/paper-zero-money-basedpyright.txt` shows `0 errors, 410 warnings, 0 notes`.

## Blockers

- Reject JSON booleans for all paper trade-result numeric fields and restored open-position money/size fields, then add focused adversarial tests proving `true`/`false` are rejected or skipped.
