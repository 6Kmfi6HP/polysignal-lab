# PolySignal Lab

PolySignal Lab is a read-only Polymarket short-cycle signal and Nautilus-backed paper trading validation system.

It implements the current production scope:

- Polymarket market discovery, public market data, and Nautilus Polymarket data wiring.
- Spot, price-to-beat, and market metadata sidecar data for Nautilus strategies.
- PolySignal alpha cores for VWAP Momentum, Late Consensus, PTB Diff, and additional configured strategies.
- Nautilus `TradingNode` runtime with strategy callbacks, decision policy, native order submission, and sandbox paper execution.
- Telegram formatting and publisher with dry-run mode by default plus a redacted real Telegram QA path.
- Nautilus cache/portfolio projections for paper orders, fills, positions, account state, daily reports, and dashboard reads.
- SQLite canonical storage plus JSONL audit logs and atomic state files.
- Safety scanner (`scripts/safety_scan.py`) that blocks disallowed execution symbols.
- Test suite covering config safety, market data parsing, strategies, gates, Nautilus runtime boundaries, paper projections, settlement, reporting, storage, and dashboard behavior.
- Generated history was removed from the repo root; runtime `logs/`, `state/`, and root `data/*.sqlite*` outputs stay generated-only. Evidence artifacts under `.omo/evidence/` are allowed.

## Safety boundary

The project is designed as a non-custodial, read-only signal and Nautilus sandbox paper-validation service.

- No wallet secret material is required.
- No authenticated Polymarket trading client is instantiated.
- No live market action endpoint is implemented.
- No chain payout claim module is implemented.
- Telegram tokens are redacted in error text.
- Telegram publisher runs in `dry_run: true` by default.

## Installation

```bash
cd polysignal-lab
.venv/bin/python -m pip install -e '.[dev]'
```

## Run tests

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/safety_scan.py .
```

Expected result from the current project:

```text
All tests pass
Safety scan passed
```

## Runtime modes

The supported runtime modes are `nautilus`, `dashboard`, and bounded `smoke`. `scheduler` is a temporary deprecated alias that always resolves to `nautilus`, emits a warning, and rejects smoke flags; migrate automation to the explicit modes before the alias is removed.
With the production config, the Python entry point defaults to the Nautilus runtime. Explicit modes remain available for bounded checks:

```bash
.venv/bin/python -m polysignal_lab.app.main --config config/signal_bot.yaml
.venv/bin/python -m polysignal_lab.app.main --mode nautilus --config config/signal_bot.yaml
.venv/bin/python -m polysignal_lab.app.main --mode dashboard --config config/signal_bot.yaml
.venv/bin/python -m polysignal_lab.app.main --mode smoke --config config/signal_bot.yaml --evidence .omo/evidence/local-smoke.json
```

The bounded live smoke path performs public read-only Gamma `/events`, CLOB `/book`, expected CLOB 404, and Binance public REST fallback. Retired scheduler/dashboard/safety surfaces are recorded as `not_run`; the smoke records JSON evidence and does not contact authenticated or trading endpoints:

```bash
timeout 120 .venv/bin/python -m polysignal_lab.app.main --mode smoke --config config/signal_bot.yaml --evidence .omo/evidence/final-live-market-smoke.json
```

When the first Gamma page does not contain configured crypto Up/Down markets, the smoke records the public fallback market detail instead of pretending configured discovery happened. Deterministic tests cover the configured BTC Up/Down path.

## Run dashboard

```bash
.venv/bin/python -m polysignal_lab.app.main --config config/signal_bot.yaml --dashboard
```

Read-only endpoints:

- `/health`
- `/api/overview`
- `/api/signals`
- `/api/rejected-signals`
- `/api/positions`
- `/api/trades`
- `/api/leaderboard`

## Telegram QA

Production publishing reads credentials only from externally exported process variables named `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID`; `.env` files are intentionally not read for QA. The real Telegram send path records redacted evidence:

```bash
.venv/bin/python -m polysignal_lab.publish.telegram_qa --live --evidence .omo/evidence/final-telegram-real-send-redacted.json
```

Without exported credentials, the same command exits with status 2 and writes redacted failure evidence with `TELEGRAM_NOT_CONFIGURED`.

## Main directories

```text
config/                  Runtime configuration
src/polysignal_lab/       Application source code
tests/                   Test suite
logs/                    JSONL audit logs
state/                   Atomic state snapshots
data/                    SQLite databases
scripts/                 Safety scan entrypoint
docs/                    Delivery notes and test result summary
```
