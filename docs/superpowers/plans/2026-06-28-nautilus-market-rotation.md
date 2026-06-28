# Nautilus 5m/15m Market Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让默认 Nautilus paper runtime 在不重启 `TradingNode` 的前提下，持续跟随 Polymarket crypto Up/Down 5m/15m 市场轮换，并让现有 native strategies 动态切到新市场。

**Architecture:** 新增 `MarketRotationActor`，在 Nautilus node 内周期执行 market discovery，发布不可变 `PolySignalMarketUniverseData` epoch，并为进入 active set 的市场发布 metadata / PTB。`PolySignalNativeStrategy` 增加 active condition set 与幂等订阅状态，对 `PolySignalMarketUniverseData` 动态订阅/退订 instruments，同时继续用 Nautilus callbacks 驱动 alpha core。`build_trading_node()` 与 `build_paper_trading_node_config()` 负责把 rotation actor 和 Polymarket adapter dynamic auto-load 配好，保证新 instrument 不需要重建 node。

**Tech Stack:** Python 3.11 base project, optional `nautilus_trader[polymarket]==1.229.0` on Python >= 3.12, Pydantic settings, existing `MarketUniverseService`, `PolymarketMarketRegistry`, `ExternalDataSidecar`, Nautilus `Actor` / `Strategy`, pytest, basedpyright, uv.

## Global Constraints

- Default runtime must not use live Polymarket execution.
- Default runtime uses real Polymarket market data plus Nautilus sandbox execution.
- Do not change the three alpha algorithms (`vwap_momentum`, `late_consensus`, `ptb_diff`).
- Do not reintroduce `PaperWallet` or a second position ledger.
- Do not restart `TradingNode` for market rotation.
- Market rotation scope is only crypto Up/Down `assets × timeframes` from config.
- Every new published message must be immutable; publish a new epoch payload instead of mutating old payloads.
- Keep Nautilus optional at import time; default `polysignal_lab` import must still work without Nautilus installed.
- All verification commands use `uv run ...`.
- Before final completion run `uv run python -m py_compile` on changed Python modules.
- Before final completion run focused `uv run pytest ...` and `uv run basedpyright ...` over the touched runtime files/tests.

---

## File Structure

- Create `src/polysignal_lab/nautilus_runtime/market_rotation.py`
  - Owns periodic discovery, active-market diffing, epoch publication, entered/exited bookkeeping, RTDS spot fan-out over the current active market set, and PTB publication for active markets.

- Modify `src/polysignal_lab/config.py`
  - Adds `NautilusMarketRotationConfig` under `runtime.nautilus` so the runtime has an explicit rotation contract.

- Modify `src/polysignal_lab/nautilus_runtime/market_data.py`
  - Adds immutable `PolySignalMarketUniverseData` and registers it with Nautilus serialization.

- Modify `src/polysignal_lab/nautilus_runtime/native_strategy.py`
  - Adds active condition gating, idempotent instrument subscription state, `PolySignalMarketUniverseData` handling, and best-effort unsubscribe helpers.

- Modify `src/polysignal_lab/nautilus_runtime/trading_node.py`
  - Configures `PolymarketDataClientConfig` for dynamic instrument auto-load and optional adapter-side new-market events.

- Modify `src/polysignal_lab/nautilus_runtime/node.py`
  - Wires `MarketRotationActor` into `TradingNode`, passes scheduler `market_universe` into runtime assembly, and stops registering the static startup-only sidecar actor.

- Modify `src/polysignal_lab/nautilus_runtime/sidecar_data.py`
  - Keep `SidecarDataActor` as the shared publisher helper and add `publish_market_universe()` so rotation epochs use the same `DataType(...)` path as spot / PTB / metadata.

- Modify `config/signal_bot.yaml` and `config/signal_bot.lab.yaml`
  - Add the `runtime.nautilus.market_rotation` section with paper-safe defaults.

- Create `tests/test_nautilus_market_rotation.py`
  - Covers `PolySignalMarketUniverseData` round-trip, `MarketRotationActor` epoch publication, entered/exited diffs, and failure retention of last-good state.

- Modify `tests/test_nautilus_strategy_base.py`
  - Covers dynamic native-strategy subscription, exited-market gating, and best-effort unsubscribe behavior.

- Modify `tests/test_nautilus_trading_node_runtime.py`
  - Verifies Polymarket dynamic instrument auto-load config and adapter-side event toggle wiring.

- Modify `tests/test_nautilus_node.py`
  - Verifies `build_trading_node()` registers the rotation actor and passes scheduler market-universe state through runtime assembly.

- Modify `tests/test_nautilus_full_paper_runtime_smoke.py`
  - Adds a focused in-process rotation smoke test proving one strategy instance survives `A -> B` market rotation without node rebuild.

- Modify `tests/test_nautilus_runtime_config.py`
  - Verifies model defaults and production YAML exposure of `runtime.nautilus.market_rotation`.

---

### Task 1: Rotation config and immutable universe payload

**Files:**
- Modify: `src/polysignal_lab/config.py`
- Modify: `src/polysignal_lab/nautilus_runtime/market_data.py`
- Modify: `config/signal_bot.yaml`
- Modify: `config/signal_bot.lab.yaml`
- Modify: `tests/test_nautilus_runtime_config.py`
- Create: `tests/test_nautilus_market_rotation.py`

**Interfaces:**
- Consumes: existing `NautilusRuntimeConfig`, `_PolySignalDataBase`, `register_polysignal_data_types()`.
- Produces:
  - `class NautilusMarketRotationConfig(BaseModel)`
  - `NautilusRuntimeConfig.market_rotation: NautilusMarketRotationConfig`
  - `class PolySignalMarketUniverseData(_PolySignalDataBase)`

- [ ] **Step 1: Write failing tests for rotation config defaults and universe payload round-trip**

Add to `tests/test_nautilus_runtime_config.py`:

```python
def test_nautilus_market_rotation_defaults_are_enabled() -> None:
    settings = Settings()

    cfg = settings.runtime.nautilus.market_rotation
    assert cfg.enabled is True
    assert cfg.interval_sec == 10
    assert cfg.include_next_periods == 1
    assert cfg.stale_grace_sec == 5
    assert cfg.unsubscribe_exited is True
    assert cfg.allow_adapter_new_market_events is False


def test_production_yaml_declares_market_rotation_section() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")

    cfg = settings.runtime.nautilus.market_rotation
    assert cfg.enabled is True
    assert cfg.interval_sec == 10
    assert cfg.include_next_periods == 1
    assert cfg.stale_grace_sec == 5
    assert cfg.unsubscribe_exited is True
```

Create `tests/test_nautilus_market_rotation.py`:

