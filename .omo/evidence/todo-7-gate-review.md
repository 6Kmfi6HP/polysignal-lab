# Todo 7 Gate Review

recommendation: REJECT

AdversarialVerify verdict: needs-fix
confidence: high

## originalIntent

Todo 7 was intended to align public market-data contracts with official public APIs only:
- Gamma `/events` active/closed offset pagination and crypto Up/Down token extraction.
- Polymarket public CLOB REST book, midpoint, and spread parsing without auth.
- Polymarket public market WebSocket handling for book, price changes, best bid/ask, last trade, and lifecycle events.
- Binance public `<symbol>@bookTicker` updates into the spot registry.
- Official-payload fixtures and deterministic tests with no live network requirement.

## desiredOutcome

The user should be able to check off Todo 7 only if current source and tests prove official public payload shapes are parsed, authenticated/trading surfaces are absent, malformed public events are ignored safely, and the requested test/grep/compile/quality gates pass.

## userOutcomeReview

The requested tests and guard commands pass on the current tree, and most of the implementation matches the intended public contracts. However, Todo 7 cannot be checked off because CLOB midpoint parsing is not aligned with the current official Polymarket response shape. The current code parses `mid` or `midpoint`, while current official Polymarket docs show `/midpoint` returning `mid_price`. The fixture also uses `mid`, so the tests pass by mirroring the implementation rather than proving the official payload.

## blockers

1. `src/polysignal_lab/data/polymarket_clob_rest.py:27` does not parse official CLOB midpoint payloads using `mid_price`. Local adversarial probe with `{"mid_price": "0.475"}` returned `None`.

2. `tests/fixtures/public_market_payloads.json:147` through `tests/fixtures/public_market_payloads.json:149` uses `"mid": "0.475"` for `clob_midpoint`, which is not the current official docs response field.

3. `tests/test_market_data.py:125` through `tests/test_market_data.py:134` proves midpoint parsing only for the non-official fixture key, creating false confidence for the CLOB REST acceptance criterion.

4. Todo 7-specific review artifacts are incomplete: no Todo 7 code-review report, manual QA matrix, or notepad path was present under `.omo/evidence/`. Only `.omo/evidence/task-7-complete-prd-old-remove-demo.txt` exists for Todo 7.

## checked artifact paths

- `docs/EXTERNAL_API_RESEARCH.md`
- `src/polysignal_lab/data/polymarket_market_discovery.py`
- `src/polysignal_lab/data/polymarket_clob_ws.py`
- `src/polysignal_lab/data/polymarket_clob_rest.py`
- `src/polysignal_lab/data/binance_spot_ws.py`
- `src/polysignal_lab/domain/orderbook.py`
- `src/polysignal_lab/domain/market.py`
- `tests/test_market_data.py`
- `tests/test_websocket_contracts.py`
- `tests/fixtures/public_market_payloads.json`
- `.omo/evidence/task-7-complete-prd-old-remove-demo.txt`
- `.omo/plans/complete-prd-old-remove-demo.md`
- `git status --short`
- Official Polymarket docs: `https://docs.polymarket.com/market-data/overview`, `https://docs.polymarket.com/market-data/fetching-markets`, `https://docs.polymarket.com/market-data/websocket/market-channel`, `https://docs.polymarket.com/api-reference/market-data/get-order-book`, `https://docs.polymarket.com/api-reference/data/get-midpoint-price`, `https://docs.polymarket.com/api-reference/market-data/get-spread`
- Official Binance docs: `https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams`

## repro_commands

