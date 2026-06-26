# Nautilus Matching Paper Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut `runtime.engine="nautilus"` over from local paper matching to a PolySignal-owned NautilusTrader `SimulatedExchange` matching adapter, with no live Polymarket execution and no local-paper runtime fallback.

**Architecture:** Keep the existing PolySignal-owned `NautilusOrchestrator` loop and strategy wrappers. Split legacy local-paper execution types out of `nautilus_runtime/execution.py`, add a new Nautilus matching adapter that owns `SimulatedExchange`, feed it public CLOB book/trade data, and mirror Nautilus execution events back into existing `PaperOrder` / `PaperFill` / `PaperPosition` read models for settlement, Telegram, SQLite, JSONL, and reports.

**Tech Stack:** Python 3.11 core package, Python 3.12+ `polysignal-nautilus` runtime, `nautilus_trader[polymarket]` optional extra, Pydantic settings, pytest, uv, existing PolySignal persistence/Telegram services.

## Global Constraints

- Complete cutover: `runtime.engine="nautilus"` paper execution uses Nautilus matching only; no dual backend, no rollback config, no phased production rollout.
- Legacy local paper modules stay in the repository but are not imported or instantiated by default Nautilus runtime wiring.
- Default runtime must not construct `PolymarketExecutionClient`, `PolymarketLiveExecClientFactory`, authenticated `exec_clients`, `PolymarketExecClientConfig`, allowance scripts, or API-key helper scripts.
- Default paper mode must not read `POLYMARKET_PK`, `POLYMARKET_FUNDER`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, or `POLYMARKET_PASSPHRASE`.
- Preserve `PublicCLOBClient` alias convention; source must avoid the blocked `ClobClient(` token.
- Core package import on Python 3.11 remains Nautilus-free; Nautilus matching runtime requires Python 3.12+ and the optional `nautilus` extra.
- Production accuracy mode at cutover is `depth_l2`; `queue_l2` is config-only after trade tick side/size quality is proven.
- Active runtime must log/report `paper_engine=nautilus_matching` and the active accuracy mode in startup, health, daily report, and paper execution assumptions.
- Settlement remains PolySignal-owned: CTF chain -> Gamma exact lookup -> WS cache hints.
- Tests use `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest ...` for core checks; Nautilus-dependent checks use Python 3.12+ with `--extra nautilus`.
- Known unrelated failure: `test_telegram_interactive_yaml_defaults_load`.
- After runtime code/config changes, rebuild Docker with `docker compose up -d --build --force-recreate` and verify with `docker compose ps` before declaring the runtime live.
- Commits use Conventional Commit types only, 72-character subject limit, lowercase non-vague descriptions.

---

## File Structure

### Create

- `src/polysignal_lab/nautilus_runtime/execution_types.py` — shared Nautilus-runtime result dataclasses that do not import local paper executors.
- `src/polysignal_lab/nautilus_runtime/instrument_mapping.py` — deterministic Polymarket token -> Nautilus `BinaryOption` mapping, with lazy Nautilus imports.
- `src/polysignal_lab/nautilus_runtime/matching.py` — `NautilusMatchingPaperExecutionClient`, accuracy-mode settings, public book/trade feed, order submission, event drain, and wallet mirror.
- `tests/nautilus_optional.py` — one helper for skipping Nautilus-dependent tests when Python 3.12+ / optional extra is unavailable.
- `tests/test_nautilus_instrument_mapping.py` — instrument ID determinism and precision tests.
- `tests/test_nautilus_matching_execution.py` — matching adapter construction, order mapping, L2 consumption, GTD, FOK/IOC, stale/malformed book, and wallet mirror tests.

### Modify

- `pyproject.toml` — pin optional Nautilus dependency to `nautilus_trader[polymarket]>=1.230.0; python_version >= '3.12'`.
- `uv.lock` — refresh lockfile after dependency bump.
- `src/polysignal_lab/config.py` — add Nautilus paper engine and accuracy mode config; keep `execution_mode="paper_sandbox"` as paper-only safety name.
- `src/polysignal_lab/nautilus_runtime/execution.py` — keep legacy local paper client only for isolated tests; move `PaperExecutionResult` out.
- `src/polysignal_lab/nautilus_runtime/observability.py` — import `PaperExecutionResult` from `execution_types.py`, record matching engine metadata, and avoid importing legacy `execution.py`.
- `src/polysignal_lab/nautilus_runtime/data_ingestor.py` — replace `paper_client.update_book()` with matching-client book/trade feed calls.
- `src/polysignal_lab/nautilus_runtime/node.py` — wire `NautilusMatchingPaperExecutionClient` only; update bundle field names without a backend branch.
- `src/polysignal_lab/nautilus_runtime/orchestrator.py` — add event drain, resting-order, and position-exit phases; remove default imports of legacy local paper client.
- `tests/test_nautilus_platform_boundary.py` — strengthen live-symbol and local-paper isolation source scans.
- `tests/test_nautilus_safety_boundary.py` — keep bridge/runtime safety scan aligned with new source boundaries.
- `tests/test_nautilus_data_ingestor.py` — assert books/trades feed the matching client and no local paper update path exists.
- `tests/test_nautilus_node.py` — assert node wiring uses `NautilusMatchingPaperExecutionClient`; isolate Python 3.12+ runtime construction.
- `tests/test_nautilus_orchestrator.py` — assert new phase order, event drain, position exits, and settlement/reporting compatibility.
- `tests/test_nautilus_observability.py` — assert order/fill/position rows include Nautilus matching metadata and idempotency keys.
- `tests/test_nautilus_execution.py` — keep local `PolySignalPaperExecutionClient` tests as isolated legacy tests or move legacy-specific tests under `tests/test_paper_*`.

---

## Task 1: Dependency and runtime config foundation

**Files:**
- Modify: `pyproject.toml:26-28`
- Modify: `uv.lock`
- Modify: `src/polysignal_lab/config.py:253-272`
- Modify: `tests/test_nautilus_platform_boundary.py:14-18`
- Modify: `tests/test_nautilus_runtime_config.py`

**Interfaces:**
- Produces: `NautilusRuntimeConfig.paper_engine: Literal["nautilus_matching"]`
- Produces: `NautilusRuntimeConfig.matching_accuracy_mode: Literal["fast_l1", "depth_l2", "queue_l2"]`
- Produces: optional dependency spec `nautilus_trader[polymarket]>=1.230.0; python_version >= '3.12'`

- [ ] **Step 1: Write failing config tests**

Add these tests to `tests/test_nautilus_runtime_config.py`:

```python
import pytest
from pydantic import ValidationError

from polysignal_lab.config import Settings


def test_nautilus_matching_defaults_are_paper_only() -> None:
    settings = Settings()

    assert settings.runtime.nautilus.execution_mode == "paper_sandbox"
    assert settings.runtime.nautilus.paper_engine == "nautilus_matching"
    assert settings.runtime.nautilus.matching_accuracy_mode == "depth_l2"
    assert settings.runtime.nautilus.allow_live_polymarket_execution is False


def test_nautilus_rejects_unknown_matching_accuracy_mode() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({
            "runtime": {
                "nautilus": {
                    "matching_accuracy_mode": "legacy_local",
                }
            }
        })
```

Update `tests/test_nautilus_platform_boundary.py::test_nautilus_extra_is_optional_and_polymarket_scoped`:

```python
def test_nautilus_extra_is_optional_and_polymarket_scoped() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert all("nautilus_trader" not in dep for dep in data["project"]["dependencies"])
    assert data["project"]["optional-dependencies"]["nautilus"] == [
        "nautilus_trader[polymarket]>=1.230.0; python_version >= '3.12'"
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_runtime_config.py tests/test_nautilus_platform_boundary.py::test_nautilus_extra_is_optional_and_polymarket_scoped -q
```

Expected: FAIL because `paper_engine`, `matching_accuracy_mode`, and the dependency pin are not present.

- [ ] **Step 3: Add config fields and dependency pin**

In `pyproject.toml`, replace the Nautilus optional dependency line with:

```toml
nautilus = ["nautilus_trader[polymarket]>=1.230.0; python_version >= '3.12'"]
```

In `src/polysignal_lab/config.py`, change `NautilusRuntimeConfig` to:

