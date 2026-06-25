# Nautilus Strategy Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first paper-safe NautilusTrader bridge slice by extracting `PTBDiffStrategy` alpha logic into a reusable `AlphaCore`, assembling PolySignal `MarketView` objects from paired YES/NO market data, and mapping decisions into order intents without enabling live Polymarket execution.

**Architecture:** `src/polysignal_lab/alpha/` owns pure strategy input/output types and `PTBDiffAlphaCore`. Legacy `PTBDiffStrategy.evaluate(MarketSnapshot)` becomes a thin adapter over the alpha core, preserving existing scheduler behavior. `src/polysignal_lab/nautilus_bridge/` owns market pairing, sidecar data, view assembly, versioned state serialization, and a Nautilus-compatible host wrapper whose imports stay optional so the default Python 3.11 runtime and Docker path do not require NautilusTrader.

**Tech Stack:** Python 3.11 default runtime, Python 3.12+ bridge verification environment, Pydantic v2, pytest, uv, optional `nautilus_trader[polymarket]`, NautilusTrader `Strategy` lifecycle, existing PolySignal domain models (`MarketSnapshot`, `SignalCandidate`, `Side`, `OrderIntent`, `FreshnessPolicy`).

## Global Constraints

- Current PolySignal default runtime remains Python 3.11+; default install, default tests, and Docker startup must not install or import NautilusTrader.
- NautilusTrader bridge verification requires Python 3.12-3.14.
- Linux bridge verification requires glibc >= 2.35.
- Linux ARM64 / rk3588 must record whether a wheel is available or whether source build is required.
- Polymarket adapter dependency must be `nautilus_trader[polymarket]`, not base `nautilus_trader`.
- Default implementation must not enable real Polymarket authenticated execution.
- Default implementation must not import, instantiate, or register `PolymarketExecutionClient`, `PolymarketLiveExecClientFactory`, or `exec_clients`.
- Default implementation must not read or pass `POLYMARKET_PK`, `POLYMARKET_FUNDER`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, or `POLYMARKET_PASSPHRASE`.
- Default implementation must not call Nautilus Polymarket allowance or credential helpers `set_allowances.py` or `create_api_key.py`.
- First migrated strategy is `PTBDiffStrategy`; do not start with `LateConsensus`, `VWAPMomentum`, `DumpHedge`, `MidPriceSizing`, `PreOrderMarket`, `LowSideDualReversion`, or `CrossMarketBot`.
- `PTBDiffStrategy.evaluate(MarketSnapshot)` and `PTBDiffAlphaCore.evaluate(MarketView)` must be equivalent for side, confidence, max_entry_price, reason_codes, metrics, order_intent, expiry_seconds, and hedge_leg; do not compare signal_id, snapshot_id, or created_at.
- `on_save()` returns `dict[str, bytes]`; `on_load(state: dict[str, bytes]) -> None` accepts only versioned JSON bytes.
- Stateful payload key format is `polysignal.<strategy_name>.state.v1`.
- JSON payload rules: enum values use `.value`, datetimes use UTC ISO strings, deque/set/defaultdict become list/dict, unknown schema versions fail closed, missing optional state records a migration reason.
- Existing safety scanner flags source text containing trading-capable symbols; keep default code free of blocked live execution names.
- Use `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest ...` for default-environment tests.
- After runtime code changes intended for formal runtime, rebuild with `docker compose up -d --build --force-recreate` and verify health with a cache-busted URL.

---

## Scope Check

This plan covers Wave 0 and Wave 1 from `docs/superpowers/specs/2026-06-24-15-nautilus-strategy-bridge-design.md`:

- package/runtime isolation for NautilusTrader;
- alpha extraction for `PTBDiffStrategy`;
- minimal `nautilus_bridge` market view path;
- minimal Nautilus-compatible PTB wrapper;
- standard state serialization contract;
- default safety boundary tests;
- Python 3.12+/ARM64/glibc verification instructions.

The spec also names Wave 1.5, Wave 2, Wave 3, and Wave 4 migrations. Those cover independent strategy groups with stateful callbacks, cross-market group evaluation, and optional live execution hosting. They require separate implementation plans because each group can be reviewed and tested independently.

## File Structure

Create and modify these files only:

```text
pyproject.toml
  Adds optional dependency group `nautilus = ["nautilus_trader[polymarket]"]` without changing default dependencies.

docs/NAUTILUS_BRIDGE_BOUNDARY.md
  Records Python/platform/ARM64 verification commands and the default read-only safety boundary.

src/polysignal_lab/alpha/__init__.py
  Exports pure alpha types and PTB core.

src/polysignal_lab/alpha/types.py
  Pure immutable bridge-neutral dataclasses: `SideBookView`, `SpotView`, `TradeView`, `FreshnessView`, `MarketView`, `OrderIntentSpec`, `AlphaDecision`, and `AlphaCore` protocol.

src/polysignal_lab/alpha/ptb_diff_core.py
  Contains the extracted PTB diff alpha formula, using only `PTBDiffConfig`, alpha types, `Side`, and existing `compute_tp_sl_thresholds`-equivalent helper logic.

src/polysignal_lab/strategies/ptb_diff.py
  Keeps the existing public `PTBDiffStrategy` class and helper function, but delegates decision logic to `PTBDiffAlphaCore` through a `MarketSnapshot -> MarketView` adapter.

src/polysignal_lab/nautilus_bridge/__init__.py
  Empty package marker with safe exports only.

src/polysignal_lab/nautilus_bridge/market_registry.py
  Maintains binary YES/NO market metadata and token/instrument mapping by `condition_id` and token id.

src/polysignal_lab/nautilus_bridge/external_data.py
  Stores latest spot/PTB/anchor metadata from sidecar producers without reaching into scheduler services.

src/polysignal_lab/nautilus_bridge/market_view_assembler.py
  Builds coherent immutable `MarketView` objects from a registry, book/trade provider protocols, and sidecar data.

src/polysignal_lab/nautilus_bridge/state.py
  Provides JSON bytes encode/decode helpers for Nautilus `on_save`/`on_load` contracts.

src/polysignal_lab/nautilus_bridge/strategy_base.py
  Defines `PolySignalNautilusStrategy` with optional Nautilus import handling and testable callback-to-intent flow.

src/polysignal_lab/nautilus_bridge/strategies/__init__.py
  Package marker for bridge strategy wrappers.

src/polysignal_lab/nautilus_bridge/strategies/ptb_diff.py
  Nautilus-compatible PTB wrapper that calls `MarketViewAssembler`, `PTBDiffAlphaCore`, and records/submits `OrderIntentSpec`.

tests/test_nautilus_dependency_boundary.py
  Verifies default import path and pyproject optional dependency isolation.

tests/test_alpha_types.py
  Verifies immutable alpha type behavior and required field semantics.

tests/test_alpha_ptb_diff.py
  Verifies PTB core emits expected decisions and matches legacy `PTBDiffStrategy` for equivalent inputs.

tests/test_nautilus_market_registry.py
  Verifies YES/NO pair assembly and non-binary rejection.

tests/test_nautilus_external_data.py
  Verifies sidecar data injection and freshness metadata.

tests/test_nautilus_market_view_assembler.py
  Verifies coherent view assembly, missing leg no-view behavior, spot/PTB injection, and freshness.

tests/test_nautilus_state.py
  Verifies versioned bytes state encoding/decoding and fail-closed unknown schema behavior.

tests/test_nautilus_strategy_base.py
  Verifies default import without Nautilus, not-ready no-order behavior, decision-to-intent mapping, and state hooks.

tests/test_nautilus_safety_boundary.py
  Verifies default bridge source avoids live execution symbols and credential env names.
```

---

### Task 1: Optional Dependency and Safety Boundary

**Files:**
- Modify: `pyproject.toml:26-28`
- Create: `docs/NAUTILUS_BRIDGE_BOUNDARY.md`
- Test: `tests/test_nautilus_dependency_boundary.py`

**Interfaces:**
- Consumes: current `pyproject.toml` optional dependencies and default package import behavior.
- Produces: optional dependency key `nautilus`, documentation path `docs/NAUTILUS_BRIDGE_BOUNDARY.md`, and default import invariant used by all bridge tasks.

- [ ] **Step 1: Write the failing dependency-boundary test**

Create `tests/test_nautilus_dependency_boundary.py` with this complete content:

```python
from __future__ import annotations

import importlib
import tomllib
from pathlib import Path


def test_default_package_import_does_not_require_nautilus() -> None:
    module = importlib.import_module("polysignal_lab")

    assert module is not None


def test_nautilus_is_optional_polymarket_extra_not_default_dependency() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    default_deps = data["project"]["dependencies"]
    optional_deps = data["project"]["optional-dependencies"]

    assert all("nautilus_trader" not in dep for dep in default_deps)
    assert optional_deps["nautilus"] == ["nautilus_trader[polymarket]"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_dependency_boundary.py -v
```

Expected: `test_default_package_import_does_not_require_nautilus` passes and `test_nautilus_is_optional_polymarket_extra_not_default_dependency` fails with `KeyError: 'nautilus'`.

