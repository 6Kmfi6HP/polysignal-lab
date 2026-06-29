# Nautilus Custom Data Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the approved pure Nautilus Polymarket market-data path real by ensuring native strategies bootstrap from Nautilus custom data/callbacks, default node wiring uses shared projections, and legacy manual sync paths are labeled non-default.

**Architecture:** Keep the existing shared `PolymarketMarketRegistry`, `ExternalDataSidecar`, `NautilusBookDataProvider`, and `MarketViewAssembler` projections because default `build_trading_node()` already injects them. Fix `PolySignalNativeStrategy` so default native startup fails clearly when required projections are missing, and so injected-projection strategies always subscribe to metadata/universe/spot/PTB custom data. Do not add standalone projection mode, new abstractions, or live execution; default market data flows through Nautilus callbacks and actor-published custom data.

**Tech Stack:** Python 3.11 base project, optional NautilusTrader runtime, existing Nautilus Polymarket data adapter, existing sandbox execution client, pytest, basedpyright, uv.

## Global Constraints

- Do not implement live Polymarket execution.
- Do not change the three default strategy alpha rules: `vwap_momentum`, `late_consensus`, `ptb_diff`.
- Do not rewrite the Nautilus Polymarket adapter.
- Do not introduce a new market-data scheduler.
- Do not turn Nautilus cache/portfolio back into a PolySignal-owned truth source.
- Do not add a new dependency.
- `MarketView` must be built only from Nautilus callback/custom-data-fed projections.
- Default runtime must keep `PolymarketLiveDataClientFactory` plus `SandboxLiveExecClientFactory`.
- Default runtime must not register `PolymarketLiveExecClientFactory` as an execution client.
- Default runtime must not read `POLYMARKET_PK`, `POLYMARKET_FUNDER`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, or `POLYMARKET_PASSPHRASE`.
- Keep Nautilus optional at import time; `polysignal_lab` imports must still work without Nautilus installed.
- All verification commands use `uv run ...`.
- Before final completion run `uv run python -m py_compile` on changed Python modules.
- Before final completion run the focused pytest commands in this plan and `uv run basedpyright` over changed Python files.

---

## Scope Check

The approved spec covers one migration path with three tightly coupled concerns: native strategy custom-data bootstrap, default node projection wiring, and legacy/manual sync labeling. These change together because the strategy bootstrap fix is what lets Nautilus custom data replace scheduler-fed projection sync. No separate sub-project specs are needed.

---

## File Structure

- Modify `src/polysignal_lab/nautilus_runtime/native_strategy.py`
  - Owns native strategy bootstrap, custom-data subscriptions, metadata/spot/PTB handling, market-data callbacks, and active/wire subscription state.

- Modify `tests/test_nautilus_strategy_base.py`
  - Adds focused tests for fail-fast missing projections, injected-projection custom-data subscription, and callback-driven evaluation without `NautilusDataIngestor`.

- Modify `tests/test_nautilus_node.py`
  - Adds one default-runtime wiring test proving built strategies receive the shared registry/sidecar/assembler projections and the runtime dictionary does not expose manual-sync components.

- Modify `src/polysignal_lab/nautilus_runtime/data_ingestor.py`
  - Adds a class docstring that marks `NautilusDataIngestor` as legacy/manual sync only.

- Modify `src/polysignal_lab/nautilus_runtime/orchestrator.py`
  - Adds a class docstring that marks `NautilusOrchestrator` as legacy/manual loop only.

No new source files are needed.

---

### Task 1: Native strategy custom-data bootstrap

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py:167-230`
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py:232-290`
- Test: `tests/test_nautilus_strategy_base.py`

**Interfaces:**
- Consumes: `PolymarketMarketRegistry`, `ExternalDataSidecar`, `MarketViewAssembler`, `PolySignalMarketMetaData`, `PolySignalMarketUniverseData`, `PolySignalSpotData`, `PolySignalPriceToBeatData`, `_subscribe_custom_data(strategy, data_type, allow_fallback=True)`.
- Produces:
  - `PolySignalNativeStrategy._require_registry() -> PolymarketMarketRegistry`
  - `PolySignalNativeStrategy._require_sidecar() -> ExternalDataSidecar`
  - `PolySignalNativeStrategy._require_assembler() -> _Assembler`
  - `PolySignalNativeStrategy.on_start() -> None` raising a clear `RuntimeError` when required projections are missing.
  - `PolySignalNativeStrategy.on_start() -> None` subscribing all custom data types when projections are injected.
  - `PolySignalNativeStrategy.on_data(data: object) -> None` raising a clear `RuntimeError` instead of silently dropping metadata/spot/PTB when projections are missing.

