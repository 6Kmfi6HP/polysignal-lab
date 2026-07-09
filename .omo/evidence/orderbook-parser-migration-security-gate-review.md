recommendation: REJECT
verdict: FAIL
severity: MEDIUM

originalIntent: Security-focused read-only review of the OrderBook parser migration, scoped to `.omo/ulw-loop/evidence/orderbook-changed-files.txt` and `.omo/ulw-loop/evidence/orderbook-diff.patch`.

desiredOutcome: Public CLOB/Gamma payload parsing and restored REST/WS boundary modules should fail safely on malformed external input, avoid unsafe client/auth/secret handling, avoid dependency/supply-chain drift, and avoid leaking sensitive errors.

userOutcomeReview: The shipped artifact does not satisfy the security outcome. It restores the data path and focused tests pass, but malformed public WS/order-book payloads can still create unbounded in-memory metric keys and accepted corrupt books at the trust boundary.

checked artifact paths:
- `.omo/ulw-loop/evidence/orderbook-changed-files.txt`
- `.omo/ulw-loop/evidence/orderbook-diff.patch`
- `src/polysignal_lab/data/orderbook_payload.py`
- `src/polysignal_lab/data/polymarket_clob_rest.py`
- `src/polysignal_lab/data/polymarket_clob_ws.py`
- `src/polysignal_lab/app/readonly_smoke_public.py`
- `src/polysignal_lab/domain/orderbook.py`
- `tests/test_market_data.py`
- `tests/test_orderbook_snapshot.py`
- `tests/test_polymarket_clob_rest.py`
- `src/polysignal_lab/observability/metrics.py`
- `src/polysignal_lab/observability/safety.py`
- `pyproject.toml`
- `uv.lock`

blockers:
- `src/polysignal_lab/data/polymarket_clob_ws.py:106`: unknown public WS `event_type` is interpolated directly into the metric name at `registry.metrics.inc(f"ws_event_unknown_{event_type}")`. `MetricsRegistry` stores names in an unbounded `Counter` at `src/polysignal_lab/observability/metrics.py:28-30`, so an external stream can create arbitrarily many high-cardinality keys and large key strings. Proof command sent three unknown 1000-byte event types and produced `3` counters with max key length `1018`.
- `src/polysignal_lab/data/orderbook_payload.py:31-50` and `src/polysignal_lab/data/orderbook_payload.py:61-79`: malformed public book payloads are accepted instead of rejected or ignored. Missing token IDs become `""`, negative prices are preserved, and NaN/Inf values are coerced to `0.0`, allowing corrupt books at the external data boundary. Proof command returned `'' -1.0 0.0 0.0` for a malformed book payload.

evidence:
- Scoped focused tests passed: `uv run pytest -q tests/test_market_data.py::test_clob_rest_public_book_mid_and_spread_parsing_handles_official_shapes tests/test_market_data.py::test_clob_ws_exposes_connection_and_invalid_event_metrics tests/test_market_data.py::test_websocket_event_types_reconciliation tests/test_orderbook_snapshot.py::test_parse_orderbook_from_polymarket_payload tests/test_polymarket_clob_rest.py` -> `8 passed`.
- Safety scan passed on the new REST/WS files: `uv run python -m polysignal_lab.observability.safety src/polysignal_lab/data/polymarket_clob_rest.py` and `...polymarket_clob_ws.py`.
- Secret/auth scan over scoped files found only negative test assertions for `Authorization`/`private_key`, no production credential emission.
- `git diff -- pyproject.toml uv.lock` was empty; no dependency-file drift in the worktree for this review.

slop_overfit_review:
- Direct remove-ai-slops pass found test coverage is mostly happy-path/restored-path coverage. It does not cover adversarial malformed payload classes for unknown event metric cardinality, missing token ID, negative price, or NaN/Inf coercion.
- No dependency churn or unnecessary production abstraction was found as a separate blocker.

evidence_gaps:
- No independent code review report or manual QA matrix was provided in the input; this report is based on direct inspection and read-only command evidence.
- HEAVY ultrawork reviewer subagent could not be spawned because no multi-agent tool is available in this harness.

notepad: `/tmp/ulw-20260709-000837.OuY7Gw.md`
