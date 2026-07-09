recommendation: REJECT

blockers:
- Current-scope security boundary crash in `SQLiteStore.restore_latest_wallet_snapshot()`.
  A valid JSON wallet snapshot with a huge integer `open_position_count` raises
  `OverflowError: int too large to convert to float` instead of failing closed to
  `None`. The crash is in `_valid_count_value()` at
  `src/polysignal_lab/storage/sqlite_store.py:158-165`, where `float(parsed)` is
  called after `int(value)` succeeds. This is in the final paper/reporting/storage
  hardening scope and is the same persisted-payload class as the required wallet
  restore security probe.

originalIntent: Continue the unfinished Nautilus alignment refactor from cursor
and omp sessions without committing, preserve the dirty working tree, and keep
the protected `refs`, `@refs`, and `docs/nautilus_reference` subset unchanged.
The intended completed slices are the OrderBook data-boundary safe slice, paper
model/converter/schema cleanup, R10 direct cache calls, and final
paper/reporting/storage hardening.

desiredOutcome: Return APPROVE only if current source and current evidence prove
the intended slices pass focused/full tests, no-excuse, basedpyright error gate,
compileall, diff-check, refs-check, corrected manual QA, debug/security audit,
and the direct `programming` plus `remove-ai-slops` review finds no current-scope
bug, false-confidence test, slop, or scope drift.

userOutcomeReview: CHANGES_REQUESTED. The required artifacts are present and most
current gates pass, but the shipped storage boundary still has a reproducible
crash on hostile valid JSON. From the user's perspective, the final hardening is
not complete because malformed persisted wallet state can still crash restore
instead of producing the expected safe `wallet_restore None` outcome.

checked artifact paths:
- `.omo/evidence/paper-final-current-code-review.md` - APPROVE; includes
  explicit `programming`, `remove-ai-slops`, and ponytail skill-perspective
  coverage.
- `.omo/evidence/paper-final-current-qa-corrected/manual-qa-verdict.md` - PASS;
  focused smoke is documented as 56 tests and protected subset PASS.
- `.omo/evidence/paper-final-current-qa-corrected/focused-smoke-pytest.txt` -
  current corrected focused smoke reached `[100%]`, exit 0.
- `.omo/evidence/paper-final-current-qa-corrected/protected-subset.txt` -
  protected subset status/diff PASS.
- `.omo/evidence/paper-final-current-qa-corrected/required-artifacts.txt` -
  required artifacts non-empty.
- `.omo/evidence/paper-final-current-qa-corrected/cleanup-receipt.txt` - no
  runtime resources spawned.
- `.omo/evidence/paper-final-current-security-review.md` - stale
  CHANGES_REQUESTED; inspected as prior blocker context.
- `.omo/evidence/paper-final-current-security-review-2.md` - stale
  CHANGES_REQUESTED; inspected as prior closed-position/confidence blocker
  context.
- `.omo/ulw-loop/evidence/paper-final-focused-pytest.txt` - focused artifact
  reaches `[100%]`.
- `.omo/ulw-loop/evidence/paper-final-full-pytest.txt` - full pytest artifact
  reaches `[100%]` with only third-party warnings.
- `.omo/ulw-loop/evidence/paper-final-no-excuse.txt` - `no violations in 18 file(s)`.
- `.omo/ulw-loop/evidence/paper-final-basedpyright.txt` - `0 errors`, warnings only.
- `.omo/ulw-loop/evidence/paper-final-compileall.txt` - compileall exit 0.
- `.omo/ulw-loop/evidence/paper-final-diff-check.txt` - git diff check PASS.
- `.omo/ulw-loop/evidence/paper-final-refs-check.txt` - protected refs/docs check PASS.
- `.omo/ulw-loop/evidence/paper-final-debug-audit.md` - includes closed-position
  and confidence blockers as H5/H6, marked refuted after fixes.
- `.omo/ulw-loop/evidence/paper-final-security-probe.txt` - shows
  `wallet_restore None`, `daily_reports []`, `leaderboard []`,
  `closed_positions []`, and `confidence_bucket low`.