```python
from __future__ import annotations

from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData


def test_market_universe_data_round_trips() -> None:
    payload = PolySignalMarketUniverseData(
        epoch=2,
        active_condition_ids=("c1", "c2"),
        entered_condition_ids=("c2",),
        exited_condition_ids=("c0",),
        condition_to_up_token={"c1": "up-1", "c2": "up-2"},
        condition_to_down_token={"c1": "down-1", "c2": "down-2"},
        condition_to_asset={"c1": "BTC", "c2": "ETH"},
        condition_to_timeframe={"c1": "5m", "c2": "15m"},
        ts_event=11,
        ts_init=12,
    )

    restored = PolySignalMarketUniverseData.from_dict(payload.to_dict())

    assert restored == payload
    assert restored.active_condition_ids == ("c1", "c2")
    assert restored.condition_to_up_token["c2"] == "up-2"
    assert restored.condition_to_timeframe["c1"] == "5m"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_nautilus_runtime_config.py::test_nautilus_market_rotation_defaults_are_enabled \
  tests/test_nautilus_runtime_config.py::test_production_yaml_declares_market_rotation_section \
  tests/test_nautilus_market_rotation.py::test_market_universe_data_round_trips -q
```

Expected: FAIL because `market_rotation` does not exist on `NautilusRuntimeConfig` and `PolySignalMarketUniverseData` is not defined.

- [ ] **Step 3: Implement the config model, YAML defaults, and immutable payload**

Add this model near the other Nautilus runtime config models in `src/polysignal_lab/config.py`:

```python
class NautilusMarketRotationConfig(BaseModel):
    enabled: bool = True
    interval_sec: int = 10
    include_next_periods: int = 1
    stale_grace_sec: int = 5
    unsubscribe_exited: bool = True
    allow_adapter_new_market_events: bool = False


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
    market_rotation: NautilusMarketRotationConfig = Field(default_factory=NautilusMarketRotationConfig)
```

Add the payload to `src/polysignal_lab/nautilus_runtime/market_data.py`:

```python
from types import MappingProxyType


def _as_str_tuple(values: object) -> tuple[str, ...]:
    if isinstance(values, tuple):
        return tuple(str(value) for value in values)
    if isinstance(values, list):
        return tuple(str(value) for value in values)
    return (str(values),)


def _as_str_map(values: object) -> MappingProxyType[str, str]:
    mapping = dict(values) if isinstance(values, dict) else dict(values)
    return MappingProxyType({str(key): str(value) for key, value in mapping.items()})


class PolySignalMarketUniverseData(_PolySignalDataBase):
    __slots__ = (
        "epoch",
        "active_condition_ids",
        "entered_condition_ids",
        "exited_condition_ids",
        "condition_to_up_token",
        "condition_to_down_token",
        "condition_to_asset",
        "condition_to_timeframe",
    )
    _fields = (
        "epoch",
        "active_condition_ids",
        "entered_condition_ids",
        "exited_condition_ids",
        "condition_to_up_token",
        "condition_to_down_token",
        "condition_to_asset",
        "condition_to_timeframe",
    )

    def __init__(
        self,
        *,
        epoch: int,
        active_condition_ids: tuple[str, ...],
        entered_condition_ids: tuple[str, ...],
        exited_condition_ids: tuple[str, ...],
        condition_to_up_token: dict[str, str],
        condition_to_down_token: dict[str, str],
        condition_to_asset: dict[str, str],
        condition_to_timeframe: dict[str, str],
        ts_event: int,
        ts_init: int,
    ) -> None:
        self.epoch = int(epoch)
        self.active_condition_ids = tuple(active_condition_ids)
        self.entered_condition_ids = tuple(entered_condition_ids)
        self.exited_condition_ids = tuple(exited_condition_ids)
        self.condition_to_up_token = MappingProxyType(dict(condition_to_up_token))
        self.condition_to_down_token = MappingProxyType(dict(condition_to_down_token))
        self.condition_to_asset = MappingProxyType(dict(condition_to_asset))
        self.condition_to_timeframe = MappingProxyType(dict(condition_to_timeframe))
        self._ts_event = int(ts_event)
        self._ts_init = int(ts_init)

    def to_dict(self) -> dict[str, object]:
        return {
            "epoch": self.epoch,
            "active_condition_ids": list(self.active_condition_ids),
            "entered_condition_ids": list(self.entered_condition_ids),
            "exited_condition_ids": list(self.exited_condition_ids),
            "condition_to_up_token": dict(self.condition_to_up_token),
            "condition_to_down_token": dict(self.condition_to_down_token),
            "condition_to_asset": dict(self.condition_to_asset),
            "condition_to_timeframe": dict(self.condition_to_timeframe),
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "PolySignalMarketUniverseData":
        return cls(
            epoch=_as_int(d["epoch"]),
            active_condition_ids=_as_str_tuple(d["active_condition_ids"]),
            entered_condition_ids=_as_str_tuple(d["entered_condition_ids"]),
            exited_condition_ids=_as_str_tuple(d["exited_condition_ids"]),
            condition_to_up_token=dict(d["condition_to_up_token"]),
            condition_to_down_token=dict(d["condition_to_down_token"]),
            condition_to_asset=dict(d["condition_to_asset"]),
            condition_to_timeframe=dict(d["condition_to_timeframe"]),
            ts_event=_as_int(d["ts_event"]),
            ts_init=_as_int(d["ts_init"]),
        )
```

Register it in `register_polysignal_data_types()`:

```python
register_serializable_type(
    PolySignalMarketUniverseData,
    PolySignalMarketUniverseData.to_dict,
    PolySignalMarketUniverseData.from_dict,
)
```

Add this block to both `config/signal_bot.yaml` and `config/signal_bot.lab.yaml` under `runtime.nautilus`:

```yaml
    market_rotation:
      enabled: true
      interval_sec: 10
      include_next_periods: 1
      stale_grace_sec: 5
      unsubscribe_exited: true
      allow_adapter_new_market_events: false
```

- [ ] **Step 4: Run the focused tests again**

Run:

```bash
uv run pytest \
  tests/test_nautilus_runtime_config.py::test_nautilus_market_rotation_defaults_are_enabled \
  tests/test_nautilus_runtime_config.py::test_production_yaml_declares_market_rotation_section \
  tests/test_nautilus_market_rotation.py::test_market_universe_data_round_trips -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  src/polysignal_lab/config.py \
  src/polysignal_lab/nautilus_runtime/market_data.py \
  config/signal_bot.yaml \
  config/signal_bot.lab.yaml \
  tests/test_nautilus_runtime_config.py \
  tests/test_nautilus_market_rotation.py
git commit -m "feat: add nautilus market rotation config"
```