```python
class NautilusRuntimeConfig(BaseModel):
    trader_id: str = "PolySignal-Nautilus-001"
    python: str = "3.12"
    execution_mode: Literal["paper_sandbox"] = "paper_sandbox"
    paper_engine: Literal["nautilus_matching"] = "nautilus_matching"
    matching_accuracy_mode: Literal["fast_l1", "depth_l2", "queue_l2"] = "depth_l2"
    allow_live_polymarket_execution: bool = False
    polymarket_data: NautilusDataClientConfig = Field(default_factory=NautilusDataClientConfig)
    sidecar: NautilusSidecarConfig = Field(default_factory=NautilusSidecarConfig)
    decision_policy: NautilusDecisionPolicyConfig = Field(default_factory=NautilusDecisionPolicyConfig)

    @model_validator(mode="after")
    def validate_paper_safe(self) -> "NautilusRuntimeConfig":
        if self.allow_live_polymarket_execution:
            raise ValueError("live Polymarket execution is invalid in the default runtime")
        return self
```

Refresh the lockfile with Python 3.12+:

```bash
uv lock --extra nautilus --python 3.12
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_runtime_config.py tests/test_nautilus_platform_boundary.py::test_nautilus_extra_is_optional_and_polymarket_scoped -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/polysignal_lab/config.py tests/test_nautilus_runtime_config.py tests/test_nautilus_platform_boundary.py
git commit -m "build: pin nautilus matching runtime dependency"
```

---

## Task 2: Split shared execution result types away from legacy local paper

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/execution_types.py`
- Modify: `src/polysignal_lab/nautilus_runtime/execution.py`
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py:7-13`
- Modify: `src/polysignal_lab/nautilus_runtime/orchestrator.py:11-14`
- Modify: `tests/test_nautilus_platform_boundary.py`

**Interfaces:**
- Produces: `PaperExecutionResult(order: PaperOrder | None, fills: list[PaperFill], positions: list[PaperPosition], status: OrderStatus, reason: str | None)` from `polysignal_lab.nautilus_runtime.execution_types`.
- Preserves: `order_spec_from_decision(...) -> NautilusOrderSpec` in `polysignal_lab.nautilus_runtime.execution` for existing strategy tests until a separate order-mapping cleanup is needed.

- [ ] **Step 1: Write failing source-boundary test**

Add this test to `tests/test_nautilus_platform_boundary.py`:

```python
def test_default_nautilus_runtime_source_avoids_local_paper_executors() -> None:
    forbidden = (
        "from polysignal_lab.paper.order_intent_executor import",
        "BestAskTakerExecutor",
        "PassiveGtdExecutor",
        "PaperSimulator",
        "PolySignalPaperExecutionClient(",
    )
    allowed_files = {
        Path("src/polysignal_lab/nautilus_runtime/execution.py"),
    }
    findings: list[str] = []
    for path in Path("src/polysignal_lab/nautilus_runtime").rglob("*.py"):
        if path in allowed_files:
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_platform_boundary.py::test_default_nautilus_runtime_source_avoids_local_paper_executors -q
```

Expected: FAIL because `orchestrator.py`, `node.py`, `data_ingestor.py`, or `observability.py` still reach legacy execution symbols.

- [ ] **Step 3: Create shared execution types**

Create `src/polysignal_lab/nautilus_runtime/execution_types.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from polysignal_lab.domain.enums import OrderStatus
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition


@dataclass(slots=True)
class PaperExecutionResult:
    order: PaperOrder | None = None
    fills: list[PaperFill] = field(default_factory=list)
    positions: list[PaperPosition] = field(default_factory=list)
    status: OrderStatus = OrderStatus.PENDING
    reason: str | None = None
```

In `src/polysignal_lab/nautilus_runtime/execution.py`, remove the local `PaperExecutionResult` dataclass definition and import it instead:

```python
from polysignal_lab.nautilus_runtime.execution_types import PaperExecutionResult
```

In `src/polysignal_lab/nautilus_runtime/observability.py`, replace:

```python
from polysignal_lab.nautilus_runtime.execution import PaperExecutionResult
```

with:

```python
from polysignal_lab.nautilus_runtime.execution_types import PaperExecutionResult
```

In `src/polysignal_lab/nautilus_runtime/orchestrator.py`, replace the legacy execution import block with:

```python
from polysignal_lab.nautilus_runtime.execution_types import PaperExecutionResult
```

- [ ] **Step 4: Run boundary and observability tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_platform_boundary.py::test_default_nautilus_runtime_source_avoids_local_paper_executors tests/test_nautilus_observability.py -q
```

Expected: PASS for updated imports; node/data-ingestor references will be removed in later tasks if still listed by the boundary test.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/execution_types.py src/polysignal_lab/nautilus_runtime/execution.py src/polysignal_lab/nautilus_runtime/observability.py src/polysignal_lab/nautilus_runtime/orchestrator.py tests/test_nautilus_platform_boundary.py
git commit -m "refactor: split nautilus execution result types"
```

---

## Task 3: Deterministic Polymarket `BinaryOption` instrument mapping

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/instrument_mapping.py`
- Modify: `src/polysignal_lab/nautilus_bridge/market_registry.py`
- Create: `tests/nautilus_optional.py`
- Create: `tests/test_nautilus_instrument_mapping.py`

**Interfaces:**
- Produces: `NautilusInstrumentMeta(token_id: str, instrument_id: str, condition_id: str, side: Side, tick_size: float, size_increment: float, market_slug: str)`.
- Produces: `build_binary_option(pair: MarketPairMeta, token: InstrumentTokenMeta, *, tick_size: float | None, min_order_size: float | None, ts_init_ns: int) -> BinaryOption`.
- Produces: `instrument_id_for_token(token_id: str, venue: str = "POLYSIGNAL_PM_PAPER") -> str`.

- [ ] **Step 1: Add Nautilus optional test helper**

Create `tests/nautilus_optional.py`:

```python
from __future__ import annotations

import importlib.util
import sys

import pytest


def require_nautilus() -> None:
    if sys.version_info < (3, 12):
        pytest.skip("Nautilus matching tests require Python 3.12+")
    if importlib.util.find_spec("nautilus_trader") is None:
        pytest.skip("Nautilus matching tests require the nautilus optional extra")
```

- [ ] **Step 2: Write failing instrument tests**

Create `tests/test_nautilus_instrument_mapping.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from factories import MarketFactoryConfig, sample_market
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.market_registry import MarketPairMeta
from tests.nautilus_optional import require_nautilus


def test_instrument_id_for_token_is_stable() -> None:
    from polysignal_lab.nautilus_runtime.instrument_mapping import instrument_id_for_token

    first = instrument_id_for_token("123456789", venue="POLYSIGNAL_PM_PAPER")
    second = instrument_id_for_token("123456789", venue="POLYSIGNAL_PM_PAPER")

    assert first == second
    assert first == "123456789.POLYSIGNAL_PM_PAPER"


def test_build_binary_option_preserves_precision_and_metadata() -> None:
    require_nautilus()
    from polysignal_lab.nautilus_runtime.instrument_mapping import build_binary_option

    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    pair = MarketPairMeta.from_market(market)
    token = pair.up

    instrument = build_binary_option(
        pair,
        token,
        tick_size=0.001,
        min_order_size=5.0,
        ts_init_ns=1,
    )

    assert instrument.id.to_str() == f"{token.token_id}.POLYSIGNAL_PM_PAPER"
    assert instrument.price_increment.as_double() == pytest.approx(0.001)
    assert instrument.price_precision == 3
    assert instrument.size_increment.as_double() == pytest.approx(0.000001)
    assert instrument.size_precision == 6
    assert instrument.info["condition_id"] == pair.condition_id
    assert instrument.info["market_slug"] == pair.market_slug
    assert instrument.info["side"] == Side.UP.value


def test_build_binary_option_rejects_invalid_tick_size() -> None:
    require_nautilus()
    from polysignal_lab.nautilus_runtime.instrument_mapping import build_binary_option

    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    pair = MarketPairMeta.from_market(market)

    with pytest.raises(ValueError, match="tick_size must be positive"):
        build_binary_option(pair, pair.up, tick_size=0.0, min_order_size=5.0, ts_init_ns=1)
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_instrument_mapping.py -q
```

Expected: first test FAIL because `instrument_mapping.py` is missing; Nautilus-specific tests skip on Python 3.11 if the helper runs first.

- [ ] **Step 4: Implement instrument mapping with lazy Nautilus imports**

Create `src/polysignal_lab/nautilus_runtime/instrument_mapping.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.market_registry import InstrumentTokenMeta, MarketPairMeta