- [ ] **Step 1: Write failing tests for fail-fast bootstrap and injected custom-data subscriptions**

Append these tests to `tests/test_nautilus_strategy_base.py` near the other native strategy tests:

```python
def test_native_strategy_constructor_requires_injected_projections() -> None:
    import pytest

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(RuntimeError, match="requires injected registry, sidecar, and assembler projections"):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=_assembler(None),
            condition_ids=(),
            strategy_name="ptb_diff",
        )


def test_native_strategy_constructor_requires_injected_assembler() -> None:
    import pytest

    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(RuntimeError, match="requires injected registry, sidecar, and assembler projections"):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=cast(Any, None),
            condition_ids=(),
            strategy_name="ptb_diff",
            registry=PolymarketMarketRegistry(),
            sidecar=ExternalDataSidecar(),
        )


def test_native_strategy_on_start_subscribes_all_custom_data_with_injected_projections() -> None:
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
    from polysignal_lab.nautilus_runtime.market_data import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
        PolySignalPriceToBeatData,
        PolySignalSpotData,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.custom_subscriptions: list[object] = []

        def subscribe_data(self, data_type):
            self.custom_subscriptions.append(data_type)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
    )

    strategy.on_start()

    assert PolySignalMarketMetaData in strategy.custom_subscriptions
    assert PolySignalMarketUniverseData in strategy.custom_subscriptions
    assert PolySignalSpotData in strategy.custom_subscriptions
    assert PolySignalPriceToBeatData in strategy.custom_subscriptions


def test_native_strategy_constructor_without_registry_fails_clearly() -> None:
    import pytest

    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(RuntimeError, match="requires injected registry, sidecar, and assembler projections"):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=_assembler(None),
            condition_ids=(),
            strategy_name="ptb_diff",
            sidecar=ExternalDataSidecar(),
            instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_nautilus_strategy_base.py::test_native_strategy_constructor_requires_injected_projections \
  tests/test_nautilus_strategy_base.py::test_native_strategy_constructor_requires_injected_assembler \
  tests/test_nautilus_strategy_base.py::test_native_strategy_on_start_subscribes_all_custom_data_with_injected_projections \
  tests/test_nautilus_strategy_base.py::test_native_strategy_constructor_without_registry_fails_clearly \
  -q
```

Expected: FAIL. Current `on_start()` silently uses the `registry is None` branch instead of raising, and the injected-projection startup path does not guard a missing assembler.

- [ ] **Step 3: Implement fail-fast projection guards and unconditional custom-data subscriptions for injected strategies**

In `src/polysignal_lab/nautilus_runtime/native_strategy.py`, add these methods inside `PolySignalNativeStrategy` after `__init__` and before `on_start()`:

```python
    def _require_registry(self) -> PolymarketMarketRegistry:
        if self.registry is None:
            raise RuntimeError(
                "PolySignalNativeStrategy requires injected registry, sidecar, and assembler projections"
            )
        return self.registry

    def _require_sidecar(self) -> ExternalDataSidecar:
        if self.sidecar is None:
            raise RuntimeError(
                "PolySignalNativeStrategy requires injected registry, sidecar, and assembler projections"
            )
        return self.sidecar

    def _require_assembler(self) -> _Assembler:
        if self.assembler is None:
            raise RuntimeError(
                "PolySignalNativeStrategy requires injected registry, sidecar, and assembler projections"
            )
        return self.assembler
```

Replace the whole `on_start()` method with this implementation:

```python
    def on_start(self) -> None:
        _ = self._require_registry()
        _ = self._require_sidecar()
        _ = self._require_assembler()
        self._subscribe_market_conditions(self._startup_condition_ids)
        _subscribe_custom_data(self, PolySignalSpotData)
        _subscribe_custom_data(self, PolySignalPriceToBeatData)
        _subscribe_custom_data(self, PolySignalMarketMetaData)
        _subscribe_custom_data(self, PolySignalMarketUniverseData)
```

