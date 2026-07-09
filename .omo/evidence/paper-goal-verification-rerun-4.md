recommendation: REJECT
verdict: FAIL
confidence: high

# Paper Goal Verification Rerun 4

<verdict>FAIL</verdict>

## originalIntent

Continue the two-session Nautilus alignment refactor without committing, preserve the dirty worktree, do not modify `refs`, `@refs`, or `docs/nautilus_reference`, and complete the real ULW criteria rather than the placeholder duplicate auto-split goals.

The concrete current criteria are G001-G003:

- G001: OrderBook boundary parser / safe-slice migration completed.
- G002: paper/converter/domain/schema/R10 verification completed.
- G003: prior paper model/converter/schema/R10 completion bundle verified.
- G004-G014: intentionally blocked duplicate placeholder fragments already covered by G001-G003.

## desiredOutcome

The user-visible result should be a current approvable completion package where malformed paper trade rows and incomplete or invalid position state cannot leak through storage, dashboard, repair, reporting, cache, or publish paths, and where current tests, manual QA, static checks, protected-path checks, code review, and security/context review all support completion.

## userOutcomeReview

The latest storage/dashboard/repair fixes materially improved the outcome. Current artifacts show focused pytest `55 passed`, full pytest `670 passed`, basedpyright `0 errors`, compileall/diff/refs/focused no-excuse pass, and manual QA markers for `repair_missing_side`, `dashboard_missing_side`, `dashboard_invalid_opened_at`, `storage_missing_side`, and `storage_invalid_opened_at`.

I still cannot pass the final gate. There is no current approving code-review artifact after the latest fixes, and the newest context review still reports remaining downstream paper-position side fabrication. Direct source inspection and a direct runtime probe confirm that at least two current paths still default missing or unresolved position side to `UP`.

## blockers

1. HIGH: No current approving code-review artifact exists for the latest source.
   - Latest code-review report: `.omo/evidence/paper-code-review-rerun-3.md` at `2026-07-09 04:20:00 +0200`, verdict `FAIL`, recommendation `REQUEST_CHANGES`.
   - Newer regenerated evidence exists at `04:43`-`04:45`, but it is test/manual evidence only, not a current code-review approval.
   - The final-gate requirement cannot be satisfied from stale or rejecting review artifacts.

2. HIGH: Current source still contains downstream side fabrication.
   - `src/polysignal_lab/app/_settlement_check.py:245-255` returns `Side.UP` when projection side is absent/invalid and `token_id` cannot be matched to a market outcome token.
   - Direct probe result: `_paper_trade_result_from_projection()` on a cancelled projection with unknown token and no side produced `settlement_check_result_side= UP`.
   - `src/polysignal_lab/publish/telegram_bot.py:668-692` defaults display payload side to `UP` when no side is present.
   - Direct probe result: `_position_display_payload({"position_id":"p1","token_id":"t1","entry_price":0.5,"quantity":2})["side"] == "UP"`.

3. MEDIUM: Latest context review is still a current FAIL after the regenerated evidence.
   - `.omo/evidence/paper-context-rerun-5.md` at `2026-07-09 04:50:05 +0200` has `<verdict>FAIL</verdict>`.
   - It agrees that `SQLiteStore.restore_open_positions()` is now fail-closed, but still flags downstream presentation/repair/publish side fallback paths.

## findings

- PASS: `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/goals.json` marks G001-G003 complete and G004-G014 blocked as duplicate auto-split fragments.
- PASS: `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt` records `55 passed, 2 warnings`.
- PASS: `.omo/ulw-loop/evidence/paper-full-pytest.txt` records `670 passed, 2 warnings`.
- PASS: `.omo/ulw-loop/evidence/paper-blockers-basedpyright.txt` records `0 errors` with warnings.
- PASS: `.omo/ulw-loop/evidence/paper-compileall.txt`, `paper-diff-check.txt`, `paper-refs-check.txt`, and `paper-no-excuse-security-scope.txt` record pass.
- PASS: direct rerun of the current focused storage/dashboard/repair regression tests passed `6 passed`.
- FAIL: direct source/probe review found remaining `UP` fallback fabrication in `_settlement_check.py` and `telegram_bot.py`.

## slopAndProgrammingReview

- `remove-ai-slops` direct pass: the focused new tests for missing side and invalid `opened_at` are behavioral, not deletion-only, tautological, or implementation-mirroring. They assert observable storage/dashboard/repair exclusion.
- `programming` direct pass: the remaining downstream defaults violate parse-don't-validate and fail-closed boundary expectations because unknown side is converted to a concrete trade direction.
- Report-coverage check: `.omo/evidence/paper-code-review-rerun-3.md` includes explicit `remove-ai-slops` and `programming` coverage, but its verdict is `FAIL`; no newer approving report supersedes it.

## checked artifact paths

- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/brief.md`
- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/goals.json`
- `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-full-pytest.txt`
- `.omo/ulw-loop/evidence/paper-blockers-basedpyright.txt`
- `.omo/ulw-loop/evidence/paper-compileall.txt`
- `.omo/ulw-loop/evidence/paper-diff-check.txt`
- `.omo/ulw-loop/evidence/paper-refs-check.txt`
- `.omo/ulw-loop/evidence/paper-no-excuse-security-scope.txt`
- `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`
- `.omo/evidence/paper-code-review-rerun-3.md`
- `.omo/evidence/paper-security-rerun-4.md`
- `.omo/evidence/paper-context-rerun-5.md`
- `.omo/evidence/paper-goal-verification-rerun-3.md`
- `src/polysignal_lab/storage/sqlite_store.py`
- `tests/test_storage_restore.py`
- `src/polysignal_lab/dashboard/app.py`
- `tests/test_dashboard.py`
- `scripts/repair_settlement_results.py`
- `tests/test_repair_settlement_results.py`
- `src/polysignal_lab/app/_settlement_check.py`
- `src/polysignal_lab/publish/telegram_bot.py`
- `tests/test_telegram_bot_service.py`
- `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/remove-ai-slops/SKILL.md`
- `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/SKILL.md`
- `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/references/python/README.md`

## exact evidence gaps

- No post-`04:43` approving code-review artifact covers the latest missing-side and invalid-`opened_at` fixes.
- No current security/context approval supersedes `.omo/evidence/paper-context-rerun-5.md`, which is a newer FAIL artifact.
- No test covers the cancelled settlement projection case where `token_id` is unmapped and `side` is missing, yet `_paper_trade_result_from_projection()` emits `Side.UP`.
- No test covers Telegram open-position display with a missing side; direct helper output still defaults to `UP`.

## finalRecommendation

REJECT / FAIL. The latest focused evidence is improved, but the current artifact set and direct code/probe review do not support final completion.