DEFAULT_VENUE = "POLYSIGNAL_PM_PAPER"
DEFAULT_TICK_SIZE = 0.001
DEFAULT_SIZE_INCREMENT = 0.000001
DEFAULT_MIN_ORDER_SIZE = 5.0


@dataclass(frozen=True, slots=True)
class NautilusInstrumentMeta:
    token_id: str
    instrument_id: str
    condition_id: str
    side: Side
    tick_size: float
    size_increment: float
    market_slug: str


def instrument_id_for_token(token_id: str, venue: str = DEFAULT_VENUE) -> str:
    token = str(token_id).strip()
    if not token:
        raise ValueError("token_id is required")
    return f"{token}.{venue}"


def _positive(value: float | None, default: float, name: str) -> float:
    number = default if value is None else float(value)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def build_binary_option(
    pair: MarketPairMeta,
    token: InstrumentTokenMeta,
    *,
    tick_size: float | None,
    min_order_size: float | None,
    ts_init_ns: int,
):
    from nautilus_trader.core.rust.model import AssetClass
    from nautilus_trader.model.currencies import USDC
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
    from nautilus_trader.model.instruments import BinaryOption
    from nautilus_trader.model.objects import Price, Quantity

    tick = _positive(tick_size, DEFAULT_TICK_SIZE, "tick_size")
    min_size = _positive(min_order_size, DEFAULT_MIN_ORDER_SIZE, "min_order_size")
    size_increment = DEFAULT_SIZE_INCREMENT
    raw_symbol = Symbol(token.token_id)
    price_increment = Price.from_str(f"{tick:g}")
    quantity_increment = Quantity.from_str(f"{size_increment:g}")
    expiration_ns = int(pair.end_ts.timestamp() * 1_000_000_000) if pair.end_ts else 0
    info = {
        "condition_id": pair.condition_id,
        "market_id": pair.market_id,
        "market_slug": pair.market_slug,
        "asset": pair.asset,
        "timeframe": pair.timeframe,
        "token_id": token.token_id,
        "side": token.side.value,
        "tick_size": tick,
        "min_order_size": min_size,
    }
    return BinaryOption(
        instrument_id=InstrumentId(symbol=raw_symbol, venue=Venue(DEFAULT_VENUE)),
        raw_symbol=raw_symbol,
        outcome=token.side.value,
        description=pair.market_slug,
        asset_class=AssetClass.ALTERNATIVE,
        currency=USDC,
        price_precision=price_increment.precision,
        price_increment=price_increment,
        size_precision=quantity_increment.precision,
        size_increment=quantity_increment,
        activation_ns=0,
        expiration_ns=expiration_ns,
        max_quantity=None,
        min_quantity=Quantity.from_str(f"{min_size:g}"),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        ts_event=ts_init_ns,
        ts_init=ts_init_ns,
        info=info,
    )
```

In `src/polysignal_lab/nautilus_bridge/market_registry.py`, add a method for token metadata lookup:

```python
    def token_meta(self, token_id: str) -> InstrumentTokenMeta | None:
        pair = self.by_token(token_id)
        if pair is None:
            return None
        if pair.up.token_id == token_id:
            return pair.up
        if pair.down.token_id == token_id:
            return pair.down
        return None
```

- [ ] **Step 5: Run tests to verify they pass or skip correctly**

Run Python 3.11 boundary:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_instrument_mapping.py::test_instrument_id_for_token_is_stable -q
```

Expected: PASS.

Run Python 3.12+ Nautilus checks:

```bash
uv run --extra nautilus --python 3.12 python -m pytest tests/test_nautilus_instrument_mapping.py -q
```

Expected: PASS when Python 3.12+ and Nautilus are available; otherwise the worker must install/sync the configured Python 3.12+ environment before continuing.

- [ ] **Step 6: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/instrument_mapping.py src/polysignal_lab/nautilus_bridge/market_registry.py tests/nautilus_optional.py tests/test_nautilus_instrument_mapping.py
git commit -m "feat: map polymarket tokens to binary options"
```

---

## Task 4: Matching adapter skeleton and accuracy settings

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/matching.py`
- Create: `tests/test_nautilus_matching_execution.py`

**Interfaces:**
- Produces: `MatchingAccuracySettings.from_mode(mode: str) -> MatchingAccuracySettings`.
- Produces: `NautilusMatchingPaperExecutionClient.submit_spec(spec: NautilusOrderSpec) -> PaperExecutionResult`.
- Produces: `NautilusMatchingPaperExecutionClient.update_book(token_id: str, book: OrderBook) -> None`.
- Produces: `NautilusMatchingPaperExecutionClient.drain_events() -> list[PaperExecutionResult]`.

- [ ] **Step 1: Write failing adapter tests**

Create `tests/test_nautilus_matching_execution.py`:

```python
from __future__ import annotations

import pytest

from factories import BookFactoryConfig, sample_book
from polysignal_lab.alpha.types import NautilusOrderSpec
from polysignal_lab.domain.enums import OrderIntent, OrderStatus, Side
from polysignal_lab.paper.wallet import PaperWallet


def _spec(token_id: str, *, price: float = 0.82, quantity: float = 10.0, intent: OrderIntent = OrderIntent.TAKER_IOC) -> NautilusOrderSpec:
    return NautilusOrderSpec(
        instrument_id=token_id,
        side=Side.UP,
        price=price,
        quantity=quantity,
        intent=intent,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={
            "strategy": "test",
            "asset": "BTC",
            "timeframe": "5m",
            "market_id": "m1",
            "market_slug": "btc-updown-5m",
            "condition_id": "c1",
            "signal_id": "sig-1",
            "confidence": "0.8",
            "max_entry_price": "0.83",
            "entry_reference_price": "0.82",
        },
    )


def test_accuracy_settings_match_spec_modes() -> None:
    from polysignal_lab.nautilus_runtime.matching import MatchingAccuracySettings

    fast = MatchingAccuracySettings.from_mode("fast_l1")
    depth = MatchingAccuracySettings.from_mode("depth_l2")
    queue = MatchingAccuracySettings.from_mode("queue_l2")

    assert fast.book_type == "L1_MBP"
    assert fast.liquidity_consumption is False
    assert depth.book_type == "L2_MBP"
    assert depth.liquidity_consumption is True
    assert depth.queue_position is False
    assert queue.queue_position is True


def test_matching_client_constructs_without_credentials() -> None:
    from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient

    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet(), accuracy_mode="depth_l2")

    assert client.paper_engine == "nautilus_matching"
    assert client.accuracy_mode == "depth_l2"


def test_submit_without_book_rejects() -> None:
    from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient

    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet(), accuracy_mode="depth_l2")
    result = client.submit_spec(_spec("up-token"))

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "MISSING_ORDERBOOK"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py -q
```

Expected: FAIL because `matching.py` is missing.

- [ ] **Step 3: Implement the adapter shell without local paper executors**

