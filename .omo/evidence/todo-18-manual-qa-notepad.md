# Todo 18 Manual QA Notepad

## Scenarios
- Deterministic fake-public-API outage: `tests/test_integration_smoke.py::test_fake_public_api_outage_degrades_without_unhandled_exception`
  - Result: pass.
  - Observable: Binance 503 is recorded as one degraded public surface; Gamma, CLOB book, CLOB 404, scheduler snapshot, dashboard reads, and safety scan remain observable.

- Full local suite: `.venv/bin/python -m pytest -q`
  - Result: pass.
  - Observable: 120 tests passed, one existing FastAPI/httpx2 deprecation warning.

- Safety: `.venv/bin/python scripts/safety_scan.py .`
  - Result: pass.
  - Observable: `Safety scan passed`.

- Live Gamma curl: `curl -fsS "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=3" >/tmp/polysignal-gamma-smoke.json`
  - Result: pass.
  - Observable: `/tmp/polysignal-gamma-smoke.json` non-empty, 48835 bytes.

- Bounded live read-only smoke: `timeout 120 .venv/bin/python -m polysignal_lab.app.main --config config/signal_bot.yaml --once --real-readonly-smoke --evidence .omo/evidence/final-live-market-smoke.json`
  - Result: pass.
  - Observable: `Bounded read-only smoke passed`; evidence JSON `passed=true`, `failure_count=0`.

- Process cleanup: `ps -eo pid,ppid,stat,comm,args | rg -v 'rg|ps -eo' | rg 'polysignal_lab.app.main|uvicorn|websockets|python -m polysignal_lab|docker run polysignal' || true`
  - Result: pass.
  - Observable: no matches.

## Notes
- The live smoke used a public active Gamma fallback market for scheduler snapshot creation because the first three active Gamma records at validation time were not configured crypto Up/Down markets.
- No `.env` or `.env*` file was opened.
