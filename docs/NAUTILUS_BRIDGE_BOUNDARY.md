# Nautilus Bridge Boundary

PolySignal Lab remains read-only and paper-safe by default. The default Python 3.11 environment, Docker runtime, and `polysignal-lab` entry point do not install NautilusTrader and do not import NautilusTrader at package import time.

## Default Runtime

- Python: project default is `>=3.11`.
- Default install: `uv sync --extra dev`.
- Default import check: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -c "import polysignal_lab"`.
- Default Docker path: `docker compose up -d --build --force-recreate`.
- Default runtime does not register live Polymarket execution clients.

## Bridge Runtime

NautilusTrader is isolated behind the optional dependency group:

```bash
uv sync --extra nautilus --python 3.12
uv run python -c "import nautilus_trader.adapters.polymarket"
```

The bridge environment must use Python 3.12-3.14. On Linux, verify glibc first:

```bash
ldd --version
```

The first line must report glibc 2.35 or newer.

## ARM64 / rk3588 Verification

On the ARM64 host, record the outcome of this command before using the bridge runtime:

```bash
uv sync --extra nautilus --python 3.12
```

Accepted outcomes:

- A binary wheel installs successfully for Linux ARM64.
- A source build succeeds after installing the build toolchain required by NautilusTrader.

If neither path works, the bridge package remains source-present but disabled on that host.

## Safety Boundary

Default code must not import, instantiate, or register live execution classes or helper scripts from the Nautilus Polymarket adapter. Default code must not read these environment variables:

- `POLYMARKET_PK`
- `POLYMARKET_FUNDER`
- `POLYMARKET_API_KEY`
- `POLYMARKET_API_SECRET`
- `POLYMARKET_PASSPHRASE`

Default code must not invoke allowance or API-key scripts from the adapter.


## Verification Log

Record the exact command output in the pull request or commit notes when executing this plan:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -c "import polysignal_lab"
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_dependency_boundary.py tests/test_alpha_types.py tests/test_alpha_ptb_diff.py tests/test_nautilus_market_registry.py tests/test_nautilus_external_data.py tests/test_nautilus_market_view_assembler.py tests/test_nautilus_state.py tests/test_nautilus_strategy_base.py tests/test_nautilus_safety_boundary.py tests/test_ptb_diff.py -v
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run polysignal-safety-scan .
ldd --version
uv sync --extra nautilus --python 3.12
uv run python -c "import nautilus_trader.adapters.polymarket"
docker compose up -d --build --force-recreate
docker compose ps
```

### Actual Results (2026-06-25)

- `import polysignal_lab`: exit 0, no output (default 3.11 runtime, no Nautilus).
- `pytest` bridge tests: **35 passed** in 0.17s across 10 test files.
- `polysignal-safety-scan`: `Safety scan passed`.
- `ldd --version`: glibc 2.35 (aarch64).
- `uv sync --extra nautilus --python 3.12`: not run (Nautilus not required for default verification).
- `import nautilus_trader.adapters.polymarket`: not run (Python 3.12 env not active).
- `docker compose up -d --build --force-recreate`: not run (verification is source-level only).
- `docker compose ps`: not run.

After Docker rebuild, verify dashboard health with a cache-busted URL:

```text
http://127.0.0.1:8081/health?fresh=nautilus_bridge
```