---

### Task 2: MarketRotationActor publishes active-market epochs

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/market_rotation.py`
- Modify: `src/polysignal_lab/nautilus_runtime/sidecar_data.py`
- Modify: `tests/test_nautilus_market_rotation.py`
- Reference: `src/polysignal_lab/app/services/market_universe_service.py`

**Interfaces:**
- Consumes: `Settings`, `MarketUniverseService`, `PolymarketMarketRegistry`, `ExternalDataSidecar`, `SidecarDataActor`, `PolySignalMarketMetaData`, `PolySignalMarketUniverseData`.
- Produces:
  - `runtime_market_rotation_actor_type(nautilus_base: type[object] | None, config_factory: Callable[[], object] | None) -> type[MarketRotationActor]`
  - `class MarketRotationActor`
  - `MarketRotationActor.refresh_once() -> Awaitable[tuple[Market, ...]]`
  - `MarketRotationActor.active_markets() -> tuple[Market, ...]`

- [ ] **Step 1: Write failing tests for epoch publication and last-good retention**

Append to `tests/test_nautilus_market_rotation.py`:

```python
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from polysignal_lab.config import Settings
from polysignal_lab.data.price_to_beat_provider import PriceToBeatResult
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketMetaData, PolySignalMarketUniverseData
from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor


def _market(condition_id: str, *, asset: str = "BTC", timeframe: str = "5m") -> Market:
    return Market(
        market_id=condition_id,
        market_slug=f"{asset.lower()}-updown-{timeframe}-{condition_id}",
        condition_id=condition_id,
        asset=asset,
        timeframe=timeframe,
        start_ts=datetime(2026, 6, 28, tzinfo=UTC),
        end_ts=datetime(2026, 6, 28, tzinfo=UTC) + timedelta(minutes=5),
        outcome_tokens=[
            OutcomeToken(token_id=f"{condition_id}-up", side=Side.UP, outcome_name="Up", market_id=condition_id),
            OutcomeToken(token_id=f"{condition_id}-down", side=Side.DOWN, outcome_name="Down", market_id=condition_id),
        ],
    )


class _Universe:
    def __init__(self, rounds: list[list[Market] | Exception]) -> None:
        self.rounds = rounds
        self.calls = 0

    async def refresh_once(self) -> list[Market]:
        result = self.rounds[self.calls]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


class _DummyTask:
    def cancel(self) -> None:
        return None


def test_market_rotation_actor_initial_publish_and_diff(monkeypatch) -> None:
    published: list[object] = []
    created: list[object] = []
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    universe = _Universe([
        [_market("condition-a")],
        [_market("condition-a"), _market("condition-b")],
    ])
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(_market("condition-a"),),
        market_universe=universe,
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )
    actor.publish_data = lambda data_type, data: published.append(data)

    async def fake_ptb(market: Market) -> PriceToBeatResult:
        return PriceToBeatResult(
            value=100000.0,
            source="anchor",
            verified=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            from_anchor_service=True,
        )

    monkeypatch.setattr(actor.ptb_provider, "get", fake_ptb)
    monkeypatch.setattr("asyncio.create_task", lambda coro: created.append(coro) or _DummyTask())

    actor.on_start()
    asyncio.run(actor.refresh_once())

    epochs = [item for item in published if isinstance(item, PolySignalMarketUniverseData)]
    metas = [item for item in published if isinstance(item, PolySignalMarketMetaData)]

    assert epochs[0].epoch == 1
    assert epochs[-1].epoch == 2
    assert epochs[-1].entered_condition_ids == ("condition-b",)
    assert epochs[-1].exited_condition_ids == ()
    assert {meta.condition_id for meta in metas} == {"condition-a", "condition-b"}


def test_market_rotation_actor_keeps_last_good_state_on_failure(monkeypatch) -> None:
    published: list[object] = []
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    universe = _Universe([
        [_market("condition-a")],
        RuntimeError("gamma down"),
    ])
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(_market("condition-a"),),
        market_universe=universe,
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )
    actor.publish_data = lambda data_type, data: published.append(data)
    async def fake_none_ptb(market: Market) -> PriceToBeatResult:
        _ = market
        return PriceToBeatResult(value=None, source="gamma", verified=False, anchor_source=None, anchor_lag_ms=None, from_anchor_service=False)
    monkeypatch.setattr(actor.ptb_provider, "get", fake_none_ptb)
    monkeypatch.setattr("asyncio.create_task", lambda coro: _DummyTask())

    actor.on_start()

    first_epoch = [item for item in published if isinstance(item, PolySignalMarketUniverseData)][-1]
    try:
        asyncio.run(actor.refresh_once())
    except RuntimeError:
        pass

    assert actor.active_markets()[0].condition_id == "condition-a"
    assert [item for item in published if isinstance(item, PolySignalMarketUniverseData)][-1] == first_epoch
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_nautilus_market_rotation.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `polysignal_lab.nautilus_runtime.market_rotation`.

- [ ] **Step 3: Implement the rotation actor with epoch diffing**

Create `src/polysignal_lab/nautilus_runtime/market_rotation.py`:

```python
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from types import new_class
from typing import Awaitable, Callable, Protocol, cast

from polysignal_lab.config import Settings
from polysignal_lab.data.anchor_price_service import AnchorPriceService, AnchorPriceStore
from polysignal_lab.data.polymarket_rtds_ws import PolymarketRtdsPriceFeed
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import SpotRegistry
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketMetaData, PolySignalMarketUniverseData, register_polysignal_data_types
from polysignal_lab.nautilus_runtime.sidecar_data import SidecarDataActor

logger = logging.getLogger("polysignal_lab.nautilus.market_rotation")


class _MarketUniverse(Protocol):
    async def refresh_once(self) -> list[Market]: ...


class MarketRotationActor:
    def __init__(
        self,
        *,
        settings: Settings,
        startup_markets: tuple[Market, ...],
        market_universe: _MarketUniverse,
        registry: PolymarketMarketRegistry,
        sidecar: ExternalDataSidecar,
        anchor_store: AnchorPriceStore | None = None,
        health: object | None = None,
    ) -> None:
        self.settings = settings
        self.market_universe = market_universe
        self.registry = registry
        self.sidecar = sidecar
        self.health = health
        self.publisher = SidecarDataActor(publisher=self, sidecar=sidecar, registry=registry)
        self.spots = SpotRegistry()
        self.anchor_prices = AnchorPriceService(self.spots, anchor_store) if anchor_store is not None else None
        self.ptb_provider = PriceToBeatProvider(
            use_crypto_price_api=settings.data.polymarket.use_crypto_price_api,
            anchor_store=anchor_store,
        )
        self.rtds_feed = PolymarketRtdsPriceFeed(self.spots, settings.data.polymarket, on_spot=self._on_spot)
        self._active_markets: tuple[Market, ...] = tuple(startup_markets)
        self._active_by_condition: dict[str, Market] = {market.condition_id: market for market in startup_markets if market.condition_id}
        self._epoch = 0
        self._refresh_task: object | None = None
        self._rtds_task: object | None = None

    def publish_data(self, data_type: object, data: object) -> None:
        base_publish = getattr(super(MarketRotationActor, self), "publish_data", None)
        if callable(base_publish):
            base_publish(data_type, data)

    def active_markets(self) -> tuple[Market, ...]:
        return self._active_markets

    def on_start(self) -> None:
        register_polysignal_data_types()
        self._publish_epoch(self._active_markets, previous={})
        if self.settings.runtime.nautilus.sidecar.spot_source == "polymarket_rtds":
            self._rtds_task = asyncio.create_task(self.rtds_feed.run())
        if self.settings.runtime.nautilus.market_rotation.enabled:
            self._refresh_task = asyncio.create_task(self._run_loop())

    def on_stop(self) -> None:
        self.rtds_feed.stop()
        for task in (self._refresh_task, self._rtds_task):
            if task is not None and hasattr(task, "cancel"):
                task.cancel()

    async def _run_loop(self) -> None:
        interval = max(int(self.settings.runtime.nautilus.market_rotation.interval_sec), 1)
        while True:
            await asyncio.sleep(interval)
            await self.refresh_once()

    async def refresh_once(self) -> tuple[Market, ...]:
        latest = tuple(await self.market_universe.refresh_once())
        previous = dict(self._active_by_condition)
        self._publish_epoch(latest, previous=previous)
        return latest

    def _publish_epoch(self, markets: tuple[Market, ...], *, previous: dict[str, Market]) -> None:
        by_condition = {market.condition_id: market for market in markets if market.condition_id}
        entered = tuple(sorted(set(by_condition) - set(previous)))
        exited = tuple(sorted(set(previous) - set(by_condition)))
        active = tuple(sorted(by_condition))
        if self._epoch > 0 and active == tuple(sorted(previous)):
            self._active_markets = markets
            self._active_by_condition = by_condition
            return
        self._epoch += 1
        self._active_markets = markets
        self._active_by_condition = by_condition
        now = _timestamp_ns(datetime.now(UTC))
        payload = PolySignalMarketUniverseData(
            epoch=self._epoch,
            active_condition_ids=active,
            entered_condition_ids=entered if previous else active,
            exited_condition_ids=exited,
            condition_to_up_token={cid: market.token_for(Side.UP).token_id for cid, market in by_condition.items()},
            condition_to_down_token={cid: market.token_for(Side.DOWN).token_id for cid, market in by_condition.items()},
            condition_to_asset={cid: market.asset for cid, market in by_condition.items()},
            condition_to_timeframe={cid: market.timeframe for cid, market in by_condition.items()},
            ts_event=now,
            ts_init=now,
        )
        self.publisher.publish_market_universe(payload)
        for condition_id in entered if previous else active:
            market = by_condition[condition_id]
            self.publisher.publish_market_metadata(_market_metadata(market, ts_now=now))
            asyncio.create_task(self._publish_price_to_beat(market))

    def _on_spot(self, spot: SpotPrice) -> None:
        self.publisher.publish_spot(
            asset=spot.asset,
            symbol=spot.symbol,
            price=spot.price,
            source=spot.source,
            freshness_ms=spot.freshness_ms(),
            ts_event=_timestamp_ns(spot.event_time),
            ts_init=_timestamp_ns(spot.received_at),
        )
        if self.anchor_prices is None:
            return
        for market in self._active_markets:
            if market.asset.upper() != spot.asset.upper():
                continue
            self.anchor_prices.capture_for_market(market)
            asyncio.create_task(self._publish_price_to_beat(market))
```

Add this import and method to `src/polysignal_lab/nautilus_runtime/sidecar_data.py` so the rotation actor reuses the same publishing path as the existing custom data:
```python
from polysignal_lab.nautilus_runtime.market_data import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
    register_polysignal_data_types,
)


class SidecarDataActor:
    def publish_market_universe(self, data: PolySignalMarketUniverseData) -> None:
        self.publisher.publish_data(_data_type(PolySignalMarketUniverseData), data)
```

Add these concrete helpers to `src/polysignal_lab/nautilus_runtime/market_rotation.py`:
```python
    async def _publish_price_to_beat(self, market: Market) -> None:
        result = await self.ptb_provider.get(market)
        if result.value is None:
            return
        now = datetime.now(UTC)
        self.publisher.publish_price_to_beat(
            condition_id=market.condition_id,
            value=result.value,
            source=result.source,
            verified=result.verified,
            from_anchor_service=result.from_anchor_service,
            anchor_source=result.anchor_source,
            anchor_lag_ms=result.anchor_lag_ms,
            ts_event=_timestamp_ns(now),
            ts_init=_timestamp_ns(now),
        )


def _market_metadata(market: Market, *, ts_now: int) -> PolySignalMarketMetaData:
    return PolySignalMarketMetaData(
        market_id=market.market_id,
        market_slug=market.market_slug,
        condition_id=market.condition_id,
        asset=market.asset,
        timeframe=market.timeframe,
        start_ts_ns=_timestamp_ns(market.start_ts) if market.start_ts is not None else None,
        end_ts_ns=_timestamp_ns(market.end_ts) if market.end_ts is not None else None,
        up_token_id=market.token_for(Side.UP).token_id,
        down_token_id=market.token_for(Side.DOWN).token_id,
        ts_event=ts_now,
        ts_init=ts_now,
    )


def _timestamp_ns(value: datetime | None) -> int:
    if value is None:
        return 0
    return int(value.timestamp() * 1_000_000_000)


def runtime_market_rotation_actor_type(
    nautilus_base: type[object] | None,
    config_factory: Callable[[], object] | None,
) -> type[MarketRotationActor]:
    if nautilus_base is None:
        return MarketRotationActor

    def exec_body(namespace: dict[str, object]) -> None:
        def __init__(
            self: MarketRotationActor,
            *,
            settings: Settings,
            startup_markets: tuple[Market, ...],
            market_universe: _MarketUniverse,
            registry: PolymarketMarketRegistry,
            sidecar: ExternalDataSidecar,
            anchor_store: AnchorPriceStore | None = None,
            health: object | None = None,
        ) -> None:
            base_init = cast(Callable[..., None], nautilus_base.__init__)
            if config_factory is None:
                base_init(self)
            else:
                base_init(self, config=config_factory())
            MarketRotationActor.__init__(
                self,
                settings=settings,
                startup_markets=startup_markets,
                market_universe=market_universe,
                registry=registry,
                sidecar=sidecar,
                anchor_store=anchor_store,
                health=health,
            )

        namespace["__init__"] = __init__

    actor_cls = new_class(
        "NautilusMarketRotationActor",
        (MarketRotationActor, nautilus_base),
        exec_body=exec_body,
    )
    return cast(type[MarketRotationActor], actor_cls)
```