- [ ] **Step 3: Add optional dependency only**

Modify `pyproject.toml` optional dependencies to this exact block:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "pre-commit>=4.6.0", "httpx2>=2.4"]
nautilus = ["nautilus_trader[polymarket]"]
```

Do not add NautilusTrader to `[project].dependencies`.

- [ ] **Step 4: Add boundary documentation**

Create `docs/NAUTILUS_BRIDGE_BOUNDARY.md` with this complete content:

```markdown
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
```

- [ ] **Step 5: Run dependency-boundary test to verify it passes**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_dependency_boundary.py -v
```

Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml docs/NAUTILUS_BRIDGE_BOUNDARY.md tests/test_nautilus_dependency_boundary.py
git commit -m "build: isolate nautilus bridge dependency"
```

---

### Task 2: Pure Alpha Types

**Files:**
- Create: `src/polysignal_lab/alpha/__init__.py`
- Create: `src/polysignal_lab/alpha/types.py`
- Test: `tests/test_alpha_types.py`

**Interfaces:**
- Consumes: existing `polysignal_lab.domain.enums.Side` and `OrderIntent`.
- Produces:
  - `SideBookView.best_bid: float | None`
  - `SideBookView.best_ask: float | None`
  - `SideBookView.spread: float | None`
  - `MarketView.ask_for(side: Side) -> float | None`
  - `MarketView.book_for(side: Side) -> SideBookView`
  - `OrderIntentSpec`
  - `AlphaDecision`
  - `AlphaCore.evaluate(view: MarketView) -> list[AlphaDecision]`

- [ ] **Step 1: Write failing alpha type tests**

Create `tests/test_alpha_types.py` with this complete content:

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from polysignal_lab.alpha.types import (
    AlphaDecision,
    FreshnessView,
    MarketView,
    OrderIntentSpec,
    SideBookView,
    SpotView,
)
from polysignal_lab.domain.enums import OrderIntent, Side


def _view() -> MarketView:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MarketView(
        view_id="view-1",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        asset="BTC",
        timeframe="5m",
        start_ts=now,
        end_ts=now,
        created_at=now,
        seconds_to_close=60,
        up=SideBookView(token_id="up-token", best_bid=0.81, best_ask=0.82, spread=0.01, freshness_ms=100),
        down=SideBookView(token_id="down-token", best_bid=0.17, best_ask=0.18, spread=0.01, freshness_ms=120),
        spot=SpotView(asset="BTC", symbol="BTCUSD", price=100120.0, source="polymarket_rtds", freshness_ms=90),
        price_to_beat=100000.0,
        up_trades=(),
        down_trades=(),
        metrics={"price_to_beat_verified": True},
        freshness=FreshnessView(up_book_ms=100, down_book_ms=120, spot_ms=90, max_ms=120),
    )


def test_market_view_exposes_side_books_and_asks() -> None:
    view = _view()

    assert view.book_for(Side.UP).token_id == "up-token"
    assert view.book_for(Side.DOWN).token_id == "down-token"
    assert view.ask_for(Side.UP) == 0.82
    assert view.ask_for(Side.DOWN) == 0.18


def test_market_view_is_immutable() -> None:
    view = _view()

    with pytest.raises(AttributeError):
        view.asset = "ETH"  # type: ignore[misc]


def test_alpha_decision_carries_order_intent_spec() -> None:
    intent = OrderIntentSpec(intent=OrderIntent.PASSIVE_GTD, expiry_seconds=45)
    decision = AlphaDecision(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.75,
        entry_reference_price=0.82,
        max_entry_price=0.92,
        seconds_to_close=60,
        data_freshness_ms=120,
        reason_codes=("PTB_DIFF_THRESHOLD_OK",),
        metrics={"diff_usd": 120.0},
        order_intent=intent,
        hedge_leg=False,
    )

    assert decision.order_intent == intent
    assert decision.reason_codes == ("PTB_DIFF_THRESHOLD_OK",)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_types.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'polysignal_lab.alpha'`.

- [ ] **Step 3: Create pure alpha types**

Create `src/polysignal_lab/alpha/types.py` with this complete content:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence

from polysignal_lab.domain.enums import OrderIntent, Side


@dataclass(frozen=True, slots=True)
class SideBookView:
    token_id: str
    best_bid: float | None
    best_ask: float | None
    spread: float | None
    freshness_ms: int | None
    min_order_size: float | None = None
    tick_size: float | None = None


@dataclass(frozen=True, slots=True)
class SpotView:
    asset: str
    symbol: str
    price: float
    source: str
    freshness_ms: int | None


@dataclass(frozen=True, slots=True)
class TradeView:
    price: float
    size: float
    side: str | None
    ts: datetime | None


@dataclass(frozen=True, slots=True)
class FreshnessView:
    up_book_ms: int | None
    down_book_ms: int | None
    spot_ms: int | None
    max_ms: int | None


@dataclass(frozen=True, slots=True)
class MarketView:
    view_id: str
    market_id: str
    market_slug: str
    condition_id: str
    asset: str
    timeframe: str
    start_ts: datetime | None
    end_ts: datetime | None
    created_at: datetime
    seconds_to_close: int | None
    up: SideBookView
    down: SideBookView
    spot: SpotView | None
    price_to_beat: float | None
    up_trades: Sequence[TradeView]
    down_trades: Sequence[TradeView]
    metrics: Mapping[str, Any]
    freshness: FreshnessView

    def book_for(self, side: Side) -> SideBookView:
        return self.up if side == Side.UP else self.down

    def ask_for(self, side: Side) -> float | None:
        return self.book_for(side).best_ask


@dataclass(frozen=True, slots=True)
class OrderIntentSpec:
    intent: OrderIntent
    expiry_seconds: int | None = None
    pair_id: str | None = None


@dataclass(frozen=True, slots=True)
class AlphaDecision:
    strategy: str
    asset: str
    timeframe: str
    market_id: str
    market_slug: str
    condition_id: str
    token_id: str
    side: Side
    confidence: float
    entry_reference_price: float
    max_entry_price: float
    seconds_to_close: int | None
    data_freshness_ms: int | None
    reason_codes: tuple[str, ...]
    metrics: Mapping[str, Any]
    order_intent: OrderIntentSpec | None = None
    hedge_leg: bool = False


class AlphaCore(Protocol):
    def evaluate(self, view: MarketView) -> list[AlphaDecision]: ...
```

Create `src/polysignal_lab/alpha/__init__.py` with this complete content:

```python
from polysignal_lab.alpha.types import (
    AlphaCore,
    AlphaDecision,
    FreshnessView,
    MarketView,
    OrderIntentSpec,
    SideBookView,
    SpotView,
    TradeView,
)

