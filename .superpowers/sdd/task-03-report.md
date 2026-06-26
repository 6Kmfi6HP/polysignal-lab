# Task 3 Report: Deterministic Polymarket BinaryOption mapping

## Changed files

- `src/polysignal_lab/nautilus_runtime/instrument_mapping.py`
  - Added deterministic token id to Nautilus instrument id mapping.
  - Added `NautilusInstrumentMeta` and lazy Nautilus `BinaryOption` builder.
  - Kept all `nautilus_trader` imports inside `build_binary_option`.
- `src/polysignal_lab/nautilus_bridge/market_registry.py`
  - Added `PolymarketMarketRegistry.token_meta(token_id)` returning the registered up/down token metadata.
- `tests/nautilus_optional.py`
  - Added `require_nautilus()` helper for Python 3.12+ and optional `nautilus_trader` checks.
- `tests/test_nautilus_instrument_mapping.py`
  - Added focused instrument id, invalid tick size, and BinaryOption precision/metadata tests.
- `tests/test_nautilus_market_registry.py`
  - Added focused `token_meta` coverage.

## RED evidence

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_instrument_mapping.py -q
```

Result: failed as expected before implementation.

```text
Fsss                                                                     [100%]
FAILED tests/test_nautilus_instrument_mapping.py::test_instrument_id_for_token_is_stable - ModuleNotFoundError: No module named 'polysignal_lab.nautilus_runtime.instrument_mapping'
```

## GREEN / focused checks

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_instrument_mapping.py::test_instrument_id_for_token_is_stable -q
```

Result:

```text
.                                                                        [100%]
```

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_instrument_mapping.py -q
```

Result:

```text
.sss                                                                     [100%]
```

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_market_registry.py -q
```

Result:

```text
...                                                                      [100%]
```

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_platform_boundary.py::test_default_import_does_not_require_nautilus -q
```

Result:

```text
.                                                                        [100%]
```

## Nautilus optional check

Required command attempted:

```bash
uv run --extra nautilus --python 3.12 python -m pytest tests/test_nautilus_instrument_mapping.py -q
```

Result: blocked by local build environment before tests could run. `uv` selected CPython 3.12.13 and attempted to build `nautilus-trader` from source on Linux aarch64, but the build failed because `clang` is not installed:

```text
FileNotFoundError: [Errno 2] No such file or directory: 'clang'
RuntimeError: You are installing from source which requires the Clang compiler to be installed.
```

## Self-review

- `instrument_mapping.py` has no module-level Nautilus imports; Python 3.11 can import the module and the core package without `nautilus_trader`.
- `instrument_id_for_token(" 123456789 ")` returns the required `123456789.POLYSIGNAL_PM_PAPER` id.
- `build_binary_option` validates positive tick size, default size increment, and min order size before constructing Nautilus objects.
- BinaryOption metadata includes `condition_id`, `market_slug`, `asset`, `timeframe`, `token_id`, `side`, `tick_size`, and `min_order_size`.
- `MarketRegistry.token_meta` reuses the existing `by_token` lookup and returns the matching registered side metadata only.

## Concerns

- The Python 3.12 Nautilus-dependent test command could not execute in this environment because `clang` is missing for the aarch64 source build.
- An unrelated existing focused boundary test fails if run as `tests/test_nautilus_dependency_boundary.py -q`: it expects `optional_deps["nautilus"] == ["nautilus_trader[polymarket]"]`, while current `pyproject.toml` pins `nautilus_trader[polymarket]>=1.230.0; python_version >= '3.12'`.
