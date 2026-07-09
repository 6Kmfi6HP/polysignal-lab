# OrderBook Phase 4 Safe Slice Gate Review

recommendation: REJECT

## originalIntent
Continue the unfinished Nautilus alignment refactor by completing the safe OrderBook Phase 4 slice: remove `OrderBook.from_polymarket` and raw Polymarket order-book payload parsing from the domain layer while keeping a simplified custom `OrderBook` for current `MarketView` and state assembly.

## desiredOutcome
Production code no longer exposes or calls `OrderBook.from_polymarket`; raw public Polymarket order-book parsing lives at the data/app boundary; simplified `OrderBook` remains usable for existing assembly paths; Nautilus docs/scope evidence justify deferring full custom state removal; verification evidence is current, complete, and includes programming plus remove-ai-slops review coverage.

## userOutcomeReview
The main functional change is present in current source: `src/polysignal_lab/domain/orderbook.py` no longer defines `from_polymarket`, production `rg` finds no `from_polymarket` references, `src/polysignal_lab/data/orderbook_payload.py` owns raw payload parsing, focused pytest passes, compile passes, and the direct adversarial parser/WS check passes.

Approval is blocked because the corrected-state review artifacts are missing/stale and the direct programming/remove-ai-slops pass still finds current production type-erasure slop in the new data boundary code.

## blockers
1. Corrected-state review artifact coverage is not present. The only OrderBook code review/security artifacts on disk still say `FAIL`/`REJECT`:
   - `.omo/evidence/orderbook-data-boundary-parser-migration-code-review.md:3`
   - `.omo/evidence/orderbook-parser-migration-security-gate-review.md:1-2`
   They cover pre-repair blockers, not an approving review of the corrected state. No updated PASS code-review report, manual QA matrix, or executor notepad artifact was discoverable for the corrected slice.

2. Direct programming/remove-ai-slops pass found unresolved current production slop. The new boundary code still uses banned `object` annotations/type erasure:
   - `src/polysignal_lab/data/polymarket_clob_rest.py:39`
   - `src/polysignal_lab/data/polymarket_clob_rest.py:41`
   - `src/polysignal_lab/data/polymarket_clob_rest.py:56`
   - `src/polysignal_lab/data/polymarket_clob_rest.py:101`
   - `src/polysignal_lab/data/polymarket_clob_ws.py:47`

3. Typecheck evidence is narrower than the changed-file scope. The evidence-matching basedpyright command passes when excluding `tests/test_market_data.py`, but `tests/test_market_data.py` is in `.omo/ulw-loop/evidence/orderbook-changed-files.txt`; running basedpyright over all touched OrderBook files including it fails with 10 errors. This leaves the typecheck claim unsupported for the complete changed-file set.

4. Manual QA/supporting artifacts conflict with the corrected state. `.omo/evidence/orderbook-parser-migration-qa/diff-summary.txt` and `.omo/evidence/orderbook-parser-migration-qa/adversarial-malformed-levels.txt` describe the old fail-open parser state, including invalid `(0.0, 0.0)` levels. Current source and `.omo/ulw-loop/evidence/orderbook-surface.txt` show the corrected fail-closed behavior, so the QA bundle is stale rather than durable proof.

## checked artifact paths
- `.omo/ulw-loop/evidence/scope-decision.txt`
- `.omo/ulw-loop/evidence/orderbook-changed-files.txt`
- `.omo/ulw-loop/evidence/orderbook-diff.patch`
- `.omo/ulw-loop/evidence/orderbook-basedpyright.txt`
- `.omo/ulw-loop/evidence/orderbook-focused-pytest.txt`
- `.omo/ulw-loop/evidence/orderbook-regression.txt`
- `.omo/ulw-loop/evidence/orderbook-compileall.txt`
- `.omo/ulw-loop/evidence/orderbook-surface.txt`
- `.omo/ulw-loop/evidence/orderbook-debug-hypotheses.txt`
- `.omo/evidence/orderbook-phase4-gate-review.md`
- `.omo/evidence/orderbook-data-boundary-parser-migration-code-review.md`
- `.omo/evidence/orderbook-parser-migration-security-gate-review.md`
- `.omo/evidence/orderbook-parser-migration-qa/*`
- `src/polysignal_lab/domain/orderbook.py`
- `src/polysignal_lab/data/orderbook_payload.py`
- `src/polysignal_lab/data/polymarket_clob_rest.py`
- `src/polysignal_lab/data/polymarket_clob_ws.py`
- `src/polysignal_lab/app/readonly_smoke_public.py`
- `tests/test_orderbook_snapshot.py`
- `tests/test_market_data.py`
- `tests/test_polymarket_clob_rest.py`

## direct verification
- `git diff --name-only HEAD -- refs @refs` produced no `refs`/`@refs` changed paths.
- `git log -1 --oneline --decorate` showed current HEAD `3ef19dc (HEAD -> main) refactor: remove iterative refactoring workflows, keep compliance-review`; work remains uncommitted.
- `rg -n "from_polymarket" src tests -g '!**/__pycache__/**'` found no production references; only historical diff/test names.
- `PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider tests/test_orderbook_snapshot.py tests/test_market_data.py tests/test_polymarket_clob_rest.py -q` passed: 32 tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src uv run python` compile script over changed production files passed.
- Direct adversarial parser/WS script passed for missing token rejection, non-object rejection, invalid-level filtering, and bounded unknown WS metric.
- `PYTHONDONTWRITEBYTECODE=1 uv run basedpyright ... tests/test_orderbook_snapshot.py tests/test_polymarket_clob_rest.py` passed with 0 errors, 10 warnings.
- `PYTHONDONTWRITEBYTECODE=1 uv run basedpyright ... tests/test_market_data.py ...` failed with 10 errors, 73 warnings.

## evidence gaps
- No corrected-state PASS code review report exists.
- No corrected-state manual QA matrix exists.
- No executor notepad artifact path for the corrected repair was supplied or discoverable.
- Existing QA/code-review artifacts are stale or failing, so they cannot support approval.

confidence: high
