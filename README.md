# PolySignal Lab

PolySignal Lab is a read-only Polymarket short-cycle signal and paper trading validation system.

It implements the complete PRD-old scope, not the earlier MVP subset:

- Polymarket market discovery, public CLOB orderbook REST adapter, and market WebSocket handler.
- Binance spot WebSocket feed for BTC / ETH / SOL / XRP.
- Normalized market snapshot builder.
- Strategy modules: VWAP Momentum, Late Consensus, PTB Diff.
- Signal gate, dedupe, channel rate limit, consensus signal aggregation.
- Telegram formatting and publisher with dry-run mode by default plus a redacted real Telegram QA path.
- Paper wallet, paper order, best-ask taker fill model, depth/slippage checks, open positions, TP/SL/max-hold virtual exits, hold-to-resolution settlement.
- SQLite canonical storage plus JSONL audit logs and atomic state files.
- Daily report, strategy/asset/timeframe breakdown, strategy leaderboard.
- Read-only FastAPI dashboard backed by SQLite report and trade data.
- Safety scanner (`scripts/safety_scan.py`) that blocks disallowed execution symbols.
- Test suite covering config safety, market data parsing, strategies, gates, consensus, paper simulation, settlement, reporting, storage, and dashboard behavior.
- Generated history was removed from the repo root; runtime `logs/`, `state/`, and root `data/*.sqlite*` outputs stay generated-only. Evidence artifacts under `.omo/evidence/` are allowed.

## Safety boundary

The project is designed as a non-custodial, read-only signal and paper simulation service.

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
120 passed, 1 warning
Safety scan passed
```

The warning is the existing FastAPI/Starlette `httpx` deprecation warning.

## Runtime modes

Supported container modes are `scheduler`, `dashboard`, `test`, `shell`, and `smoke`.
The Python entry point supports `scheduler`, `dashboard`, and bounded `smoke`:

```bash
.venv/bin/python -m polysignal_lab.app.main --mode scheduler --config config/signal_bot.yaml
.venv/bin/python -m polysignal_lab.app.main --mode dashboard --config config/signal_bot.yaml
.venv/bin/python -m polysignal_lab.app.main --mode smoke --config config/signal_bot.yaml --evidence .omo/evidence/local-smoke.json
```

The live bounded smoke path performs public read-only Gamma `/events`, CLOB `/book`, expected CLOB 404, Binance public REST fallback, scheduler snapshot, dashboard reads, and safety scan. It records JSON evidence and does not contact authenticated or trading endpoints:

```bash
timeout 120 .venv/bin/python -m polysignal_lab.app.main --config config/signal_bot.yaml --once --real-readonly-smoke --evidence .omo/evidence/final-live-market-smoke.json
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
