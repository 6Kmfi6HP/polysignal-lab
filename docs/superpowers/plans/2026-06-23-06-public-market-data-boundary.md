# Public Market Data Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PolySignal's read-only Polymarket market-data boundary enforceable by construction instead of relying only on substring safety scans.

**Architecture:** Introduce a narrow `PublicMarketDataClient` protocol, inject it at scheduler boundaries, and keep all SDK types private to the adapter module. Safety tests verify import boundaries, constructor surface, and deliberate forbidden fixtures.

**Tech Stack:** Python 3.11, typing Protocols, httpx, py-clob-client-v2 read-only public calls, pytest.

## Global Constraints

- Scope: One standalone architecture change. Do not execute with specs 01-05 or 07-08 in the same implementation batch.
- No migration to Polymarket beta SDK.
- No live trading capability.
- No weakening of existing safety scan.
- No broad dependency injection framework.
- Worktree branch: `spec-06-public-market-data-boundary`.
- This worktree may be developed in parallel, but merge conflicts are expected in `src/polysignal_lab/app/scheduler.py` with specs 05, 08, and 09.
- The only production module allowed to import `py_clob_client_v2` remains `src/polysignal_lab/data/polymarket_clob_rest.py`.

---

## File Structure

- Create `src/polysignal_lab/data/public_market_data_client.py` for `PublicMarketDataClient`.
- Modify `src/polysignal_lab/data/polymarket_clob_rest.py` to remove public `sdk_client` injection/state and keep SDK creation private.
- Modify `src/polysignal_lab/app/scheduler.py` to accept protocol implementation/factory and stop constructing concrete adapter outside the composition default.
- Modify `src/polysignal_lab/app/scheduler_market_data.py` only for attribute rename/type compatibility.
- Extend `tests/test_polymarket_clob_rest.py`, `tests/test_market_data.py`, `tests/test_websocket_contracts.py`, `tests/test_safety.py`, and `tests/test_config_security.py`.
- Create `tests/fixtures/forbidden_polymarket_sdk_import.py` as a deliberate policy violation fixture.

---

### Task 1: Define the public market-data protocol

**Files:**
- Create: `src/polysignal_lab/data/public_market_data_client.py`
- Test: `tests/test_market_data.py`

**Interfaces:**
- Produces: `PublicMarketDataClient` protocol with `get_book`, `get_books`, `get_mid`, `get_spread`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_market_data.py`:

```python
from typing import assert_type

from polysignal_lab.data.public_market_data_client import PublicMarketDataClient
from polysignal_lab.domain.orderbook import OrderBook


class _FakePublicMarketData:
    async def get_book(self, token_id: str) -> OrderBook:
        raise NotImplementedError

    async def get_books(self, token_ids: list[str]) -> list[OrderBook]:
        return []

    async def get_mid(self, token_id: str) -> float | None:
        return None

    async def get_spread(self, token_id: str) -> float | None:
        return None


def test_fake_market_data_client_matches_protocol() -> None:
    client: PublicMarketDataClient = _FakePublicMarketData()
    assert_type(client, PublicMarketDataClient)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_fake_market_data_client_matches_protocol -v`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement protocol**

Create `src/polysignal_lab/data/public_market_data_client.py`:

```python
from __future__ import annotations

from typing import Protocol

from polysignal_lab.domain.orderbook import OrderBook


class PublicMarketDataClient(Protocol):
    async def get_book(self, token_id: str) -> OrderBook: ...
    async def get_books(self, token_ids: list[str]) -> list[OrderBook]: ...
    async def get_mid(self, token_id: str) -> float | None: ...
    async def get_spread(self, token_id: str) -> float | None: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_fake_market_data_client_matches_protocol -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/data/public_market_data_client.py tests/test_market_data.py
git commit -m "feat: define public market data protocol"
```

---

### Task 2: Remove public SDK escape hatch from CLOB adapter

**Files:**
- Modify: `src/polysignal_lab/data/polymarket_clob_rest.py`
- Test: `tests/test_polymarket_clob_rest.py`

**Interfaces:**
- Consumes: existing read methods.
- Produces: `PolymarketCLOBRestClient` with no public `sdk_client` parameter or attribute.

- [ ] **Step 1: Write failing public-surface tests**

Add to `tests/test_polymarket_clob_rest.py`:

```python
import inspect