Inside `on_data()`, replace the `PolySignalSpotData` block with this implementation:

```python
        if isinstance(data, PolySignalSpotData):
            sidecar = self._require_sidecar()
            sidecar.update_spot(
                SpotView(
                    asset=data.asset,
                    symbol=data.symbol,
                    price=data.price,
                    source=data.source,
                    freshness_ms=data.freshness_ms,
                )
            )
            for candidate in self._asset_condition_ids.get(data.asset.upper(), ()):
                self.evaluate_condition(candidate)
            return
```

Inside `on_data()`, replace the `PolySignalPriceToBeatData` block with this implementation:

```python
        if isinstance(data, PolySignalPriceToBeatData):
            sidecar = self._require_sidecar()
            sidecar.update_price_to_beat(
                condition_id=data.condition_id,
                value=data.value,
                source=data.source,
                verified=data.verified,
                from_anchor_service=data.from_anchor_service,
                anchor_source=data.anchor_source,
                anchor_lag_ms=data.anchor_lag_ms,
            )
            self.evaluate_condition(data.condition_id)
            return
```

Inside `on_data()`, replace the `PolySignalMarketMetaData` block with this implementation:

```python
        if isinstance(data, PolySignalMarketMetaData):
            registry = self._require_registry()
            registry.register(
                _pair_from_metadata(
                    registry,
                    data,
                    instrument_id_resolver=self.instrument_id_resolver,
                )
            )
            self._refresh_asset_conditions()
            if data.condition_id in self._active_condition_ids:
                self._subscribe_market_conditions((data.condition_id,))
            return
```

Keep the existing `PolySignalMarketUniverseData` block unchanged except remove the unreachable `if self.registry is None: return` branch if it is still present after the metadata block.

- [ ] **Step 4: Run focused tests to verify they pass**

Run:

```bash
uv run pytest \
  tests/test_nautilus_strategy_base.py::test_native_strategy_constructor_requires_injected_projections \
  tests/test_nautilus_strategy_base.py::test_native_strategy_constructor_requires_injected_assembler \
  tests/test_nautilus_strategy_base.py::test_native_strategy_on_start_subscribes_all_custom_data_with_injected_projections \
  tests/test_nautilus_strategy_base.py::test_native_strategy_constructor_without_registry_fails_clearly \
  tests/test_nautilus_strategy_base.py::test_native_strategy_active_market_without_metadata_stays_pending_until_metadata_arrives \
  tests/test_nautilus_strategy_base.py::test_native_strategy_active_market_without_subscribe_hooks_marks_pending_subscribe \
  -q
```

Expected: PASS for all six tests.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/native_strategy.py tests/test_nautilus_strategy_base.py
git commit -m "fix: require native strategy projections"
```

---

### Task 2: Default runtime wiring stays shared-projection and callback-driven

**Files:**
- Modify: `tests/test_nautilus_node.py`
- Test: `tests/test_nautilus_node.py`

**Interfaces:**
- Consumes: `build_trading_node(condition_ids: Sequence[str] = ..., market_universe: object | None = ..., health: object | None = ...) -> dict[str, object]`.
- Produces: Test coverage proving default `build_trading_node()` returns shared projections and does not expose `data_ingestor`, `orchestrator`, `paper_client`, or `matching_client` as default-runtime components.

- [ ] **Step 1: Write the failing wiring test**

Add this test to `tests/test_nautilus_node.py` after `test_build_trading_node_returns_nautilus_runtime_components`:

```python
def test_build_trading_node_injects_shared_projections_and_no_manual_sync_components(monkeypatch) -> None:
    built = {}

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            built["node"] = self

        def add_data_client_factory(self, name, factory):
            built.setdefault("data_factories", []).append((name, factory))

        def add_exec_client_factory(self, name, factory):
            built.setdefault("exec_factories", []).append((name, factory))

        def build(self):
            self.built = True

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_paper_trading_node_config",
        lambda settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.register_paper_factories",
        lambda node: (
            node.add_data_client_factory("POLYMARKET", object()),
            node.add_exec_client_factory(PAPER_EXEC_CLIENT_ID, object()),
        ),
    )

    runtime = build_trading_node(condition_ids=("condition-btc-5m",))
    strategies = cast(list[object], runtime["strategies"])

    assert "registry" in runtime
    assert "sidecar" in runtime
    assert "book_data_provider" in runtime
    assert "assembler" in runtime
    assert "market_rotation_actor" in runtime
    assert "data_ingestor" not in runtime
    assert "orchestrator" not in runtime
    assert "paper_client" not in runtime
    assert "matching_client" not in runtime
    assert strategies
    first_strategy = strategies[0]
    assert getattr(first_strategy, "registry") is runtime["registry"]
    assert getattr(first_strategy, "sidecar") is runtime["sidecar"]
    assert getattr(first_strategy, "assembler") is runtime["assembler"]
