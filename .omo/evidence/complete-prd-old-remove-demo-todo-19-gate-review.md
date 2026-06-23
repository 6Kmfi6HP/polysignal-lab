recommendation: APPROVE
verdict: CONFIRM
follow_up_review: 2026-06-22 repair recheck supersedes the initial rejection below.

# Todo 19 Gate Review

## Follow-up Repair Review

Follow-up verdict: CONFIRM.

The focused repair addresses the original blockers. `docs/PRD_GAP_ANALYSIS.md` is now a dated 2026-06-22 completion status document and explicitly says it replaces the 2026-06-21 baseline. It no longer presents current AC-002/003/004 failures, incomplete settlement/runtime/storage/Docker work, or a 69+ real Telegram delivery claim. It now states that the real Telegram path exists, dry-run/no-credential behavior is evidenced, and actual channel delivery is deferred to Todo 20 with externally exported credentials.

The repaired self-review now supports the repair: `.omo/evidence/complete-prd-old-remove-demo-todo-19-code-review.md` explicitly covers the GAP doc repair, stale-doc removal, semantic overfit guard, command accuracy, safety scan, help commands, and env secrecy. My direct remove-ai-slops/programming pass found no unresolved documentation slop in the repaired Todo 19 scope.

## Follow-up Commands Run

- `rg "PRD-old|real Telegram|safety_scan.py|scheduler|dashboard|generated history" README.md docs && ! rg "offline demo|fake data|demo run|polysignal-demo" README.md docs`
  - Exit 0. Required current terms matched and stale demo literals did not.

- `! rg "offline demo|fake data|demo run|polysignal-demo|PRIVATE_KEY|create_order|redeem" README.md docs`
  - Exit 0. Exact failure QA command found no forbidden literals.

- `rg -n "69\\+|40%|0%|AC-002.*(fail|失败|❌)|AC-003.*(fail|失败|❌)|AC-004.*(fail|失败|❌)|AC-010.*(incomplete|未|仍需|⚠️)|TELEGRAM.*69|Telegram.*69|已发送|未接入|待接|最大差距|必须修复|未实现|current.*gap|current.*blocker|still needs|still incomplete|not wired|not connected" docs/PRD_GAP_ANALYSIS.md README.md docs/IMPLEMENTATION_SUMMARY.md docs/TEST_RESULTS.md docs/PRD_OLD_COMPLIANCE.md`
  - Exit 0 only because the broad `0%` pattern matched benign `100%` substrings in `docs/PRD_OLD_COMPLIANCE.md:79-82`; it did not match stale failure/current-gap claims in `docs/PRD_GAP_ANALYSIS.md`.

- `rg -n "real Telegram|Telegram.*(sent|delivered|message id|delivery|channel delivery|TELEGRAM_NOT_CONFIGURED|externally exported|Todo 20|dry-run|dry_run|69\\+)" README.md docs .omo/evidence/task-19-complete-prd-old-remove-demo.txt .omo/evidence/complete-prd-old-remove-demo-todo-19-code-review.md .omo/evidence/todo-19-manual-qa-notepad.md`
  - Exit 0. Matches now describe dry-run/no-credential evidence or Todo 20 external-credential delivery; no unsupported actual-delivery claim remains.

- `.venv/bin/python scripts/safety_scan.py .`
  - Exit 0. Output: `Safety scan passed`.

- `.venv/bin/python -m polysignal_lab.app.main --help && .venv/bin/python -m polysignal_lab.publish.telegram_qa --help`
  - Exit 0. Main help shows scheduler/dashboard/smoke plus `--once`, `--real-readonly-smoke`, and `--evidence`; Telegram QA help shows `--live`, `--evidence`, `--message`, `--message-type`, `--max-chars`, and `--retry-attempts`.

## Follow-up Checked Artifacts

- `docs/PRD_GAP_ANALYSIS.md`
- `.omo/evidence/task-19-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-19-code-review.md`
- `.omo/evidence/todo-19-manual-qa-notepad.md`
- `.omo/evidence/todo-19-repair-exact-acceptance.txt`
- `.omo/evidence/todo-19-repair-exact-failure-qa.txt`
- `.omo/evidence/todo-19-repair-gap-required-rg.txt`
- `.omo/evidence/todo-19-repair-gap-semantic-scan.txt`
- `.omo/evidence/todo-19-repair-safety-scan.txt`
- `.omo/evidence/todo-19-repair-main-help.txt`
- `.omo/evidence/todo-19-repair-telegram-help.txt`
- `.omo/evidence/todo-19-repair-whitespace-conflict-scan.txt`

## Follow-up Residual Risks

