<verdict>FAIL</verdict>

# Paper QA Rerun 5

Read-only QA rerun in `/home/debian/polysignal-lab`. Product files were not intentionally edited. Existing dirty worktree was preserved.

## Blocking Failures

- Required focused pytest fails because `tests/test_scheduler_cancelled_markets.py` cannot collect without `nautilus_trader`.
- `tests/test_telegram_bot_service.py` cannot collect without `nautilus_trader`, so the real Telegram malformed-position/no-UP-default surface does not pass in this environment.
- Manual live-settlement adversarial probe for invalid `opened_at` raises `ValueError` instead of rejecting the malformed projection.

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| SE-01 | Inspect prior manual QA | Prior evidence file | `sed -n '1,260p' .omo/ulw-loop/evidence/paper-blockers-manual-qa.txt \| tee .omo/evidence/paper-qa-rerun-5/prior-manual-qa.txt` | PASS | A1 |
| SE-02 | Required focused pytest | Pytest | `python -m pytest tests/test_scheduler_settlement_resolution.py tests/test_scheduler_cancelled_markets.py tests/test_settlement.py tests/test_telegram_bot_service.py tests/test_repair_settlement_results.py -q` | FAIL | A2 |
| SE-03 | Settlement resolution tests | Pytest | `python -m pytest tests/test_scheduler_settlement_resolution.py -q` | PASS | A3 |
| SE-04 | Cancelled-market settlement tests | Pytest | `python -m pytest tests/test_scheduler_cancelled_markets.py -q` | FAIL | A4 |
| SE-05 | Settlement unit tests | Pytest | `python -m pytest tests/test_settlement.py -q` | PASS | A5 |
| SE-06 | Telegram bot service tests | Pytest | `python -m pytest tests/test_telegram_bot_service.py -q` | FAIL | A6 |
| SE-07 | Repair settlement tests | Pytest | `python -m pytest tests/test_repair_settlement_results.py -q` | PASS | A7 |
| SE-08 | Telegram import surface | CLI Python import | `python - <<'PY' ... from polysignal_lab.publish.telegram_bot import TelegramBotService ... PY` | FAIL | A8 |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| AC-01 | Storage malformed position | Missing `side` | Reject open position row, no open-position restore | PASS | A9, A10 |
| AC-02 | Storage malformed position | Missing `opened_at` | Reject open position row | PASS | A9, A10 |
| AC-03 | Storage malformed position | Invalid `opened_at` | Reject open position row | PASS | A9, A10 |
| AC-04 | Dashboard malformed position | Missing `side` | Exclude invalid payload | PASS | A9, A11 |
| AC-05 | Dashboard malformed position | Missing `opened_at` | Exclude invalid payload | PASS | A9, A11 |
| AC-06 | Dashboard malformed position | Invalid `opened_at` | Exclude invalid payload | PASS | A9, A11 |
| AC-07 | Live settlement malformed position | Unmatched token side with no explicit side | Return `None`, do not settle/store | PASS | A9, A12 |
| AC-08 | Live settlement malformed position | Missing `opened_at` | Return `None`, do not settle/store | PASS | A9, A12 |
| AC-09 | Live settlement malformed position | Invalid `opened_at` | Return `None`, do not settle/store | FAIL | A9, A12 |
| AC-10 | Repair import | Import repair module without `nautilus_trader` installed | Import succeeds without loading `nautilus_trader` | PASS | A7, A9, A13 |
| AC-11 | Repair malformed position | Missing `side` | Return `None`, do not repair-settle | PASS | A9, A13 |
| AC-12 | Telegram malformed position | Missing `side`, no default UP | Should import service and render no UP default | FAIL | A6, A8, A14 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | text | Prior manual QA inspection | `.omo/evidence/paper-qa-rerun-5/prior-manual-qa.txt` |
| A2 | pytest | Required combined focused pytest output | `.omo/evidence/paper-qa-rerun-5/focused-required-pytest.txt` |
| A3 | pytest | Scheduler settlement resolution pytest output | `.omo/evidence/paper-qa-rerun-5/pytest-scheduler-settlement-resolution.txt` |
| A4 | pytest | Scheduler cancelled markets pytest output | `.omo/evidence/paper-qa-rerun-5/pytest-scheduler-cancelled-markets.txt` |
| A5 | pytest | Settlement pytest output | `.omo/evidence/paper-qa-rerun-5/pytest-settlement.txt` |
| A6 | pytest | Telegram bot service pytest output | `.omo/evidence/paper-qa-rerun-5/pytest-telegram-bot-service.txt` |
| A7 | pytest | Repair settlement results pytest output | `.omo/evidence/paper-qa-rerun-5/pytest-repair-settlement-results.txt` |
| A8 | cli | Telegram import probe | `.omo/evidence/paper-qa-rerun-5/telegram-import-probe.txt` |
| A9 | cli | Collected manual adversarial probes | `.omo/evidence/paper-qa-rerun-5/manual-adversarial-probes-collected.txt` |
| A10 | source snapshot | Storage validation source snapshot | `.omo/evidence/paper-qa-rerun-5/src-sqlite-store-validation-nl.txt` |
| A11 | source snapshot | Dashboard validation source snapshot | `.omo/evidence/paper-qa-rerun-5/src-dashboard-app-validation-nl.txt` |
| A12 | source snapshot | Live settlement source snapshot | `.omo/evidence/paper-qa-rerun-5/src-settlement-check-nl.txt` |
| A13 | source snapshot | Repair settlement script snapshot | `.omo/evidence/paper-qa-rerun-5/script-repair-settlement-results-nl.txt` |
| A14 | source snapshot | Telegram bot source snapshot | `.omo/evidence/paper-qa-rerun-5/src-telegram-bot-nl.txt` |
| A15 | cleanup | Cleanup receipt | `.omo/evidence/paper-qa-rerun-5/cleanup-receipt.txt` |

## cleanup receipt

`cleanup-receipt.txt` recorded: no server/browser/tmux/container/port was spawned; no rerun temp logs found; evidence artifacts retained under `.omo/evidence/paper-qa-rerun-5/`.
