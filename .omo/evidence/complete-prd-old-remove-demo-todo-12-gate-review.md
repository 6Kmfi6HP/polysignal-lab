recommendation: REJECT
verdictForTodo12: NEEDS_FIX

# Todo 12 Gate Review

## originalIntent

Todo 12 asks to complete signal gate validation, formatter safety language, Telegram publisher/startup validation, dedupe/rate-limit behavior, token redaction, and a bounded real `sendMessage` QA path. It must not read `.env` and must not add real trading.

## desiredOutcome

Todo 12 can be checked off only if the implementation and artifacts prove:

- Gate rejections include PRD audit details and dedupe/rate-limit behavior is tested.
- Signal/result/daily Telegram messages include paper-only, no-profit-guarantee, and non-advice language where applicable.
- Missing and malformed live Telegram credentials fail before runtime work, while dry-run remains allowed.
- Publisher and QA evidence redact token/channel values and avoid HTTP requests for invalid credentials.
- The real-send QA command is bounded, writes accurate redacted evidence to the requested path, and does not misrepresent the command/status/path.
- The touched/relevant Python paths pass the requested programming and slop checks.
- No real trading/order path was added.

## userOutcomeReview

The main functional tests pass and the no-credential live path exits with redacted failure evidence. However, the shipped artifact does not satisfy the user's expected traceable QA outcome. `telegram_qa` hardcodes a misleading command string in evidence, so generated dry-run and live-failure artifacts record a different evidence path from the path actually written. The provided code review also claims quality grep coverage that is contradicted by a scoped grep over the user-requested relevant paths.

Todo 12 should not be marked complete.

## blockers

1. Misleading real-send/dry-run evidence command path.
   - Source: `src/polysignal_lab/publish/telegram_qa.py:91` to `src/polysignal_lab/publish/telegram_qa.py:94` hardcodes:
     `.venv/bin/python -m polysignal_lab.publish.telegram_qa --live --evidence .omo/evidence/final-telegram-real-send-redacted.json`
   - Fresh dry-run command wrote `.omo/evidence/todo-12-gate-dry-run-redacted.json`, but that artifact records the hardcoded final live path at `.omo/evidence/todo-12-gate-dry-run-redacted.json:6`.
   - Fresh live no-credential command wrote `.omo/evidence/todo-12-gate-live-unset-redacted.json`, but that artifact also records the hardcoded final live path at `.omo/evidence/todo-12-gate-live-unset-redacted.json:6`.
   - Existing Todo 12 evidence has the same issue in `.omo/evidence/todo-12-telegram-real-send-redacted.json:6` and `.omo/evidence/todo-12-telegram-dry-run-redacted.json:6`.
   - This directly violates the requested risk check for real-send QA traceability.

2. Requested quality grep is not clean over the relevant user-scoped paths.
   - Command found `src/polysignal_lab/app/scheduler.py:3:import asyncio`.
   - Command found broad exceptions in `src/polysignal_lab/app/scheduler_processing.py:36`, `:65`, `:67`, `:92`, `:105`, and `:119`.
   - The publish path specifically catches broad `Exception` at `src/polysignal_lab/app/scheduler_processing.py:105` around `scheduler.publisher.send(...)`.
   - The supplied code review claims "Escape-hatch grep ... no matches" at `.omo/evidence/complete-prd-old-remove-demo-todo-12-code-review.md:19`, but my scoped grep over the requested relevant files found matches.

3. Required slop/programming coverage is absent or unsupported in the code review report.
   - The code review report lists general checks but does not explicitly show `remove-ai-slops` overfit/slop criterion coverage or a programming skill-perspective pass.
   - My direct slop pass found an unresolved QA traceability slop: tests do not cover the evidence command/path, allowing `telegram_qa` to hardcode misleading success/failure provenance.
   - Per the gate instructions, absent/unsupported slop coverage is itself a rejection condition.

## checkedArtifactPaths

