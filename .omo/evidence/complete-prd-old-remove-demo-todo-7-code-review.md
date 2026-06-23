# Todo 7 Code Review: Public Market Data Contracts

work: complete-prd-old-remove-demo
task: 7. Align Polymarket/Binance data contracts to official public APIs.
status: ready-for-final-gate
notepad: .omo/evidence/todo-7-manual-qa-notepad.md

## Scope Reviewed

- `src/polysignal_lab/data/polymarket_market_discovery.py`
- `src/polysignal_lab/data/polymarket_clob_ws.py`
- `src/polysignal_lab/data/polymarket_clob_rest.py`
- `src/polysignal_lab/data/binance_spot_ws.py`
- `tests/test_market_data.py`
- `tests/test_websocket_contracts.py`
- `tests/fixtures/public_market_payloads.json`
- `.omo/evidence/task-7-complete-prd-old-remove-demo.txt`
- `.omo/evidence/todo-7-gate-review.md`
- `.omo/evidence/todo-7-clob-midpoint-repair-gate-review.md`

## Official Contract Sources

- Polymarket market overview: `https://docs.polymarket.com/market-data/overview`
- Polymarket fetching markets: `https://docs.polymarket.com/market-data/fetching-markets`
- Polymarket market WebSocket: `https://docs.polymarket.com/market-data/websocket/market-channel`
- Polymarket CLOB order book: `https://docs.polymarket.com/api-reference/market-data/get-order-book`
- Polymarket CLOB midpoint: `https://docs.polymarket.com/api-reference/data/get-midpoint-price`
- Polymarket CLOB spread: `https://docs.polymarket.com/api-reference/market-data/get-spread`
- Binance Spot streams: `https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams`

## Findings

- Gamma active market discovery paginates and filters fixture-backed active markets and extracts token IDs without auth headers.
- Polymarket public CLOB REST parses official order book, spread, and midpoint payloads. The prior midpoint blocker is fixed: `/midpoint` now accepts official `mid_price`, and the fixture is exactly `{"mid_price": "0.475"}`.
- Polymarket public market WebSocket handling updates registry state for `price_changes`, `book`, `best_bid_ask`, `last_trade_price`, and lifecycle payloads.
- Binance public `bookTicker` handling updates spot registry state with the expected bid, ask, midpoint, and timestamp fields.
- Malformed public market events are ignored without crashing.
- Public payload text is treated as inert data. The prompt-injection fixture test leaves no `/tmp/polysignal_prompt_injection` artifact.
- No authenticated client or trading endpoint surface was added in `src/polysignal_lab/data` or `src/polysignal_lab/app`.

## Programming Pass

- Touched Todo 7 Python files remain below the 250 pure-LOC ceiling recorded by the final gate:
  - `polymarket_market_discovery.py`: 115
  - `polymarket_clob_ws.py`: 128
  - `polymarket_clob_rest.py`: 31
  - `binance_spot_ws.py`: 78
  - `tests/test_market_data.py`: 108
  - `tests/test_websocket_contracts.py`: 80
- Scoped quality grep found no `Any`, `cast(`, `type: ignore`, `import asyncio`, `import pandas`, broad `except Exception`, raw `dict[str, Any]`/`dict[str, object]`, `print`, `TODO`, `eval`, or `exec` in the Todo 7 touched Python files.
- `py_compile` passed for all Todo 7 touched Python files.

## Remove-AI-Slops / Overfit Pass

- Tests assert parsed values and registry state, not log-only success or implementation echoes.
- The CLOB midpoint test no longer mirrors the older implementation-only `mid` key. It asserts the official fixture shape before calling the parser.
- Tests are fixture-backed and deterministic. No live network dependency is required.
- No production-only extraction or broad abstraction was added for the midpoint repair.
- No deletion-only or tautological tests are used for the public WebSocket, Binance, Gamma, or CLOB REST contract behavior.

## Superseded Findings

`.omo/evidence/todo-7-gate-review.md` correctly rejected the earlier implementation because CLOB midpoint parsing used non-official `mid`. That finding is stale after the repair captured in:

- `.omo/evidence/task-7-complete-prd-old-remove-demo.txt`
- `.omo/evidence/todo-7-clob-midpoint-repair-gate-review.md`

The current authoritative state is:

- `src/polysignal_lab/data/polymarket_clob_rest.py` parses `mid_price` first, with backward-compatible `mid`/`midpoint` fallback.
- `tests/fixtures/public_market_payloads.json` uses only `mid_price` for `clob_midpoint`.
- `tests/test_market_data.py` asserts `midpoint_payload == {"mid_price": "0.475"}` before parsing.
- Focused and full Todo 7 contract tests pass.

## Verification Commands

- `.venv/bin/python -m pytest tests/test_market_data.py tests/test_websocket_contracts.py -q` -> PASS, 9 tests.
- `.venv/bin/python -m pytest tests/test_market_data.py::test_clob_rest_public_book_mid_and_spread_parsing_handles_official_shapes -q` -> PASS.
- `.venv/bin/python -m pytest tests/test_websocket_contracts.py::test_polymarket_price_changes_event_updates_registry tests/test_websocket_contracts.py::test_polymarket_book_best_bid_ask_last_trade_and_lifecycle_events_are_public_contract_safe tests/test_websocket_contracts.py::test_binance_bookticker_updates_spot_registry tests/test_websocket_contracts.py::test_malformed_public_market_events_are_ignored_without_crash -q` -> PASS, 4 tests.
- `.venv/bin/python -m pytest tests/test_websocket_contracts.py::test_polymarket_public_payload_text_is_not_executed -q && test ! -e /tmp/polysignal_prompt_injection` -> PASS.
- `bash -lc '! rg "Authorization|private_key|create_order|cancel_order|POLY_|api_secret|signer|submit_order|order submit" src/polysignal_lab/data src/polysignal_lab/app'` -> PASS.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m py_compile ...` over Todo 7 touched Python files -> PASS.

## Residual Risk

- No live external API smoke was run by scope; coverage is official-doc and fixture-backed.
- The broader worktree remains intentionally dirty from the multi-task plan. This review did not revert unrelated changes.
- `.env` was not read.
