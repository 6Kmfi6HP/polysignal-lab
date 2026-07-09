recommendation: APPROVE
verdict: PASS
severity: NONE

originalIntent: Re-run a security-only, read-only review of the corrected OrderBook parser and Polymarket CLOB WS metric changes in `/home/debian/polysignal-lab`.

desiredOutcome: Confirm the two prior security blockers are fixed: unknown public WS event types must not create unbounded metric names, and malformed public order-book payloads must not be accepted into valid book state except for bounded invalid-level filtering.

userOutcomeReview: The corrected artifact satisfies the requested security slice. Unknown WS event types now increment only the constant `ws_event_unknown` counter, and malformed book snapshots without token IDs raise `InvalidOrderBookPayload`; invalid levels with missing, non-finite, zero, or negative price/size are filtered before `OrderBook` construction. REST public JSON is validated as `JsonValue` and required to be an object before parsing.

blockers: []

checked artifact paths:
- `.omo/ulw-loop/evidence/orderbook-changed-files.txt`
- `.omo/ulw-loop/evidence/orderbook-diff.patch`
- `.omo/ulw-loop/evidence/orderbook-focused-pytest.txt`
- `.omo/ulw-loop/evidence/orderbook-regression.txt`
- `.omo/ulw-loop/evidence/orderbook-basedpyright.txt`
- `.omo/ulw-loop/evidence/orderbook-compileall.txt`
- `.omo/ulw-loop/evidence/orderbook-surface.txt`
- `.omo/evidence/orderbook-parser-migration-security-gate-review.md`
- `.omo/evidence/orderbook-data-boundary-parser-migration-code-review.md`
- `src/polysignal_lab/data/orderbook_payload.py`
- `src/polysignal_lab/data/polymarket_clob_ws.py`
- `src/polysignal_lab/data/polymarket_clob_rest.py`
- `src/polysignal_lab/app/readonly_smoke_public.py`
- `src/polysignal_lab/domain/orderbook.py`
- `src/polysignal_lab/observability/metrics.py`
- `src/polysignal_lab/utils.py`
- `tests/test_market_data.py`
- `tests/test_orderbook_snapshot.py`
- `tests/test_polymarket_clob_rest.py`

direct evidence:
- `src/polysignal_lab/data/polymarket_clob_ws.py:89-114` dispatches WS events with `match`; the unknown case increments only `ws_event_unknown`.
- `src/polysignal_lab/observability/metrics.py:28-30` still stores arbitrary names in a `Counter`, so bounding at the call site is necessary and present for unknown WS events.
- `src/polysignal_lab/data/orderbook_payload.py:42-69` constructs `OrderBook` only after token-id parsing and raises `InvalidOrderBookPayload` for non-object helper input or missing token ID.
- `src/polysignal_lab/data/orderbook_payload.py:72-90` filters invalid book levels by requiring dict level objects plus finite positive price and size.
- `src/polysignal_lab/data/polymarket_clob_rest.py:111-119` validates public REST response JSON as `JsonValue` and requires a JSON object before parser entry.
- Focused pytest re-run: `10 passed` for WS unknown metric, invalid decode metric, REST public parsing, missing token rejection, invalid-level filtering, and REST batch fallback tests.
- Inline security smoke passed for non-object payload rejection, missing token rejection, invalid-level filtering, repeated attacker-controlled unknown WS event names, and WS invalid book payload rejection without registry update.
- Static safety scan retried with supported CLI shape and passed on `src/polysignal_lab/data`.
- Manifest diff for dependency files was empty.

slop_overfit_review:
- remove-ai-slops direct pass found no blocking overfit in the corrected security tests: assertions cover observable counter cardinality, parser rejection, and level filtering, not private call order.
- programming direct pass found the corrected parser uses `JsonValue`/typed `InvalidOrderBookPayload` for this boundary and avoids broad exception swallowing in the parser/WS security slice.
- Remaining non-security style issues, such as existing `object` Protocol annotations in the REST client and oversized pre-existing test modules, do not reopen the requested security blockers.

evidence gaps:
- No updated independent reviewer artifact was supplied after the correction; this artifact is based on direct inspection and executable read-only verification.
- Broader repo dirty state is outside this security slice and was not used as evidence for approval.

notepad: `/tmp/ulw-20260709-003801.IcHQQF.md`