- `.venv/bin/python -m pytest tests/test_market_data.py tests/test_websocket_contracts.py -q` -> PASS, 9 tests.
- `.venv/bin/python -m pytest tests/test_websocket_contracts.py::test_polymarket_price_changes_event_updates_registry tests/test_websocket_contracts.py::test_binance_bookticker_updates_spot_registry -q` -> PASS, 2 tests.
- `.venv/bin/python -m pytest tests/test_websocket_contracts.py::test_malformed_public_market_events_are_ignored_without_crash -q` -> PASS, 1 test.
- `.venv/bin/python -m pytest tests/test_market_data.py::test_gamma_active_market_discovery_paginates_filters_and_extracts_token_ids tests/test_market_data.py::test_clob_rest_public_book_mid_and_spread_parsing_handles_official_shapes -q` -> PASS, 2 tests.
- `bash -lc '! rg "Authorization|private_key|create_order|cancel_order|POLY_|api_secret|signer|submit_order|order submit" src/polysignal_lab/data src/polysignal_lab/app'` -> PASS, no matches.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m py_compile src/polysignal_lab/data/polymarket_market_discovery.py src/polysignal_lab/data/polymarket_clob_ws.py src/polysignal_lab/data/polymarket_clob_rest.py src/polysignal_lab/data/binance_spot_ws.py tests/test_market_data.py tests/test_websocket_contracts.py` -> PASS.
- Pure LOC scan -> 115, 128, 31, 78, 104, 80 for the six touched Todo 7 Python files; all <= 250.
- Quality grep for `Any`, `cast(`, `type: ignore`, `import asyncio`, `pandas`, broad exceptions, and raw `dict[str, Any]`/`dict[str, object]` in touched Todo 7 Python files -> no matches.
- Adversarial CLOB midpoint probe:
  `PolymarketCLOBRestClient(... FakeAsyncClient([{"mid_price": "0.475"}])).get_mid("token-up")` -> `None`.

## adversarial_probe_results

- stale_state: reread `docs/EXTERNAL_API_RESEARCH.md` and current data files. Local research says public/no-auth surfaces only; current code mostly follows that, but official docs spot-check found the CLOB midpoint field mismatch.
- dirty_worktree: inspected only. Working tree has broad unrelated changes and untracked docs/tests; no source edits were made by this review.
- misleading_success_output: tests assert concrete registry state and parsed values, but the CLOB midpoint test uses a non-official fixture key and misses `mid_price`.
- malformed_input: covered by `tests/test_websocket_contracts.py:80` through `tests/test_websocket_contracts.py:92`; focused test passes.
- prompt_injection: fixture text and `new_market` payload are treated as inert data; test asserts `/tmp/polysignal_prompt_injection` absent.
- authenticated_client_guard: grep clean; CLOB/Gamma fake clients record no auth headers in tested paths.
- programming_quality: touched Todo 7 Python files are under 250 pure LOC and focused quality grep is clean.
- env_secrecy: `.env` was not read.
- remove_ai_slops direct pass: tests are not deletion-only or tautological for WebSocket/Binance/Gamma registry behavior, but the CLOB midpoint test is implementation-mirroring because the fixture shape matches the code rather than current official docs.
- programming direct pass: no `Any`, broad catches, `asyncio`, casts, type ignores, or oversized touched Todo 7 files found. Remaining blocker is boundary parsing incompleteness for official CLOB midpoint payloads.

## exact evidence gaps

- Missing Todo 7 code-review report with explicit skill-perspective and overfit/slop coverage.
- Missing Todo 7 manual QA matrix artifact separate from executor command transcript.
- Missing notepad path.
- Tests lack an official `mid_price` CLOB midpoint fixture/probe.

## conclusion

Todo 7 should not be checked off until CLOB midpoint parsing accepts `mid_price`, the official-payload fixture is corrected, and the focused test proves that official payload shape.

## supersession note

This gate report rejected the pre-repair Todo 7 implementation. The CLOB midpoint blocker above is superseded by the later repair and final review artifacts:

- `.omo/evidence/task-7-complete-prd-old-remove-demo.txt`
- `.omo/evidence/todo-7-clob-midpoint-repair-gate-review.md`
- `.omo/evidence/complete-prd-old-remove-demo-todo-7-code-review.md`
- `.omo/evidence/todo-7-manual-qa-notepad.md`

Current disk state after the repair parses official `mid_price`, uses an official `{"mid_price": "0.475"}` fixture, asserts that fixture shape before parsing, and passes the focused and full Todo 7 contract tests. The old `mid`/`midpoint` finding should be treated as historical evidence, not a current blocker.