__all__ = [
    "AlphaCore",
    "AlphaDecision",
    "FreshnessView",
    "MarketView",
    "OrderIntentSpec",
    "SideBookView",
    "SpotView",
    "TradeView",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_types.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/alpha/__init__.py src/polysignal_lab/alpha/types.py tests/test_alpha_types.py
git commit -m "feat: add pure alpha decision types"
```

---

### Task 3: PTBDiff Alpha Core and Legacy Adapter

**Files:**
- Create: `src/polysignal_lab/alpha/ptb_diff_core.py`
- Modify: `src/polysignal_lab/alpha/__init__.py`
- Modify: `src/polysignal_lab/strategies/ptb_diff.py:70-228`
- Test: `tests/test_alpha_ptb_diff.py`
- Test: existing `tests/test_ptb_diff.py`
- Test: existing `tests/test_strategies.py::test_ptb_diff_generates_buy_up`

**Interfaces:**
- Consumes: `PTBDiffConfig`, `PTBTriggerConfig`, `PTBExitConfig`, `MarketView`, existing `compute_tp_sl_thresholds()` semantics, and existing `PTBDiffStrategy` public API.
- Produces:
  - `PTBDiffAlphaCore(config: PTBDiffConfig)`
  - `PTBDiffAlphaCore.evaluate(view: MarketView) -> list[AlphaDecision]`
  - `market_view_from_snapshot(snapshot: MarketSnapshot) -> MarketView`
  - `decision_to_signal(decision: AlphaDecision, snapshot_id: str | None, freshness_policy: FreshnessPolicy | None) -> SignalCandidate`
  - unchanged `PTBDiffStrategy.evaluate(snapshot: MarketSnapshot) -> list[SignalCandidate]`

- [ ] **Step 1: Write failing alpha equivalence tests**

Create `tests/test_alpha_ptb_diff.py` with this complete content:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore, market_view_from_snapshot
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
from polysignal_lab.strategies.config import PTBDiffConfig, PTBTriggerConfig
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from polysignal_lab.utils import utc_now
from factories import BookFactoryConfig, MarketFactoryConfig, SpotFactoryConfig, sample_book, sample_market, sample_spot

PRICE_TO_BEAT: Final = 100_000.0


@dataclass(frozen=True, slots=True)
class CoreScenario:
    side: Side = Side.UP
    diff_usd: float = 120.0
    side_ask: float = 0.82
    other_ask: float = 0.18
    seconds_to_close: int = 60
    verified_ptb: bool = True
    anchor_ptb: bool = True
    spot_source: str = "polymarket_rtds"


def _config() -> PTBDiffConfig:
    return PTBDiffConfig(
        enabled=True,
        assets=["BTC"],
        timeframes=["5m"],
        require_verified_ptb_source=True,
        require_anchor_price_source=True,
        require_chainlink_spot_source=True,
        max_spread=0.08,
        triggers=[
            PTBTriggerConfig(
                name="test_up",
                side=Side.UP,
                min_diff_usd=80.0,
                max_token_price=0.92,
                min_token_price=0.80,
                min_seconds_to_close=0,
                max_seconds_to_close=120,
            ),
            PTBTriggerConfig(
                name="test_down",
                side=Side.DOWN,
                min_diff_usd=80.0,
                max_token_price=0.92,
                min_token_price=0.80,
                min_seconds_to_close=0,
                max_seconds_to_close=120,
            ),
        ],
    )


def _snapshot(scenario: CoreScenario) -> MarketSnapshot:
    created_at = utc_now()
    market = sample_market(
        MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=scenario.seconds_to_close, price_to_beat=PRICE_TO_BEAT)
    ).model_copy(update={"end_ts": created_at + timedelta(seconds=scenario.seconds_to_close)})
    up_ask = scenario.side_ask if scenario.side == Side.UP else scenario.other_ask
    down_ask = scenario.side_ask if scenario.side == Side.DOWN else scenario.other_ask
    up_book = sample_book(market.token_for(Side.UP).token_id, BookFactoryConfig(ask=up_ask, bid=max(0.01, up_ask - 0.02), size=500))
    down_book = sample_book(market.token_for(Side.DOWN).token_id, BookFactoryConfig(ask=down_ask, bid=max(0.01, down_ask - 0.02), size=500))
    signed_diff = scenario.diff_usd if scenario.side == Side.UP else -scenario.diff_usd
    spot = sample_spot(SpotFactoryConfig(asset="BTC", price=PRICE_TO_BEAT + signed_diff)).model_copy(
        update={"source": scenario.spot_source, "received_at": created_at}
    )
    return MarketSnapshot(
        snapshot_id="snapshot-ptb-core",
        created_at=created_at,
        market=market,
        up_book=up_book.model_copy(update={"received_at": created_at}),
        down_book=down_book.model_copy(update={"received_at": created_at}),
        spot=spot,
        price_to_beat=PRICE_TO_BEAT,
        freshness=FreshnessState(up_book_ms=0, down_book_ms=0, spot_ms=0, max_ms=0),
        metrics={
            "price_to_beat_source": "anchor",
            "price_to_beat_verified": scenario.verified_ptb,
            "price_to_beat_from_anchor_service": scenario.anchor_ptb,
            "spot_source": scenario.spot_source,
        },
    )


def test_ptb_alpha_core_matches_legacy_strategy_for_equivalent_up_input() -> None:
    config = _config()
    snapshot = _snapshot(CoreScenario(side=Side.UP, diff_usd=120.0, side_ask=0.82))

    legacy_signal = PTBDiffStrategy(config).evaluate(snapshot)[0]
    core_decision = PTBDiffAlphaCore(config).evaluate(market_view_from_snapshot(snapshot))[0]

    assert core_decision.side == legacy_signal.side
    assert core_decision.confidence == legacy_signal.confidence
    assert core_decision.max_entry_price == legacy_signal.max_entry_price
    assert core_decision.reason_codes == tuple(legacy_signal.reason_codes)
    assert dict(core_decision.metrics) == legacy_signal.metrics
    assert core_decision.order_intent is None
    assert legacy_signal.order_intent is None
    assert core_decision.hedge_leg == legacy_signal.hedge_leg


def test_ptb_alpha_core_matches_legacy_strategy_for_equivalent_down_input() -> None:
    config = _config()
    snapshot = _snapshot(CoreScenario(side=Side.DOWN, diff_usd=140.0, side_ask=0.83))

    legacy_signal = PTBDiffStrategy(config).evaluate(snapshot)[0]
    core_decision = PTBDiffAlphaCore(config).evaluate(market_view_from_snapshot(snapshot))[0]

    assert core_decision.side == legacy_signal.side
    assert core_decision.reason_codes == tuple(legacy_signal.reason_codes)
    assert core_decision.metrics["diff_usd"] == legacy_signal.metrics["diff_usd"]
    assert core_decision.metrics["trigger"] == "test_down"


def test_ptb_alpha_core_rejects_missing_verified_anchor_source() -> None:
    config = _config()
    snapshot = _snapshot(CoreScenario(verified_ptb=False, anchor_ptb=False))

    assert PTBDiffAlphaCore(config).evaluate(market_view_from_snapshot(snapshot)) == []


def test_ptb_alpha_core_rejects_missing_market_data() -> None:
    config = _config()
    snapshot = _snapshot(CoreScenario()).model_copy(update={"up_book": None})

    assert PTBDiffAlphaCore(config).evaluate(market_view_from_snapshot(snapshot)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_ptb_diff.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'polysignal_lab.alpha.ptb_diff_core'`.

- [ ] **Step 3: Add PTBDiffAlphaCore**

Create `src/polysignal_lab/alpha/ptb_diff_core.py` with this complete content:

```python
from __future__ import annotations

from typing import assert_never

from polysignal_lab.alpha.types import AlphaDecision, FreshnessView, MarketView, SideBookView, SpotView
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.config import PTBDiffConfig


class TpSlThresholds(dict[str, float | None]):
    pass


def compute_tp_sl_thresholds(entry_prob: float, stop_loss_pct: float, tp_rr: float, tp_cap: float) -> TpSlThresholds:
    if entry_prob <= 0.0:
        return TpSlThresholds(stop_prob=0.0, tp_trigger_prob=None, risk_abs=0.0)

    stop_prob = max(0.0, entry_prob * (1.0 - stop_loss_pct))
    risk_abs = max(0.0, entry_prob - stop_prob)
    raw_tp = entry_prob + risk_abs * tp_rr

    if raw_tp <= entry_prob:
        return TpSlThresholds(stop_prob=stop_prob, tp_trigger_prob=None, risk_abs=risk_abs)

    tp_trigger_prob = min(tp_cap, raw_tp)

    if tp_trigger_prob < raw_tp:
        balanced_risk = (tp_trigger_prob - entry_prob) / tp_rr
        balanced_stop = max(0.0, entry_prob - balanced_risk)
        if balanced_stop < entry_prob:
            stop_prob = balanced_stop
            risk_abs = entry_prob - stop_prob
            return TpSlThresholds(
                stop_prob=stop_prob,
                tp_trigger_prob=tp_trigger_prob,
                risk_abs=risk_abs,
                balanced_stop=balanced_stop,
            )

    return TpSlThresholds(stop_prob=stop_prob, tp_trigger_prob=tp_trigger_prob, risk_abs=risk_abs)


class PTBDiffAlphaCore:
    name = "ptb_diff"

    def __init__(self, config: PTBDiffConfig):
        self.config = config

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        if not self.config.enabled:
            return []
        if view.asset not in [a.upper() for a in self.config.assets]:
            return []
        if view.timeframe not in self.config.timeframes:
            return []
        if view.spot is None or view.price_to_beat is None:
            return []
        if self.config.require_verified_ptb_source and view.metrics.get("price_to_beat_verified") is not True:
            return []
        if self.config.require_anchor_price_source and not view.metrics.get("price_to_beat_from_anchor_service"):
            return []
        spot_source = str(view.metrics.get("spot_source") or view.spot.source)
        if self.config.require_chainlink_spot_source and spot_source not in self.config.chainlink_spot_sources:
            return []

        seconds = view.seconds_to_close
        if seconds is None or seconds <= 0:
            return []

        diff = view.spot.price - view.price_to_beat
        exit_cfg = self.config.exit_config

        for trigger in self.config.triggers:
            wanted_side = trigger.side
            if not self._diff_supports_side(diff, wanted_side):
                continue
            if not (trigger.min_seconds_to_close <= seconds <= trigger.max_seconds_to_close):
                continue
            if abs(diff) < trigger.min_diff_usd:
                continue

            entry_price = view.ask_for(wanted_side)
            if entry_price is None or entry_price <= 0.0:
                continue
            if entry_price > trigger.max_token_price:
                continue

            if trigger.min_token_price > 0.0:
                if not (trigger.min_token_price <= entry_price <= trigger.max_token_price):
                    continue
                directional_probability = entry_price
                probability_edge = max(0.0, entry_price - trigger.min_token_price)
            else:
                directional_probability = self._directional_probability(diff, wanted_side)
                probability_edge = max(0.0, directional_probability - entry_price)
                if probability_edge < trigger.min_probability_edge:
                    continue

            side_book = view.book_for(wanted_side)
            if side_book.best_bid is None or side_book.best_ask is None:
                continue
            if side_book.spread is None or side_book.spread > self.config.max_spread:
                continue

            max_lag_ms = exit_cfg.market_data_max_lag_sec * 1000
            orderbook_freshness_ms = side_book.freshness_ms
            spot_freshness_ms = view.spot.freshness_ms
            tp_sl = compute_tp_sl_thresholds(
                entry_prob=entry_price,
                stop_loss_pct=exit_cfg.stop_loss_prob_pct,
                tp_rr=exit_cfg.take_profit_rr,
                tp_cap=exit_cfg.take_profit_cap,
            )
            confidence = min(0.98, 0.55 + min(0.25, abs(diff) / 500) + min(0.18, probability_edge))
            prob_ok_code = "PTB_PROB_RANGE_OK" if trigger.min_token_price > 0.0 else "PTB_PROBABILITY_EDGE_OK"
            reason_codes = (
                self._spot_reason(wanted_side),
                "PTB_DIFF_THRESHOLD_OK",
                "PTB_TOKEN_PRICE_OK",
                prob_ok_code,
                "PTB_TIME_WINDOW_OK",
                "PTB_SPREAD_OK",
                trigger.name,
            )
            return [
                AlphaDecision(
                    strategy=self.name,
                    asset=view.asset,
                    timeframe=view.timeframe,
                    market_id=view.market_id,
                    market_slug=view.market_slug,
                    condition_id=view.condition_id,
                    token_id=side_book.token_id,
                    side=wanted_side,
                    confidence=confidence,
                    entry_reference_price=entry_price,
                    max_entry_price=trigger.max_token_price,
                    seconds_to_close=seconds,
                    data_freshness_ms=view.freshness.max_ms,
                    reason_codes=reason_codes,
                    metrics={
                        "spot_price": view.spot.price,
                        "spot_source": spot_source,
                        "price_to_beat": view.price_to_beat,
                        "price_to_beat_source": view.metrics.get("price_to_beat_source"),
                        "price_to_beat_verified": view.metrics.get("price_to_beat_verified"),
                        "diff_usd": diff,
                        "abs_diff_usd": abs(diff),
                        "trigger": trigger.name,
                        "trigger_side": trigger.side.value,
                        "entry_prob": entry_price,
                        "token_ask": entry_price,
                        "directional_probability": directional_probability,
                        "max_token_price": trigger.max_token_price,
                        "min_token_price": trigger.min_token_price,
                        "probability_edge": probability_edge,
                        "min_probability_edge": trigger.min_probability_edge,
                        "min_diff_usd": trigger.min_diff_usd,
                        "seconds_to_close": seconds,
                        "min_seconds_to_close": trigger.min_seconds_to_close,
                        "max_seconds_to_close": trigger.max_seconds_to_close,
                        "tp_sl_stop_prob": tp_sl["stop_prob"],
                        "tp_sl_tp_prob": tp_sl["tp_trigger_prob"],
                        "tp_sl_risk_abs": tp_sl["risk_abs"],
                        "tp_sl_stop_loss_pct": exit_cfg.stop_loss_prob_pct,
                        "tp_sl_take_profit_rr": exit_cfg.take_profit_rr,
                        "tp_sl_take_profit_cap": exit_cfg.take_profit_cap,
                        "spread": side_book.spread,
                        "max_spread": self.config.max_spread,
                        "orderbook_freshness_ms": orderbook_freshness_ms,
                        "max_lag_ms": max_lag_ms,
                        "spot_freshness_ms": spot_freshness_ms,
                    },
                )
            ]
        return []

    @staticmethod
    def _diff_supports_side(diff_usd: float, side: Side) -> bool:
        match side:
            case Side.UP:
                return diff_usd > 0
            case Side.DOWN:
                return diff_usd < 0
            case unreachable:
                assert_never(unreachable)

    @staticmethod
    def _directional_probability(diff_usd: float, side: Side) -> float:
        match side:
            case Side.UP:
                return 1.0 if diff_usd > 0 else 0.0
            case Side.DOWN:
                return 1.0 if diff_usd < 0 else 0.0
            case unreachable:
                assert_never(unreachable)

    @staticmethod
    def _spot_reason(side: Side) -> str:
        match side:
            case Side.UP:
                return "PTB_SPOT_ABOVE_PTB"
            case Side.DOWN:
                return "PTB_SPOT_BELOW_PTB"
            case unreachable:
                assert_never(unreachable)


def market_view_from_snapshot(snapshot: MarketSnapshot) -> MarketView:
    def book_view(side: Side) -> SideBookView:
        book = snapshot.book_for(side)
        token = snapshot.market.token_for(side)
        return SideBookView(
            token_id=token.token_id,
            best_bid=book.best_bid if book else None,
            best_ask=book.best_ask if book else None,
            spread=book.spread if book else None,
            freshness_ms=book.freshness_ms(snapshot.created_at) if book else None,
            min_order_size=book.min_order_size if book else None,
            tick_size=book.tick_size if book else None,
        )

    spot = None
    if snapshot.spot is not None:
        spot = SpotView(
            asset=snapshot.spot.asset,
            symbol=snapshot.spot.symbol,
            price=snapshot.spot.price,
            source=snapshot.spot.source,
            freshness_ms=snapshot.spot.freshness_ms(snapshot.created_at),
        )
    return MarketView(
        view_id=snapshot.snapshot_id,
        market_id=snapshot.market.market_id,
        market_slug=snapshot.market.market_slug,
        condition_id=snapshot.market.condition_id,
        asset=snapshot.market.asset,
        timeframe=snapshot.market.timeframe,
        start_ts=snapshot.market.start_ts,
        end_ts=snapshot.market.end_ts,
        created_at=snapshot.created_at,
        seconds_to_close=snapshot.seconds_to_close,
        up=book_view(Side.UP),
        down=book_view(Side.DOWN),
        spot=spot,
        price_to_beat=snapshot.price_to_beat,
        up_trades=tuple(snapshot.metrics.get("up_trades") or ()),
        down_trades=tuple(snapshot.metrics.get("down_trades") or ()),
        metrics=snapshot.metrics,
        freshness=FreshnessView(
            up_book_ms=snapshot.freshness.up_book_ms,
            down_book_ms=snapshot.freshness.down_book_ms,
            spot_ms=snapshot.freshness.spot_ms,
            max_ms=snapshot.freshness.max_ms,
        ),
    )


def decision_to_signal(decision: AlphaDecision, snapshot_id: str | None, freshness_policy) -> SignalCandidate:
    return SignalCandidate.build(
        strategy=decision.strategy,
        asset=decision.asset,
        timeframe=decision.timeframe,
        market_id=decision.market_id,
        market_slug=decision.market_slug,
        condition_id=decision.condition_id,
        token_id=decision.token_id,
        side=decision.side,
        confidence=decision.confidence,
        entry_reference_price=decision.entry_reference_price,
        max_entry_price=decision.max_entry_price,
        seconds_to_close=decision.seconds_to_close,
        data_freshness_ms=decision.data_freshness_ms,
        freshness_policy=freshness_policy,
        reason_codes=list(decision.reason_codes),
        metrics=dict(decision.metrics),
        snapshot_id=snapshot_id,
        order_intent=decision.order_intent.intent if decision.order_intent else None,
        expiry_seconds=decision.order_intent.expiry_seconds if decision.order_intent else None,
        pair_id=decision.order_intent.pair_id if decision.order_intent else None,
        hedge_leg=decision.hedge_leg,
    )
```

- [ ] **Step 4: Export PTB core from alpha package**

Modify `src/polysignal_lab/alpha/__init__.py` to this complete content:

```python
from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore, decision_to_signal, market_view_from_snapshot
from polysignal_lab.alpha.types import (
    AlphaCore,
    AlphaDecision,
    FreshnessView,
    MarketView,
    OrderIntentSpec,
    SideBookView,
    SpotView,
    TradeView,
)

__all__ = [
    "AlphaCore",
    "AlphaDecision",
    "FreshnessView",
    "MarketView",
    "OrderIntentSpec",
    "PTBDiffAlphaCore",
    "SideBookView",
    "SpotView",
    "TradeView",
    "decision_to_signal",
    "market_view_from_snapshot",
]
```

- [ ] **Step 5: Replace PTBDiffStrategy evaluate body with adapter**

Modify `src/polysignal_lab/strategies/ptb_diff.py` imports and class body as follows:

```python
from polysignal_lab.alpha.ptb_diff_core import (
    PTBDiffAlphaCore,
    compute_tp_sl_thresholds,
    decision_to_signal,
    market_view_from_snapshot,
)
```

Keep the public `compute_tp_sl_thresholds` import name available from this module for existing tests.

Inside `PTBDiffStrategy.__init__`, add the core:

```python
    def __init__(self, config: PTBDiffConfig):
        self.config = config
        self.core = PTBDiffAlphaCore(config)
```

Replace `PTBDiffStrategy.evaluate()` with this complete method:

```python
    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        view = market_view_from_snapshot(snapshot)
        return [
            decision_to_signal(decision, snapshot.snapshot_id, self.freshness_policy)
            for decision in self.core.evaluate(view)
        ]
```

Keep `_diff_supports_side`, `_directional_probability`, and `_spot_reason` only if existing tests import them. If no tests import them, delete those duplicate static methods and use the core methods only. Do not leave copied alpha logic in the legacy strategy.

- [ ] **Step 6: Run new and existing PTB tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_ptb_diff.py tests/test_ptb_diff.py tests/test_strategies.py::test_ptb_diff_generates_buy_up -v
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/polysignal_lab/alpha/__init__.py src/polysignal_lab/alpha/ptb_diff_core.py src/polysignal_lab/strategies/ptb_diff.py tests/test_alpha_ptb_diff.py
git commit -m "feat: extract ptb diff alpha core"
```

---

### Task 4: Market Registry and External Sidecar

**Files:**
- Create: `src/polysignal_lab/nautilus_bridge/__init__.py`
- Create: `src/polysignal_lab/nautilus_bridge/market_registry.py`
- Create: `src/polysignal_lab/nautilus_bridge/external_data.py`
- Test: `tests/test_nautilus_market_registry.py`
- Test: `tests/test_nautilus_external_data.py`

**Interfaces:**
- Consumes: `Market`, `OutcomeToken`, `Side`, and `SpotView`.
- Produces:
  - `InstrumentTokenMeta(instrument_id: str, token_id: str, side: Side)`
  - `MarketPairMeta.from_market(market: Market, up_instrument_id: str | None = None, down_instrument_id: str | None = None) -> MarketPairMeta`
  - `PolymarketMarketRegistry.register(pair: MarketPairMeta) -> None`
  - `PolymarketMarketRegistry.by_condition(condition_id: str) -> MarketPairMeta | None`
  - `PolymarketMarketRegistry.by_token(token_id: str) -> MarketPairMeta | None`
  - `ExternalDataSidecar.update_spot(spot: SpotView) -> None`
  - `ExternalDataSidecar.update_price_to_beat(condition_id: str, value: float, source: str, verified: bool, from_anchor_service: bool, anchor_source: str | None, anchor_lag_ms: int | None) -> None`
  - `ExternalDataSidecar.spot_for(asset: str) -> SpotView | None`
  - `ExternalDataSidecar.ptb_for(condition_id: str) -> PriceToBeatView | None`

- [ ] **Step 1: Write failing market registry tests**

Create `tests/test_nautilus_market_registry.py` with this complete content:

```python
from __future__ import annotations

import pytest

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import OutcomeToken
from polysignal_lab.nautilus_bridge.market_registry import MarketPairMeta, PolymarketMarketRegistry
from factories import MarketFactoryConfig, sample_market


def test_market_registry_registers_binary_yes_no_pair() -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    pair = MarketPairMeta.from_market(market, up_instrument_id="PM-UP", down_instrument_id="PM-DOWN")
    registry = PolymarketMarketRegistry()

    registry.register(pair)

    assert registry.by_condition(market.condition_id) == pair
    assert registry.by_token(market.token_for(Side.UP).token_id) == pair
    assert registry.by_token(market.token_for(Side.DOWN).token_id) == pair
    assert pair.up.instrument_id == "PM-UP"
    assert pair.down.instrument_id == "PM-DOWN"


def test_market_registry_rejects_non_binary_market() -> None:
    market = sample_market().model_copy(
        update={
            "outcome_tokens": [
                OutcomeToken(token_id="a", side=Side.UP, outcome_name="A", market_id="m"),
                OutcomeToken(token_id="b", side=Side.DOWN, outcome_name="B", market_id="m"),
                OutcomeToken(token_id="c", side=Side.UP, outcome_name="C", market_id="m"),
            ]
        }
    )

    with pytest.raises(ValueError, match="binary YES/NO"):
        MarketPairMeta.from_market(market)
```

- [ ] **Step 2: Write failing external sidecar tests**

Create `tests/test_nautilus_external_data.py` with this complete content:

```python
from __future__ import annotations

from datetime import UTC, datetime

from polysignal_lab.alpha.types import SpotView
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar


def test_sidecar_stores_spot_by_uppercase_asset() -> None:
    sidecar = ExternalDataSidecar()
    spot = SpotView(asset="btc", symbol="BTCUSD", price=100120.0, source="polymarket_rtds", freshness_ms=15)

    sidecar.update_spot(spot)

    assert sidecar.spot_for("BTC") == spot
    assert sidecar.spot_for("btc") == spot


def test_sidecar_stores_price_to_beat_metadata() -> None:
    sidecar = ExternalDataSidecar()
    sidecar.update_price_to_beat(
        condition_id="condition-btc-5m",
        value=100000.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=25,
    )

    ptb = sidecar.ptb_for("condition-btc-5m")

    assert ptb is not None
    assert ptb.value == 100000.0
    assert ptb.source == "anchor"
    assert ptb.verified is True
    assert ptb.from_anchor_service is True
    assert ptb.anchor_source == "chainlink"
    assert ptb.anchor_lag_ms == 25
    assert isinstance(ptb.updated_at, datetime)
    assert ptb.updated_at.tzinfo == UTC
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_market_registry.py tests/test_nautilus_external_data.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'polysignal_lab.nautilus_bridge'`.

- [ ] **Step 4: Create bridge package marker**

Create `src/polysignal_lab/nautilus_bridge/__init__.py` with this complete content:

```python
__all__: list[str] = []
```

- [ ] **Step 5: Implement market registry**

Create `src/polysignal_lab/nautilus_bridge/market_registry.py` with this complete content:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market


@dataclass(frozen=True, slots=True)
class InstrumentTokenMeta:
    instrument_id: str
    token_id: str
    side: Side


@dataclass(frozen=True, slots=True)
class MarketPairMeta:
    market_id: str
    market_slug: str
    condition_id: str
    asset: str
    timeframe: str
    start_ts: datetime | None
    end_ts: datetime | None
    up: InstrumentTokenMeta
    down: InstrumentTokenMeta

    @classmethod
    def from_market(
        cls,
        market: Market,
        *,
        up_instrument_id: str | None = None,
        down_instrument_id: str | None = None,
    ) -> "MarketPairMeta":
        if len(market.outcome_tokens) != 2:
            raise ValueError("Only binary YES/NO markets are supported by the Nautilus bridge")
        up_token = market.token_for(Side.UP)
        down_token = market.token_for(Side.DOWN)
        return cls(
            market_id=market.market_id,
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            asset=market.asset.upper(),
            timeframe=market.timeframe,
            start_ts=market.start_ts,
            end_ts=market.end_ts,
            up=InstrumentTokenMeta(
                instrument_id=up_instrument_id or up_token.token_id,
                token_id=up_token.token_id,
                side=Side.UP,
            ),
            down=InstrumentTokenMeta(
                instrument_id=down_instrument_id or down_token.token_id,
                token_id=down_token.token_id,
                side=Side.DOWN,
            ),
        )


class PolymarketMarketRegistry:
    def __init__(self) -> None:
        self._by_condition: dict[str, MarketPairMeta] = {}
        self._by_token: dict[str, MarketPairMeta] = {}

    def register(self, pair: MarketPairMeta) -> None:
        self._by_condition[pair.condition_id] = pair
        self._by_token[pair.up.token_id] = pair
        self._by_token[pair.down.token_id] = pair

    def by_condition(self, condition_id: str) -> MarketPairMeta | None:
        return self._by_condition.get(condition_id)

    def by_token(self, token_id: str) -> MarketPairMeta | None:
        return self._by_token.get(token_id)
```

- [ ] **Step 6: Implement external data sidecar**

Create `src/polysignal_lab/nautilus_bridge/external_data.py` with this complete content:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from polysignal_lab.alpha.types import SpotView


@dataclass(frozen=True, slots=True)
class PriceToBeatView:
    condition_id: str
    value: float
    source: str
    verified: bool
    from_anchor_service: bool
    anchor_source: str | None
    anchor_lag_ms: int | None
    updated_at: datetime


class ExternalDataSidecar:
    def __init__(self) -> None:
        self._spots: dict[str, SpotView] = {}
        self._ptb: dict[str, PriceToBeatView] = {}

    def update_spot(self, spot: SpotView) -> None:
        self._spots[spot.asset.upper()] = spot

    def spot_for(self, asset: str) -> SpotView | None:
        return self._spots.get(asset.upper())

    def update_price_to_beat(
        self,
        *,
        condition_id: str,
        value: float,
        source: str,
        verified: bool,
        from_anchor_service: bool,
        anchor_source: str | None,
        anchor_lag_ms: int | None,
    ) -> None:
        self._ptb[condition_id] = PriceToBeatView(
            condition_id=condition_id,
            value=value,
            source=source,
            verified=verified,
            from_anchor_service=from_anchor_service,
            anchor_source=anchor_source,
            anchor_lag_ms=anchor_lag_ms,
            updated_at=datetime.now(UTC),
        )

    def ptb_for(self, condition_id: str) -> PriceToBeatView | None:
        return self._ptb.get(condition_id)
```

- [ ] **Step 7: Run registry and sidecar tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_market_registry.py tests/test_nautilus_external_data.py -v
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/polysignal_lab/nautilus_bridge/__init__.py src/polysignal_lab/nautilus_bridge/market_registry.py src/polysignal_lab/nautilus_bridge/external_data.py tests/test_nautilus_market_registry.py tests/test_nautilus_external_data.py
git commit -m "feat: add polymarket bridge registry"
```

---

### Task 5: MarketViewAssembler

**Files:**
- Create: `src/polysignal_lab/nautilus_bridge/market_view_assembler.py`
- Test: `tests/test_nautilus_market_view_assembler.py`

**Interfaces:**
- Consumes: `MarketPairMeta`, `ExternalDataSidecar`, `SideBookView`, `TradeView`, and `MarketView`.
- Produces:
  - `BookDataProvider.book_for_token(token_id: str) -> SideBookView | None`
  - `BookDataProvider.trades_for_token(token_id: str) -> Sequence[TradeView]`
  - `MarketViewAssembler.build(condition_id: str, created_at: datetime | None = None) -> MarketView | None`
  - not-ready behavior: returns `None` when registry pair, either leg book, spot, or PTB is missing.

- [ ] **Step 1: Write failing assembler tests**

Create `tests/test_nautilus_market_view_assembler.py` with this complete content:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polysignal_lab.alpha.types import SideBookView, SpotView, TradeView
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import MarketPairMeta, PolymarketMarketRegistry
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from factories import MarketFactoryConfig, sample_market


class FakeBookProvider:
    def __init__(self) -> None:
        self.books: dict[str, SideBookView] = {}
        self.trades: dict[str, tuple[TradeView, ...]] = {}

    def book_for_token(self, token_id: str) -> SideBookView | None:
        return self.books.get(token_id)

    def trades_for_token(self, token_id: str) -> tuple[TradeView, ...]:
        return self.trades.get(token_id, ())


def _components() -> tuple[MarketViewAssembler, MarketPairMeta, FakeBookProvider, ExternalDataSidecar]:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=60, price_to_beat=100000.0))
    pair = MarketPairMeta.from_market(market)
    registry = PolymarketMarketRegistry()
    registry.register(pair)
    books = FakeBookProvider()
    sidecar = ExternalDataSidecar()
    assembler = MarketViewAssembler(registry=registry, books=books, sidecar=sidecar)
    return assembler, pair, books, sidecar