- [ ] **Step 4: Run the actor tests again**

Run:

```bash
uv run pytest tests/test_nautilus_market_rotation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  src/polysignal_lab/nautilus_runtime/market_rotation.py \
  tests/test_nautilus_market_rotation.py
git commit -m "feat: add nautilus market rotation actor"
```

---

### Task 3: Native strategy dynamic subscriptions and exited-market gate

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Modify: `tests/test_nautilus_strategy_base.py`

**Interfaces:**
- Consumes: `PolySignalMarketMetaData`, `PolySignalMarketUniverseData`, `PolymarketMarketRegistry`, existing order-book/trade callbacks.
- Produces:
  - `class MarketSubscriptionState`
  - `PolySignalNativeStrategy._active_condition_ids: set[str]`
  - `PolySignalNativeStrategy.unsubscribe_exited: bool`
  - `PolySignalNativeStrategy._sync_market_subscriptions(active_condition_ids: Iterable[str], *, unsubscribe: bool) -> None`

- [ ] **Step 1: Write failing tests for dynamic subscribe/unsubscribe behavior**

Append to `tests/test_nautilus_strategy_base.py`:

```python
def test_native_strategy_universe_update_subscribes_entered_market_once() -> None:
    from polysignal_lab.nautilus_bridge.market_registry import InstrumentTokenMeta, MarketPairMeta, PolymarketMarketRegistry
    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketMetaData, PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    registry = PolymarketMarketRegistry()
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
    )

    strategy.on_data(
        PolySignalMarketMetaData(
            market_id="condition-b",
            market_slug="btc-updown-5m-b",
            condition_id="condition-b",
            asset="BTC",
            timeframe="5m",
            start_ts_ns=1,
            end_ts_ns=2,
            up_token_id="up-b",
            down_token_id="down-b",
            ts_event=1,
            ts_init=1,
        )
    )
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=2,
            active_condition_ids=("condition-a", "condition-b"),
            entered_condition_ids=("condition-b",),
            exited_condition_ids=(),
            condition_to_up_token={"condition-a": "up-a", "condition-b": "up-b"},
            condition_to_down_token={"condition-a": "down-a", "condition-b": "down-b"},
            condition_to_asset={"condition-a": "BTC", "condition-b": "BTC"},
            condition_to_timeframe={"condition-a": "5m", "condition-b": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=2,
            active_condition_ids=("condition-a", "condition-b"),
            entered_condition_ids=("condition-b",),
            exited_condition_ids=(),
            condition_to_up_token={"condition-a": "up-a", "condition-b": "up-b"},
            condition_to_down_token={"condition-a": "down-a", "condition-b": "down-b"},
            condition_to_asset={"condition-a": "BTC", "condition-b": "BTC"},
            condition_to_timeframe={"condition-a": "5m", "condition-b": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_subscriptions.count("up-b.POLYMARKET") == 1
    assert strategy.trade_subscriptions.count("down-b.POLYMARKET") == 1


def test_native_strategy_exited_market_is_gated_even_if_late_tick_arrives() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    seen: list[str] = []

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

        def _handle_decision(self, decision, view):
            seen.append(view.condition_id)

    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(_view(condition_id="condition-a")),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
    )
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=("condition-b",),
            entered_condition_ids=("condition-b",),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={"condition-b": "up-b"},
            condition_to_down_token={"condition-b": "down-b"},
            condition_to_asset={"condition-b": "BTC"},
            condition_to_timeframe={"condition-b": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    strategy.evaluate_condition("condition-a")

    assert seen == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_nautilus_strategy_base.py::test_native_strategy_universe_update_subscribes_entered_market_once \
  tests/test_nautilus_strategy_base.py::test_native_strategy_exited_market_is_gated_even_if_late_tick_arrives -q
```

Expected: FAIL because `PolySignalNativeStrategy` does not handle `PolySignalMarketUniverseData` and still evaluates inactive startup conditions.

- [ ] **Step 3: Implement active-set tracking and best-effort unsubscribe**

Add this dataclass near the top of `src/polysignal_lab/nautilus_runtime/native_strategy.py`:

```python
from dataclasses import dataclass, field


@dataclass(slots=True)
class MarketSubscriptionState:
    subscribed_condition_ids: set[str] = field(default_factory=set)
    subscribed_instrument_ids: set[str] = field(default_factory=set)

    def remember(self, condition_id: str, instrument_ids: tuple[str, ...]) -> tuple[str, ...]:
        fresh = tuple(instrument_id for instrument_id in instrument_ids if instrument_id not in self.subscribed_instrument_ids)
        self.subscribed_condition_ids.add(condition_id)
        self.subscribed_instrument_ids.update(fresh)
        return fresh

    def forget(self, condition_id: str, instrument_ids: tuple[str, ...]) -> tuple[str, ...]:
        if condition_id in self.subscribed_condition_ids:
            self.subscribed_condition_ids.remove(condition_id)
        removed = tuple(instrument_id for instrument_id in instrument_ids if instrument_id in self.subscribed_instrument_ids)
        for instrument_id in removed:
            self.subscribed_instrument_ids.discard(instrument_id)
        return removed
```

Update `PolySignalNativeStrategy.__init__`:

```python
self._startup_condition_ids = tuple(condition_ids)
self._active_condition_ids: set[str] = set(condition_ids)
self._market_epoch = 0
self.unsubscribe_exited = unsubscribe_exited
self._subscription_state = MarketSubscriptionState()
```

Update `on_start()` to seed the state through one helper instead of open-coded subscriptions:

```python
def on_start(self) -> None:
    if self.registry is None:
        for name in self.data_names:
            self.subscribe_data(name)
        return
    self._sync_market_subscriptions(self._active_condition_ids, unsubscribe=False)
    _subscribe_custom_data(self, PolySignalSpotData)
    _subscribe_custom_data(self, PolySignalPriceToBeatData)
    _subscribe_custom_data(self, PolySignalMarketMetaData)
    _subscribe_custom_data(self, PolySignalMarketUniverseData)
```

Handle `PolySignalMarketMetaData` and `PolySignalMarketUniverseData` in `on_data()`:

```python
if self.registry is not None and isinstance(data, PolySignalMarketMetaData):
    self.registry.register(_pair_from_metadata(self.registry, data))
    self._asset_condition_ids = _asset_conditions(self.registry, tuple(self._active_condition_ids or self._startup_condition_ids))
    if data.condition_id in self._active_condition_ids:
        self._sync_market_subscriptions((data.condition_id,), unsubscribe=False)
    return

if self.registry is not None and isinstance(data, PolySignalMarketUniverseData):
    if data.epoch <= self._market_epoch:
        return
    self._market_epoch = data.epoch
    previous_active = set(self._active_condition_ids)
    self._active_condition_ids = set(data.active_condition_ids)
    self._asset_condition_ids = _asset_conditions(self.registry, tuple(self._active_condition_ids))
    self._sync_market_subscriptions(tuple(data.entered_condition_ids), unsubscribe=False)
    exited = tuple(condition_id for condition_id in data.exited_condition_ids if condition_id in previous_active)
    if exited:
        self._sync_market_subscriptions(exited, unsubscribe=self._should_unsubscribe_exited())
    return
```

Gate evaluation and add best-effort unsubscribe helpers:

```python
def evaluate_condition(self, condition_id: str) -> None:
    if self._active_condition_ids and condition_id not in self._active_condition_ids:
        return
    view = self.assembler.build(condition_id)
    if view is None:
        return
    for decision in self.core.evaluate(view):
        self._handle_decision(decision, view)


def _sync_market_subscriptions(self, active_condition_ids: Iterable[str], *, unsubscribe: bool) -> None:
    if self.registry is None:
        return
    for condition_id in active_condition_ids:
        instrument_ids = tuple(str(value) for value in _instrument_ids(self.registry, (condition_id,)))
        if unsubscribe:
            for instrument_id in self._subscription_state.forget(condition_id, instrument_ids):
                self._unsubscribe_instrument_streams(instrument_id)
            continue
        for instrument_id in self._subscription_state.remember(condition_id, instrument_ids):
            _ = getattr(self, "subscribe_order_book_deltas")(instrument_id=instrument_id, book_type=_nautilus_book_type(self.book_type))
            _ = getattr(self, "subscribe_trade_ticks")(instrument_id)


def _unsubscribe_instrument_streams(self, instrument_id: str) -> None:
    unsubscribe_books = getattr(self, "unsubscribe_order_book_deltas", None)
    unsubscribe_trades = getattr(self, "unsubscribe_trade_ticks", None)
    if callable(unsubscribe_books):
        unsubscribe_books(_nautilus_instrument_id(instrument_id))
    if callable(unsubscribe_trades):
        unsubscribe_trades(_nautilus_instrument_id(instrument_id))


def _should_unsubscribe_exited(self) -> bool:
    return self.unsubscribe_exited
```

Also extend the `PolySignalNativeStrategy.__init__` signature with the new flag:
```python
def __init__(
    self,
    *,
    core: AlphaCore,
    assembler: _Assembler,
    condition_ids: Sequence[str],
    strategy_name: str,
    policy: DecisionPolicyActor | None = None,
    fixed_stake_usdc: float = 10.0,
    data_names: Sequence[str] = DEFAULT_NATIVE_DATA_NAMES,
    book_type: str = "L2_MBP",
    instrument_id_resolver: Callable[[str], object] | None = None,
    registry: PolymarketMarketRegistry | None = None,
    sidecar: ExternalDataSidecar | None = None,
    observability: _Observability | None = None,
    unsubscribe_exited: bool = True,
) -> None:
```

- [ ] **Step 4: Run the strategy tests again**

Run:

```bash
uv run pytest \
  tests/test_nautilus_strategy_base.py::test_native_strategy_universe_update_subscribes_entered_market_once \
  tests/test_nautilus_strategy_base.py::test_native_strategy_exited_market_is_gated_even_if_late_tick_arrives \
  tests/test_nautilus_strategy_base.py::test_native_strategy_on_start_subscribes_built_in_market_data_by_instrument -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  src/polysignal_lab/nautilus_runtime/native_strategy.py \
  tests/test_nautilus_strategy_base.py
git commit -m "feat: rotate native strategy subscriptions"
```

---

### Task 4: Wire MarketRotationActor into TradingNode and enable adapter auto-load

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/trading_node.py`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py`
- Modify: `tests/test_nautilus_trading_node_runtime.py`
- Modify: `tests/test_nautilus_node.py`

**Interfaces:**
- Consumes: `build_paper_trading_node_config(settings, *, instrument_config)`, `_prepare_nautilus_runtime_context()`, `MarketRotationActor`.
- Produces:
  - `build_trading_node(..., market_universe: object | None = None, health: object | None = None) -> dict[str, object]`
  - runtime component key `market_rotation_actor`

- [ ] **Step 1: Write failing tests for dynamic adapter flags and node actor wiring**

Add to `tests/test_nautilus_trading_node_runtime.py`:

```python
def test_build_paper_trading_node_config_enables_dynamic_instrument_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_nautilus(monkeypatch)
    settings = Settings()
    settings.runtime.nautilus.market_rotation.allow_adapter_new_market_events = True

    config = build_paper_trading_node_config(
        settings,
        instrument_config=SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"})),
    )

    data_clients = _dict_attr(config, "data_clients")
    polymarket = data_clients["POLYMARKET"]

    assert getattr(polymarket, "auto_load_missing_instruments") is True
    assert getattr(polymarket, "auto_load_debounce_ms") == 100
    assert getattr(polymarket, "auto_load_max_retries") == 12
    assert getattr(polymarket, "subscribe_new_markets") is True
```

Add to `tests/test_nautilus_node.py`:

```python
def test_build_trading_node_registers_market_rotation_actor(monkeypatch) -> None:
    built = {}

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            built["node"] = self

        def add_data_client_factory(self, name, factory):
            pass

        def add_exec_client_factory(self, name, factory):
            pass

        def build(self):
            return None

    class FakeRotationActor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig", lambda *, load_ids: SimpleNamespace(load_ids=load_ids))
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.build_paper_trading_node_config", lambda settings, **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.register_paper_factories", lambda node: None)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.market_rotation.runtime_market_rotation_actor_type",
        lambda base, config: FakeRotationActor,
    )

    universe = SimpleNamespace(refresh_once=lambda: None)
    runtime = build_trading_node(markets=(), market_universe=universe, health=object())

    assert len(built["node"].trader.actors) == 1
    assert isinstance(runtime["market_rotation_actor"], FakeRotationActor)
    assert runtime["market_rotation_actor"].kwargs["market_universe"] is universe
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_nautilus_trading_node_runtime.py::test_build_paper_trading_node_config_enables_dynamic_instrument_loading \
  tests/test_nautilus_node.py::test_build_trading_node_registers_market_rotation_actor -q
```