from polysignal_lab.data.polymarket_clob_rest import PolymarketCLOBRestClient


def test_clob_rest_constructor_does_not_expose_sdk_client() -> None:
    params = inspect.signature(PolymarketCLOBRestClient).parameters
    assert "sdk_client" not in params
    assert "key" not in params
    assert "private_key" not in params
    assert "creds" not in params


def test_clob_rest_instance_does_not_expose_sdk_client(polymarket_config) -> None:
    client = PolymarketCLOBRestClient(polymarket_config)
    assert "sdk_client" not in vars(client)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_polymarket_clob_rest.py::test_clob_rest_constructor_does_not_expose_sdk_client -v`

Expected: FAIL because constructor currently accepts `sdk_client`.

- [ ] **Step 3: Implement private SDK storage**

Change `PolymarketCLOBRestClient.__init__` to:

```python
def __init__(self, config: PolymarketDataConfig, client: httpx.AsyncClient | None = None):
    self.config = config
    self.client = client or httpx.AsyncClient(timeout=10.0)
    self._sdk_client_instance: _CLOBSDKClient | None = None
    self.rate_limiter = AsyncRateLimiter(config.rest_rate_limit_per_sec)
```

Change `_sdk_client()` to:

```python
def _sdk_client(self) -> _CLOBSDKClient:
    if self._sdk_client_instance is None:
        from py_clob_client_v2 import ClobClient as PublicCLOBClient

        self._sdk_client_instance = PublicCLOBClient(
            host=self.config.clob_base_url,
            chain_id=self.config.chain_id,
        )
    return cast(_CLOBSDKClient, self._sdk_client_instance)
```

Update existing batch tests that injected `sdk_client` by monkeypatching `_get_order_books_batch_sync`:

```python
async def test_get_books_uses_batch_path(polymarket_config, monkeypatch) -> None:
    client = PolymarketCLOBRestClient(polymarket_config)

    def fake_batch(token_ids: list[str]) -> list[object]:
        return [{"asset_id": token_ids[0], "bids": [], "asks": []}]

    monkeypatch.setattr(client, "_get_order_books_batch_sync", fake_batch)
    books = await client.get_books(["token-up"])
    assert [book.token_id for book in books] == ["token-up"]
```

- [ ] **Step 4: Run adapter tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_polymarket_clob_rest.py tests/test_market_data.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/data/polymarket_clob_rest.py tests/test_polymarket_clob_rest.py tests/test_market_data.py
git commit -m "fix: hide clob sdk client boundary"
```

---

### Task 3: Inject protocol into scheduler boundary

**Files:**
- Modify: `src/polysignal_lab/app/scheduler.py`
- Modify: `src/polysignal_lab/app/scheduler_market_data.py`
- Test: `tests/test_scheduler.py`
- Test: `tests/test_websocket_contracts.py`

**Interfaces:**
- Consumes: `PublicMarketDataClient`
- Produces: `PolySignalScheduler(..., market_data_client: PublicMarketDataClient | None = None)` and internal `scheduler.market_data`.

- [ ] **Step 1: Write failing scheduler injection test**

Add to `tests/test_scheduler.py`:

```python
from polysignal_lab.app.scheduler import PolySignalScheduler


class _FakeMarketData:
    async def get_book(self, token_id: str):
        raise AssertionError("not used")

    async def get_books(self, token_ids: list[str]):
        return []

    async def get_mid(self, token_id: str):
        return None

    async def get_spread(self, token_id: str):
        return None


def test_scheduler_accepts_public_market_data_protocol(settings) -> None:
    fake = _FakeMarketData()
    scheduler = PolySignalScheduler(settings, market_data_client=fake)
    assert scheduler.market_data is fake
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler.py::test_scheduler_accepts_public_market_data_protocol -v`

Expected: FAIL because `market_data_client` is not accepted.

- [ ] **Step 3: Implement scheduler protocol injection**

In `src/polysignal_lab/app/scheduler.py`, import protocol:

```python
from polysignal_lab.data.public_market_data_client import PublicMarketDataClient
```