Create `src/polysignal_lab/nautilus_runtime/matching.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from polysignal_lab.alpha.types import NautilusOrderSpec
from polysignal_lab.domain.enums import OrderStatus
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.paper_order import PaperOrder
from polysignal_lab.nautilus_runtime.execution_types import PaperExecutionResult
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.utils import new_id, utc_now


@dataclass(frozen=True, slots=True)
class MatchingAccuracySettings:
    mode: str
    book_type: str
    trade_execution: bool
    bar_execution: bool
    liquidity_consumption: bool
    queue_position: bool
    support_gtd_orders: bool
    support_contingent_orders: bool
    use_reduce_only: bool
    price_protection_points: int

    @classmethod
    def from_mode(cls, mode: str) -> "MatchingAccuracySettings":
        if mode == "fast_l1":
            return cls(mode, "L1_MBP", True, False, False, False, True, False, True, 0)
        if mode == "depth_l2":
            return cls(mode, "L2_MBP", True, False, True, False, True, False, True, 0)
        if mode == "queue_l2":
            return cls(mode, "L2_MBP", True, False, True, True, True, False, True, 0)
        raise ValueError(f"unknown Nautilus matching accuracy mode: {mode}")


class NautilusMatchingPaperExecutionClient:
    paper_engine = "nautilus_matching"

    def __init__(
        self,
        *,
        wallet: PaperWallet | None = None,
        accuracy_mode: str = "depth_l2",
        max_book_staleness_ms: int = 10_000,
    ) -> None:
        self.wallet = wallet or PaperWallet(starting_balance=10_000.0)
        self.settings = MatchingAccuracySettings.from_mode(accuracy_mode)
        self.accuracy_mode = self.settings.mode
        self.max_book_staleness_ms = max_book_staleness_ms
        self._books: dict[str, OrderBook] = {}
        self._pending: list[PaperExecutionResult] = []
        self._exchange: Any | None = None

    def update_book(self, token_id: str, book: OrderBook) -> None:
        self._books[token_id] = book

    def drain_events(self) -> list[PaperExecutionResult]:
        drained = list(self._pending)
        self._pending.clear()
        return drained

    def submit_spec(self, spec: NautilusOrderSpec) -> PaperExecutionResult:
        book = self._books.get(spec.instrument_id)
        order = self._paper_order_from_spec(spec)
        if book is None:
            return PaperExecutionResult(order=order, status=OrderStatus.REJECTED, reason="MISSING_ORDERBOOK")
        return PaperExecutionResult(order=order, status=OrderStatus.PENDING, reason="MATCHING_NOT_CONNECTED")

    def _paper_order_from_spec(self, spec: NautilusOrderSpec) -> PaperOrder:
        tags = dict(spec.tags or {})
        return PaperOrder(
            paper_order_id=new_id("paper"),
            signal_id=tags.get("signal_id", ""),
            token_id=spec.instrument_id,
            side=spec.side,
            limit_price=float(tags.get("max_entry_price", spec.price)),
            reference_price=spec.price,
            stake_usdc=spec.quantity * spec.price,
            shares=spec.quantity,
            asset=tags.get("asset", ""),
            timeframe=tags.get("timeframe", ""),
            strategy=tags.get("strategy", ""),
            market_id=tags.get("market_id", ""),
            market_slug=tags.get("market_slug", ""),
            order_intent=spec.intent,
            pair_id=spec.pair_id,
            reduce_only=spec.reduce_only,
            hedge_leg=spec.hedge_leg,
            signal_confidence=float(tags["confidence"]) if tags.get("confidence") else None,
            metrics={**tags, "paper_engine": self.paper_engine, "accuracy_mode": self.accuracy_mode},
            created_at=utc_now(),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_accuracy_settings_match_spec_modes tests/test_nautilus_matching_execution.py::test_matching_client_constructs_without_credentials tests/test_nautilus_matching_execution.py::test_submit_without_book_rejects -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/matching.py tests/test_nautilus_matching_execution.py
git commit -m "feat: add nautilus matching adapter shell"
```

---

## Task 5: Public book/trade feed into Nautilus matching state

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/matching.py`
- Modify: `src/polysignal_lab/nautilus_runtime/data_ingestor.py`
- Modify: `tests/test_nautilus_matching_execution.py`
- Modify: `tests/test_nautilus_data_ingestor.py`

**Interfaces:**
- Produces: `NautilusMatchingPaperExecutionClient.update_trade(token_id: str, price: float, size: float, side: str | None, ts_event: datetime | None) -> None`.
- Produces: `NautilusDataIngestor.sync_orderbooks()` feeds `matching_client.update_book()` and recent trades without referencing local paper clients.

- [ ] **Step 1: Write failing book/trade feed tests**

Add to `tests/test_nautilus_matching_execution.py`:

```python
from datetime import UTC, datetime, timedelta


def test_update_book_rejects_stale_book_before_matching() -> None:
    from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient

    book = sample_book("up-token", BookFactoryConfig(ask=0.82, size=500))
    book.received_at = datetime.now(UTC) - timedelta(seconds=30)
    client = NautilusMatchingPaperExecutionClient(
        wallet=PaperWallet(),
        accuracy_mode="depth_l2",
        max_book_staleness_ms=1_000,
    )
    client.update_book("up-token", book)

    result = client.submit_spec(_spec("up-token"))

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "STALE_ORDERBOOK"


def test_update_trade_records_recent_trade_for_queue_mode() -> None:
    from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient

    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet(), accuracy_mode="queue_l2")
    client.update_trade("up-token", price=0.82, size=25.0, side="BUY", ts_event=datetime.now(UTC))

    assert client.recent_trades_for("up-token")[-1].price == 0.82
    assert client.recent_trades_for("up-token")[-1].size == 25.0
```

Update `tests/test_nautilus_data_ingestor.py` helper with a matching sink:

```python
class RecordingMatchingClient:
    def __init__(self) -> None:
        self.books: list[tuple[str, object]] = []
        self.trades: list[tuple[str, float, float, object, object]] = []

    def update_book(self, token_id, book) -> None:
        self.books.append((token_id, book))

    def update_trade(self, token_id, price, size, side, ts_event) -> None:
        self.trades.append((token_id, price, size, side, ts_event))
```

Replace `test_sync_orderbooks_updates_provider_and_paper_client` with:

```python
def test_sync_orderbooks_updates_provider_and_matching_client() -> None:
    ingestor, _, _, provider, matching = _ingestor()

    ingestor.sync_orderbooks()

    assert provider.book_for_token("up-token") is not None
    assert matching.books[0][0] == "up-token"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_update_book_rejects_stale_book_before_matching tests/test_nautilus_matching_execution.py::test_update_trade_records_recent_trade_for_queue_mode tests/test_nautilus_data_ingestor.py::test_sync_orderbooks_updates_provider_and_matching_client -q
```

Expected: FAIL because stale rejection, trade storage, and ingestor matching-client injection are not implemented.

- [ ] **Step 3: Implement feed methods and ingestor rewiring**

In `src/polysignal_lab/nautilus_runtime/matching.py`, add:

```python
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class MatchingTrade:
    token_id: str
    price: float
    size: float
    side: str | None
    ts_event: datetime | None


def _freshness_ms(book: OrderBook) -> int | None:
    if book.received_at is None:
        return None
    return max(0, int((datetime.now(UTC) - book.received_at).total_seconds() * 1000))
```

Add methods to `NautilusMatchingPaperExecutionClient`:

```python
    def update_trade(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str | None,
        ts_event: datetime | None,
    ) -> None:
        if price <= 0 or size <= 0:
            return
        self._trades.setdefault(token_id, []).append(
            MatchingTrade(token_id=token_id, price=float(price), size=float(size), side=side, ts_event=ts_event)
        )

    def recent_trades_for(self, token_id: str) -> list[MatchingTrade]:
        return list(self._trades.get(token_id, ()))
```

Initialize trades in `__init__`:

```python
        self._trades: dict[str, list[MatchingTrade]] = {}
```

At the start of `submit_spec`, after fetching `book`, add:

```python
        if book is None:
            return PaperExecutionResult(order=order, status=OrderStatus.REJECTED, reason="MISSING_ORDERBOOK")
        freshness = _freshness_ms(book)
        if freshness is not None and freshness > self.max_book_staleness_ms:
            return PaperExecutionResult(order=order, status=OrderStatus.REJECTED, reason="STALE_ORDERBOOK")
```

In `src/polysignal_lab/nautilus_runtime/data_ingestor.py`, remove the import of `PolySignalPaperExecutionClient`, add a protocol, and use `matching_client`:

```python
from typing import Protocol


class MatchingBookSink(Protocol):
    def update_book(self, token_id: str, book: OrderBook) -> None: ...
    def update_trade(self, token_id: str, price: float, size: float, side: str | None, ts_event: object) -> None: ...
```

Change the constructor argument and assignment:

```python
        matching_client: MatchingBookSink,
```

```python
        self.matching_client = matching_client