- Real Telegram channel delivery remains Todo 20 and still requires externally exported credentials plus redacted evidence containing a non-empty Telegram message id.
- The relevant docs/evidence files remain untracked in this dirty shared worktree, so normal tracked diff context is limited.
- I did not read `.env` or `.env*`.

## Initial Rejection History

## originalIntent

Refresh README, runbooks, implementation/compliance docs, test results, and related docs for the PRD-old completion work. The intended user-visible outcome is current documentation that describes the real scheduler, dashboard, safety scan, generated-history deletion, Telegram credential handling, real Telegram QA path, and PRD-old compliance without stale demo claims, false real-send claims, forbidden trading setup, or credential-handling instructions.

## desiredOutcome

A reader should be able to trust `README.md` and `docs/` as the current operator and compliance documentation: 120-test state, one FastAPI/Starlette warning, public read-only smoke, scheduler/dashboard modes, real Telegram command path requiring externally exported credentials, no `.env` QA instructions, no stale demo/product claims, and no forbidden trading setup.

## userOutcomeReview

The exact literal acceptance and failure greps pass, and the main README, implementation summary, test results, generated-history manifest, external API notes, and compliance ledger mostly describe the current runbook correctly.

However, the shipped docs still include a stale current-state gap report at `docs/PRD_GAP_ANALYSIS.md`. It says real data and WebSocket runtime wiring are still not connected, market settlement polling is unimplemented, current acceptance AC-002/003/004 fail, AC-010 still needs real outcome polling, and AC-006 has already sent 69+ Telegram messages. That directly conflicts with Todo 19's desired documentation outcome and with the instruction not to claim final real Telegram delivery already happened.

The executor evidence and code review also explicitly claim this file was refreshed, but the current artifact disproves that claim. This is a user-visible documentation blocker, not just a narrow grep issue.

## blockers

1. Stale user-facing gap analysis remains in `docs/PRD_GAP_ANALYSIS.md`.
   - `docs/PRD_GAP_ANALYSIS.md:16-18` still reports real data/WebSocket as only 40% and market settlement polling as 0%.
   - `docs/PRD_GAP_ANALYSIS.md:81-94` still says PRD real data flow remains to be connected end to end and repeated snapshots/signals are the observed problem.
   - `docs/PRD_GAP_ANALYSIS.md:105-107` still marks AC-002, AC-003, and AC-004 failed.
   - `docs/PRD_GAP_ANALYSIS.md:109` says Telegram has already sent 69+ messages, while the documented real-send artifact shows no real send occurred without credentials.
   - `docs/PRD_GAP_ANALYSIS.md:113` and `docs/PRD_GAP_ANALYSIS.md:136-147` still describe settlement/runtime/storage/Docker gaps as current work.

2. The self-review artifact is unsupported and misses the stale-doc blocker.
   - `.omo/evidence/complete-prd-old-remove-demo-todo-19-code-review.md:36-37` claims legacy PRD/GAP terms were rewritten and that the remove-ai-slops/overfit pass did not find invented success.
   - Current `docs/PRD_GAP_ANALYSIS.md` contradicts that review. The review's stale-doc and overfit coverage is therefore unsupported.

3. Todo 19 verification is overfit to literal greps.
   - The exact acceptance command passes, but it misses the stale Chinese/current-state claims and the `69+` Telegram-delivery claim in `docs/PRD_GAP_ANALYSIS.md`.
   - This is unresolved documentation slop under the remove-ai-slops/programming review criteria: the tests/checks create false confidence while leaving misleading user-visible docs.

## sourcePrdSanitizationDecision

The executor changed `docs/PRD-old.md` and `docs/PRD.md` to avoid forbidden literal terms such as `redeem`. I do not treat that as the blocker by itself. The current PRD docs still preserve high-level safety requirements and prohibitions, for example:

- `docs/PRD-old.md:11`, `docs/PRD-old.md:67`, `docs/PRD-old.md:116-118`, `docs/PRD-old.md:1012-1017`, `docs/PRD-old.md:1042-1047`
- `docs/PRD.md:11`, `docs/PRD.md:51-54`, `docs/PRD.md:96-102`, `docs/PRD.md:964-969`, `docs/PRD.md:994-999`

Those edits do not document forbidden setup or execution instructions. The blocker is that a separate source/history-like doc, `docs/PRD_GAP_ANALYSIS.md`, remains stale and misleading.

## commandsRun

- `rg "PRD-old|real Telegram|safety_scan.py|scheduler|dashboard|generated history" README.md docs && ! rg "offline demo|fake data|demo run|polysignal-demo" README.md docs`
  - Exit 0. Positive matches were present; forbidden demo literals were absent.

