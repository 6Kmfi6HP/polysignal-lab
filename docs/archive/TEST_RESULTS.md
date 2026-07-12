# Test Results (Archived Snapshot)

**Date:** 2026-06-22
**Status:** Historical snapshot from the original implementation phase.

> ⚠️ This file is retained for historical reference. Current test counts will differ.
> See the project's CI output or run `uv run pytest -q` for current results.

## pytest

```text
120 passed, 1 warning
```

Observable: `.venv/bin/python -m pytest -q` exits 0. The remaining warning is the existing FastAPI/Starlette `httpx` deprecation warning.

## safety scan

```text
Safety scan passed
```

Observable: `.venv/bin/python scripts/safety_scan.py .` exits 0.

## bounded smoke

```text
Bounded read-only smoke passed
```

Observable: `timeout 120 .venv/bin/python -m polysignal_lab.app.main --config config/signal_bot.yaml --once --real-readonly-smoke --evidence .omo/evidence/final-live-market-smoke.json` exits 0 and writes non-empty JSON with `passed=true` and `failure_count=0`.

The smoke covers public Gamma events, public CLOB book, expected public CLOB 404, and Binance public REST fallback. Retired scheduler snapshot, dashboard-read, and safety surfaces are recorded as `not_run`; they are not treated as successful runtime checks.

## real Telegram QA

The real Telegram QA command is:

```bash
.venv/bin/python -m polysignal_lab.publish.telegram_qa --live --evidence .omo/evidence/final-telegram-real-send-redacted.json
```

With no exported credentials, the command exits 2 and records redacted `TELEGRAM_NOT_CONFIGURED` evidence. With externally exported credentials, the same command performs the real Telegram `sendMessage` QA and records redacted status evidence.
