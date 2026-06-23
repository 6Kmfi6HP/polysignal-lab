# Task 1 Report

## Status
DONE

## Files changed
- `src/polysignal_lab/paper/preflight.py`
- `tests/test_paper_execution_preflight.py`

## Tests run
- `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_execution_preflight.py::test_normalize_paper_reject_reason -v`
  - Initial TDD red result: failed with `ModuleNotFoundError: No module named 'polysignal_lab.paper.preflight'`.
  - Green result after adding preflight mapping: 14 passed.
- `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_execution_preflight.py -v`
  - Result before commit: 21 passed.
  - Fresh result after commit: 21 passed.

## Commit SHA(s)
- `db1f8a77f3a3746b92787aa5b65bf31b53a21b37` (`feat: add paper execution preflight`)

## Self-review notes
- Implemented only the Task 1 preflight service and its dedicated tests.
- Did not touch simulator, report, dashboard, live trading, authenticated CLOB, or order placement/cancel/redeem paths.
- Preflight accepts explicit orderbook snapshots and optional registry freshness checks; it does not perform network or trading operations.
- Reason mapping preserves `PAPER_` reasons and normalizes known fill/orderbook rejection reasons to paper-prefixed codes.

## Review fix: preflight realism findings

### Status
DONE

### Files changed
- `src/polysignal_lab/paper/preflight.py`
- `tests/test_paper_execution_preflight.py`

### TDD red results
- `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_execution_preflight.py::test_preflight_rejects_fak_slippage_above_limit tests/test_paper_execution_preflight.py::test_preflight_revalidates_stored_probability_edge -v`
  - Initial result after adding review tests: 2 failed.
  - Failures showed both review cases were incorrectly accepted with `PAPER_ACCEPTED`.

### Tests run
- `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_execution_preflight.py::test_preflight_rejects_fak_slippage_above_limit tests/test_paper_execution_preflight.py::test_preflight_revalidates_stored_probability_edge -v`
  - Green result: 2 passed.
- `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_execution_preflight.py -v`
  - Acceptance result before report append: 23 passed.

### Commit SHA(s)
- `a164cfd0e21a530c37a9593328f5eed15cfd80ec` (`fix: tighten paper preflight checks`)

### Fix notes
- `TAKER_FAK` preflight now mirrors executor slippage rejection after executable depth is found, preserving original `SLIPPAGE_EXCEEDS_MAX_ENTRY` and normalized `PAPER_EXTREME_SLIPPAGE`.
- Preflight now revalidates stored `probability_edge` with `entry_prob` and `directional_probability` when `min_probability_edge` is absent.

## Re-review fix: stale-edge and registry stale reasons

### Status
DONE

### Files changed
- `src/polysignal_lab/paper/preflight.py`
- `tests/test_paper_execution_preflight.py`

### TDD red results
- `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_execution_preflight.py::test_normalize_paper_reject_reason tests/test_paper_execution_preflight.py::test_preflight_normalizes_registry_stale_reasons tests/test_paper_execution_preflight.py::test_preflight_accepts_refs_style_min_token_price_edge -v`
  - Initial result after adding re-review tests: 7 failed, 14 passed.
  - Failures showed the three registry stale reasons normalized to `PAPER_FILL_REJECTED`, registry preflight decisions returned `PAPER_FILL_REJECTED`, and refs-style `min_token_price` edge revalidation incorrectly rejected unchanged ask as `PAPER_EDGE_VANISHED`.

### Green results
- `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_execution_preflight.py::test_normalize_paper_reject_reason tests/test_paper_execution_preflight.py::test_preflight_normalizes_registry_stale_reasons tests/test_paper_execution_preflight.py::test_preflight_accepts_refs_style_min_token_price_edge -v`
  - Targeted result after implementation: 21 passed.
- `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_execution_preflight.py -v`
  - Acceptance result before report append: 30 passed.

### Commit SHA(s)
- `abc02e4564acc9b2eca920eb596978ef6393efd6` (`fix: handle preflight stale edges`)

### Fix notes
- Refs-style PTB signals with `min_token_price` now revalidate against the token price floor before falling back to legacy stored `probability_edge` semantics.
- `RECONNECT_RESEED_FAILED`, `TICK_SIZE_CHANGE_RESEED_REQUIRED`, and `BOOK_SEQUENCE_INVALID` now normalize to `PAPER_STALE_ORDERBOOK` while `paper_original_reason` preserves the registry reason.