```

- [ ] **Step 2: Run test to verify current state**

Run:

```bash
uv run pytest tests/test_nautilus_node.py::test_build_trading_node_injects_shared_projections_and_no_manual_sync_components -q
```

Expected: PASS if current node assembly already satisfies the approved spec. If it fails because no strategies are built under default settings, set `settings = Settings()` inside the test, enable one explicit strategy using existing test patterns in the same file, and call `build_trading_node(settings=settings, condition_ids=("condition-btc-5m",))`.

- [ ] **Step 3: If the test fails because strategies are not enabled by default, use this exact test body instead**

Replace the test body from Step 1 with this version:

```python
def test_build_trading_node_injects_shared_projections_and_no_manual_sync_components(monkeypatch) -> None:
    built = {}

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            built["node"] = self

        def add_data_client_factory(self, name, factory):
            built.setdefault("data_factories", []).append((name, factory))

        def add_exec_client_factory(self, name, factory):
            built.setdefault("exec_factories", []).append((name, factory))

        def build(self):
            self.built = True

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_paper_trading_node_config",
        lambda settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.register_paper_factories",
        lambda node: (
            node.add_data_client_factory("POLYMARKET", object()),
            node.add_exec_client_factory(PAPER_EXEC_CLIENT_ID, object()),
        ),
    )

    settings = Settings()
    settings.strategies.enabled = ["ptb_diff"]

    runtime = build_trading_node(settings=settings, condition_ids=("condition-btc-5m",))
    strategies = cast(list[object], runtime["strategies"])

    assert "registry" in runtime
    assert "sidecar" in runtime
    assert "book_data_provider" in runtime
    assert "assembler" in runtime
    assert "market_rotation_actor" in runtime
    assert "data_ingestor" not in runtime
    assert "orchestrator" not in runtime
    assert "paper_client" not in runtime
    assert "matching_client" not in runtime
    assert strategies
    first_strategy = strategies[0]
    assert getattr(first_strategy, "registry") is runtime["registry"]
    assert getattr(first_strategy, "sidecar") is runtime["sidecar"]
    assert getattr(first_strategy, "assembler") is runtime["assembler"]
```

Run again:

```bash
uv run pytest tests/test_nautilus_node.py::test_build_trading_node_injects_shared_projections_and_no_manual_sync_components -q
```

Expected: PASS.

- [ ] **Step 4: Run existing node paper-safety tests**

Run:

```bash
uv run pytest \
  tests/test_nautilus_node.py::test_build_trading_node_returns_nautilus_runtime_components \
  tests/test_nautilus_node.py::test_build_trading_node_registers_market_rotation_actor \
  tests/test_nautilus_node.py::test_build_trading_node_uses_sandbox_execution_not_matching_client \
  tests/test_nautilus_trading_node_runtime.py::test_build_paper_trading_node_config_uses_polymarket_data_and_sandbox_exec \
  tests/test_nautilus_trading_node_runtime.py::test_register_paper_factories_registers_data_and_sandbox_exec_only \
  -q
```

Expected: PASS for all five tests.

- [ ] **Step 5: Commit**

```bash
git add tests/test_nautilus_node.py
git commit -m "test: lock pure nautilus runtime wiring"
```

---

### Task 3: Legacy/manual sync labeling

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/data_ingestor.py:31-32`
- Modify: `src/polysignal_lab/nautilus_runtime/orchestrator.py:23-24`
- Test: `tests/test_nautilus_data_ingestor.py`
- Test: `tests/test_nautilus_node.py`