def test_assembler_builds_coherent_market_view() -> None:
    assembler, pair, books, sidecar = _components()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    books.books[pair.up.token_id] = SideBookView(pair.up.token_id, best_bid=0.81, best_ask=0.82, spread=0.01, freshness_ms=10)
    books.books[pair.down.token_id] = SideBookView(pair.down.token_id, best_bid=0.17, best_ask=0.18, spread=0.01, freshness_ms=20)
    books.trades[pair.up.token_id] = (TradeView(price=0.82, size=5.0, side="BUY", ts=now),)
    sidecar.update_spot(SpotView(asset="BTC", symbol="BTCUSD", price=100120.0, source="polymarket_rtds", freshness_ms=30))
    sidecar.update_price_to_beat(
        condition_id=pair.condition_id,
        value=100000.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=40,
    )

    view = assembler.build(pair.condition_id, created_at=now)

    assert view is not None
    assert view.market_id == pair.market_id
    assert view.condition_id == pair.condition_id
    assert view.ask_for(Side.UP) == 0.82
    assert view.ask_for(Side.DOWN) == 0.18
    assert view.spot is not None
    assert view.spot.price == 100120.0
    assert view.price_to_beat == 100000.0
    assert view.up_trades == books.trades[pair.up.token_id]
    assert view.metrics["price_to_beat_verified"] is True
    assert view.metrics["price_to_beat_from_anchor_service"] is True
    assert view.freshness.max_ms == 30