- `! rg "offline demo|fake data|demo run|polysignal-demo|PRIVATE_KEY|create_order|redeem" README.md docs`
  - Exit 0. No exact forbidden literals matched.

- `.venv/bin/python scripts/safety_scan.py .`
  - Exit 0. Output: `Safety scan passed`.

- `.venv/bin/python -m polysignal_lab.app.main --help`
  - Exit 0. Help shows `--mode {scheduler,dashboard,smoke}`, positional `{scheduler,dashboard,smoke}`, `--dashboard`, `--once`, `--real-readonly-smoke`, and `--evidence`.

- `.venv/bin/python -m polysignal_lab.publish.telegram_qa --help`
  - Exit 0. Help shows `--live`, `--evidence`, `--message`, `--message-type`, `--max-chars`, and `--retry-attempts`.

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider`
  - Exit 0. Output reached `[100%]` with 72 + 48 dots and the existing FastAPI/Starlette `httpx` deprecation warning.

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest --collect-only -q -p no:cacheprovider`
  - Exit 0. Per-file collected counts sum to 120 tests; the same FastAPI/Starlette warning appeared.

- `git diff --check -- README.md docs/IMPLEMENTATION_SUMMARY.md docs/TEST_RESULTS.md docs/PRD_OLD_COMPLIANCE.md docs/EXTERNAL_API_RESEARCH.md docs/GENERATED_HISTORY_DELETION.md docs/PRD_GAP_ANALYSIS.md docs/PRD-old.md docs/PRD.md`
  - Exit 0, no output. Caveat: these files are untracked in this worktree, so `git diff --check` does not meaningfully validate their content.

- `rg -n "[ \t]+$|<<<<<<<|=======|>>>>>>>" README.md docs/IMPLEMENTATION_SUMMARY.md docs/TEST_RESULTS.md docs/PRD_OLD_COMPLIANCE.md docs/EXTERNAL_API_RESEARCH.md docs/GENERATED_HISTORY_DELETION.md docs/PRD_GAP_ANALYSIS.md docs/PRD-old.md docs/PRD.md`
  - Exit 1, no matches. No trailing whitespace or conflict markers found by this fallback scan.

## checkedArtifactPaths

- `README.md`
- `docs/IMPLEMENTATION_SUMMARY.md`
- `docs/TEST_RESULTS.md`
- `docs/PRD_OLD_COMPLIANCE.md`
- `docs/EXTERNAL_API_RESEARCH.md`
- `docs/GENERATED_HISTORY_DELETION.md`
- `docs/PRD_GAP_ANALYSIS.md`
- `docs/PRD-old.md`
- `docs/PRD.md`
- `pyproject.toml`
- `scripts/safety_scan.py`
- `.omo/plans/complete-prd-old-remove-demo.md`
- `.omo/evidence/task-19-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-19-code-review.md`
- `.omo/evidence/todo-19-manual-qa-notepad.md`
- `.omo/evidence/todo-19-pytest.txt`
- `.omo/evidence/todo-19-safety-scan.txt`
- `.omo/evidence/todo-19-main-help.txt`
- `.omo/evidence/todo-19-telegram-help.txt`
- `.omo/evidence/todo-19-live-smoke.txt`
- `.omo/evidence/todo-19-live-smoke.json`
- `.omo/evidence/todo-19-telegram-dry-run-redacted.json`
- `.omo/evidence/todo-12-telegram-real-send-redacted.json`

## exactEvidenceGaps

- No artifact proves `docs/PRD_GAP_ANALYSIS.md` was actually refreshed; current file content proves the opposite.
- `.omo/evidence/task-19-complete-prd-old-remove-demo.txt:18-23` claims stale demo-era and early-baseline claims were replaced across the changed docs, including `docs/PRD_GAP_ANALYSIS.md`, but stale current-state claims remain.
- `.omo/evidence/complete-prd-old-remove-demo-todo-19-code-review.md:36-37` claims the PRD/GAP rewrite and overfit check passed, but it did not catch the stale GAP report.
- `.omo/evidence/todo-12-telegram-real-send-redacted.json:7-13` shows the live Telegram QA command was attempted without credentials and failed with `TELEGRAM_NOT_CONFIGURED`, so any documentation implying actual Telegram delivery is unsupported for Todo 19.
- Todo 19 evidence uses exact literal grep gates that miss semantically stale claims outside the English forbidden terms.

## residualRisks

- The docs are mostly correct outside `docs/PRD_GAP_ANALYSIS.md`, but because this stale file lives under `docs/` and was explicitly listed for inspection, a user can still receive contradictory current-state guidance.
- All relevant target files are untracked, so normal git diff review is unavailable. I preserved the dirty worktree and did not read `.env` or `.env*`.
