**Todo 12 Code Review - Repair Pass**

Reviewed repair scope:
- `src/polysignal_lab/publish/telegram_qa.py`
- `tests/test_telegram_validation.py`
- `.omo/evidence/todo-12-manual-qa-notepad.md`
- `.omo/evidence/task-12-complete-prd-old-remove-demo.txt`

Programming perspective:
- `telegram_qa` now records provenance from parsed `TelegramQaOptions`: exact dry-run/live mode, actual evidence path, and an equivalent module command using that same path.
- Regression coverage was added for dry-run and live-failure QA evidence. Reverting the provenance fix makes both tests fail on missing `mode`/`evidence_path`.
- Touched Python files compile with `py_compile`.
- Pure LOC remains below the 250-line ceiling: `telegram_qa.py` 126, `test_telegram_validation.py` 134.
- Repair-file escape-hatch grep is clean for `Any`, `cast(`, `type: ignore`, `import asyncio`, `from asyncio`, `import pandas`, broad exceptions, and raw `dict[str, Any]` / `dict[str, object]`.

Remove-ai-slops / overfit perspective:
- The prior slop was traceability overfit: tests covered Telegram validation and redaction, but not the externally observable evidence command/path. The new tests assert generated JSON fields through the public QA runner, not private implementation structure.
- No speculative abstraction was added. `build_evidence` derives the command locally from existing options.
- No real Telegram delivery was required for this repair; dry-run and no-credential live-failure paths are bounded and deterministic.
- No real trading/order API behavior was added.

Findings:
- Blocking issue fixed: fresh QA artifacts no longer report the hardcoded `.omo/evidence/final-telegram-real-send-redacted.json` path.
- Inherited scheduler quality findings remain outside this narrow repair and are documented honestly below.

Inherited / scheduler-scope quality grep:
- Command:
  `.venv/bin/python` was not needed; direct grep was run with:
  `rg -n '(^|[^A-Za-z_])Any([^A-Za-z_]|$)|cast\(|type: ignore|import asyncio|from asyncio|import pandas|except Exception|except BaseException|dict\[str, Any\]|dict\[str, object\]' src/polysignal_lab/signal_layer/gate.py src/polysignal_lab/signal_layer/formatter.py src/polysignal_lab/publish/telegram_publisher.py src/polysignal_lab/publish/telegram_qa.py src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_processing.py tests/test_signal_gate.py tests/test_storage_reporting_publish.py tests/test_telegram_validation.py`
- Result: exit 0 with inherited scheduler findings:
  - `src/polysignal_lab/app/scheduler.py:3:import asyncio`
  - `src/polysignal_lab/app/scheduler_processing.py:36: except Exception`
  - `src/polysignal_lab/app/scheduler_processing.py:65: except Exception`
  - `src/polysignal_lab/app/scheduler_processing.py:67: except Exception`
  - `src/polysignal_lab/app/scheduler_processing.py:92: except Exception as exc`
  - `src/polysignal_lab/app/scheduler_processing.py:105: except Exception as exc`
  - `src/polysignal_lab/app/scheduler_processing.py:119: except Exception as exc`
- Classification: inherited/unchanged scheduler lifecycle scope. The publish-path broad catch at `scheduler_processing.py:105` wraps formatter, publisher, JSONL append, and SQLite insert. Narrowing it safely would require splitting the scheduler publish boundary and adding focused scheduler tests, which is broader than this Todo 12 evidence repair.

Verification:
- Red-first regression:
  `.venv/bin/python -m pytest tests/test_telegram_validation.py::test_telegram_qa_records_actual_dry_run_invocation tests/test_telegram_validation.py::test_telegram_qa_records_actual_live_failure_invocation -q`
  first failed with `KeyError: 'mode'`, proving the hardcoded evidence writer was uncovered.
- Same regression after fix: exit 0, `2 passed`.
- Full required pytest:
  `.venv/bin/python -m pytest tests/test_signal_gate.py tests/test_storage_reporting_publish.py tests/test_telegram_validation.py -q`
  exit 0, `17 passed`; Starlette/httpx deprecation warning only.
- Happy QA:
  `.venv/bin/python -m pytest tests/test_telegram_validation.py::test_mocked_telegram_send_returns_sent_and_redacts_token tests/test_signal_gate.py::test_signal_deduper_prevents_duplicate_channel_publish -q`
  exit 0, `2 passed`.
- Failure QA:
  `env -u TELEGRAM_BOT_TOKEN -u TELEGRAM_CHANNEL_ID .venv/bin/python -m pytest tests/test_telegram_validation.py::test_missing_telegram_credentials_fail_startup_when_publish_enabled -q`
  exit 0, `1 passed`.
- `py_compile`:
  `.venv/bin/python -m py_compile src/polysignal_lab/publish/telegram_qa.py tests/test_telegram_validation.py`
  exit 0.
- Repair-file quality grep:
  `rg -n '(^|[^A-Za-z_])Any([^A-Za-z_]|$)|cast\(|type: ignore|import asyncio|from asyncio|import pandas|except Exception|except BaseException|dict\[str, Any\]|dict\[str, object\]' src/polysignal_lab/publish/telegram_qa.py tests/test_telegram_validation.py`
  exit 1, no matches.
- Trading/order API grep:
  `rg -n 'create_order|cancel_order|submit_order|post_order|place_order|redeem|private_key|mnemonic|wallet_key|clob.*order' src/polysignal_lab/publish/telegram_qa.py tests/test_telegram_validation.py`
  exit 1, no matches.
- Token leak grep:
  `rg -n '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi|-1001234567890' .omo/evidence/todo-12-repair-temp-dry-run-redacted.json .omo/evidence/todo-12-repair-temp-live-unset-redacted.json`
  exit 1, no matches.

Fresh QA artifacts:
- `.omo/evidence/todo-12-repair-temp-dry-run-redacted.json`
  - command: `.venv/bin/python -m polysignal_lab.publish.telegram_qa --evidence .omo/evidence/todo-12-repair-temp-dry-run-redacted.json`
  - mode: `dry_run`
  - evidence_path: `.omo/evidence/todo-12-repair-temp-dry-run-redacted.json`
  - dry_run: `true`
  - status: `DRY_RUN`
- `.omo/evidence/todo-12-repair-temp-live-unset-redacted.json`
  - command: `.venv/bin/python -m polysignal_lab.publish.telegram_qa --live --evidence .omo/evidence/todo-12-repair-temp-live-unset-redacted.json`
  - mode: `live`
  - evidence_path: `.omo/evidence/todo-12-repair-temp-live-unset-redacted.json`
  - dry_run: `false`
  - status: `FAILED`
  - error: `TELEGRAM_NOT_CONFIGURED`

Residual risks:
- Scheduler lifecycle `asyncio` and broad exception catches remain inherited/unchanged.
- No real Telegram delivery was attempted because live credentials were intentionally unset for the bounded failure QA.
- The worktree was already broadly dirty and many Todo 12 files are untracked; unrelated work was preserved.