Expected: FAIL because `build_paper_trading_node_config()` does not set the auto-load flags and `build_trading_node()` still registers the static sidecar actor.

- [ ] **Step 3: Implement dynamic-load flags and node wiring**

Update `src/polysignal_lab/nautilus_runtime/trading_node.py` so `PolymarketDataClientConfig(...)` receives the dynamic flags:

```python
config = trading_node_config(
    trader_id=trader_id("POLYSIGNAL-001"),
    logging=logging_config(log_level="INFO", use_pyo3=True),
    data_engine=live_data_engine_config(validate_data_sequence=True),
    exec_engine=live_exec_engine_config(reconciliation=False),
    data_clients={
        POLYMARKET_CLIENT_ID: polymarket_data_config(
            instrument_config=instrument_config,
            ws_max_subscriptions=settings.runtime.nautilus.polymarket_data.ws_max_subscriptions_per_connection,
            update_instruments_interval_mins=1,
            subscribe_new_markets=settings.runtime.nautilus.market_rotation.allow_adapter_new_market_events,
            auto_load_missing_instruments=True,
            auto_load_debounce_ms=100,
            auto_load_max_retries=12,
        ),
    },
    exec_clients={
        PAPER_EXEC_CLIENT_ID: sandbox_exec_config(
            venue=POLYMARKET_CLIENT_ID,
            starting_balances=[f"{float(settings.paper_trading.starting_balance_usdc)} USDC"],
            base_currency="USDC",
            oms_type="NETTING",
            account_type="CASH",
            book_type=_book_type_for(settings.runtime.nautilus.matching_accuracy_mode),
            bar_execution=False,
            trade_execution=True,
            support_gtd_orders=True,
            support_contingent_orders=False,
            use_reduce_only=False,
            routing=routing_config(venues=frozenset({POLYMARKET_CLIENT_ID})),
        ),
    },
    timeout_connection=20.0,
    timeout_reconciliation=5.0,
    timeout_portfolio=5.0,
    timeout_disconnection=5.0,
    timeout_post_stop=2.0,
)
```

Update `src/polysignal_lab/nautilus_runtime/node.py`:

```python
def build_trading_node(
    settings: Settings | None = None,
    *,
    condition_ids: Sequence[str] = (),
    markets: Sequence[Market] = (),
    store: AnchorPriceStore | None = None,
    wallet: object | None = None,
    observability: ObservabilityActor | None = None,
    market_universe: object | None = None,
    health: object | None = None,
) -> dict[str, object]:
```

Replace the static sidecar actor registration with the rotation actor:

```python
from polysignal_lab.nautilus_runtime.market_rotation import runtime_market_rotation_actor_type

actor_type = runtime_market_rotation_actor_type(NautilusActor, NautilusActorConfig)
market_rotation_actor = actor_type(
    settings=settings,
    startup_markets=configured_markets,
    market_universe=market_universe,
    registry=registry,
    sidecar=sidecar,
    anchor_store=store,
    health=health,
)
node.trader.add_actor(market_rotation_actor)
```

Return the new actor in the runtime dict:

```python
return {
    "node": node,
    "config": config,
    "registry": registry,
    "sidecar": sidecar,
    "market_rotation_actor": market_rotation_actor,
    "book_data_provider": book_data_provider,
    "assembler": assembler,
    "policy": policy,
    "strategies": strategies,
    "strategy_names": [strategy.strategy_name for strategy in strategies],
    "cache_reader": cache_reader,
}
```

When adding the rotation actor in `src/polysignal_lab/nautilus_runtime/node.py`, keep the no-`market_universe` call sites working with a tiny fallback:
```python
class _StaticMarketUniverse:
    def __init__(self, markets: Sequence[Market]) -> None:
        self._markets = tuple(markets)

    async def refresh_once(self) -> list[Market]:
        return list(self._markets)
```

Construct the actor with:
```python
rotation_universe = market_universe or _StaticMarketUniverse(configured_markets)
market_rotation_actor = actor_type(
    settings=settings,
    startup_markets=configured_markets,
    market_universe=rotation_universe,
    registry=registry,
    sidecar=sidecar,
    anchor_store=store,
    health=health,
)
```

Pass scheduler services through `_build_nautilus_runtime_bundle()`:

```python
components = build_trading_node(
    settings,
    condition_ids=condition_ids,
    markets=discovered_markets,
    store=getattr(scheduler, "sqlite", None),
    observability=observability,
    market_universe=scheduler.market_universe,
    health=scheduler.health,
)
```

Also pass the unsubscribe policy through `_build_native_strategies()` in the same file:
```python
        strategy = strategy_type(
            core=core,
            assembler=assembler,
            condition_ids=tuple(condition_ids),
            strategy_name=name,
            policy=policy,
            fixed_stake_usdc=fixed_stake,
            book_type=strategy_book_type,
            instrument_id_resolver=instrument_id_resolver,
            registry=registry,
            sidecar=sidecar,
            observability=observability,
            unsubscribe_exited=settings.runtime.nautilus.market_rotation.unsubscribe_exited,
        )
```

- [ ] **Step 4: Run the node/runtime tests again**

Run:

```bash
uv run pytest \
  tests/test_nautilus_trading_node_runtime.py::test_build_paper_trading_node_config_enables_dynamic_instrument_loading \
  tests/test_nautilus_trading_node_runtime.py::test_build_paper_trading_node_config_uses_polymarket_data_and_sandbox_exec \
  tests/test_nautilus_node.py::test_build_trading_node_registers_market_rotation_actor \
  tests/test_nautilus_node.py::test_build_nautilus_runtime_discovers_market_universe_for_trading_node -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  src/polysignal_lab/nautilus_runtime/trading_node.py \
  src/polysignal_lab/nautilus_runtime/node.py \
  tests/test_nautilus_trading_node_runtime.py \
  tests/test_nautilus_node.py
git commit -m "feat: wire nautilus market rotation runtime"
```

---

### Task 5: Rotation smoke regression and final focused verification

**Files:**
- Modify: `tests/test_nautilus_full_paper_runtime_smoke.py`
- Reference: `tests/test_nautilus_market_rotation.py`
- Reference: `tests/test_nautilus_strategy_base.py`

**Interfaces:**
- Consumes: `MarketRotationActor`, `PolySignalNativeStrategy`, `build_trading_node()`.
- Produces: a focused smoke test proving one strategy instance survives `A -> B` rotation without node rebuild.

- [ ] **Step 1: Write the failing smoke regression**

