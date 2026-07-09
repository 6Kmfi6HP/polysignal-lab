# OrderBook Corrected Manual QA Matrix

verdict: PASS
date: 2026-07-09

## Scope

Corrected safe OrderBook Phase 4 slice:
- remove `OrderBook.from_polymarket` from the domain model
- parse raw public Polymarket CLOB book payloads at the data/app boundary
- keep simplified `OrderBook` for MarketView/state assembly
- fail closed for malformed book payloads
- bound unknown WebSocket event metric cardinality
- remove production `object` type-erasure in the new REST/WS boundary code

## Surface Evidence

| criterion | channel | artifact | verdict |
| --- | --- | --- | --- |
| C1 scope decision | docs + source search | `.omo/ulw-loop/evidence/scope-decision.txt`, `.omo/ulw-loop/evidence/orderbook-from-polymarket-rg.txt` | PASS |
| C2 focused behavior | CLI pytest stdout | `.omo/ulw-loop/evidence/orderbook-focused-pytest.txt` | PASS, 32 passed |
| C3 real surface | CLI driver exercising parser -> registry + WS metric | `.omo/ulw-loop/evidence/orderbook-surface.txt` | PASS |
| C4 regression | CLI pytest stdout | `.omo/ulw-loop/evidence/orderbook-regression.txt` | PASS, 101 passed |
| type coverage | CLI basedpyright stdout | `.omo/ulw-loop/evidence/orderbook-basedpyright.txt` | PASS, 0 errors |
| syntax/import coverage | CLI compileall stdout | `.omo/ulw-loop/evidence/orderbook-compileall.txt` | PASS |
| whitespace | CLI git diff check | `.omo/ulw-loop/evidence/orderbook-diff-check.txt` | PASS |
| refs protection | git diff path check | `.omo/ulw-loop/evidence/orderbook-refs-check.txt` | PASS, empty output |

## Adversarial Cases

| case | expected | artifact | verdict |
| --- | --- | --- | --- |
| missing CLOB token id | parser raises `InvalidOrderBookPayload` | `.omo/ulw-loop/evidence/orderbook-surface.txt`, `tests/test_orderbook_snapshot.py` | PASS |
| non-positive or non-finite levels | invalid levels ignored, valid levels kept | `.omo/ulw-loop/evidence/orderbook-surface.txt`, `tests/test_orderbook_snapshot.py` | PASS |
| unknown WS event type | constant `ws_event_unknown`, no attacker-controlled metric key | `.omo/ulw-loop/evidence/orderbook-surface.txt`, `tests/test_market_data.py` | PASS |
| full changed-test typecheck | includes `tests/test_market_data.py` | `.omo/ulw-loop/evidence/orderbook-basedpyright.txt` | PASS |

## Cleanup Receipt

No persistent server, browser, tmux session, container, or bound port was spawned for this QA. CLI commands exited. The timed-out worker `019f43f1-61d1-7820-8bff-e5bd8ffd0eae` was closed with `multi_agent_v1.close_agent`.

## QA Recheck After 2026-07-09 Review

The final QA reviewer rejected the first corrected bundle because pytest artifacts were quiet-mode outputs without literal summaries and the refs artifact was empty. Re-runs appended explicit summaries:
- `.omo/ulw-loop/evidence/orderbook-focused-pytest.txt` now contains `summary=32 passed`.
- `.omo/ulw-loop/evidence/orderbook-regression.txt` now contains `summary=101 passed`.
- `.omo/ulw-loop/evidence/orderbook-refs-check.txt` now contains `refs_check=pass no refs/@refs changed`.