**Interfaces:**
- Consumes: Existing `NautilusDataIngestor` and `NautilusOrchestrator` public behavior.
- Produces: Documentation in code that these classes are not default Nautilus market-data or strategy-evaluation owners.

- [ ] **Step 1: Add class docstring to `NautilusDataIngestor`**

In `src/polysignal_lab/nautilus_runtime/data_ingestor.py`, change the class header to:

```python
class NautilusDataIngestor:
    """Legacy/manual sync bridge for tests and compatibility paths.

    Default Nautilus runtime market data must come from Nautilus callbacks and
    actor-published custom data. This class must not be wired as the default
    strategy-evaluation data owner.
    """
```

Keep the existing `__init__` method directly below the docstring.

- [ ] **Step 2: Add class docstring to `NautilusOrchestrator`**

In `src/polysignal_lab/nautilus_runtime/orchestrator.py`, change the class header to:

```python
class NautilusOrchestrator:
    """Legacy/manual phase loop kept for compatibility.

    Default Nautilus runtime strategy evaluation must be triggered by Nautilus
    callbacks and custom data, not by this scheduler-style sync/evaluate loop.
    """
```

Keep the existing `__init__` method directly below the docstring.

- [ ] **Step 3: Run tests proving behavior remains unchanged**

Run:

```bash
uv run pytest \
  tests/test_nautilus_data_ingestor.py \
  tests/test_nautilus_node.py::test_build_trading_node_injects_shared_projections_and_no_manual_sync_components \
  -q
```

Expected: PASS. `NautilusDataIngestor` behavior remains available for legacy/manual/test paths, and default node wiring still does not expose manual-sync components.

- [ ] **Step 4: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/data_ingestor.py src/polysignal_lab/nautilus_runtime/orchestrator.py tests/test_nautilus_data_ingestor.py tests/test_nautilus_node.py
git commit -m "docs: label manual nautilus sync paths"
```

---

### Task 4: Final verification and cleanup

**Files:**
- Verify: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Verify: `src/polysignal_lab/nautilus_runtime/data_ingestor.py`
- Verify: `src/polysignal_lab/nautilus_runtime/orchestrator.py`
- Verify: `tests/test_nautilus_strategy_base.py`
- Verify: `tests/test_nautilus_node.py`
- Verify: `tests/test_nautilus_data_ingestor.py`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: Evidence that the approved spec acceptance criteria touched by this plan are covered by focused tests and static checks.

- [ ] **Step 1: Run focused native strategy tests**

Run:

```bash
uv run pytest \
  tests/test_nautilus_strategy_base.py::test_native_strategy_constructor_requires_injected_projections \
  tests/test_nautilus_strategy_base.py::test_native_strategy_constructor_requires_injected_assembler \
  tests/test_nautilus_strategy_base.py::test_native_strategy_constructor_without_registry_fails_clearly \
  tests/test_nautilus_strategy_base.py::test_native_strategy_on_start_subscribes_all_custom_data_with_injected_projections \
  tests/test_nautilus_strategy_base.py::test_native_strategy_routes_ptb_custom_data_to_matching_active_condition_only \
  tests/test_nautilus_strategy_base.py::test_native_strategy_active_market_without_metadata_stays_pending_until_metadata_arrives \
  tests/test_nautilus_strategy_base.py::test_native_strategy_active_market_without_subscribe_hooks_marks_pending_subscribe \
  tests/test_nautilus_strategy_base.py::test_native_strategy_order_book_callback_updates_shared_books_and_submits \
  tests/test_nautilus_strategy_base.py::test_native_strategy_trade_tick_callback_updates_shared_trade_history \
  -q
```

Expected: PASS for all nine tests.

- [ ] **Step 2: Run focused runtime wiring tests**

Run:

```bash
uv run pytest \
  tests/test_nautilus_node.py::test_build_trading_node_injects_shared_projections_and_no_manual_sync_components \
  tests/test_nautilus_node.py::test_build_trading_node_returns_nautilus_runtime_components \
  tests/test_nautilus_node.py::test_build_trading_node_registers_market_rotation_actor \
  tests/test_nautilus_trading_node_runtime.py::test_build_paper_trading_node_config_uses_polymarket_data_and_sandbox_exec \
  tests/test_nautilus_trading_node_runtime.py::test_build_paper_trading_node_config_enables_dynamic_instrument_loading \
  tests/test_nautilus_trading_node_runtime.py::test_register_paper_factories_registers_data_and_sandbox_exec_only \
  -q