def test_assembler_returns_none_when_down_leg_missing() -> None:
    assembler, pair, books, sidecar = _components()
    books.books[pair.up.token_id] = SideBookView(pair.up.token_id, best_bid=0.81, best_ask=0.82, spread=0.01, freshness_ms=10)
    sidecar.update_spot(SpotView(asset="BTC", symbol="BTCUSD", price=100120.0, source="polymarket_rtds", freshness_ms=30))
    sidecar.update_price_to_beat(
        condition_id=pair.condition_id,
        value=100000.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=40,
    )

    assert assembler.build(pair.condition_id) is None


def test_assembler_returns_none_when_sidecar_data_missing() -> None:
    assembler, pair, books, _sidecar = _components()
    books.books[pair.up.token_id] = SideBookView(pair.up.token_id, best_bid=0.81, best_ask=0.82, spread=0.01, freshness_ms=10)
    books.books[pair.down.token_id] = SideBookView(pair.down.token_id, best_bid=0.17, best_ask=0.18, spread=0.01, freshness_ms=20)

    assert assembler.build(pair.condition_id) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_market_view_assembler.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'polysignal_lab.nautilus_bridge.market_view_assembler'`.

- [ ] **Step 3: Implement assembler**

Create `src/polysignal_lab/nautilus_bridge/market_view_assembler.py` with this complete content:

```python
from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence

from polysignal_lab.alpha.types import FreshnessView, MarketView, SideBookView, TradeView
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.utils import stable_hash, utc_now


class BookDataProvider(Protocol):
    def book_for_token(self, token_id: str) -> SideBookView | None: ...

    def trades_for_token(self, token_id: str) -> Sequence[TradeView]: ...


class MarketViewAssembler:
    def __init__(self, *, registry: PolymarketMarketRegistry, books: BookDataProvider, sidecar: ExternalDataSidecar):
        self.registry = registry
        self.books = books
        self.sidecar = sidecar

    def build(self, condition_id: str, *, created_at: datetime | None = None) -> MarketView | None:
        pair = self.registry.by_condition(condition_id)
        if pair is None:
            return None
        up_book = self.books.book_for_token(pair.up.token_id)
        down_book = self.books.book_for_token(pair.down.token_id)
        spot = self.sidecar.spot_for(pair.asset)
        ptb = self.sidecar.ptb_for(pair.condition_id)
        if up_book is None or down_book is None or spot is None or ptb is None:
            return None

        now = created_at or utc_now()
        seconds_to_close = None
        if pair.end_ts is not None and hasattr(pair.end_ts, "__sub__"):
            seconds_to_close = max(0, int((pair.end_ts - now).total_seconds()))
        freshness_values = [value for value in (up_book.freshness_ms, down_book.freshness_ms, spot.freshness_ms) if value is not None]
        freshness = FreshnessView(
            up_book_ms=up_book.freshness_ms,
            down_book_ms=down_book.freshness_ms,
            spot_ms=spot.freshness_ms,
            max_ms=max(freshness_values) if freshness_values else None,
        )
        return MarketView(
            view_id=f"view_{stable_hash(pair.condition_id, now.isoformat())}",
            market_id=pair.market_id,
            market_slug=pair.market_slug,
            condition_id=pair.condition_id,
            asset=pair.asset,
            timeframe=pair.timeframe,
            start_ts=pair.start_ts,
            end_ts=pair.end_ts,
            created_at=now,
            seconds_to_close=seconds_to_close,
            up=up_book,
            down=down_book,
            spot=spot,
            price_to_beat=ptb.value,
            up_trades=tuple(self.books.trades_for_token(pair.up.token_id)),
            down_trades=tuple(self.books.trades_for_token(pair.down.token_id)),
            metrics={
                "price_to_beat_source": ptb.source,
                "price_to_beat_verified": ptb.verified,
                "price_to_beat_from_anchor_service": ptb.from_anchor_service,
                "anchor_price_source": ptb.anchor_source,
                "anchor_price_lag_ms": ptb.anchor_lag_ms,
                "spot_source": spot.source,
                "up_token_id": pair.up.token_id,
                "down_token_id": pair.down.token_id,
            },
            freshness=freshness,
        )
```

- [ ] **Step 4: Run assembler tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_market_view_assembler.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_bridge/market_view_assembler.py tests/test_nautilus_market_view_assembler.py
git commit -m "feat: assemble nautilus market views"
```

---

### Task 6: Versioned Stateful Contract

**Files:**
- Create: `src/polysignal_lab/nautilus_bridge/state.py`
- Test: `tests/test_nautilus_state.py`

**Interfaces:**
- Consumes: JSON-serializable state mappings.
- Produces:
  - `StateSchemaError(ValueError)`
  - `state_key(strategy_name: str, version: int = 1) -> str`
  - `encode_state(strategy_name: str, payload: Mapping[str, Any], version: int = 1) -> dict[str, bytes]`
  - `decode_state(strategy_name: str, state: Mapping[str, bytes], version: int = 1) -> dict[str, Any]`
  - unknown schema versions fail with `StateSchemaError`.

- [ ] **Step 1: Write failing state tests**

Create `tests/test_nautilus_state.py` with this complete content:

```python
from __future__ import annotations

import pytest

from polysignal_lab.nautilus_bridge.state import StateSchemaError, decode_state, encode_state, state_key


def test_state_key_uses_polysignal_strategy_version_format() -> None:
    assert state_key("ptb_diff") == "polysignal.ptb_diff.state.v1"


def test_encode_decode_state_round_trip_json_bytes() -> None:
    encoded = encode_state("late_consensus", {"accepted": {"BTC": 2}, "migration_reasons": []})

    assert set(encoded) == {"polysignal.late_consensus.state.v1"}
    assert isinstance(encoded["polysignal.late_consensus.state.v1"], bytes)
    assert decode_state("late_consensus", encoded) == {"accepted": {"BTC": 2}, "migration_reasons": []}


def test_decode_missing_state_returns_empty_payload_with_reason() -> None:
    decoded = decode_state("vwap_momentum", {})

    assert decoded == {"migration_reasons": ["missing polysignal.vwap_momentum.state.v1"]}


def test_decode_unknown_version_fails_closed() -> None:
    state = encode_state("dump_hedge", {"positions": {}}, version=2)

    with pytest.raises(StateSchemaError, match="Unsupported state schema"):
        decode_state("dump_hedge", state, version=1)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_state.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'polysignal_lab.nautilus_bridge.state'`.

- [ ] **Step 3: Implement versioned state helpers**

Create `src/polysignal_lab/nautilus_bridge/state.py` with this complete content:

```python
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class StateSchemaError(ValueError):
    pass


def state_key(strategy_name: str, version: int = 1) -> str:
    return f"polysignal.{strategy_name}.state.v{version}"


def encode_state(strategy_name: str, payload: Mapping[str, Any], version: int = 1) -> dict[str, bytes]:
    key = state_key(strategy_name, version)
    body = {"schema_version": version, "payload": payload}
    return {key: json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")}


def decode_state(strategy_name: str, state: Mapping[str, bytes], version: int = 1) -> dict[str, Any]:
    key = state_key(strategy_name, version)
    if key not in state:
        same_strategy_prefix = f"polysignal.{strategy_name}.state.v"
        unknown_keys = sorted(name for name in state if name.startswith(same_strategy_prefix))
        if unknown_keys:
            raise StateSchemaError(f"Unsupported state schema for {strategy_name}: {unknown_keys[0]}")
        return {"migration_reasons": [f"missing {key}"]}

    raw = json.loads(state[key].decode("utf-8"))
    if raw.get("schema_version") != version:
        raise StateSchemaError(f"Unsupported state schema for {strategy_name}: {raw.get('schema_version')}")
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise StateSchemaError(f"Invalid state payload for {strategy_name}")
    return payload
```

- [ ] **Step 4: Run state tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_state.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_bridge/state.py tests/test_nautilus_state.py
git commit -m "feat: add nautilus state contract"
```

---

### Task 7: Nautilus-Compatible Strategy Base and PTB Wrapper

**Files:**
- Create: `src/polysignal_lab/nautilus_bridge/strategy_base.py`
- Create: `src/polysignal_lab/nautilus_bridge/strategies/__init__.py`
- Create: `src/polysignal_lab/nautilus_bridge/strategies/ptb_diff.py`
- Test: `tests/test_nautilus_strategy_base.py`

**Interfaces:**
- Consumes: `AlphaCore`, `MarketViewAssembler`, `PTBDiffAlphaCore`, `OrderIntentSpec`, and state helpers.
- Produces:
  - `is_nautilus_available() -> bool`
  - `PolySignalNautilusStrategy(core: AlphaCore, assembler: MarketViewAssembler, condition_ids: Sequence[str], strategy_name: str)`
  - `PolySignalNautilusStrategy.on_save() -> dict[str, bytes]`
  - `PolySignalNautilusStrategy.on_load(state: dict[str, bytes]) -> None`
  - `PolySignalNautilusStrategy.evaluate_condition(condition_id: str) -> list[OrderIntentSpec]`
  - `PTBDiffNautilusStrategy(config: PTBDiffConfig, assembler: MarketViewAssembler, condition_ids: Sequence[str])`

- [ ] **Step 1: Write failing strategy wrapper tests**

Create `tests/test_nautilus_strategy_base.py` with this complete content:

```python
from __future__ import annotations

from datetime import UTC, datetime

from polysignal_lab.alpha.types import AlphaDecision, MarketView, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_bridge.state import state_key
from polysignal_lab.nautilus_bridge.strategy_base import PolySignalNautilusStrategy, is_nautilus_available
from polysignal_lab.nautilus_bridge.strategies.ptb_diff import PTBDiffNautilusStrategy
from polysignal_lab.strategies.config import PTBDiffConfig, PTBTriggerConfig


class FakeAssembler:
    def __init__(self, view: MarketView | None):
        self.view = view

    def build(self, condition_id: str) -> MarketView | None:
        return self.view


class FakeCore:
    def __init__(self, decisions: list[AlphaDecision]):
        self.decisions = decisions

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        return self.decisions


def _decision() -> AlphaDecision:
    return AlphaDecision(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.82,
        max_entry_price=0.92,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=("PTB_DIFF_THRESHOLD_OK",),
        metrics={"diff_usd": 120.0},
        order_intent=OrderIntentSpec(intent=OrderIntent.PASSIVE_GTD, expiry_seconds=45, pair_id="pair-1"),
        hedge_leg=False,
    )


def test_strategy_base_imports_without_nautilus_installed() -> None:
    assert isinstance(is_nautilus_available(), bool)


def test_strategy_base_returns_no_intents_when_view_not_ready() -> None:
    strategy = PolySignalNautilusStrategy(
        core=FakeCore([_decision()]),
        assembler=FakeAssembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
    )

    assert strategy.evaluate_condition("condition-btc-5m") == []
    assert strategy.submitted_intents == []


