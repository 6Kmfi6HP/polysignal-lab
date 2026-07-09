# OrderBook Data-Boundary Parser Migration Code Review

<verdict>FAIL</verdict>

codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: .omo/evidence/orderbook-data-boundary-parser-migration-code-review.md

## Skill-Perspective Check

- remove-ai-slops: ran. The diff violates this perspective: the new boundary code silently normalizes invalid/non-object payloads to `{}` and current tests do not cover the adversarial boundary case.
- programming: ran with Python README plus data-modeling/type-patterns references. The diff violates this perspective: the new parser uses `object` at the JSON boundary and produces basedpyright unknown-type warnings instead of preserving `JsonValue`/typed payload shape.
- ponytail: active. The fix should be small: make the parser fail closed on missing token/non-object payloads and keep JSON typing, rather than adding new abstraction.

## CRITICAL

None.

## HIGH

1. `src/polysignal_lab/data/orderbook_payload.py:27`, `src/polysignal_lab/data/orderbook_payload.py:54`, `src/polysignal_lab/data/orderbook_payload.py:77`: the new data-boundary parser is fail-open and type-erased. `JsonObject = Mapping[str, object]` drops the `JsonValue` proof at the new boundary; `json_object()` returns `{}` for non-object JSON; `_token_id()` turns a missing token into `""`. That means callers can get an apparently valid `OrderBook(token_id="")` from malformed/non-object/missing-token payloads. The downstream REST and WS paths call this parser directly at `src/polysignal_lab/data/polymarket_clob_rest.py:54` and `src/polysignal_lab/data/polymarket_clob_ws.py:89`, and `OrderBookRegistry` keys state by `token_id`, so this can poison state under the empty token instead of rejecting bad input. I verified the behavior with `parse_order_book_payload({}) -> token_id ''` and `json_object(['not', 'object']) -> {}`. This blocks approval because the migration's core intent is to move raw payload parsing to the data/app boundary; that boundary must parse-or-reject, not synthesize an empty book.

## MEDIUM

None beyond the HIGH blocker above.

## LOW

None blocking.

## Verification

- Reviewed scope from `.omo/ulw-loop/evidence/orderbook-changed-files.txt` and `.omo/ulw-loop/evidence/orderbook-diff.patch`.
- Reviewed full changed file contents and adjacent patterns in `readonly_smoke_types.py`, `data/state.py`, `domain/market.py`, and `market_discovery_helpers.py`.
- `PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider tests/test_market_data.py tests/test_orderbook_snapshot.py tests/test_polymarket_clob_rest.py` -> 30 passed, 2 third-party deprecation warnings.
- `PYTHONDONTWRITEBYTECODE=1 uv run ruff check ...changed files...` -> passed.
- Production compile smoke using `compile(source, path, "exec")` -> passed.
- `PYTHONDONTWRITEBYTECODE=1 uv run basedpyright ...changed production files...` -> 0 errors, 13 warnings. Relevant warnings are on the new boundary/JSON handling: `orderbook_payload.py:65`, `orderbook_payload.py:70`, `orderbook_payload.py:71`, `polymarket_clob_rest.py:116`, `polymarket_clob_rest.py:120`, `polymarket_clob_ws.py:112`, `polymarket_clob_ws.py:116`.

## Blocking Issues

- Fix the OrderBook payload boundary so non-object payloads and payloads without a usable token id are rejected or surfaced as parse failure before constructing `OrderBook`, and keep the boundary typed as JSON (`JsonValue`/`dict[str, JsonValue]` or a specific typed payload), not `Mapping[str, object]`.
- Add a focused adversarial regression for that boundary behavior so the parser cannot silently produce `OrderBook(token_id="")` again.
