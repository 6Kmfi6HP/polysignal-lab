# Implementation Summary

## Delivered complete-version capabilities

| Area | Delivered |
|---|---|
| Config and safety | Pydantic settings, YAML config, disallowed environment key detection, `scripts/safety_scan.py`, CI workflow |
| Polymarket data | Gamma market discovery adapter, public CLOB REST/orderbook adapters, Nautilus Polymarket data wiring |
| Sidecar data | Spot, price-to-beat, anchor, and market metadata custom data for Nautilus strategies |
| Snapshots | Market view assembly, freshness metrics, derived metrics |
| Strategies | PolySignal alpha cores wrapped by Nautilus strategy callbacks |
| Signal layer | SignalCandidate schema, gate, dedupe, channel rate limiter, consensus engine, formatter |
| Telegram | Dry-run default publisher, retry-capable HTTP sender, publish audit record, real Telegram QA command with redacted evidence |
| Paper trading | Nautilus `TradingNode`, native order submission, sandbox paper execution, cache/portfolio projections |
| Node surface | Current default uses legacy Nautilus `TradingNode`; this is tracked as a non-wheel design deviation with a separate `LiveNode.builder` migration gate |
| Exits/settlement | Paper TP/SL/max-hold virtual exit and hold-to-resolution settlement over projected positions |
| Reporting | Daily report, PnL, ROI, win rate, drawdown, profit factor, breakdowns |
| Storage | SQLite tables, JSONL audit logs, atomic state files |
| Dashboard | Read-only FastAPI dashboard and JSON endpoints backed by SQLite data |
| Scheduler/smoke | Nautilus mode, legacy scheduler compatibility mode, dashboard mode, and bounded public read-only smoke mode |
| Tests | Automated tests cover config safety, Nautilus runtime boundaries, strategy callbacks, paper projections, settlement, reporting, and dashboard behavior |

## Runtime-generated files and generated history

Runtime writes JSONL audit logs under `logs/`, atomic state snapshots under `state/`, and SQLite outputs under `data/`. Those root generated-history paths were removed from the repository and remain generated-only. `.omo/evidence/` is the approved location for validation artifacts, including bounded smoke SQLite files.

See `docs/GENERATED_HISTORY_DELETION.md` for the deletion boundary.

## Test result

```text
120 passed, 1 warning
Safety scan passed
```

## Current operator commands

```bash
.venv/bin/python -m polysignal_lab.app.main --config config/signal_bot.yaml
.venv/bin/python -m polysignal_lab.app.main --mode nautilus --config config/signal_bot.yaml
.venv/bin/python -m polysignal_lab.app.main --mode dashboard --config config/signal_bot.yaml
timeout 120 .venv/bin/python -m polysignal_lab.app.main --config config/signal_bot.yaml --once --real-readonly-smoke --evidence .omo/evidence/final-live-market-smoke.json
.venv/bin/python -m polysignal_lab.publish.telegram_qa --live --evidence .omo/evidence/final-telegram-real-send-redacted.json
```