- `.omo/plans/complete-prd-old-remove-demo.md:195` to `.omo/plans/complete-prd-old-remove-demo.md:200`
- `.omo/evidence/task-12-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-12-code-review.md`
- `.omo/evidence/todo-12-manual-qa-notepad.md`
- `.omo/evidence/todo-12-telegram-real-send-redacted.json`
- `.omo/evidence/todo-12-telegram-dry-run-redacted.json`
- `.omo/evidence/todo-12-gate-dry-run-redacted.json`
- `.omo/evidence/todo-12-gate-live-unset-redacted.json`
- `docs/PRD-old.md:374` to `docs/PRD-old.md:442`
- `docs/PRD-old.md:996` to `docs/PRD-old.md:1047`
- `pyproject.toml`
- `src/polysignal_lab/app/scheduler.py`
- `src/polysignal_lab/app/scheduler_processing.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/app/scheduler_runtime.py` for startup-order confirmation
- `src/polysignal_lab/signal_layer/consensus.py`
- `src/polysignal_lab/signal_layer/deduper.py`
- `src/polysignal_lab/signal_layer/formatter.py`
- `src/polysignal_lab/signal_layer/gate.py`
- `src/polysignal_lab/signal_layer/rate_limit.py`
- `src/polysignal_lab/publish/telegram_publisher.py`
- `src/polysignal_lab/publish/telegram_qa.py`
- `tests/test_signal_gate.py`
- `tests/test_storage_reporting_publish.py`
- `tests/test_telegram_validation.py`

## commandsAndResults

- `git status --short`: dirty worktree with many modified/deleted/untracked files; generated fresh evidence files are untracked.
- `.venv/bin/python -m pytest tests/test_signal_gate.py tests/test_storage_reporting_publish.py tests/test_telegram_validation.py -q`: exit 0, `15 passed`; Starlette/httpx deprecation warning only.
- `.venv/bin/python -m pytest tests/test_telegram_validation.py::test_mocked_telegram_send_returns_sent_and_redacts_token tests/test_signal_gate.py::test_signal_deduper_prevents_duplicate_channel_publish -q`: exit 0, `2 passed`.
- `env -u TELEGRAM_BOT_TOKEN -u TELEGRAM_CHANNEL_ID .venv/bin/python -m pytest tests/test_telegram_validation.py::test_missing_telegram_credentials_fail_startup_when_publish_enabled -q`: exit 0, `1 passed`.
- Dry-run QA with fake exported Telegram values to `.omo/evidence/todo-12-gate-dry-run-redacted.json`: exit 0, status `DRY_RUN`, raw fake token/channel grep exit 1 no matches, but command path is wrong.
- Live QA with `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` unset to `.omo/evidence/todo-12-gate-live-unset-redacted.json`: exit 2, status `FAILED`, error `TELEGRAM_NOT_CONFIGURED`, but command path is wrong.
- `.venv/bin/python -m py_compile ...`: exit 0 for scoped Python files.
- Quality grep for `Any`, `cast(`, `type: ignore`, `import asyncio`, `from asyncio`, `import pandas`, broad exceptions, and raw `dict[str, Any]` / `dict[str, object]`: exit 0 with findings listed under blockers.
- Trading/order grep for real trading additions over scoped files: exit 1, no matches.
- Tight `.env`/dotenv grep over scoped files: exit 1, no matches.
- `git diff --check -- ...`: exit 0.

## adversarialChecks

- dirty_worktree: checked; broad dirty tree exists, and generated gate evidence files are untracked.
- stale_state: fresh evidence artifacts were generated during this review on 2026-06-22.
- misleading_success_output: failed because evidence command/path is hardcoded and misleading.
- malformed_input: relevant tests pass for missing/malformed credentials and invalid publisher credentials.
- token_redaction: raw fake token/channel grep over generated and provided Todo 12 evidence returned no matches.
- no_env_read: no `.env` or dotenv reads found in scoped code; commands did not read `.env`.
- real_send_path: bounded one-shot CLI exists and no-credential live run exits 2 with evidence, but evidence traceability fails.
- no_real_trading: scoped trading/order grep returned no matches.
- programming_quality: compile and LOC pass; scoped grep has forbidden findings in relevant paths.
- remove_ai_slops_overfit: failed due missing evidence-path test and hardcoded misleading command in production evidence writer.
- cleanup: no long-lived processes were started; generated review evidence files are retained for audit.

## exactEvidenceGaps

- No test asserts that `telegram_qa` evidence records the actual `--evidence` path or the actual dry-run/live command.
- The Todo 12 code review does not explicitly cover the remove-ai-slops overfit/slop criteria and is contradicted by scoped quality grep results.
- The executor evidence reports no escape-hatch grep matches but did not include all relevant paths requested for this gate review.

