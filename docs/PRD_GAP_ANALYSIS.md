# PolySignal Lab PRD Completion Status

Date: 2026-06-22

This document replaces the 2026-06-21 baseline comparison. The earlier baseline was useful while Todo 6-18 work was still in progress, but it is not current operator guidance.

## Current Status

PolySignal Lab now runs as a PRD-old aligned, read-only signal and paper-simulation system:

| Area | Current status | Evidence |
| --- | --- | --- |
| Safety boundary | Complete. The product has no wallet-secret intake, no authenticated trading client, and no real order execution path. | `.omo/evidence/todo-19-safety-scan.txt` |
| Strategy scope | Complete. Runtime defaults are limited to VWAP Momentum, Late Consensus, and PTB Diff with PRD-old assets. | `docs/PRD_OLD_COMPLIANCE.md` |
| Public market discovery | Complete for bounded public read-only smoke. Gamma discovery runs before market-data subscription. | `.omo/evidence/todo-19-live-smoke.json` |
| Public CLOB reads | Complete for read-only book checks and runtime snapshot input. Public invalid-token behavior is handled as an expected 404. | `.omo/evidence/todo-19-live-smoke.txt` |
| Binance spot reads | Complete for bounded public bookTicker smoke and runtime spot registry input. | `.omo/evidence/todo-19-live-smoke.json` |
| WebSocket/runtime wiring | Complete in code and covered by tests. The public smoke may use a fallback market when a bounded Gamma page does not include the configured crypto Up/Down market set. | `.omo/evidence/todo-19-live-smoke.json` |
| Paper fill, exit, settlement, reporting | Complete for PRD states WIN, LOSS, VOID, and UNKNOWN with scheduler/report/storage coverage. | `docs/TEST_RESULTS.md` |
| SQLite storage and dashboard | Complete for read-only operator views backed by stored data. | `.omo/evidence/todo-19-live-smoke.txt` |
| Docker and CLI modes | Complete for scheduler, dashboard, smoke, test, and shell modes. Demo runtime modes are removed. | `.omo/evidence/todo-19-main-help.txt` |
| Telegram dry-run path | Complete. Dry-run QA records redacted evidence without needing credentials. | `.omo/evidence/todo-19-telegram-dry-run-redacted.json` |
| Real Telegram delivery | Path exists. A dry-run pass and no-credential error path are evidenced. Actual channel delivery waits for externally exported `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` in Todo 20. | `.omo/evidence/todo-19-telegram-dry-run-redacted.json` |

## Acceptance Status

| ID | Current status |
| --- | --- |
| AC-001 | Service starts without wallet-secret configuration. |
| AC-002 | Public market discovery passed bounded read-only smoke after Todo 18. |
| AC-003 | Public CLOB orderbook reads and runtime book wiring passed tests and bounded smoke. |
| AC-004 | Binance spot read path passed tests and bounded smoke. |
| AC-005 | The three PRD strategy families generate signal candidates from normalized snapshots. |
| AC-006 | Telegram publisher and QA path are implemented. Real channel delivery is not claimed until Todo 20 supplies external credentials and records a Telegram message id. |
| AC-007 | Paper orders are created from accepted signals. |
| AC-008 | Paper fills use best-ask/depth checks and reject stale or insufficient-depth inputs. |
| AC-009 | Paper positions are persisted and restored through storage. |
| AC-010 | Settlement supports WIN, LOSS, VOID, and UNKNOWN; unresolved markets remain retriable instead of inflating results. |
| AC-011 | Daily reports include win-rate metrics from stored paper results. |
| AC-012 | Daily reports include PnL and equity metrics from stored paper results. |

## Remaining Operator Item

The only remaining acceptance item for this plan is Todo 20: run the real Telegram QA command with externally exported Telegram credentials and capture redacted evidence containing a non-empty Telegram message id. Todo 19 intentionally does not read `.env` or any `.env*` file to obtain credentials.

## Current Validation Commands

Use these commands to validate the documented state:

```bash
.venv/bin/python scripts/safety_scan.py .
.venv/bin/python -m polysignal_lab.app.main --help
.venv/bin/python -m polysignal_lab.publish.telegram_qa --help
timeout 120 .venv/bin/python -m polysignal_lab.app.main --config config/signal_bot.yaml --once --real-readonly-smoke --evidence .omo/evidence/todo-19-live-smoke.json
.venv/bin/python -m polysignal_lab.publish.telegram_qa --evidence .omo/evidence/todo-19-telegram-dry-run-redacted.json
```

The real Telegram command uses the same QA module with `--live` after the operator exports credentials into the process environment. Do not source credentials from repository files.
