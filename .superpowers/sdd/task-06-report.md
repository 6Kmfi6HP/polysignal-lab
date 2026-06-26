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

---

## Re-review blocker fix addendum

### Changed files

- `src/polysignal_lab/nautilus_runtime/matching.py`
- `tests/test_nautilus_matching_execution.py`
- `.superpowers/sdd/task-06-report.md`

### Implementation summary

- Replaced the owned matching boundary stub with a lazy Nautilus sandbox boundary: it stores books, builds a sandbox `BinaryOption`, publishes `OrderBookDeltas`, submits IOC/FOK limit orders through `SandboxExecutionClient`, and mirrors Nautilus `OrderFilled` / `OrderRejected` events into `NautilusMatchingOutcome`.
- Kept Nautilus imports inside `_load_nautilus_components()` so Python 3.11 core imports remain Nautilus-free when the optional extra is absent.
- Fixed replay idempotency by skipping already mirrored fill ids before creating returned `PaperFill` / `PaperPosition` records and before wallet apply.
- Added regressions for replayed fill ids and for the owned boundary submit path delegating past the lazy Nautilus seam without importing Nautilus under Python 3.11.

### RED evidence

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_replayed_fill_id_is_not_returned_or_applied_twice tests/test_nautilus_matching_execution.py::test_owned_boundary_stores_books_and_delegates_to_nautilus_path -q
```

Result before implementation: failed as expected (`FF`, exit code 1). The replay test returned a duplicate `PaperFill`; the owned-boundary contract test raised `NautilusMatchingUnavailable` from the stubbed unconditional Nautilus load/raise path.

### GREEN focused checks

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py -q
```

Result: PASS (`............. [100%]`, exit code 0).

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

### Source boundary checks

- `matching.py` / focused tests contain no `ClobClient(` source token.
- `matching.py` contains no top-level `nautilus_trader` imports.
- `matching.py` contains no `BestAskTakerExecutor`, `PassiveGtdExecutor`, or `PaperSimulator` references.

### Self-review

- Verified the required Python 3.11 focused matching suite after the optional Python 3.12 attempt recreated `.venv`.
- Verified replayed fill ids are absent from the second returned result and do not create a second wallet position.
- Verified the owned boundary update/submit contract stores the latest book and reaches the overridable Nautilus submit seam instead of unconditionally raising.
- Did not run project-wide gates, formatters, linters, Docker, safety scan, or unrelated tests per Task 6 constraints.

### Concerns / blockers

- Native Nautilus execution still cannot be exercised in this environment until `clang` is installed for the Python 3.12 `nautilus-trader` source build.

---

## Final review blocker fix addendum

### Changed files

- `src/polysignal_lab/nautilus_runtime/matching.py`
- `tests/test_nautilus_matching_execution.py`
- `.superpowers/sdd/task-06-report.md`

### Implementation summary

- Removed the post-submit stored-book replay from the owned Nautilus submit path; the boundary now publishes the stored book before submission and only publishes again when `update_book()` receives a fresh external book.
- Added an owned-boundary price ceiling precheck: if the stored top ask is above `PaperOrder.limit_price`, `submit_order()` returns `NautilusMatchingOutcome(REJECTED, reason="PRICE_ABOVE_LIMIT")` before ensuring a Nautilus session or submitting.
- Replaced `SandboxExecutionClient` construction with direct `SimulatedExchange` + `BacktestExecClient` wiring, passing `liquidity_consumption`, `queue_position`, and `price_protection_points` from `MatchingAccuracySettings` into the exchange before instruments are added.
- Added Python 3.11 focused regression tests using fake seams so Nautilus remains optional/lazy at core import time.

### RED evidence

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_owned_boundary_rejects_best_ask_above_limit_before_session tests/test_nautilus_matching_execution.py::test_owned_boundary_does_not_replay_stored_book_after_submit tests/test_nautilus_matching_execution.py::test_owned_boundary_configures_exchange_with_accuracy_settings -q
```

Result before implementation: failed as expected (`FFF`, exit code 1):

- price-ceiling test returned `FILLED` instead of `REJECTED`;
- no-replay test observed two stored-book publishes (`['token-up', 'token-up']`);
- exchange-settings test did not see any direct `SimulatedExchange` construction.

### GREEN focused checks

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py -q
```

Result: PASS (`................ [100%]`, exit code 0).

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

### Source boundary checks

- `matching.py` / focused tests contain no `ClobClient(` source token.
- `matching.py` contains no top-level `nautilus_trader` imports.
- `matching.py` contains no `SandboxExecutionClient`, `SandboxExecutionClientConfig`, or post-submit stored-book replay.

### Self-review

- Verified the three final-review regressions fail before the fix and pass after the fix.
- Verified the required Python 3.11 focused matching suite after the optional Python 3.12 attempt recreated `.venv`.
- Verified direct Nautilus exchange wiring follows the upstream `SimulatedExchange` / `BacktestExecClient` construction pattern and explicitly forwards depth/queue/protection settings.
- Did not run project-wide gates, formatters, linters, Docker, safety scan, or unrelated tests per Task 6 constraints.

### Concerns / blockers

- Native Nautilus optional execution still cannot be exercised in this environment until `clang` is installed for the Python 3.12 `nautilus-trader` source build.


---

## Approval review dirty-book fix addendum

### Changed files

- `src/polysignal_lab/nautilus_runtime/matching.py`
- `tests/test_nautilus_matching_execution.py`
- `.superpowers/sdd/task-06-report.md`

### Command result

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py -q
```

Result: PASS (`................ [100%]`, exit code 0).

### Self-review

- Added dirty-book tracking so a stored public book is published to Nautilus once per external `update_book()`.
- Verified repeated owned-boundary submissions after one book update no longer replay the same book and reset consumed depth.
- Verified a fresh second `update_book()` republishes for an already-created session/instrument.
- Did not run project-wide gates, formatters, linters, Docker, safety scan, or unrelated tests per Task 6 constraints.

### Concerns / blockers

- None for the focused Python 3.11 dirty-book fix.