- `.omo/ulw-loop/evidence/paper-closed-position-state-red.txt`
- `.omo/ulw-loop/evidence/paper-closed-position-state-green.txt`
- `.omo/ulw-loop/evidence/paper-confidence-bad-red.txt`
- `.omo/ulw-loop/evidence/paper-confidence-bad-green.txt`
- `/tmp/ulw-20260709-135652.1pSjBM.md` - gate-review notepad.

direct verification:
- `PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_paper_report_boundaries.py tests/test_storage_restore.py tests/test_nautilus_reporting_cache_source.py tests/test_reporting.py tests/test_strategy_stats.py -q`
  -> PASS, 56 tests reached `[100%]`.
- `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q` -> PASS, full suite reached
  `[100%]`, with only Nautilus/Pandas deprecation warnings.
- `PYTHONDONTWRITEBYTECODE=1 uv run python .../check-no-excuse-rules.py <18 scoped files>`
  -> PASS, `no violations in 18 file(s)`.
- `PYTHONDONTWRITEBYTECODE=1 uv run basedpyright <18 scoped files>` -> PASS
  for the required error gate, `0 errors, 495 warnings, 0 notes`.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/paper-final-current-gate-review-4-pycache uv run python -m compileall -q src tests`
  -> PASS; temp pycache prefix removed.
- `git diff --check` -> PASS.
- `git status --short -- refs @refs docs/nautilus_reference` -> PASS, no output.
- `git diff --name-only -- refs @refs docs/nautilus_reference` -> PASS, no output.
- Direct adversarial wallet probe with huge integer `open_position_count` ->
  FAIL, printed `OverflowError int too large to convert to float`.

remove-ai-slops/programming direct pass:
- Report coverage exists in `.omo/evidence/paper-final-current-code-review.md`,
  and I also loaded the current `programming` and `remove-ai-slops` skills for
  this gate.
- No deletion-only tests, tautological tests, implementation-mirroring tests, or
  needless production extraction were found in the inspected current focused
  tests and production paths.
- The direct pass did find unresolved over-defensive/parse-boundary slop:
  `_valid_count_value()` attempts a float round-trip on untrusted persisted JSON
  counts and can crash on a huge integer. This creates false confidence because
  the existing hostile wallet probe covers `NaN`/bool money but not an oversized
  count that trips the same restore boundary.

checked source/test paths:
- `src/polysignal_lab/storage/sqlite_store.py`
- `src/polysignal_lab/domain/paper_result.py`
- `src/polysignal_lab/domain/paper_report.py`
- `src/polysignal_lab/paper/report.py`
- `src/polysignal_lab/paper/report_aggregates.py`
- `src/polysignal_lab/paper/report_rejections.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/app/scheduler_reporting_build.py`
- `src/polysignal_lab/app/scheduler_reporting_equity.py`
- `src/polysignal_lab/app/scheduler_reporting_sources.py`
- `src/polysignal_lab/app/scheduler_reporting_storage.py`
- `src/polysignal_lab/app/scheduler_reporting_types.py`
- `tests/test_storage_restore.py`
- `tests/test_paper_report_boundaries.py`
- `tests/test_nautilus_reporting_cache_source.py`
- `tests/test_reporting.py`
- `tests/test_strategy_stats.py`

exact evidence gaps:
- Current required evidence proves one hostile wallet case returns
  `wallet_restore None`, but it does not cover huge persisted count integers.
- No current artifact demonstrates `restore_latest_wallet_snapshot()` fails
  closed for oversized `open_position_count`; my direct probe shows it crashes.
- The current APPROVE code-review report does not mention or refute this overflow
  class, so approval would be unsupported.

cleanupState: This gate spawned no server, browser, tmux session, container, or
bound port. The compileall temp pycache prefix
`/tmp/paper-final-current-gate-review-4-pycache` was removed. The direct wallet
probe used `TemporaryDirectory()` and exited.