def test_strategy_base_records_decision_order_intents() -> None:
    strategy = PolySignalNautilusStrategy(
        core=FakeCore([_decision()]),
        assembler=FakeAssembler(object()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
    )

    intents = strategy.evaluate_condition("condition-btc-5m")

    assert intents == [OrderIntentSpec(intent=OrderIntent.PASSIVE_GTD, expiry_seconds=45, pair_id="pair-1")]
    assert strategy.submitted_intents == intents


def test_strategy_base_save_load_uses_versioned_bytes() -> None:
    strategy = PolySignalNautilusStrategy(
        core=FakeCore([]),
        assembler=FakeAssembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
    )
    strategy.accepted_state["condition-btc-5m"] = "accepted"

    state = strategy.on_save()
    restored = PolySignalNautilusStrategy(
        core=FakeCore([]),
        assembler=FakeAssembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
    )
    restored.on_load(state)

    assert set(state) == {state_key("ptb_diff")}
    assert restored.accepted_state == {"condition-btc-5m": "accepted"}


def test_ptb_nautilus_strategy_constructs_with_core_without_nautilus_dependency() -> None:
    config = PTBDiffConfig(
        triggers=[
            PTBTriggerConfig(
                name="test_up",
                side=Side.UP,
                min_diff_usd=80.0,
                max_token_price=0.92,
                min_token_price=0.80,
                min_seconds_to_close=0,
                max_seconds_to_close=120,
            )
        ]
    )

    strategy = PTBDiffNautilusStrategy(config=config, assembler=FakeAssembler(None), condition_ids=("condition-btc-5m",))

    assert strategy.strategy_name == "ptb_diff"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_strategy_base.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'polysignal_lab.nautilus_bridge.strategy_base'`.

- [ ] **Step 3: Implement strategy base with optional Nautilus import**

Create `src/polysignal_lab/nautilus_bridge/strategy_base.py` with this complete content:

```python
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from polysignal_lab.alpha.types import AlphaCore, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_bridge.state import decode_state, encode_state


def _load_strategy_base() -> type:
    try:
        from nautilus_trader.trading.strategy import Strategy
    except ModuleNotFoundError:
        return object
    return Strategy


def is_nautilus_available() -> bool:
    return _load_strategy_base() is not object


_NautilusBase = _load_strategy_base()


class PolySignalNautilusStrategy(_NautilusBase):
    def __init__(
        self,
        *,
        core: AlphaCore,
        assembler: MarketViewAssembler,
        condition_ids: Sequence[str],
        strategy_name: str,
    ) -> None:
        if _NautilusBase is not object:
            super().__init__()
        self.core = core
        self.assembler = assembler
        self.condition_ids = tuple(condition_ids)
        self.strategy_name = strategy_name
        self.submitted_intents: list[OrderIntentSpec] = []
        self.accepted_state: dict[str, str] = {}
        self.fill_state: dict[str, str] = {}
        self.cancel_state: dict[str, str] = {}
        self.migration_reasons: list[str] = []

    def on_start(self) -> None:
        for condition_id in self.condition_ids:
            self.evaluate_condition(condition_id)

    def evaluate_condition(self, condition_id: str) -> list[OrderIntentSpec]:
        view = self.assembler.build(condition_id)
        if view is None:
            return []
        intents = [
            decision.order_intent or OrderIntentSpec(intent=OrderIntent.PASSIVE_GTD)
            for decision in self.core.evaluate(view)
        ]
        self.submitted_intents.extend(intents)
        return intents

    def on_order_submitted(self, event: Any) -> None:
        self.accepted_state[str(getattr(event, "client_order_id", getattr(event, "id", "unknown")))] = "submitted"

    def on_order_accepted(self, event: Any) -> None:
        self.accepted_state[str(getattr(event, "client_order_id", getattr(event, "id", "unknown")))] = "accepted"

    def on_order_rejected(self, event: Any) -> None:
        self.cancel_state[str(getattr(event, "client_order_id", getattr(event, "id", "unknown")))] = "rejected"

    def on_order_canceled(self, event: Any) -> None:
        self.cancel_state[str(getattr(event, "client_order_id", getattr(event, "id", "unknown")))] = "canceled"

    def on_order_expired(self, event: Any) -> None:
        self.cancel_state[str(getattr(event, "client_order_id", getattr(event, "id", "unknown")))] = "expired"

    def on_order_filled(self, event: Any) -> None:
        self.fill_state[str(getattr(event, "client_order_id", getattr(event, "id", "unknown")))] = "filled"

    def on_save(self) -> dict[str, bytes]:
        return encode_state(
            self.strategy_name,
            {
                "accepted_state": self.accepted_state,
                "fill_state": self.fill_state,
                "cancel_state": self.cancel_state,
                "migration_reasons": self.migration_reasons,
            },
        )

    def on_load(self, state: dict[str, bytes]) -> None:
        payload = decode_state(self.strategy_name, state)
        self.accepted_state = dict(payload.get("accepted_state", {}))
        self.fill_state = dict(payload.get("fill_state", {}))
        self.cancel_state = dict(payload.get("cancel_state", {}))
        self.migration_reasons = list(payload.get("migration_reasons", []))
```

- [ ] **Step 4: Implement PTB bridge wrapper**

Create `src/polysignal_lab/nautilus_bridge/strategies/__init__.py` with this complete content:

```python
__all__: list[str] = []
```

Create `src/polysignal_lab/nautilus_bridge/strategies/ptb_diff.py` with this complete content:

```python
from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_bridge.strategy_base import PolySignalNautilusStrategy
from polysignal_lab.strategies.config import PTBDiffConfig


class PTBDiffNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(self, *, config: PTBDiffConfig, assembler: MarketViewAssembler, condition_ids: Sequence[str]) -> None:
        super().__init__(
            core=PTBDiffAlphaCore(config),
            assembler=assembler,
            condition_ids=condition_ids,
            strategy_name="ptb_diff",
        )
        self.config = config
```

- [ ] **Step 5: Run strategy wrapper tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_strategy_base.py -v
```

Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/polysignal_lab/nautilus_bridge/strategy_base.py src/polysignal_lab/nautilus_bridge/strategies/__init__.py src/polysignal_lab/nautilus_bridge/strategies/ptb_diff.py tests/test_nautilus_strategy_base.py
git commit -m "feat: add ptb nautilus strategy wrapper"
```

---

### Task 8: Default Safety Boundary Tests

**Files:**
- Create: `tests/test_nautilus_safety_boundary.py`
- Modify only if test forces it: bridge files from Tasks 4-7.

**Interfaces:**
- Consumes: source files under `src/polysignal_lab/nautilus_bridge` and existing `polysignal-safety-scan` command.
- Produces: regression tests that keep live execution symbols and credential env names out of default bridge source.

- [ ] **Step 1: Write failing-or-passing static safety tests before code adjustment**

Create `tests/test_nautilus_safety_boundary.py` with this complete content:

```python
from __future__ import annotations

from pathlib import Path

BRIDGE_ROOT = Path("src/polysignal_lab/nautilus_bridge")
FORBIDDEN_TEXT = (
    "PolymarketExecutionClient",
    "PolymarketLiveExecClientFactory",
    "exec_clients",
    "POLYMARKET_PK",
    "POLYMARKET_FUNDER",
    "POLYMARKET_API_KEY",
    "POLYMARKET_API_SECRET",
    "POLYMARKET_PASSPHRASE",
    "set_allowances.py",
    "create_api_key.py",
)


def test_nautilus_bridge_default_source_avoids_live_execution_symbols() -> None:
    findings: list[str] = []
    for path in BRIDGE_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_TEXT:
            if forbidden in text:
                findings.append(f"{path}:{forbidden}")

    assert findings == []
```

- [ ] **Step 2: Run static safety test**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_safety_boundary.py -v
```

Expected: pass. If it fails, remove the reported text from default bridge source and rerun the command until it passes.

- [ ] **Step 3: Run project safety scanner**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run polysignal-safety-scan .
```

Expected: `Safety scan passed`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_nautilus_safety_boundary.py src/polysignal_lab/nautilus_bridge
git commit -m "test: guard nautilus bridge safety boundary"
```

---

### Task 9: Bridge Environment Verification and Final Runtime Check

**Files:**
- Modify: `docs/NAUTILUS_BRIDGE_BOUNDARY.md`
- No production source changes unless verification exposes a concrete defect.

**Interfaces:**
- Consumes: optional dependency from Task 1 and bridge package from Tasks 4-7.
- Produces: recorded verification commands and final proof that default runtime still works.

- [ ] **Step 1: Add explicit verification log section**

Modify `docs/NAUTILUS_BRIDGE_BOUNDARY.md` by appending this section:

````markdown
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

After Docker rebuild, verify dashboard health with a cache-busted URL:

```text
http://127.0.0.1:8081/health?fresh=nautilus_bridge
```
````

- [ ] **Step 2: Run focused Python 3.11 tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_dependency_boundary.py tests/test_alpha_types.py tests/test_alpha_ptb_diff.py tests/test_nautilus_market_registry.py tests/test_nautilus_external_data.py tests/test_nautilus_market_view_assembler.py tests/test_nautilus_state.py tests/test_nautilus_strategy_base.py tests/test_nautilus_safety_boundary.py tests/test_ptb_diff.py -v
```

Expected: all selected tests pass.

- [ ] **Step 3: Run import and safety checks**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -c "import polysignal_lab"
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run polysignal-safety-scan .
```

Expected: first command exits 0 with no output; second command prints `Safety scan passed`.

- [ ] **Step 4: Run bridge environment commands in Python 3.12+ environment**

Run:

```bash
ldd --version
uv sync --extra nautilus --python 3.12
uv run python -c "import nautilus_trader.adapters.polymarket"
```

Expected:

- `ldd --version` first line reports glibc 2.35 or newer.
- `uv sync --extra nautilus --python 3.12` completes without resolver or build failure.
- `uv run python -c "import nautilus_trader.adapters.polymarket"` exits 0.

If ARM64 wheel or source build fails, stop bridge execution and record the exact resolver/build error in the commit notes. The default Python 3.11 runtime still must pass Step 2 and Step 3.

- [ ] **Step 5: Rebuild formal Docker runtime**

Run:

```bash
docker compose up -d --build --force-recreate
docker compose ps
```

Expected: all configured services are running or healthy according to `docker compose ps`.

- [ ] **Step 6: Verify cache-busted health endpoint**

Open or read:

```text
http://127.0.0.1:8081/health?fresh=nautilus_bridge
```

Expected: response is current health JSON or dashboard health page, and no bridge import error appears in service logs.

- [ ] **Step 7: Commit verification documentation**

```bash
git add docs/NAUTILUS_BRIDGE_BOUNDARY.md
git commit -m "docs: record nautilus bridge verification"
```

---

## Self-Review

### Spec Coverage

- Architecture layering: Tasks 2-7 create `alpha/` and `nautilus_bridge/` boundaries.
- Platform boundary: Task 1 adds optional dependency and Task 9 verifies Python 3.11 default import plus Python 3.12 bridge import.
- Pilot migration: Task 3 extracts `PTBDiffAlphaCore`, preserves legacy wrapper, and verifies equivalence.
- Market pairing: Task 4 implements binary YES/NO registry by condition and token.
- Sidecar data: Task 4 implements spot/PTB sidecar; Task 5 injects it into `MarketView`.
- MarketViewAssembler readiness: Task 5 returns `None` when required leg or sidecar data is missing.
- Nautilus wrapper: Task 7 adds `PolySignalNautilusStrategy` and `PTBDiffNautilusStrategy` with callback/state methods and intent mapping.
- Stateful contract: Task 6 defines versioned JSON bytes save/load helpers and fail-closed unknown schema behavior.
- Safety boundary: Task 8 guards live execution symbols and credential env names; Task 9 runs project safety scanner.
- Default runtime: Tasks 1, 8, and 9 prove default import and Docker runtime do not require Nautilus.

### Placeholder Scan

No task uses unspecified file paths. Each code-changing step includes concrete code. No step asks the implementer to invent validation, unspecified tests, or missing interfaces.

### Type Consistency

The plan defines `MarketView`, `OrderIntentSpec`, `AlphaDecision`, `PTBDiffAlphaCore`, `MarketPairMeta`, `ExternalDataSidecar`, `MarketViewAssembler`, `encode_state`, `decode_state`, `PolySignalNautilusStrategy`, and `PTBDiffNautilusStrategy` before any later task consumes them. Method names and return types match across tests and implementation snippets.
