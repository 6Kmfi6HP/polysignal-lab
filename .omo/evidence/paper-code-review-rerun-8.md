# Paper Code Review Rerun 8

verdict: PASS
codeQualityStatus: WATCH
recommendation: APPROVE
reportPath: .omo/evidence/paper-code-review-rerun-8.md
notepadPath: /tmp/ulw-20260709-073730.YBLY2j.md
blockers: []

## CRITICAL

None.

## HIGH

None.

## MEDIUM

1. Typed debt remains in the reviewed settlement surface.

   Fresh `basedpyright` over the requested settlement/projection files completed with `0 errors, 176 warnings, 0 notes`. The warnings include explicit `Any` and unknown flows in `src/polysignal_lab/app/_settlement_check.py:55`, `:77`, `:91`, `:146`, `:188`, and `:320`, plus private import warnings in `tests/test_settlement.py:20` and `tests/test_scheduler_settlement_resolution.py:22`.

   I am not blocking rerun 8 on this because the prior zero-money blocker is fixed and this branch already carries dict-shaped storage compatibility work. Under the programming perspective it is still real debt, not clean strict-typing proof.

## LOW

1. `tests/test_scheduler_settlement_resolution.py:96` and `tests/test_scheduler_settlement_resolution.py:255` cover nearly the same unresolved-side scenario.

   This is small duplicate test coverage, not a false pass for the zero-money fix. It is worth trimming later, but it does not block approval.

2. `tests/FOLDER_INDEX.md:27` still names the removed deletion-only test.

   The actual deletion-only test is gone from `tests/test_settlement.py`, and behavior coverage replaced it. This index entry is stale metadata only.

## Rerun 7 Blocker Recheck

- Zero-valued money fields no longer produce a valid-looking WIN row: PASS.
  `src/polysignal_lab/app/_settlement_check.py:189-209` now reads `shares`/`quantity`, `entry_price`/`avg_entry_price`, and `stake_usdc`, then returns `None` when any is missing, non-finite, or `<= 0.0` before a result row is built.

- `project_position()` no longer fabricates missing money as zero: PASS.
  `src/polysignal_lab/nautilus_runtime/projections.py:80-86` uses optional parsing for `signed_qty` and `avg_px_open`, and only derives `stake_usdc` when both parsed values exist.

- Deletion-only settlement test is gone/replaced by behavior coverage: PASS.
  `tests/test_settlement.py:35-154` now covers settlement construction, missing timestamp, missing money, non-finite money, and zero money. The previous `test_paper_settlement_engine_module_is_removed` is absent.

- Scheduler behavior coverage exists: PASS.
  `tests/test_scheduler_settlement_resolution.py:336-403` covers missing money fields and invalid numeric money fields, including `0.0` for `quantity`, `avg_entry_price`, and `stake_usdc`, and asserts no insert happens.

- Manual QA evidence exists: PASS.
  `.omo/ulw-loop/evidence/paper-post-zero-money-manual-qa.txt` exists and records `settlement_zero_money None`, missing projected money fields as `None`, and a cleanup receipt.

## Skill-Perspective Check

- `remove-ai-slops`: ran by loading and applying the skill. No remaining deletion-only test, requested-removal-only test, tautological zero-money test, or implementation-constant mirror blocks this fix. The duplicate side-resolution scheduler tests are LOW slop only.
- `programming`: ran by loading the skill and Python README. The diff still carries typed debt through `Any`/private imports, but the zero-money behavior now fails closed at the settlement boundary and has focused behavior coverage. No HIGH programming violation remains for this rerun.

## Evidence Inspected

- Previous blocker report: `.omo/evidence/paper-code-review-rerun-7.md`
- Current source and tests:
  - `src/polysignal_lab/app/_settlement_check.py:42-52`, `:77-142`, `:182-263`
  - `src/polysignal_lab/nautilus_runtime/projections.py:77-98`, `:186-222`
  - `tests/test_settlement.py:35-154`
  - `tests/test_nautilus_projections.py:117-151`
  - `tests/test_scheduler_settlement_resolution.py:336-403`
- Existing evidence artifacts:
  - `.omo/ulw-loop/evidence/paper-zero-money-red.txt`: RED showed zero-money settlement returned a dict and missing projection money returned `0.0`.
  - `.omo/ulw-loop/evidence/paper-zero-money-green.txt`: `.. [100%]`.
  - `.omo/ulw-loop/evidence/paper-zero-money-scheduler-green.txt`: `........ [100%]`.
  - `.omo/ulw-loop/evidence/paper-post-zero-money-focused-pytest.txt`: `48 passed`.
  - `.omo/ulw-loop/evidence/paper-post-zero-money-system-python-focused-pytest.txt`: `48 passed`.
  - `.omo/ulw-loop/evidence/paper-post-zero-money-full-pytest.txt`: full suite pass.
  - `.omo/ulw-loop/evidence/paper-post-zero-money-basedpyright.txt`: `0 errors, 176 warnings, 0 notes`.
  - `.omo/ulw-loop/evidence/paper-post-zero-money-compileall.txt`: `compileall=pass`.
  - `.omo/ulw-loop/evidence/paper-post-zero-money-diff-check.txt`: `git diff --check=pass`.
  - `.omo/ulw-loop/evidence/paper-post-zero-money-refs-check.txt`: `refs_check=pass`.
  - `.omo/ulw-loop/evidence/paper-post-zero-money-manual-qa.txt`: manual QA pass with cleanup receipt.
  - `.omo/ulw-loop/evidence/paper-post-security-fix-summary.txt`: summary agrees with zero-money post-fix evidence.

## Fresh Commands Run

- `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_settlement.py tests/test_nautilus_projections.py tests/test_scheduler_settlement_resolution.py`
  - Result: `30 passed`.
- Manual probe with direct domain objects:
  - `settlement_zero_money None`
  - `project_position_missing_quantity None`
  - `project_position_missing_avg_entry_price None`
  - `project_position_missing_stake_usdc None`
- `PYTHONDONTWRITEBYTECODE=1 uv run basedpyright src/polysignal_lab/app/_settlement_check.py src/polysignal_lab/nautilus_runtime/projections.py tests/test_settlement.py tests/test_nautilus_projections.py tests/test_scheduler_settlement_resolution.py`
  - Result: `0 errors, 176 warnings, 0 notes`.
- `git diff --check`
  - Result: passed with no output.
- `git diff --name-only -- refs docs/nautilus_reference`
  - Result: no protected refs/reference-doc changes.

## Verdict

PASS. The rerun-7 zero-money blockers are fixed in source, covered by behavior tests, proven by RED/GREEN evidence, and confirmed by fresh focused pytest plus manual probing. Approval is WATCH rather than CLEAR because strict typing warnings and minor test metadata/slop remain.