```

Change `sync_orderbooks`:

```python
    def sync_orderbooks(self) -> None:
        for token_id, book in self.books.books.items():
            self.book_data_provider.update_book(token_id, book)
            self.matching_client.update_book(token_id, book)
            for trade in self.books.recent_trades(token_id):
                self.matching_client.update_trade(
                    token_id,
                    price=trade.price,
                    size=trade.size,
                    side=getattr(trade, "side", None),
                    ts_event=getattr(trade, "datetime", None),
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_update_book_rejects_stale_book_before_matching tests/test_nautilus_matching_execution.py::test_update_trade_records_recent_trade_for_queue_mode tests/test_nautilus_data_ingestor.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/matching.py src/polysignal_lab/nautilus_runtime/data_ingestor.py tests/test_nautilus_matching_execution.py tests/test_nautilus_data_ingestor.py
git commit -m "feat: feed public books into nautilus matching"
```

---

## Task 6: Nautilus matching order lifecycle and wallet mirror

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/matching.py`
- Modify: `tests/test_nautilus_matching_execution.py`

**Interfaces:**
- Produces: filled `PaperExecutionResult` from Nautilus-derived matching events.
- Produces: idempotent wallet mirror: every filled event creates one `PaperFill` and one `PaperPosition`, then calls `PaperWallet.apply_fill(position)` once.
- Preserves: LateConsensus limit semantics: `max_entry_price` is a ceiling, fill price comes from book liquidity.

- [ ] **Step 1: Write failing matching correctness tests**

Add to `tests/test_nautilus_matching_execution.py`:

```python
def test_taker_fills_at_book_price_not_slippage_model() -> None:
    from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient

    book = sample_book("up-token", BookFactoryConfig(ask=0.82, size=500))
    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet(), accuracy_mode="depth_l2")
    client.update_book("up-token", book)

    result = client.submit_spec(_spec("up-token", price=0.82, quantity=10.0, intent=OrderIntent.TAKER_IOC))

    assert result.status == OrderStatus.FILLED
    assert result.fills[0].fill_price == pytest.approx(0.82)
    assert result.order is not None
    assert result.order.limit_price == pytest.approx(0.83)
    assert result.order.reference_price == pytest.approx(0.82)
    assert result.positions[0].paper_position_id in client.wallet.open_positions


def test_best_ask_above_max_entry_is_rejected() -> None:
    from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient

    book = sample_book("up-token", BookFactoryConfig(ask=0.84, size=500))
    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet(), accuracy_mode="depth_l2")
    client.update_book("up-token", book)

    result = client.submit_spec(_spec("up-token", price=0.82, quantity=10.0, intent=OrderIntent.TAKER_IOC))

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "PRICE_ABOVE_LIMIT"


def test_fok_rejects_when_full_depth_unavailable() -> None:
    from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient

    book = sample_book("up-token", BookFactoryConfig(ask=0.82, size=5))
    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet(), accuracy_mode="depth_l2")
    client.update_book("up-token", book)

    result = client.submit_spec(_spec("up-token", price=0.82, quantity=10.0, intent=OrderIntent.TAKER_FOK))

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "INSUFFICIENT_DEPTH"


def test_liquidity_consumption_prevents_reusing_same_level() -> None:
    from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient

    book = sample_book("up-token", BookFactoryConfig(ask=0.82, size=12))
    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet(starting_balance=1000.0), accuracy_mode="depth_l2")
    client.update_book("up-token", book)

    first = client.submit_spec(_spec("up-token", price=0.82, quantity=10.0, intent=OrderIntent.TAKER_IOC))
    second = client.submit_spec(_spec("up-token", price=0.82, quantity=10.0, intent=OrderIntent.TAKER_IOC))

    assert first.status == OrderStatus.FILLED
    assert second.status == OrderStatus.FILLED
    assert second.fills[0].shares == pytest.approx(2.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_taker_fills_at_book_price_not_slippage_model tests/test_nautilus_matching_execution.py::test_best_ask_above_max_entry_is_rejected tests/test_nautilus_matching_execution.py::test_fok_rejects_when_full_depth_unavailable tests/test_nautilus_matching_execution.py::test_liquidity_consumption_prevents_reusing_same_level -q
```

Expected: FAIL because the adapter shell does not fill or consume liquidity.

- [ ] **Step 3: Implement Nautilus-backed matching and read-model mirror**

Inside `NautilusMatchingPaperExecutionClient`, wire submission through the owned Nautilus `SimulatedExchange` / `BacktestExecClient`. Do not add a local fill simulator and do not call `BestAskTakerExecutor` or `PassiveGtdExecutor`.

Add imports used by the read-model mirror:

```python
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.paper_order import PaperFill
from polysignal_lab.domain.paper_position import PaperPosition
```

Add these attributes in `__init__`:

```python
        self._mirrored_fill_ids: set[str] = set()
        self._exchange_started = False
```

Replace the pending result return in `submit_spec` with the Nautilus path:

```python
        if spec.side != Side.UP:
            return PaperExecutionResult(order=order, status=OrderStatus.REJECTED, reason="UNSUPPORTED_SIDE")
        self._ensure_exchange()
        self._ensure_instrument_registered(spec.instrument_id, book)
        self._publish_book_to_exchange(spec.instrument_id, book)
        for trade in self._trades.get(spec.instrument_id, ()):
            self._publish_trade_to_exchange(trade)
        client_order_id = self._submit_to_nautilus(spec, order)
        result = self._drain_order_result(order, client_order_id)
        if spec.intent == OrderIntent.TAKER_FOK and result.status != OrderStatus.FILLED:
            return PaperExecutionResult(order=order, status=OrderStatus.REJECTED, reason="INSUFFICIENT_DEPTH")
        return result
```

Add the helper boundaries. Fill the bodies by following `refs/nautilus_trader/nautilus_trader/adapters/sandbox/execution.py:109-146` for exchange construction and `refs/nautilus_trader/nautilus_trader/backtest/engine.pyx` matching behavior; these helpers are private so all Nautilus API churn stays in one file:

```python
    def _ensure_exchange(self) -> None:
        if self._exchange_started:
            return
        self._exchange = self._build_simulated_exchange()
        self._exchange_started = True

    def _build_simulated_exchange(self):
        from nautilus_trader.backtest.exchange import SimulatedExchange
        from nautilus_trader.backtest.models import FillModel, LatencyModel, MakerTakerFeeModel
        from nautilus_trader.common.component import TestClock

        clock = TestClock()
        return SimulatedExchange(
            venue=self._venue(),
            oms_type=self._oms_type(),
            account_type=self._account_type(),
            starting_balances=self._starting_balances(),
            base_currency=self._base_currency(),
            default_leverage=1,
            leverages={},
            modules=[],
            portfolio=self._portfolio_facade(clock),
            msgbus=self._msgbus,
            cache=self._cache,
            clock=clock,
            fill_model=FillModel(),
            fee_model=MakerTakerFeeModel(),
            latency_model=LatencyModel(0),
            book_type=self._book_type(),
            frozen_account=False,
            bar_execution=self.settings.bar_execution,
            trade_execution=self.settings.trade_execution,
            reject_stop_orders=True,
            support_gtd_orders=self.settings.support_gtd_orders,
            support_contingent_orders=self.settings.support_contingent_orders,
            use_position_ids=False,
            use_random_ids=False,
            use_reduce_only=self.settings.use_reduce_only,
            use_message_queue=False,
            liquidity_consumption=self.settings.liquidity_consumption,
            queue_position=self.settings.queue_position,
            price_protection_points=self.settings.price_protection_points,
        )

    def _ensure_instrument_registered(self, token_id: str, book: OrderBook) -> None:
        if token_id in self._registered_instruments:
            return
        instrument = self._instrument_for_book(token_id, book)
        self._cache.add_instrument(instrument)
        self._exchange.add_instrument(instrument)
        self._registered_instruments.add(token_id)

    def _publish_book_to_exchange(self, token_id: str, book: OrderBook) -> None:
        deltas = self._book_to_order_book_deltas(token_id, book)
        if deltas is not None:
            self._exchange.process_order_book_deltas(deltas)

    def _publish_trade_to_exchange(self, trade: MatchingTrade) -> None:
        tick = self._trade_to_tick(trade)
        if tick is not None:
            self._exchange.process_trade_tick(tick)

    def _submit_to_nautilus(self, spec: NautilusOrderSpec, order: PaperOrder) -> str:
        nautilus_order = self._order_factory.limit(
            instrument_id=self._instrument_id(spec.instrument_id),
            order_side=self._order_side(spec.side),
            quantity=self._quantity(spec.quantity),
            price=self._price(spec.price),
            time_in_force=self._time_in_force(spec),
            reduce_only=spec.reduce_only,
            tags=list(spec.tags.values()),
        )
        self._exec_client.submit_order(nautilus_order)
        return nautilus_order.client_order_id.value

    def _drain_order_result(self, order: PaperOrder, client_order_id: str) -> PaperExecutionResult:
        events = self._collect_execution_events(client_order_id)
        fills = [self._paper_fill_from_event(order, event) for event in events if self._is_fill_event(event)]
        positions = [self._position_from_fill(order, fill) for fill in fills if fill.paper_fill_id not in self._mirrored_fill_ids]
        for fill in fills:
            self._mirrored_fill_ids.add(fill.paper_fill_id)
        for position in positions:
            self.wallet.apply_fill(position)
        if fills:
            status = OrderStatus.FILLED
            return PaperExecutionResult(order=order.model_copy(update={"status": status}), fills=fills, positions=positions, status=status)
        cancel_reason = self._cancel_or_reject_reason(events)
        if cancel_reason:
            return PaperExecutionResult(order=order.model_copy(update={"status": OrderStatus.REJECTED, "reject_reason": cancel_reason}), status=OrderStatus.REJECTED, reason=cancel_reason)
        return PaperExecutionResult(order=order, status=OrderStatus.PENDING)
```

Add `_position_from_fill`:

```python
    def _position_from_fill(self, order: PaperOrder, fill: PaperFill) -> PaperPosition:
        return PaperPosition(
            signal_id=order.signal_id,
            paper_order_id=order.paper_order_id,
            paper_fill_id=fill.paper_fill_id,
            strategy=order.strategy,
            asset=order.asset,
            timeframe=order.timeframe,
            market_id=order.market_id,
            market_slug=order.market_slug,
            token_id=order.token_id,
            side=order.side,
            entry_price=fill.fill_price,
            shares=fill.shares,
            stake_usdc=fill.stake_usdc,
            signal_confidence=order.signal_confidence,
            signal_metrics=dict(order.metrics),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run core behavior:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py -q
```

Run Nautilus optional behavior:

```bash
uv run --extra nautilus --python 3.12 python -m pytest tests/test_nautilus_matching_execution.py tests/test_nautilus_instrument_mapping.py -q
```

Expected: PASS; if Python 3.12+ environment is missing, create it before continuing.

- [ ] **Step 6: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/matching.py tests/test_nautilus_matching_execution.py
git commit -m "feat: execute paper orders through nautilus matching"
```

---

## Task 7: Passive GTD, expiry, and position exits

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/matching.py`
- Modify: `src/polysignal_lab/nautilus_runtime/orchestrator.py`
- Modify: `tests/test_nautilus_matching_execution.py`
- Modify: `tests/test_nautilus_orchestrator.py`

**Interfaces:**
- Produces: `NautilusMatchingPaperExecutionClient.process_resting_orders() -> list[PaperExecutionResult]`.
- Produces: `NautilusMatchingPaperExecutionClient.submit_exit(position: PaperPosition, bid_price: float, reason: str) -> PaperExecutionResult`.
- Produces: orchestrator phases `_phase_resting_orders()` and `_phase_position_exits()`.

- [ ] **Step 1: Write failing GTD and exit tests**

Add to `tests/test_nautilus_matching_execution.py`:

```python
def test_passive_gtd_rests_then_expires() -> None:
    from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient

    book = sample_book("up-token", BookFactoryConfig(ask=0.82, size=500))
    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet(), accuracy_mode="depth_l2")
    client.update_book("up-token", book)
    spec = _spec("up-token", price=0.80, quantity=10.0, intent=OrderIntent.PASSIVE_GTD)
    spec = NautilusOrderSpec(**{**spec.__dict__, "expiry_seconds": 0})

    submitted = client.submit_spec(spec)
    expired = client.process_resting_orders()

    assert submitted.status in (OrderStatus.RESTING, OrderStatus.PENDING)
    assert expired[-1].status == OrderStatus.REJECTED
    assert expired[-1].reason == "GTD_EXPIRED"
```

Add to `tests/test_nautilus_orchestrator.py`:

```python
async def test_run_once_drains_resting_orders_and_position_exits() -> None:
    calls: list[str] = []

    class MatchingClient:
        wallet = SimpleNamespace(open_positions={})
        def drain_events(self):
            calls.append("drain_before")
            return []
        def process_resting_orders(self):
            calls.append("resting")
            return []
        def submit_exit(self, position, bid_price, reason):
            calls.append(f"exit:{reason}")
            return PaperExecutionResult(status=OrderStatus.FILLED)

    orch = _orchestrator(paper_client=MatchingClient())

    await orch.run_once()

    assert "resting" in calls
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_passive_gtd_rests_then_expires tests/test_nautilus_orchestrator.py::test_run_once_drains_resting_orders_and_position_exits -q
```

Expected: FAIL because resting and exit phases are missing.

- [ ] **Step 3: Implement resting order processing**

In `matching.py`, add a resting store and processor:

```python
from polysignal_lab.domain.enums import OrderStatus


@dataclass(slots=True)
class RestingMatchingOrder:
    spec: NautilusOrderSpec
    order: PaperOrder
    created_at: datetime
```

Initialize:

```python
        self._resting: list[RestingMatchingOrder] = []
```

When `spec.intent == OrderIntent.PASSIVE_GTD` and the best ask is above the limit, store and return resting:

```python
        if spec.intent == OrderIntent.PASSIVE_GTD and matchable == []:
            self._resting.append(RestingMatchingOrder(spec=spec, order=order, created_at=utc_now()))
            resting_order = order.model_copy(update={"status": OrderStatus.RESTING})
            return PaperExecutionResult(order=resting_order, status=OrderStatus.RESTING)
```

Add processor:

```python
    def process_resting_orders(self) -> list[PaperExecutionResult]:
        results: list[PaperExecutionResult] = []
        still_resting: list[RestingMatchingOrder] = []
        now = utc_now()
        for resting in self._resting:
            expiry = resting.spec.expiry_seconds
            if expiry is not None and (now - resting.created_at).total_seconds() >= expiry:
                expired = resting.order.model_copy(update={"status": OrderStatus.REJECTED, "reject_reason": "GTD_EXPIRED"})
                results.append(PaperExecutionResult(order=expired, status=OrderStatus.REJECTED, reason="GTD_EXPIRED"))
                continue
            result = self.submit_spec(resting.spec)
            if result.status == OrderStatus.FILLED:
                results.append(result)
            else:
                still_resting.append(resting)
        self._resting = still_resting
        return results
```

- [ ] **Step 4: Implement orchestrator phases**

In `orchestrator.py`, update `run_once` ordering:

```python
    async def run_once(self) -> None:
        await self._phase_market_refresh()
        condition_ids = self._phase_sync()
        await self._phase_event_drain()
        await self._phase_resting_orders()
        if condition_ids:
            await self._phase_strategy_eval(condition_ids)
        await self._phase_event_drain()
        await self._phase_position_exits()
        await self._phase_settlement()
        await self._phase_daily_report()
        self._phase_health()
```

Add methods:

```python
    async def _phase_event_drain(self) -> None:
        for result in self.paper_client.drain_events():
            await self._record_execution_result(result)

    async def _phase_resting_orders(self) -> None:
        for result in self.paper_client.process_resting_orders():
            await self._record_execution_result(result)
        self.health.mark_ok("resting_orders")

    async def _phase_position_exits(self) -> None:
        for position in list(self.paper_client.wallet.open_positions.values()):
            snapshot = self.book_data_provider.snapshot_for_token(position.token_id)
            bid = snapshot.bid if snapshot is not None else None
            decision = self.position_policy.evaluate(position, current_bid=bid)
            if decision is None or bid is None:
                continue
            result = self.paper_client.submit_exit(position, bid_price=bid, reason=decision.exit_mode.value)
            await self._record_execution_result(result)
        self.health.mark_ok("position_exits")
```

Add `submit_exit` to `matching.py` using a reduce-only Nautilus order and the same event drain:

```python
    def submit_exit(self, position: PaperPosition, bid_price: float, reason: str) -> PaperExecutionResult:
        spec = NautilusOrderSpec(
            instrument_id=position.token_id,
            side=position.side,
            price=bid_price,
            quantity=position.shares,
            intent=OrderIntent.TAKER_IOC,
            expiry_seconds=None,
            pair_id=None,
            reduce_only=True,
            hedge_leg=False,
            tags={
                "signal_id": position.signal_id,
                "strategy": position.strategy,
                "asset": position.asset,
                "timeframe": position.timeframe,
                "market_id": position.market_id,
                "market_slug": position.market_slug,
                "max_entry_price": str(bid_price),
                "entry_reference_price": str(position.entry_price),
                "exit_reason": reason,
                "paper_engine": self.paper_engine,
                "accuracy_mode": self.accuracy_mode,
            },
        )
        order = self._paper_order_from_spec(spec).model_copy(update={"reduce_only": True})
        self._ensure_exchange()
        client_order_id = self._submit_to_nautilus(spec, order)
        return self._drain_order_result(order, client_order_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_passive_gtd_rests_then_expires tests/test_nautilus_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/matching.py src/polysignal_lab/nautilus_runtime/orchestrator.py tests/test_nautilus_matching_execution.py tests/test_nautilus_orchestrator.py
git commit -m "feat: process nautilus resting orders and exits"
```

---

## Task 8: Runtime rewiring and legacy paper isolation

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/node.py`
- Modify: `src/polysignal_lab/nautilus_runtime/data_ingestor.py`
- Modify: `src/polysignal_lab/nautilus_runtime/orchestrator.py`
- Modify: `tests/test_nautilus_node.py`
- Modify: `tests/test_nautilus_platform_boundary.py`

**Interfaces:**
- Produces: `NautilusRuntimeBundle.paper_client: NautilusMatchingPaperExecutionClient`.
- Preserves: strategy submitter signature `Callable[[NautilusOrderSpec], PaperExecutionResult]`.
- Removes: default runtime imports/construction of `PolySignalPaperExecutionClient`, `BestAskTakerExecutor`, `PassiveGtdExecutor`, `PaperSimulator` outside `execution.py` and isolated legacy tests.

- [ ] **Step 1: Write failing node wiring tests**

Update `tests/test_nautilus_node.py`:

```python
def test_build_trading_node_wires_matching_client() -> None:
    from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient

    node = build_trading_node()

    assert isinstance(node["paper_client"], NautilusMatchingPaperExecutionClient)
    assert node["paper_client"].paper_engine == "nautilus_matching"
    assert node["paper_client"].accuracy_mode == "depth_l2"
```

Strengthen the boundary test in `tests/test_nautilus_platform_boundary.py`:

```python
def test_default_nautilus_runtime_source_avoids_local_paper_executors() -> None:
    forbidden = (
        "from polysignal_lab.paper.order_intent_executor import",
        "BestAskTakerExecutor",
        "PassiveGtdExecutor",
        "PaperSimulator",
        "PolySignalPaperExecutionClient(",
    )
    allowed_files = {Path("src/polysignal_lab/nautilus_runtime/execution.py")}
    findings: list[str] = []
    for path in Path("src/polysignal_lab/nautilus_runtime").rglob("*.py"):
        if path in allowed_files:
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_node.py::test_build_trading_node_wires_matching_client tests/test_nautilus_platform_boundary.py::test_default_nautilus_runtime_source_avoids_local_paper_executors -q
```

Expected: FAIL until `node.py`, `data_ingestor.py`, and `orchestrator.py` import the matching client only.

- [ ] **Step 3: Rewire node and constructor types**

In `node.py`, replace:

```python
from polysignal_lab.nautilus_runtime.execution import PolySignalPaperExecutionClient
```

with:

```python
from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient
```

Update `NautilusRuntimeBundle` and `_build_wrapper` annotations:

```python
    paper_client: NautilusMatchingPaperExecutionClient
```

```python
    paper_client: NautilusMatchingPaperExecutionClient,
```

Replace client construction:

```python
    paper_client = NautilusMatchingPaperExecutionClient(
        wallet=wallet,
        accuracy_mode=settings.runtime.nautilus.matching_accuracy_mode,
        max_book_staleness_ms=settings.data.polymarket.max_book_staleness_ms,
    )
```

In `build_nautilus_runtime`, pass `matching_client`:

```python
        matching_client=components["paper_client"],
```

In `data_ingestor.py`, rename constructor parameter from `paper_client` to `matching_client` at every callsite and test helper.

In `orchestrator.py`, annotate `paper_client` as `NautilusMatchingPaperExecutionClient` or a small protocol with `submit_spec`, `drain_events`, `process_resting_orders`, `submit_exit`, and `wallet`.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_data_ingestor.py tests/test_nautilus_platform_boundary.py -q
```

Expected: PASS or Python 3.12-required node construction tests explicitly skip with `tests/nautilus_optional.py`.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/node.py src/polysignal_lab/nautilus_runtime/data_ingestor.py src/polysignal_lab/nautilus_runtime/orchestrator.py tests/test_nautilus_node.py tests/test_nautilus_platform_boundary.py tests/test_nautilus_data_ingestor.py
git commit -m "refactor: wire nautilus runtime to matching client"
```

---

## Task 9: Observability, health, startup, and report metadata

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py`
- Modify: `src/polysignal_lab/nautilus_runtime/orchestrator.py`
- Modify: `tests/test_nautilus_observability.py`
- Modify: `tests/test_nautilus_orchestrator.py`

**Interfaces:**
- Produces: order/fill/position metrics containing `paper_engine="nautilus_matching"` and `accuracy_mode`.
- Produces: startup notifier message containing engine and accuracy mode.
- Produces: health snapshot component metrics containing engine and accuracy mode.

- [ ] **Step 1: Write failing metadata tests**

Add to `tests/test_nautilus_observability.py`:

```python
async def test_startup_message_includes_matching_engine_metadata() -> None:
    publisher = FakePublisher()
    actor = ObservabilityActor(notifier=NautilusNotifierAdapter(publisher))

    await actor.notify_startup(["ptb_diff"], paper_engine="nautilus_matching", accuracy_mode="depth_l2")

    assert publisher.calls == [(
        "Nautilus runtime started — 1 strategies loaded — paper_engine=nautilus_matching accuracy_mode=depth_l2",
        "startup",
    )]


def test_record_order_preserves_matching_metadata() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)
    order = PaperOrder(
        paper_order_id="order-1",
        signal_id="sig-1",
        token_id="t1",
        side=Side.UP,
        limit_price=0.83,
        reference_price=0.82,
        stake_usdc=10.0,
        asset="BTC",
        timeframe="5m",
        strategy="test",
        market_id="m1",
        market_slug="slug",
        metrics={"paper_engine": "nautilus_matching", "accuracy_mode": "depth_l2"},
    )

    actor.record_order(PaperExecutionResult(order=order, status=OrderStatus.FILLED))

    row = store.tables["orders"][0]
    assert row["metrics"]["paper_engine"] == "nautilus_matching"
    assert row["metrics"]["accuracy_mode"] == "depth_l2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_observability.py::test_startup_message_includes_matching_engine_metadata tests/test_nautilus_observability.py::test_record_order_preserves_matching_metadata -q
```

Expected: startup test FAIL until `notify_startup` accepts metadata.

- [ ] **Step 3: Add metadata to observability**

Change `ObservabilityActor.notify_startup` signature and body:

```python
    async def notify_startup(
        self,
        strategy_names: Sequence[str] = (),
        *,
        paper_engine: str = "nautilus_matching",
        accuracy_mode: str = "depth_l2",
    ) -> None:
        if self.notifier is None:
            return
        msg = (
            f"Nautilus runtime started — {len(strategy_names)} strategies loaded — "
            f"paper_engine={paper_engine} accuracy_mode={accuracy_mode}"
        )
        self.health.mark_ok("observability_actor", paper_engine=paper_engine, accuracy_mode=accuracy_mode)
        await self.notifier.send(msg, "startup")
```

In `node.py`, update startup call in `run_nautilus_cli_async`:

```python
    await bundle.observability.notify_startup(
        bundle.components.get("strategy_names", ()),
        paper_engine=bundle.components["paper_client"].paper_engine,
        accuracy_mode=bundle.components["paper_client"].accuracy_mode,
    )
```

In `orchestrator._phase_health`, mark the paper engine:

```python
            self.health.mark_ok(
                "orchestrator",
                paper_engine=self.paper_client.paper_engine,
                accuracy_mode=self.paper_client.accuracy_mode,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_observability.py tests/test_nautilus_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/observability.py src/polysignal_lab/nautilus_runtime/node.py src/polysignal_lab/nautilus_runtime/orchestrator.py tests/test_nautilus_observability.py tests/test_nautilus_orchestrator.py
git commit -m "feat: report nautilus matching assumptions"
```

---

## Task 10: Runtime smoke and final safety gates

**Files:**
- Create: `tests/test_nautilus_matching_runtime_smoke.py`
- Modify: `tests/test_nautilus_platform_boundary.py`
- Modify: `tests/test_nautilus_safety_boundary.py`
- Modify: `scripts/safety_scan.py` if the current scanner does not check local-paper isolation.

**Interfaces:**
- Produces: bounded full-orchestrator smoke proving one accepted matching fill creates order/fill/position rows and can settle through the existing scheduler pipeline.
- Produces: source scan that fails on forbidden live Polymarket symbols and forbidden local-paper executor imports in default Nautilus runtime source.

- [ ] **Step 1: Write runtime smoke test**

Create `tests/test_nautilus_matching_runtime_smoke.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest

from polysignal_lab.domain.enums import OrderStatus, Side
from polysignal_lab.domain.paper_order import PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.nautilus_runtime.execution_types import PaperExecutionResult
from polysignal_lab.nautilus_runtime.orchestrator import NautilusOrchestrator
from polysignal_lab.utils import utc_now


class Store:
    def __init__(self) -> None:
        self.orders: list[object] = []
        self.fills: list[object] = []
        self.positions: list[object] = []


async def test_bounded_runtime_cycle_records_matching_fill_and_position() -> None:
    store = Store()
    order = PaperOrder(
        signal_id="sig-1",
        token_id="up-token",
        side=Side.UP,
        limit_price=0.83,
        reference_price=0.82,
        stake_usdc=8.2,
        shares=10.0,
        asset="BTC",
        timeframe="5m",
        strategy="ptb_diff",
        market_id="m1",
        market_slug="slug",
        metrics={"paper_engine": "nautilus_matching", "accuracy_mode": "depth_l2"},
    )
    position = PaperPosition(
        signal_id="sig-1",
        paper_order_id=order.paper_order_id,
        paper_fill_id="fill-1",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="m1",
        market_slug="slug",
        token_id="up-token",
        side=Side.UP,
        entry_price=0.82,
        shares=10.0,
        stake_usdc=8.2,
    )

    class MatchingClient:
        paper_engine = "nautilus_matching"
        accuracy_mode = "depth_l2"
        wallet = SimpleNamespace(open_positions={position.paper_position_id: position})
        def drain_events(self):
            return [PaperExecutionResult(order=order, positions=[position], status=OrderStatus.FILLED)]
        def process_resting_orders(self):
            return []
        def submit_exit(self, position, bid_price, reason):
            return PaperExecutionResult(status=OrderStatus.FILLED)

    class Observability:
        def record_signal_from_order(self, order): pass
        def record_order(self, result): store.orders.append(result.order)
        def record_fill(self, fill): store.fills.append(fill)
        def record_position(self, position): store.positions.append(position)
        def record_rejected_decision(self, rejected): pass
        def record_health_snapshot(self): pass
        async def notify_shutdown(self): pass

    class Health:
        def mark_ok(self, *args, **kwargs): pass
        def mark_down(self, *args, **kwargs): pass
        def mark_degraded(self, *args, **kwargs): pass

    scheduler = SimpleNamespace(
        settings=SimpleNamespace(telegram=SimpleNamespace(send_signals=False), paper_trading=SimpleNamespace(fixed_stake_usdc=10.0)),
        publish_service=SimpleNamespace(),
        check_settlements=lambda: None,
        generate_daily_report=lambda: None,
    )

    async def check_settlements():
        return []

    async def generate_daily_report():
        return None

    scheduler.check_settlements = check_settlements
    scheduler.generate_daily_report = generate_daily_report

    orchestrator = NautilusOrchestrator(
        scheduler=scheduler,
        registered_strategies=[],
        data_ingestor=SimpleNamespace(sync_all=lambda: ()),
        book_data_provider=SimpleNamespace(snapshot_for_token=lambda token_id: SimpleNamespace(bid=0.91)),
        paper_client=MatchingClient(),
        position_policy=SimpleNamespace(evaluate=lambda position, current_bid: None),
        settlement_actor=SimpleNamespace(),
        observability=Observability(),
        health=Health(),
        refresh_interval_sec=0.01,
    )

    await orchestrator.run_once()

    assert store.orders[0].metrics["paper_engine"] == "nautilus_matching"
    assert store.positions[0].paper_position_id == position.paper_position_id
```

- [ ] **Step 2: Run smoke test to verify it fails if wiring is incomplete**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_runtime_smoke.py -q
```

Expected: PASS after Tasks 7-9; if it fails, fix the phase ordering or event recording path before continuing.

- [ ] **Step 3: Extend safety scanner if needed**

If `scripts/safety_scan.py` does not scan for local-paper imports in `src/polysignal_lab/nautilus_runtime`, add these blocked runtime patterns to its existing pattern table:

```python
("nautilus-local-paper-executor", "BestAskTakerExecutor"),
("nautilus-local-paper-executor", "PassiveGtdExecutor"),
("nautilus-local-paper-simulator", "PaperSimulator"),
("nautilus-legacy-paper-client", "PolySignalPaperExecutionClient("),
```

Exclude only `src/polysignal_lab/nautilus_runtime/execution.py` and isolated `tests/test_paper_*` legacy tests from the new local-paper isolation rule.

- [ ] **Step 4: Run final targeted test suite**

Run Python 3.11 core/boundary checks:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_platform_boundary.py tests/test_nautilus_safety_boundary.py tests/test_nautilus_data_ingestor.py tests/test_nautilus_orchestrator.py tests/test_nautilus_observability.py tests/test_nautilus_matching_runtime_smoke.py -q
```

Run Python 3.12+ Nautilus matching checks:

```bash
uv run --extra nautilus --python 3.12 python -m pytest tests/test_nautilus_instrument_mapping.py tests/test_nautilus_matching_execution.py tests/test_nautilus_node.py -q
```

Run safety scan:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python scripts/safety_scan.py .
```

Expected: all listed checks PASS. The known unrelated `test_telegram_interactive_yaml_defaults_load` is outside this targeted suite.

- [ ] **Step 5: Rebuild formal runtime containers**

Run:

```bash
docker compose up -d --build --force-recreate
```

Then run:

```bash
docker compose ps
```

Expected: services are running after recreation.

- [ ] **Step 6: Commit**

```bash
git add tests/test_nautilus_matching_runtime_smoke.py tests/test_nautilus_platform_boundary.py tests/test_nautilus_safety_boundary.py scripts/safety_scan.py
git commit -m "test: verify nautilus matching cutover"
```

---

## Self-Review

### Spec coverage

- Complete cutover: Tasks 2, 8, and 10 remove default Nautilus runtime imports/construction of local paper executors and enforce source boundaries.
- Nautilus matching as source of truth: Tasks 4, 6, and 7 build the matching adapter, event drain, fill/position mirror, GTD processing, and reduce-only exit path.
- Public data adapter: Task 5 rewires `NautilusDataIngestor` to feed public books/trades into the matching client.
- `BinaryOption` mapping: Task 3 fixes deterministic token -> instrument mapping and precision.
- Accuracy modes: Tasks 1 and 4 define config and settings for `fast_l1`, `depth_l2`, and `queue_l2`, with `depth_l2` default.
- Safety constraints: Tasks 1, 2, 8, and 10 preserve Python 3.11 core import safety, ban live Polymarket symbols, and add local-paper isolation.
- Settlement/Telegram/SQLite/JSONL/report compatibility: Tasks 6, 7, 9, and 10 preserve `PaperWallet` mirror and existing observability outputs.
- Testing strategy: Tasks 3-10 add unit, matching correctness, safety, and bounded runtime smoke checks.
- Dependency bump: Task 1 pins and locks Nautilus 1.230.0+ for Python 3.12+.

### Placeholder scan

This plan avoids placeholder markers and open-ended instructions. Every task names files, interfaces, tests, commands, expected results, and commit messages.

### Type consistency

The plan uses one result type path: `polysignal_lab.nautilus_runtime.execution_types.PaperExecutionResult`. The default runtime client name is `NautilusMatchingPaperExecutionClient` in every task. The config field names are `paper_engine` and `matching_accuracy_mode` throughout.