Change constructor:

```python
class PolySignalScheduler:
    def __init__(
        self,
        settings: Settings,
        base_dir: str | Path = ".",
        market_data_client: PublicMarketDataClient | None = None,
    ):
        self.settings = settings
        self.ctx = ServiceContext(settings=settings)
        self.discovery = MarketDiscovery(settings.data.polymarket, settings.markets)
        self.market_data: PublicMarketDataClient = market_data_client or PolymarketCLOBRestClient(settings.data.polymarket)
```

Replace internal `scheduler.rest.get_books` callsites with `scheduler.market_data.get_books`. If short-term test compatibility requires `scheduler.rest`, make it a private compatibility property:

```python
@property
def rest(self) -> PublicMarketDataClient:
    return self.market_data
```

Prefer updating tests to assign `scheduler.market_data` rather than `scheduler.rest`.

- [ ] **Step 4: Run scheduler tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler.py tests/test_websocket_contracts.py tests/test_market_data.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_market_data.py tests/test_scheduler.py tests/test_websocket_contracts.py tests/test_market_data.py
git commit -m "feat: inject public market data client"
```

---

### Task 4: Add import-boundary safety policy

**Files:**
- Modify: `tests/test_safety.py`
- Create: `tests/fixtures/forbidden_polymarket_sdk_import.py`
- Test: `tests/test_safety.py`
- Test: `tests/test_config_security.py`

**Interfaces:**
- Produces: test helper `find_forbidden_sdk_imports(paths: list[Path]) -> list[Path]`.

- [ ] **Step 1: Add deliberate violating fixture**

Create `tests/fixtures/forbidden_polymarket_sdk_import.py`:

```python
from py_clob_client_v2 import ClobClient


def make_client():
    return ClobClient(host="https://clob.polymarket.com", chain_id=137)
```

- [ ] **Step 2: Write policy tests**

Add to `tests/test_safety.py`:

```python
from pathlib import Path

_ALLOWED_SDK_IMPORT_FILE = Path("src/polysignal_lab/data/polymarket_clob_rest.py")


def find_forbidden_sdk_imports(paths: list[Path]) -> list[Path]:
    offenders: list[Path] = []
    for root in paths:
        files = [root] if root.is_file() else list(root.rglob("*.py"))
        for path in files:
            text = path.read_text(encoding="utf-8")
            if "py_clob_client_v2" not in text:
                continue
            if path == _ALLOWED_SDK_IMPORT_FILE:
                continue
            offenders.append(path)
    return offenders


def test_polymarket_sdk_imports_are_adapter_only() -> None:
    assert find_forbidden_sdk_imports([Path("src/polysignal_lab")]) == []


def test_forbidden_sdk_import_fixture_is_detected() -> None:
    offenders = find_forbidden_sdk_imports([Path("tests/fixtures/forbidden_polymarket_sdk_import.py")])
    assert offenders == [Path("tests/fixtures/forbidden_polymarket_sdk_import.py")]
```

- [ ] **Step 3: Run tests to verify fixture is detected and source is clean**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_safety.py tests/test_config_security.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_safety.py tests/fixtures/forbidden_polymarket_sdk_import.py
git commit -m "test: enforce market data import boundary"
```

---

### Task 5: Final focused verification

**Files:**
- Modify only if failures reveal missed callsites.

**Interfaces:**
- Confirms existing CLOB read paths still work and safety remains locked down.

- [ ] **Step 1: Run targeted regression suite**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_polymarket_clob_rest.py tests/test_market_data.py tests/test_scheduler.py tests/test_websocket_contracts.py tests/test_safety.py tests/test_config_security.py -v
```

Expected: PASS.

- [ ] **Step 2: Run Docker verification after merge to runtime branch**

Run after merging this worktree into the formal runtime branch:

```bash
docker compose up -d --build --force-recreate
docker compose ps
```

Expected: compose services are recreated and no safety failure appears in startup logs.

- [ ] **Step 3: Commit verification adjustments**

```bash
git add src tests docs/superpowers/plans/2026-06-23-06-public-market-data-boundary.md
git commit -m "test: cover public market data boundary"
```
