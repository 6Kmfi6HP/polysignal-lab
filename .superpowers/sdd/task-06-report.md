# Task 6 report: Nautilus matching order lifecycle and wallet mirror

## Changed files

- `src/polysignal_lab/nautilus_runtime/matching.py`
- `tests/test_nautilus_matching_execution.py`
- `.superpowers/sdd/task-06-report.md`

## Implementation summary

- `NautilusMatchingPaperExecutionClient` now executes supported taker intents (`TAKER_IOC`, `TAKER_FAK`, `TAKER_FOK`) directly from public order book ask liquidity.
- `max_entry_price` remains the order `limit_price` ceiling; fills use actual book liquidity prices and `reference_price` remains the source order price.
- Rejects unsupported side values with `UNSUPPORTED_SIDE`, missing books with `MISSING_ORDERBOOK`, stale books with `STALE_ORDERBOOK`, best ask above ceiling with `PRICE_ABOVE_LIMIT`, and insufficient FOK/depth cases with `INSUFFICIENT_DEPTH`.
- `depth_l2`/`queue_l2` modes consume ask liquidity across submissions so a filled level cannot be reused without a fresh book update.
- Filled taker orders create one `PaperFill`, one `PaperPosition`, and mirror the position to the shared `PaperWallet` once per fill id.
- No local paper executors (`BestAskTakerExecutor`, `PassiveGtdExecutor`, `PaperSimulator`) are imported or called from `matching.py`.

## RED evidence

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_taker_fills_at_book_price_not_slippage_model tests/test_nautilus_matching_execution.py::test_best_ask_above_max_entry_is_rejected tests/test_nautilus_matching_execution.py::test_fok_rejects_when_full_depth_unavailable tests/test_nautilus_matching_execution.py::test_liquidity_consumption_prevents_reusing_same_level -q
```

Result: failed as expected before implementation (`FFFF`, exit code 1). All four new tests returned `PENDING` instead of the expected filled/rejected matching lifecycle outcomes.

## GREEN focused checks

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py -q
```

Result: PASS (`......... [100%]`, exit code 0).

## Python 3.12 Nautilus optional check

Command:

```bash
uv run --extra nautilus --python 3.12 python -m pytest tests/test_nautilus_matching_execution.py tests/test_nautilus_instrument_mapping.py -q
```

Result: environment blocker. `uv` selected CPython 3.12.13, then failed building `nautilus-trader` from source on Linux aarch64 because `clang` is not installed:

```text
FileNotFoundError: [Errno 2] No such file or directory: 'clang'
RuntimeError: You are installing from source which requires the Clang compiler to be installed.
```

## Self-review

- Verified the matching path stays credential-free and Nautilus-free at import time.
- Verified max-entry semantics: order limit uses the ceiling while fill price comes from the book.
- Verified wallet mirror uses the same `PaperWallet` instance and stores the returned position id.
- Verified liquidity is consumed only after wallet affordability succeeds.
- Did not run project-wide gates, formatters, linters, Docker, or unrelated tests per brief.

## Concerns / blockers

- Python 3.12 Nautilus optional command is blocked by missing `clang` for the `nautilus-trader` source build on this aarch64 environment.

---

## Review blocker fix addendum

### Changed files

- `src/polysignal_lab/nautilus_runtime/matching.py`
- `tests/test_nautilus_matching_execution.py`
- `.superpowers/sdd/task-06-report.md`

### Implementation summary

- Removed the in-client taker book simulator from `NautilusMatchingPaperExecutionClient`; supported taker specs now submit through an injectable `NautilusMatchingBoundary`.
- Added `NautilusMatchingOutcome` / `NautilusFillEvent` mirroring so `PaperFill`, `PaperPosition`, and wallet updates are derived from matching-boundary events rather than recomputed from the local order book.
- Added a lazy `OwnedNautilusMatchingBoundary` seam that imports `SimulatedExchange` and `BacktestExecClient` only inside the boundary, keeping Python 3.11 core imports Nautilus-free.
- Moved unsupported-side validation before `PaperOrder` construction; invalid side values now return `UNSUPPORTED_SIDE` with no order object instead of raising during Pydantic validation.
- Updated focused tests to use a small fake Nautilus boundary/event source and added regression coverage proving boundary fill events are mirrored without local repricing.

### RED evidence

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py -q
```

Result before implementation: failed during collection, exit code 2, because the new tests imported missing boundary-event types:

```text
ImportError: cannot import name 'NautilusFillEvent' from 'polysignal_lab.nautilus_runtime.matching'
```

### GREEN focused checks

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py -q
```

Result: PASS (`........... [100%]`, exit code 0).

### Python 3.12 Nautilus optional check

Command:

```bash
uv run --extra nautilus --python 3.12 python -m pytest tests/test_nautilus_matching_execution.py tests/test_nautilus_instrument_mapping.py -q
```

Result: environment blocker. `uv` selected CPython 3.12.13 and failed building `nautilus-trader` from source on Linux aarch64 because `clang` is not installed:

```text
FileNotFoundError: [Errno 2] No such file or directory: 'clang'
RuntimeError: You are installing from source which requires the Clang compiler to be installed.
```

### Self-review

- Verified focused Python 3.11 matching tests pass after the boundary/event-source change.
- Verified `matching.py` has no `_match_taker`, local depth helpers, local paper executor imports, or top-level Nautilus imports.
- Verified unsupported side values are rejected before `PaperOrder` construction.
- Did not run project-wide gates, formatters, linters, Docker, safety scan, or unrelated tests per Task 6 constraints.

### Concerns / blockers

- Native Nautilus optional execution could not be exercised in this environment because the Python 3.12 `nautilus-trader` build fails before tests start due missing `clang`. The production code now routes through the Nautilus boundary and returns `MATCHING_NOT_CONNECTED` if the optional boundary cannot load, while focused Python 3.11 tests use an injectable fake boundary/event source.
