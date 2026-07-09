# OrderBook Phase 4 Gate Review

recommendation: REJECT

## originalIntent
Continue the unfinished Nautilus alignment refactor by completing the remaining explicit slice: move raw Polymarket order book payload parsing out of `OrderBook.from_polymarket` and into `src/polysignal_lab/data/orderbook_payload.py`, while keeping a simplified domain `OrderBook`.

## desiredOutcome
Production code no longer calls or exposes `OrderBook.from_polymarket`; raw venue parsing is isolated in the data boundary; the domain model remains a simple order-book DTO with derived behavior; evidence proves parser behavior, adjacent regression safety, no `@refs` edits, no commit, and no unresolved slop/overfit findings.

## userOutcomeReview
The main functional migration is present: direct `rg` found no production `from_polymarket` references, `src/polysignal_lab/domain/orderbook.py` no longer defines the method, callers use `parse_order_book_payload`, focused pytest passed, compileall passed, and the parser-to-registry surface driver passed.

Approval is blocked because the supplied evidence set does not include the required code review/slop report coverage, and the direct slop pass found unresolved Python/type-strictness issues in the new parser boundary files.

## blockers
1. Missing required review artifacts. No OrderBook code review report, manual QA matrix, or notepad artifact was supplied or discoverable under `.omo/ulw-loop` or `.omo/evidence/orderbook-parser-migration-qa`. The required overfit/slop report coverage cannot be confirmed, so approval would rely only on tests and self-reported evidence.

2. Unresolved programming/remove-ai-slops violations in production code. The new parser boundary still uses banned `object` annotations and produces unknown-type basedpyright warnings:
   - `src/polysignal_lab/data/orderbook_payload.py:27`, `:61`, `:82`
   - `src/polysignal_lab/data/polymarket_clob_rest.py:34`, `:36`, `:51`, `:83`, `:93`, `:114`
   - `src/polysignal_lab/data/polymarket_clob_ws.py:45`
   - `.omo/ulw-loop/evidence/orderbook-basedpyright.txt:9-25` reports unknown/partially unknown types in the changed data files.

3. Minimal-scope justification gap. The scope evidence frames the slice as only the OrderBook parser migration (`.omo/ulw-loop/evidence/scope-decision.txt:1-5`), but the diff creates two full production data-client modules, `src/polysignal_lab/data/polymarket_clob_rest.py` and `src/polysignal_lab/data/polymarket_clob_ws.py` (`.omo/ulw-loop/evidence/orderbook-diff.patch:292-424`). No supplied review artifact justifies why those new modules are necessary for the parser migration slice.

## checkedArtifactPaths
- `.omo/ulw-loop/evidence/orderbook-changed-files.txt`
- `.omo/ulw-loop/evidence/orderbook-diff.patch`
- `.omo/ulw-loop/evidence/scope-decision.txt`
- `.omo/ulw-loop/evidence/orderbook-focused-pytest.txt`
- `.omo/ulw-loop/evidence/orderbook-regression.txt`
- `.omo/ulw-loop/evidence/orderbook-basedpyright.txt`
- `.omo/ulw-loop/evidence/orderbook-compileall.txt`
- `.omo/ulw-loop/evidence/orderbook-surface.txt`
- `.omo/ulw-loop/evidence/orderbook-debug-hypotheses.txt`
- `.omo/evidence/orderbook-parser-migration-qa/*`
- `src/polysignal_lab/domain/orderbook.py`
- `src/polysignal_lab/data/orderbook_payload.py`
- `src/polysignal_lab/data/polymarket_clob_rest.py`
- `src/polysignal_lab/data/polymarket_clob_ws.py`
- `src/polysignal_lab/app/readonly_smoke_public.py`
- `tests/test_orderbook_snapshot.py`
- `tests/test_market_data.py`
- `tests/test_polymarket_clob_rest.py`
- `docs/nautilus_reference/developer_guide/testing.md`
- `docs/nautilus_reference/developer_guide/spec_data_testing.md`
- `docs/nautilus_reference/developer_guide/adapters.md`
- `docs/nautilus_reference/developer_guide/python.md`

## directVerification
- `rg -n "from_polymarket" src/polysignal_lab --glob '*.py'` returned no production matches.
- `git diff --name-only -- refs @refs` returned no `@refs`/`refs` changes.
- `PYTHONPATH=src uv run pytest tests/test_orderbook_snapshot.py tests/test_market_data.py::test_order_book_parses_hash_field tests/test_market_data.py::test_registry_reconciliation_methods tests/test_polymarket_clob_rest.py::test_get_books_falls_back_to_single_book_requests_when_batch_fails -q` passed, 7 tests.
- `PYTHONPATH=src uv run pytest tests/test_orderbook_snapshot.py tests/test_market_data.py tests/test_polymarket_clob_rest.py -q` passed, 30 tests.
- `PYTHONPATH=src uv run python -m compileall -q ...` passed for changed production files.
- `PYTHONPATH=src uv run basedpyright ...` exited 0 but reported 25 warnings.
- Manual surface driver passed: parsed payload to registry with `token-surface`, `best_bid=0.44`, `best_ask=0.47`, `hash=surface-hash`.

## evidenceGaps
- No OrderBook-specific code review report found.
- No manual QA matrix artifact found.
- No executor notepad path supplied or discovered.
- No artifact shows the required skill-perspective check for programming criteria plus remove-ai-slops overfit/slop coverage.