```

Expected: PASS for all six tests.

- [ ] **Step 3: Run legacy compatibility tests**

Run:

```bash
uv run pytest tests/test_nautilus_data_ingestor.py -q
```

Expected: PASS. Manual sync helper behavior remains available outside default runtime wiring.

- [ ] **Step 4: Compile changed Python modules**

Run:

```bash
uv run python -m py_compile \
  src/polysignal_lab/nautilus_runtime/native_strategy.py \
  src/polysignal_lab/nautilus_runtime/data_ingestor.py \
  src/polysignal_lab/nautilus_runtime/orchestrator.py
```

Expected: exit 0 with no output.

- [ ] **Step 5: Run basedpyright over changed runtime files and tests**

Run:

```bash
uv run basedpyright \
  src/polysignal_lab/nautilus_runtime/native_strategy.py \
  src/polysignal_lab/nautilus_runtime/data_ingestor.py \
  src/polysignal_lab/nautilus_runtime/orchestrator.py \
  tests/test_nautilus_strategy_base.py \
  tests/test_nautilus_node.py \
  tests/test_nautilus_data_ingestor.py
```

Expected: exit 0. If basedpyright reports existing unrelated warnings in these large test files, paste the exact diagnostics into the review note and do not suppress them.

- [ ] **Step 6: Self-review against approved spec**

Use this checklist:

```text
AC1 Default node wiring is paper-safe: covered by tests/test_nautilus_trading_node_runtime.py.
AC2 Strategy bootstraps custom data: covered by Task 1 tests.
AC3 No default manual sync strategy loop: covered by Task 2 test.
AC4 Order book callback evaluates condition: covered by existing callback test in final verification.
AC5 Trade tick callback evaluates condition: covered by the trade-tick callback test asserting both projection update and one matching evaluation.
AC6 Metadata/universe drives dynamic subscription: covered by existing pending-metadata and metadata-arrival tests.
AC7 Missing metadata does not storm subscriptions: covered by existing pending-metadata repeated-universe test.
AC8 Spot/PTB are custom-data driven: covered by spot and PTB custom-data routing tests.
AC9 Changed-only PTB publishing remains intact: covered by market-rotation changed-only PTB tests outside this plan's changed files.
AC10 Logs remain explainable: covered by observability tests for decision JSONL fields and duplicate rejected-signal candidate JSONL payloads.
```

- [ ] **Step 7: Commit verification note if the project keeps manual evidence files**

Do not create a new evidence file by default. If the active branch already has an evidence note for this implementation, append the verification commands and outputs there. Otherwise, skip this step.

- [ ] **Step 8: Final commit if Step 7 changed an evidence file**

```bash
git add <evidence-file-path>
git commit -m "test: record nautilus custom data verification"
```

Skip this commit when Step 7 creates no file changes.

---

## Self-Review

### Spec coverage

- AC1 is covered by existing and re-run trading node runtime tests in Task 4.
- AC2 is covered by Task 1.
- AC3 is covered by Task 2 plus Task 3 labels.
- AC4 is covered by the order-book callback test re-run in Task 4.
- AC5 is covered by the trade-tick callback test asserting projection update and matching evaluation.
- AC6 and AC7 are covered by existing universe/pending metadata tests re-run with the Task 1 tests.
- AC8 is covered by spot and PTB custom-data routing tests.
- AC9 is covered by existing market rotation changed-only PTB tests.
- AC10 is covered by observability tests for decision JSONL fields and duplicate rejected-signal candidate JSONL payloads.

### Placeholder scan

No placeholder markers are present. No step asks an engineer to invent missing code.

### Type consistency

The plan consistently uses existing names from source: `PolySignalNativeStrategy`, `PolymarketMarketRegistry`, `ExternalDataSidecar`, `PolySignalMarketMetaData`, `PolySignalMarketUniverseData`, `PolySignalSpotData`, `PolySignalPriceToBeatData`, `_subscribe_custom_data`, `build_trading_node`, and `PAPER_EXEC_CLIENT_ID`.
