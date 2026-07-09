# Paper Code Review Rerun 6

codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: .omo/evidence/paper-code-review-rerun-6.md
blockers:
- `src/polysignal_lab/app/_settlement_check.py:187` still fabricates missing live-position money fields as zero and can persist a settled WIN row with `entry_price=0.0`, `shares=0.0`, and `stake_usdc=0.0`.

## CRITICAL

None.

## HIGH

1. `src/polysignal_lab/app/_settlement_check.py:187`: live settlement still converts incomplete Nautilus projections into valid-looking paper results instead of failing closed.

   `_paper_trade_result_from_projection()` computes `quantity` and `entry_price` with `... or 0.0`, then derives `stake` as `quantity * entry_price` when absent (`src/polysignal_lab/app/_settlement_check.py:187`, `src/polysignal_lab/app/_settlement_check.py:197`). The result payload then persists those fabricated zero values while still marking the trade according to settlement outcome (`src/polysignal_lab/app/_settlement_check.py:241`, `src/polysignal_lab/app/_settlement_check.py:249`).

   I verified the current code path with a direct probe: a projection containing a valid side/token/timestamp but no quantity, entry price, or stake returned a result with `entry_price: 0.0`, `shares: 0.0`, `stake_usdc: 0.0`, `settlement_value: 0.0`, and `result: 'WIN'`. That is the same fail-open class the refactor is trying to remove: incomplete paper state becomes durable audit data rather than being skipped.

   Required fix: treat missing/non-finite/zero-or-invalid money fields on live settlement projections the same way storage and repair now treat them: return `None` before building a paper result, and add a focused regression in `tests/test_scheduler_settlement_resolution.py`.

## MEDIUM

1. Strict typing remains weak in the reviewed surface. A fresh targeted `basedpyright` run exited with `0 errors, 439 warnings`, including many `Any` and private-use warnings in `scripts/repair_settlement_results.py`, `src/polysignal_lab/app/_settlement_check.py`, and `src/polysignal_lab/storage/sqlite_store.py`. This is not the immediate behavior blocker, but it violates the programming skill perspective and makes the dict-row refactor harder to review.

## LOW

1. Two requested evidence artifacts, `.omo/ulw-loop/evidence/paper-post-malformed-diff-check.txt` and `.omo/ulw-loop/evidence/paper-post-malformed-refs-check.txt`, are zero-byte even though `.omo/ulw-loop/evidence/paper-post-malformed-verification-summary.txt` says those checks passed. I reran `git diff --check` successfully during this review, so this is an evidence hygiene issue rather than the blocker.

## Skill-Perspective Check

- `remove-ai-slops`: ran by loading the full skill. The malformed-payload tests are not deletion-only, tautological, or implementation-constant mirrors; they exercise corrupted persisted rows through `SQLiteStore.query_json()`. The HIGH finding is production slop: missing numeric fields are normalized to zeros in a paper-result path where the goal requires fail-closed behavior.
- `programming`: ran by loading the full skill plus Python README, code-smells, error-handling, and httpx2 references. The HIGH finding violates parse-don't-validate/fail-closed discipline at a production boundary. The targeted typecheck warnings are recorded as MEDIUM typed debt.

## Evidence Inspected

- Current working-tree status and diff: broad refactor, 68 tracked files changed, plus untracked evidence/new tests.
- Scoped source inspected: `src/polysignal_lab/storage/sqlite_store.py`, `tests/test_storage_restore.py`, `src/polysignal_lab/app/_settlement_check.py`, `src/polysignal_lab/publish/telegram_bot.py`, `scripts/repair_settlement_results.py`, `src/polysignal_lab/nautilus_runtime/__init__.py`, plus adjacent `domain/paper_result.py`, `persistence_service.py`, and settlement tests.
- Requested artifacts inspected:
  - `.omo/ulw-loop/evidence/paper-post-malformed-focused-pytest.txt`: focused suite passed, `29 passed`.
  - `.omo/ulw-loop/evidence/paper-post-malformed-system-python-focused-pytest.txt`: passed.
  - `.omo/ulw-loop/evidence/paper-post-malformed-basedpyright.txt`: `0 errors, 549 warnings`.
  - `.omo/ulw-loop/evidence/paper-malformed-payload-pytest.txt`: `3 passed`.
  - `.omo/ulw-loop/evidence/paper-malformed-payload-basedpyright.txt`: `0 errors, 182 warnings`.
  - `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`: missing-side/timestamp probes passed.
  - Prior rerun reports were treated as stale context only.

## Fresh Checks Run

- `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_storage_restore.py tests/test_scheduler_settlement_resolution.py tests/test_repair_settlement_results.py`: passed, 25 tests.
- `PYTHONDONTWRITEBYTECODE=1 uv run basedpyright src/polysignal_lab/storage/sqlite_store.py tests/test_storage_restore.py src/polysignal_lab/app/_settlement_check.py src/polysignal_lab/publish/telegram_bot.py scripts/repair_settlement_results.py src/polysignal_lab/nautilus_runtime/__init__.py`: `0 errors, 439 warnings`.
- `git diff --check`: passed.
- `compileall` on reviewed production files: passed.
- Manual storage probe: malformed `paper_trade_results.payload_json` returned `[]`; malformed `signals.payload_json` still raised `JSONDecodeError`, matching the latest storage requirement.
- Manual live settlement probe: incomplete projection without money fields returned a fabricated zero-money WIN result, confirming the HIGH blocker.

## Verdict

FAIL. The latest malformed `paper_trade_results` storage fix is correct, but the current diff still has a blocking live settlement path that fabricates missing money fields into durable paper trade results.

<verdict>FAIL</verdict>
