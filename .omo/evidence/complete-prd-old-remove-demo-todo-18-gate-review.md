# Todo 18 Gate Review

recommendation: APPROVE
verdict: CONFIRM

## originalIntent
Todo 18 asks for bounded real-surface integration QA proving public market data, scheduler snapshot creation after discovery, dashboard reads, and safety checks without touching authenticated, trading, wallet, order, account, or private-key surfaces.

## desiredOutcome
The user should be able to mark Todo 18 complete with deterministic local fake-public-API coverage, bounded live read-only smoke evidence, failure/degradation evidence, clean safety scan output, generated runtime files isolated under `.omo/evidence`, and no lingering process or root generated data/log/state artifacts.

## userOutcomeReview
CONFIRM. The shipped artifact satisfies the requested user-visible outcome. The fake-public-API test covers configured BTC Up/Down discovery, CLOB book, expected CLOB 404, Binance outage degradation, scheduler snapshot creation, dashboard reads, safety status, evidence write, and absence of auth headers. The live smoke uses only public GET endpoints and produced a passing evidence JSON with `failure_count=0`. The live scheduler snapshot is from an explicit public Gamma fallback market, not a configured crypto Up/Down market, but that is acceptable for this bounded live-smoke criterion because the happy QA command only fetches Gamma `limit=3`, the evidence does not hide the fallback, and deterministic local coverage proves the configured BTC Up/Down path.

## checkedArtifactPaths
- `.omo/plans/complete-prd-old-remove-demo.md`
- `src/polysignal_lab/app/main.py`
- `src/polysignal_lab/app/readonly_smoke.py`
- `src/polysignal_lab/app/readonly_smoke_public.py`
- `src/polysignal_lab/app/readonly_smoke_runtime.py`
- `src/polysignal_lab/app/readonly_smoke_types.py`
- `tests/test_integration_smoke.py`
- `tests/test_cli_runtime_modes.py`
- `tests/test_dashboard.py`
- `config/signal_bot.yaml`
- `scripts/safety_scan.py`
- `src/polysignal_lab/observability/safety.py`
- `src/polysignal_lab/config.py`
- `src/polysignal_lab/data/price_to_beat_provider.py`
- `.omo/evidence/final-live-market-smoke.json`
- `.omo/evidence/final-live-market-smoke-gate.json`
- `.omo/evidence/task-18-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-18-code-review.md`
- `.omo/evidence/todo-18-manual-qa-notepad.md`

## commandsRun
- `.venv/bin/python -m pytest tests/test_integration_smoke.py -q`
  - exit 0; observable output: `1 passed`.
- `.venv/bin/python -m pytest tests/test_integration_smoke.py::test_fake_public_api_outage_degrades_without_unhandled_exception -q`
  - exit 0; observable output: `1 passed`.
- `.venv/bin/python -m pytest -q`
  - exit 0; observable output reached `[100%]` across 120 tests; one Starlette/FastAPI `httpx` deprecation warning.
- `.venv/bin/python scripts/safety_scan.py .`
  - exit 0; observable output: `Safety scan passed`.
- `curl -fsS "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=3" >/tmp/polysignal-gamma-smoke-gate.json`
  - exit 0; `/tmp/polysignal-gamma-smoke-gate.json` size: 48881 bytes.
- `timeout 120 .venv/bin/python -m polysignal_lab.app.main --config config/signal_bot.yaml --once --real-readonly-smoke --evidence .omo/evidence/final-live-market-smoke-gate.json`
  - exit 0; observable output included public GETs to Gamma, CLOB book, CLOB invalid-token 404, Binance bookTicker, dashboard ASGI reads, and `Bounded read-only smoke passed`.
- `rg -n --glob '!**/.env*' "Authorization|POLY_|private_key|api_secret|create_order|post_order|submit_order|cancel_order|cancel_all|redeem_positions|redeem|listenKey|userData|account" ...`
  - exit 1 with no output; no auth/trading/private-key symbols found in the checked smoke/data/CLI/test files.
- Root artifact hygiene check over `data`, `logs`, and `state`
  - exit 0 with no output; no root generated data/log/state files found.
- `find .omo/evidence/readonly-smoke-runtime -maxdepth 4 -type f -printf '%p %s bytes\n'`
  - exit 0; only runtime DB observed: `.omo/evidence/readonly-smoke-runtime/data/polysignal_lab.sqlite3 135168 bytes`.
- Process cleanup grep for PolySignal app/uvicorn/websocket/docker runtime
  - exit 0 with no output; no lingering matching process.

## findings
- No blockers.
- Public/read-only endpoint boundary holds. `src/polysignal_lab/app/readonly_smoke_public.py:39-98` builds only Gamma `/events`, CLOB `/book`, and Binance public `/api/v3/ticker/bookTicker` GET requests. `PUBLIC_HEADERS` at `src/polysignal_lab/app/readonly_smoke_public.py:24-27` contains only `Accept` and `User-Agent`.
- Degradation is not faked as success. `src/polysignal_lab/app/readonly_smoke.py:57-75` derives `passed` from `failure_count`, and `src/polysignal_lab/app/readonly_smoke_runtime.py:104-117` counts any failed surface, missing scheduler snapshot, dashboard failure, or safety finding. The failure QA test asserts Binance 503 yields `passed is False` and `failure_count == 1` at `tests/test_integration_smoke.py:84-96`.
- Live evidence explicitly records the fallback. `.omo/evidence/final-live-market-smoke-gate.json:29-34` has `created=true`, `token_count=2`, and `detail="Public active Gamma fallback market"`. The fallback path is visible in `src/polysignal_lab/app/readonly_smoke_public.py:172-186` and `src/polysignal_lab/app/readonly_smoke_runtime.py:65-71`.
- Dashboard read-only behavior is covered both in smoke and tests. The live smoke reads `/health`, `/api/overview`, `/api/leaderboard`, and `/` at `src/polysignal_lab/app/readonly_smoke_runtime.py:76-90`; `tests/test_dashboard.py:118-137` rejects write methods across dashboard routes.
- The self-review artifact explicitly covers programming quality and remove-ai-slops/overfit at `.omo/evidence/complete-prd-old-remove-demo-todo-18-code-review.md:3-12`, and auth boundary at lines 14-17. Direct reviewer pass found no tautological, deletion-only, implementation-mirroring, or excessive fake-success tests.

## blockers
None.

## evidenceGaps
- No live evidence proves a configured BTC/ETH/SOL/XRP Up/Down market was discovered in the first three Gamma active records. This is not a blocker because the Todo's happy command bounds Gamma to `limit=3`, the live evidence explicitly marks the fallback, and deterministic local fake-public-API coverage exercises configured BTC Up/Down discovery.
- `StaticPriceToBeatProvider.__init__` at `src/polysignal_lab/app/readonly_smoke_runtime.py:22-24` returns `None` instead of being omitted or using an empty body. This is nonblocking style slop: Python `__init__` may only return `None`, and focused tests plus live smoke pass. It should be cleaned in a later maintenance edit.
- `src/polysignal_lab/app/readonly_smoke_public.py` measures 231 pure LOC, which is in the programming skill's warning band but below the 250 pure-LOC defect threshold.

## residualRisks
- Live smoke quality depends on what Gamma returns for `limit=3` at runtime. The current implementation degrades honestly or records fallback detail instead of pretending configured crypto discovery happened.
- The project still uses `httpx` rather than the programming skill's preferred `httpx2`; that is an existing project dependency choice and not a Todo 18 blocker.