Add to `tests/test_nautilus_full_paper_runtime_smoke.py`:

```python
def test_market_rotation_actor_switches_active_market_without_rebuilding_node(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from polysignal_lab.config import Settings
    from polysignal_lab.data.price_to_beat_provider import PriceToBeatResult
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.market import Market, OutcomeToken
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
    from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
    from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
    from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    published: list[object] = []

    def market(condition_id: str) -> Market:
        return Market(
            market_id=condition_id,
            market_slug=f"btc-updown-5m-{condition_id}",
            condition_id=condition_id,
            asset="BTC",
            timeframe="5m",
            outcome_tokens=[
                OutcomeToken(token_id=f"{condition_id}-up", side=Side.UP, outcome_name="Up", market_id=condition_id),
                OutcomeToken(token_id=f"{condition_id}-down", side=Side.DOWN, outcome_name="Down", market_id=condition_id),
            ],
        )

    class FakeUniverse:
        def __init__(self) -> None:
            self.rounds = [[market("condition-a")], [market("condition-b")]]
            self.calls = 0

        async def refresh_once(self) -> list[Market]:
            result = self.rounds[self.calls]
            self.calls += 1
            return result

    class FakeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    registry = PolymarketMarketRegistry()
    sidecar = ExternalDataSidecar()
    assembler = MarketViewAssembler(registry=registry, books=NautilusBookDataProvider(), sidecar=sidecar)
    strategy = FakeStrategy(
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=sidecar,
    )
    actor = MarketRotationActor(
        settings=Settings(),
        startup_markets=(market("condition-a"),),
        market_universe=FakeUniverse(),
        registry=registry,
        sidecar=sidecar,
        anchor_store=None,
        health=None,
    )
    def route(data_type, data) -> None:
        _ = data_type
        published.append(data)
        strategy.on_data(data)

    actor.publish_data = route
    monkeypatch.setattr("asyncio.create_task", lambda coro: SimpleNamespace(cancel=lambda: None))

    async def fake_ptb(market: Market) -> PriceToBeatResult:
        _ = market
        return PriceToBeatResult(value=100000.0, source="anchor", verified=True, anchor_source="chainlink", anchor_lag_ms=5, from_anchor_service=True)

    monkeypatch.setattr(actor.ptb_provider, "get", fake_ptb)

    strategy_id = id(strategy)
    actor.on_start()
    asyncio.run(actor.refresh_once())

    assert id(strategy) == strategy_id
    assert any("condition-b-up.POLYMARKET" in item for item in strategy.book_subscriptions)
    assert all("condition-a-up.POLYMARKET" != item for item in strategy.book_subscriptions[-2:])
```

- [ ] **Step 2: Run the smoke regression to verify it fails**

Run:

```bash
uv run pytest tests/test_nautilus_full_paper_runtime_smoke.py::test_market_rotation_actor_switches_active_market_without_rebuilding_node -q
```

Expected: FAIL because the runtime still behaves like a startup snapshot or because the strategy never subscribes the entered market.

- [ ] **Step 3: Make the smoke regression pass and run the full focused verification set**

There is no new production file in this task. Use this task to fix any remaining gaps in the previous four tasks until the smoke regression passes.

Run syntax verification on the changed Python modules:

```bash
uv run python -m py_compile \
  src/polysignal_lab/config.py \
  src/polysignal_lab/nautilus_runtime/market_data.py \
  src/polysignal_lab/nautilus_runtime/market_rotation.py \
  src/polysignal_lab/nautilus_runtime/native_strategy.py \
  src/polysignal_lab/nautilus_runtime/node.py \
  src/polysignal_lab/nautilus_runtime/trading_node.py
```

Run the focused pytest set:

```bash
uv run pytest \
  tests/test_nautilus_runtime_config.py \
  tests/test_nautilus_market_rotation.py \
  tests/test_nautilus_strategy_base.py \
  tests/test_nautilus_trading_node_runtime.py \
  tests/test_nautilus_node.py \
  tests/test_nautilus_full_paper_runtime_smoke.py -q
```

Run basedpyright on the touched runtime code:

```bash
uv run basedpyright \
  src/polysignal_lab/config.py \
  src/polysignal_lab/nautilus_runtime/market_data.py \
  src/polysignal_lab/nautilus_runtime/market_rotation.py \
  src/polysignal_lab/nautilus_runtime/native_strategy.py \
  src/polysignal_lab/nautilus_runtime/node.py \
  src/polysignal_lab/nautilus_runtime/trading_node.py
```

Expected:

- `py_compile`: no output
- `pytest`: PASS
- `basedpyright`: 0 errors

- [ ] **Step 4: Commit**

```bash
git add \
  tests/test_nautilus_full_paper_runtime_smoke.py \
  src/polysignal_lab/config.py \
  src/polysignal_lab/nautilus_runtime/market_data.py \
  src/polysignal_lab/nautilus_runtime/market_rotation.py \
  src/polysignal_lab/nautilus_runtime/native_strategy.py \
  src/polysignal_lab/nautilus_runtime/node.py \
  src/polysignal_lab/nautilus_runtime/trading_node.py \
  tests/test_nautilus_runtime_config.py \
  tests/test_nautilus_market_rotation.py \
  tests/test_nautilus_strategy_base.py \
  tests/test_nautilus_trading_node_runtime.py \
  tests/test_nautilus_node.py
git commit -m "feat: rotate nautilus markets without rebuilding node"
```

---

## Spec Coverage Check

- `MarketRotationActor` owns periodic discovery and publishes immutable epoch data: Task 2.
- `PolySignalMarketUniverseData` exists and is registered with Nautilus serialization: Task 1.
- `PolySignalNativeStrategy` dynamically subscribes entered markets and gates exited markets: Task 3.
- `build_paper_trading_node_config()` enables dynamic instrument auto-load: Task 4.
- `build_trading_node()` registers the rotation actor and consumes scheduler `market_universe`: Task 4.
- Default runtime stays paper-safe and does not use live Polymarket execution: Tasks 1 and 4.
- Focused smoke proves the strategy instance survives `A -> B` rotation without node rebuild: Task 5.

## Placeholder Scan

Deliberately checked this plan for `TODO`, `TBD`, “implement later”, “similar to Task N”, and generic “write tests for the above” placeholders. None remain.

## Type Consistency Check

- `NautilusMarketRotationConfig` is always referenced as `settings.runtime.nautilus.market_rotation`.
- `PolySignalMarketUniverseData` is the only new epoch payload name used across runtime, tests, and actor wiring.
- The new runtime component key is consistently `market_rotation_actor`.
- `build_trading_node(..., market_universe=..., health=...)` is the same signature used in both runtime assembly and tests.
