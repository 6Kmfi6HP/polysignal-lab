# Nautilus Full Runtime Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PolySignal's production strategy executor with a paper-safe NautilusTrader `TradingNode` while preserving all 13 current strategy semantics, safety boundaries, state, observability, and operator surfaces.

**Architecture:** Keep PolySignal alpha/business logic pure in `src/polysignal_lab/alpha/`, host it in Nautilus wrappers under one new `src/polysignal_lab/nautilus_runtime/` package, and move scheduler-owned gate/paper/settlement/observability responsibilities into Nautilus actors or execution clients. The legacy scheduler remains available only as an equivalence-test fixture until cutover; production runtime must enter through `polysignal-nautilus` and report Nautilus health components.

**Tech Stack:** Python 3.11 default test/runtime boundary, Python 3.12-3.14 Nautilus verification environment, Linux ARM64 rk3588 with glibc >= 2.35, uv, pytest, optional `nautilus_trader[polymarket]`, NautilusTrader `TradingNode`, `Strategy`, custom `Data`/`DataType`, MessageBus, strategy `on_save()`/`on_load()`, existing PolySignal Pydantic v2 config/domain models, SQLite/JSONL storage, Telegram SDK service.

## Global Constraints

- Spec source: `docs/superpowers/specs/2026-06-25-nautilus-full-runtime-migration-design.md` is approved and supersedes spec 15.
- Default repo runtime remains read-only and paper-safe; no real Polymarket authenticated execution in default app or Docker target.
- Default implementation must not import, instantiate, or register `PolymarketExecutionClient`, `PolymarketLiveExecClientFactory`, or live `exec_clients`.
- Default implementation must not read or pass `POLYMARKET_PK`, `POLYMARKET_FUNDER`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, or `POLYMARKET_PASSPHRASE`.
- Default implementation must not invoke Nautilus allowance or API-key helpers `set_allowances.py` or `create_api_key.py`.
- Nautilus docs show `PolymarketDataClientConfig` credential fields fall back to `POLYMARKET_*` env vars when `None`; Wave 0 must prove a credential-free data path or select a PolySignal-owned public data adapter.
- Current `pyproject.toml:26-28` already defines `nautilus = ["nautilus_trader[polymarket]"]`; every dependency change must update `uv.lock`.
- Current `Dockerfile:1-11` uses Python 3.12 and installs `.[dev]`; it does not install the Nautilus extra today.
- Current source bridge lives under `src/polysignal_lab/nautilus_bridge/`; final runtime must have one named runtime package, `src/polysignal_lab/nautilus_runtime/`, with compatibility imports only while equivalence tests still need the old bridge path.
- Current production config enables exactly `vwap_momentum`, `late_consensus`, and `ptb_diff` in `config/signal_bot.yaml`; lab config may enable more strategies.
- All 13 registered strategies in `src/polysignal_lab/strategies/factory.py:52-66` must have alpha cores and Nautilus wrappers: `vwap_momentum`, `late_consensus`, `ptb_diff`, `binary_momentum`, `cross_market_bot`, `dump_hedge`, `fibonacci_bot`, `low_side_dual_reversion`, `mid_price_sizing`, `ninety_nine_cent_sniper`, `one_cent_buy`, `pre_order_market`, `skew_mean_reversion`.
- `StatefulAlphaCore` state uses Nautilus `Strategy.on_save() -> dict[str, bytes]` and `on_load(state: dict[str, bytes]) -> None`.
- State key format is `polysignal.<strategy_name>.state.v<version>`; payload is UTF-8 JSON bytes; unknown same-strategy future versions fail closed.
- Enums serialize by `.value`; datetimes serialize as UTC ISO strings; deques as lists; sets as sorted lists; dict keys as strings; no pickle.
- Strategy output equivalence excludes host-generated `signal_id`, `snapshot_id`/`view_id`, `created_at`, and default dedupe prefixes unless the strategy owns a suffix.
- Run default tests through `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest ...`.
- Runtime changes intended for formal use require `docker compose up -d --build --force-recreate`, `docker compose ps`, and cache-busted health verification.

---

## Research Evidence

- `src/polysignal_lab/alpha/types.py:47-103` already has immutable `MarketView`, `AlphaDecision`, `OrderIntentSpec`, and `AlphaCore`.
- `src/polysignal_lab/alpha/ptb_diff_core.py:45-178` already has `PTBDiffAlphaCore`; `market_view_from_snapshot()` keeps legacy PTB equivalence.
- `src/polysignal_lab/nautilus_bridge/state.py:12-37` already implements versioned JSON bytes and fail-closed unknown-version decoding.
- `src/polysignal_lab/nautilus_bridge/strategy_base.py:27-97` is a source-level wrapper only; it records intents and callback dictionaries, but does not submit real Nautilus orders or policy decisions.
- `src/polysignal_lab/app/scheduler.py:245-279` currently constructs `strategy_schedule`, `PaperWallet`, `PaperSimulator`, `PaperExitEngine`, and `PaperSettlementEngine`.
- `src/polysignal_lab/app/scheduler_processing.py:506-511` evaluates snapshots, arbitrates, gates, and commits; `:614-666` stores/publishes/paper-trades accepted signals and recursively processes follow-up signals.
- `src/polysignal_lab/signal_layer/gate.py:48-60` gate first-failure order is market active, time window, book freshness, spot freshness, spread, max entry, GTD expiry, confidence, dedupe, rate limit.
- `src/polysignal_lab/app/services/signal_pipeline.py:46-64` is the current manual/dependency disable surface used by Telegram controls.
- `src/polysignal_lab/app/scheduler.py:67-81` maps paper fill/cancel/leg-failure events to legacy strategy callbacks and VWAP follow-up queue.
- `src/polysignal_lab/storage/sqlite_store.py` symbols include insert methods for `signals`, `rejected_signals`, `paper_orders`, `paper_fills`, `paper_positions`, `paper_trade_results`, `paper_wallet_snapshots`, `daily_reports`, `telegram_publishes`, and `system_events`.
- Nautilus docs: `/nautechsystems/nautilus_trader` says Python 3.12-3.14, Ubuntu 22.04+ Linux support, and `nautilus_trader[polymarket]` extra.
- Nautilus docs: `PolymarketDataClientConfig` documents `private_key`, `funder`, `api_key`, `api_secret`, `passphrase` env fallback; do not rely on data-client naming as a safety proof.
- Nautilus docs: custom data can subclass `Data`, register serialization, publish with `publish_data(DataType(MyData), data)`, subscribe with `subscribe_data(DataType(MyData))`, and receive in `on_data(self, data)`.
- Nautilus docs: strategy lifecycle includes `on_start`, `on_stop`, `on_save() -> dict[str, bytes]`, and `on_load(state: dict[str, bytes])`.

## Scope Check

This spec intentionally spans multiple subsystems. Splitting into smaller specs is not required because the user's approved spec asks for a full migration, but implementation must still land in reviewable waves with independent red/green boundaries. This plan therefore uses one master plan with 14 tasks; each task produces a working, testable slice and a commit.

## File Structure

```text
pyproject.toml
  Adds `polysignal-nautilus` script and any isolated extras required by the Nautilus target; keeps default dependencies free of Nautilus.

uv.lock
  Records optional Nautilus dependency changes reproducibly.

Dockerfile
  Keeps default target paper-safe and adds a separate Nautilus target that explicitly installs the Nautilus extra.

config/signal_bot.yaml
config/signal_bot.lab.yaml
  Adds `runtime.engine` and `runtime.nautilus` sections; production default becomes `nautilus` only at Task 13 cutover.

src/polysignal_lab/config.py
  Adds `RuntimeConfig`, `NautilusRuntimeConfig`, safety validation for live execution flag, and YAML parsing for the new section.

src/polysignal_lab/app/main.py
  Adds `RuntimeMode.NAUTILUS`, `polysignal-nautilus` entry function, and SIGTERM-safe Nautilus runner.

src/polysignal_lab/alpha/types.py
  Adds `StatefulAlphaCore`, `GroupAlphaCore`, `MarketGroupView`, `AlphaOrderEvent`, `AlphaFillEvent`, and quantity-capable order metadata.

src/polysignal_lab/alpha/state.py
  Holds JSON-safe state conversion helpers shared by all cores.

src/polysignal_lab/alpha/<strategy>_core.py
  One pure core per legacy strategy; no scheduler, Nautilus, Telegram, SQLite, wallet, or snapshot imports.

src/polysignal_lab/strategies/<strategy>.py
  Becomes a legacy adapter over the matching alpha core until production cutover.

src/polysignal_lab/nautilus_runtime/__init__.py
src/polysignal_lab/nautilus_runtime/config.py
src/polysignal_lab/nautilus_runtime/node.py
src/polysignal_lab/nautilus_runtime/market_data.py
src/polysignal_lab/nautilus_runtime/sidecar_data.py
src/polysignal_lab/nautilus_runtime/decision_policy.py
src/polysignal_lab/nautilus_runtime/execution.py
src/polysignal_lab/nautilus_runtime/position_policy.py
src/polysignal_lab/nautilus_runtime/settlement.py
src/polysignal_lab/nautilus_runtime/observability.py
src/polysignal_lab/nautilus_runtime/state.py
  New Nautilus production runtime package.

src/polysignal_lab/nautilus_runtime/strategies/base.py
src/polysignal_lab/nautilus_runtime/strategies/<strategy>.py
  Nautilus wrappers for all 13 strategies.

src/polysignal_lab/nautilus_bridge/*
  Compatibility shim only during migration; final production imports come from `nautilus_runtime`.

tests/test_nautilus_platform_boundary.py
tests/test_nautilus_runtime_config.py
tests/test_alpha_types.py
tests/test_alpha_state.py
tests/test_alpha_<strategy>.py
tests/test_nautilus_custom_data.py
tests/test_nautilus_sidecar_actor.py
tests/test_nautilus_market_view_assembler.py
tests/test_nautilus_decision_policy.py
tests/test_nautilus_order_mapping.py
tests/test_nautilus_execution.py
tests/test_nautilus_position_policy.py
tests/test_nautilus_settlement_actor.py
tests/test_nautilus_observability.py
tests/test_nautilus_node.py
tests/test_nautilus_cutover.py
  New and expanded tests for the migration.
```

---

### Task 1: Runtime Config and Platform Boundary

**Files:**
- Modify: `pyproject.toml:26-31`
- Modify: `uv.lock`
- Modify: `Dockerfile:1-30`
- Modify: `config/signal_bot.yaml:1-116`
- Modify: `config/signal_bot.lab.yaml`
- Modify: `src/polysignal_lab/config.py:1-306`
- Modify: `src/polysignal_lab/app/main.py:23-164`
- Create: `tests/test_nautilus_platform_boundary.py`
- Create: `tests/test_nautilus_runtime_config.py`

**Interfaces:**
- Consumes: existing `Settings.from_yaml(path) -> Settings`, `RuntimeMode`, default safety validation.
- Produces: `RuntimeEngine = Literal["legacy", "nautilus"]`, `RuntimeConfig`, `NautilusRuntimeConfig`, CLI mode `nautilus`, script `polysignal-nautilus`, and Docker target `nautilus-runtime`.

- [ ] **Step 1: Write failing runtime config tests**

Create `tests/test_nautilus_runtime_config.py`:

```python
from __future__ import annotations

import pytest

from polysignal_lab.config import Settings


def test_runtime_config_defaults_to_legacy_until_cutover() -> None:
    settings = Settings()

    assert settings.runtime.engine == "legacy"
    assert settings.runtime.nautilus.allow_live_polymarket_execution is False
    assert settings.runtime.nautilus.execution_mode == "paper_sandbox"


def test_live_polymarket_execution_is_invalid_in_default_runtime() -> None:
    with pytest.raises(ValueError, match="live Polymarket execution"):
        Settings.model_validate(
            {
                "runtime": {
                    "engine": "nautilus",
                    "nautilus": {"allow_live_polymarket_execution": True},
                }
            }
        )


def test_production_yaml_declares_nautilus_runtime_section() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")

    assert settings.runtime.nautilus.trader_id == "PolySignal-Nautilus-001"
    assert settings.runtime.nautilus.python == "3.12"
    assert settings.runtime.nautilus.sidecar.spot_source == "polymarket_rtds"
```

- [ ] **Step 2: Write failing platform-boundary tests**

Create `tests/test_nautilus_platform_boundary.py`:

```python
from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

from polysignal_lab.app import main as app_main


def test_default_import_does_not_require_nautilus() -> None:
    assert importlib.import_module("polysignal_lab") is not None


def test_nautilus_extra_is_optional_and_polymarket_scoped() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert all("nautilus_trader" not in dep for dep in data["project"]["dependencies"])
    assert data["project"]["optional-dependencies"]["nautilus"] == ["nautilus_trader[polymarket]"]


def test_cli_exposes_nautilus_mode_and_script() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "nautilus" in app_main.MODE_VALUES
    assert pyproject["project"]["scripts"]["polysignal-nautilus"] == "polysignal_lab.nautilus_runtime.node:main"


def test_default_source_keeps_forbidden_live_symbols_out_of_runtime() -> None:
    forbidden = (
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
    scanned_roots = [Path("src/polysignal_lab/nautilus_runtime"), Path("src/polysignal_lab/nautilus_bridge")]
    findings: list[str] = []
    for root in scanned_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_runtime_config.py tests/test_nautilus_platform_boundary.py -v
```

Expected: FAIL because `Settings.runtime`, `RuntimeMode.NAUTILUS`, `polysignal-nautilus`, and `src/polysignal_lab/nautilus_runtime` do not exist yet.

- [ ] **Step 4: Add runtime config models and YAML section**

Add to `src/polysignal_lab/config.py` before `Settings`:

```python
class NautilusSidecarConfig(BaseModel):
    spot_source: str = "polymarket_rtds"
    price_to_beat_source: str = "anchor_or_gamma"


class NautilusDataClientConfig(BaseModel):
    enabled: bool = True
    ws_max_subscriptions_per_connection: int = 200


class NautilusDecisionPolicyConfig(BaseModel):
    preserve_gate_first_failure_order: bool = True
    consensus_enabled: bool = True
    arbiter_policy: Literal["suppress_ambiguous"] = "suppress_ambiguous"


class NautilusRuntimeConfig(BaseModel):
    trader_id: str = "PolySignal-Nautilus-001"
    python: str = "3.12"
    execution_mode: Literal["paper_sandbox"] = "paper_sandbox"
    allow_live_polymarket_execution: bool = False
    polymarket_data: NautilusDataClientConfig = Field(default_factory=NautilusDataClientConfig)
    sidecar: NautilusSidecarConfig = Field(default_factory=NautilusSidecarConfig)
    decision_policy: NautilusDecisionPolicyConfig = Field(default_factory=NautilusDecisionPolicyConfig)

    @model_validator(mode="after")
    def validate_paper_safe(self) -> "NautilusRuntimeConfig":
        if self.allow_live_polymarket_execution:
            raise ValueError("live Polymarket execution is invalid in the default runtime")
        return self


class RuntimeConfig(BaseModel):
    engine: Literal["legacy", "nautilus"] = "legacy"
    nautilus: NautilusRuntimeConfig = Field(default_factory=NautilusRuntimeConfig)
```

Add `runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)` to `Settings`. Add this YAML block to both configs, leaving `engine: legacy` until Task 13:

```yaml
runtime:
  engine: legacy
  nautilus:
    trader_id: PolySignal-Nautilus-001
    python: "3.12"
    execution_mode: paper_sandbox
    allow_live_polymarket_execution: false
    polymarket_data:
      enabled: true
      ws_max_subscriptions_per_connection: 200
    sidecar:
      spot_source: polymarket_rtds
      price_to_beat_source: anchor_or_gamma
    decision_policy:
      preserve_gate_first_failure_order: true
      consensus_enabled: true
      arbiter_policy: suppress_ambiguous
```

- [ ] **Step 5: Add CLI and Docker boundary**

Update `pyproject.toml` scripts:

```toml
polysignal-nautilus = "polysignal_lab.nautilus_runtime.node:main"
```

Update `src/polysignal_lab/app/main.py`:

```python
class RuntimeMode(StrEnum):
    SCHEDULER = "scheduler"
    DASHBOARD = "dashboard"
    SMOKE = "smoke"
    NAUTILUS = "nautilus"
```

Add a `case RuntimeMode.NAUTILUS` branch that imports `polysignal_lab.nautilus_runtime.node.run_nautilus_cli` inside the branch and calls it. Create `src/polysignal_lab/nautilus_runtime/node.py` with a safe stub that loads settings and raises a clear `RuntimeError("Nautilus runtime is not wired yet")`; this file is replaced in Task 13.

Add a separate Docker target instead of changing the default target:

```dockerfile
FROM builder AS nautilus-builder
RUN pip install --ignore-installed --no-cache-dir --prefix=/install-nautilus '.[dev,nautilus]'

FROM python:3.12-slim AS nautilus-runtime
WORKDIR /app
COPY --from=nautilus-builder /install-nautilus /usr/local
COPY pyproject.toml ./
COPY config/ config/
COPY src/ src/
COPY scripts/ scripts/
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN mkdir -p data logs state && chmod +x /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["nautilus"]
```

- [ ] **Step 6: Run tests and update lock**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_runtime_config.py tests/test_nautilus_platform_boundary.py tests/test_config.py tests/test_cli_runtime_modes.py -v
uv lock
```

Expected: PASS for Python tests; `uv lock` updates or confirms `uv.lock`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock Dockerfile config/signal_bot.yaml config/signal_bot.lab.yaml src/polysignal_lab/config.py src/polysignal_lab/app/main.py src/polysignal_lab/nautilus_runtime tests/test_nautilus_runtime_config.py tests/test_nautilus_platform_boundary.py
git commit -m "feat: define nautilus runtime boundary"
```

---

### Task 2: Alpha Contracts and State Serialization

**Files:**
- Modify: `src/polysignal_lab/alpha/types.py:1-104`
- Create: `src/polysignal_lab/alpha/state.py`
- Modify: `src/polysignal_lab/alpha/__init__.py`
- Modify: `tests/test_alpha_types.py`
- Create: `tests/test_alpha_state.py`

**Interfaces:**
- Consumes: existing `MarketView`, `AlphaDecision`, `OrderIntentSpec`, `AlphaCore`.
- Produces: `MarketGroupView`, `AlphaOrderEvent`, `AlphaFillEvent`, `StatefulAlphaCore`, `GroupAlphaCore`, `NautilusOrderSpec`, `json_safe_state(value)`, `restore_utc_datetime(value)`.

- [ ] **Step 1: Write failing alpha contract tests**

Append to `tests/test_alpha_types.py`:

```python
from polysignal_lab.alpha.types import AlphaFillEvent, AlphaOrderEvent, MarketGroupView, NautilusOrderSpec


def test_market_group_view_carries_relation_members() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    view = _view()
    group = MarketGroupView(
        group_id="basket-1",
        relation_id="all_markets",
        created_at=now,
        views_by_condition_id={view.condition_id: view},
        max_source_skew_ms=25,
        metrics={"relation_count": 1},
    )

    assert group.views_by_condition_id[view.condition_id] is view
    assert group.max_source_skew_ms == 25


def test_alpha_order_and_fill_events_are_immutable() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    event = AlphaFillEvent(
        strategy="vwap_momentum",
        market_id="market-1",
        condition_id="condition-1",
        token_id="token-up",
        side=Side.UP,
        order_id="order-1",
        client_order_id="client-1",
        reason=None,
        ts_event=now,
        metrics={"source": "test"},
        fill_price=0.81,
        shares=12.0,
        liquidity_side="TAKER",
    )

    assert event.fill_price == 0.81
    with pytest.raises(AttributeError):
        event.shares = 13.0  # type: ignore[misc]


def test_nautilus_order_spec_carries_quantity_and_tags() -> None:
    spec = NautilusOrderSpec(
        instrument_id="token-up.POLYMARKET",
        side=Side.UP,
        price=0.81,
        quantity=12.0,
        intent=OrderIntent.PASSIVE_GTD,
        expiry_seconds=45,
        pair_id="pair-1",
        reduce_only=False,
        hedge_leg=True,
        tags={"strategy": "vwap_momentum"},
    )

    assert spec.quantity == 12.0
    assert spec.tags["strategy"] == "vwap_momentum"
```

Create `tests/test_alpha_state.py`:

```python
from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

from polysignal_lab.alpha.state import json_safe_state, restore_utc_datetime
from polysignal_lab.domain.enums import Side


def test_json_safe_state_encodes_domain_values_deterministically() -> None:
    payload = {
        "side": Side.UP,
        "seen": {"b", "a"},
        "window": deque([1, 2]),
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }

    assert json_safe_state(payload) == {
        "side": "UP",
        "seen": ["a", "b"],
        "window": [1, 2],
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def test_restore_utc_datetime_requires_iso_string() -> None:
    restored = restore_utc_datetime("2026-01-01T00:00:00+00:00")

    assert restored.tzinfo is not None
    assert restored.isoformat() == "2026-01-01T00:00:00+00:00"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_types.py tests/test_alpha_state.py -v
```

Expected: FAIL because new alpha event/group/order/state symbols do not exist.

- [ ] **Step 3: Add alpha contracts**

Add these exact dataclasses/protocols to `src/polysignal_lab/alpha/types.py`:

```python
@dataclass(frozen=True, slots=True)
class MarketGroupView:
    group_id: str
    relation_id: str
    created_at: datetime
    views_by_condition_id: Mapping[str, MarketView]
    max_source_skew_ms: int
    metrics: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AlphaOrderEvent:
    strategy: str
    market_id: str
    condition_id: str
    token_id: str
    side: Side
    order_id: str
    client_order_id: str | None
    reason: str | None
    ts_event: datetime
    metrics: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AlphaFillEvent(AlphaOrderEvent):
    fill_price: float
    shares: float
    liquidity_side: str | None


@dataclass(frozen=True, slots=True)
class NautilusOrderSpec:
    instrument_id: str
    side: Side
    price: float
    quantity: float
    intent: OrderIntent
    expiry_seconds: int | None
    pair_id: str | None
    reduce_only: bool
    hedge_leg: bool
    tags: Mapping[str, str]


class StatefulAlphaCore(AlphaCore, Protocol):
    def on_order_submitted(self, event: AlphaOrderEvent) -> None: ...
    def on_order_accepted(self, event: AlphaOrderEvent) -> None: ...
    def on_order_rejected(self, event: AlphaOrderEvent) -> None: ...
    def on_order_canceled(self, event: AlphaOrderEvent) -> None: ...
    def on_order_expired(self, event: AlphaOrderEvent) -> None: ...
    def on_order_filled(self, event: AlphaFillEvent) -> list[AlphaDecision]: ...
    def save_state(self) -> Mapping[str, object]: ...
    def load_state(self, payload: Mapping[str, object]) -> None: ...


class GroupAlphaCore(Protocol):
    def evaluate_group(self, view: MarketGroupView) -> list[AlphaDecision]: ...
```

Create `src/polysignal_lab/alpha/state.py` with deterministic conversion of `Enum`, `datetime`, `deque`, `set`, `tuple`, `list`, and `Mapping` values.

- [ ] **Step 4: Run tests to verify they pass**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_types.py tests/test_alpha_state.py tests/test_nautilus_state.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/alpha/types.py src/polysignal_lab/alpha/state.py src/polysignal_lab/alpha/__init__.py tests/test_alpha_types.py tests/test_alpha_state.py
git commit -m "feat: add alpha runtime contracts"
```

---

### Task 3: Nautilus Custom Data and Market View Assembly

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/market_data.py`
- Create: `src/polysignal_lab/nautilus_runtime/sidecar_data.py`
- Create: `src/polysignal_lab/nautilus_runtime/state.py`
- Modify: `src/polysignal_lab/nautilus_bridge/market_registry.py`
- Modify: `src/polysignal_lab/nautilus_bridge/market_view_assembler.py`
- Modify: `src/polysignal_lab/nautilus_bridge/external_data.py`
- Create: `tests/test_nautilus_custom_data.py`
- Create: `tests/test_nautilus_sidecar_actor.py`
- Modify: `tests/test_nautilus_market_view_assembler.py`

**Interfaces:**
- Consumes: existing `ExternalDataSidecar`, `PolymarketMarketRegistry`, `MarketViewAssembler`.
- Produces: custom data classes `PolySignalSpotData`, `PolySignalPriceToBeatData`, `PolySignalMarketMetaData`, `register_polysignal_data_types()`, `SidecarDataActor`, and a book/trade provider that can read Nautilus cache or test fakes.

- [ ] **Step 1: Write custom data serialization tests**

Create `tests/test_nautilus_custom_data.py`:

```python
from __future__ import annotations

from polysignal_lab.nautilus_runtime.market_data import (
    PolySignalMarketMetaData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
)


def test_custom_spot_data_round_trips_dict() -> None:
    data = PolySignalSpotData(asset="BTC", symbol="BTCUSD", price=100000.0, source="polymarket_rtds", freshness_ms=10, ts_event=1, ts_init=2)

    assert PolySignalSpotData.from_dict(data.to_dict()) == data


def test_custom_price_to_beat_data_round_trips_dict() -> None:
    data = PolySignalPriceToBeatData(
        condition_id="condition-1",
        value=100000.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=12,
        ts_event=1,
        ts_init=2,
    )

    assert PolySignalPriceToBeatData.from_dict(data.to_dict()) == data


def test_custom_market_meta_data_round_trips_dict() -> None:
    data = PolySignalMarketMetaData(
        market_id="market-1",
        market_slug="slug-1",
        condition_id="condition-1",
        asset="BTC",
        timeframe="5m",
        start_ts_ns=1,
        end_ts_ns=2,
        up_token_id="up",
        down_token_id="down",
        ts_event=3,
        ts_init=4,
    )

    assert PolySignalMarketMetaData.from_dict(data.to_dict()) == data
```

- [ ] **Step 2: Write sidecar actor tests**

Create `tests/test_nautilus_sidecar_actor.py`:

```python
from __future__ import annotations

from polysignal_lab.nautilus_runtime.market_data import PolySignalPriceToBeatData, PolySignalSpotData
from polysignal_lab.nautilus_runtime.sidecar_data import SidecarDataActor


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    def publish_data(self, data_type: object, data: object) -> None:
        self.published.append(data)


def test_sidecar_actor_updates_registry_and_publishes_spot() -> None:
    publisher = FakePublisher()
    actor = SidecarDataActor(publisher=publisher)

    actor.publish_spot(asset="BTC", symbol="BTCUSD", price=100001.0, source="polymarket_rtds", freshness_ms=9, ts_event=1, ts_init=2)

    assert isinstance(publisher.published[-1], PolySignalSpotData)
    assert actor.sidecar.spot_for("btc").price == 100001.0


def test_sidecar_actor_updates_registry_and_publishes_price_to_beat() -> None:
    publisher = FakePublisher()
    actor = SidecarDataActor(publisher=publisher)

    actor.publish_price_to_beat(
        condition_id="condition-1",
        value=100000.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=15,
        ts_event=1,
        ts_init=2,
    )

    assert isinstance(publisher.published[-1], PolySignalPriceToBeatData)
    assert actor.sidecar.ptb_for("condition-1").verified is True
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_custom_data.py tests/test_nautilus_sidecar_actor.py tests/test_nautilus_market_view_assembler.py -v
```

Expected: FAIL because `nautilus_runtime.market_data` and `SidecarDataActor` do not exist.

- [ ] **Step 4: Implement custom data without importing Nautilus by default**

Create dataclasses with `ts_event` and `ts_init` properties plus `to_dict()` / `from_dict()` methods. Wrap Nautilus-only imports inside `register_polysignal_data_types()`:

```python
def register_polysignal_data_types() -> None:
    from nautilus_trader.serialization.base import register_serializable_type

    register_serializable_type(PolySignalSpotData, PolySignalSpotData.to_dict, PolySignalSpotData.from_dict)
    register_serializable_type(PolySignalPriceToBeatData, PolySignalPriceToBeatData.to_dict, PolySignalPriceToBeatData.from_dict)
    register_serializable_type(PolySignalMarketMetaData, PolySignalMarketMetaData.to_dict, PolySignalMarketMetaData.from_dict)
```

`SidecarDataActor` must accept an injected publisher with `publish_data(data_type, data)` so tests do not import Nautilus. In the real actor path, `data_type` is `DataType(PolySignalSpotData)`, `DataType(PolySignalPriceToBeatData)`, or `DataType(PolySignalMarketMetaData)`.

- [ ] **Step 5: Extend assembler missing-data behavior**

Keep existing behavior from `tests/test_nautilus_market_view_assembler.py`: missing book leg returns `None`, missing spot/PTB returns `None`, freshness max uses orderbook and spot lag. Add metadata ingestion from `PolySignalMarketMetaData` so market pair lookup by condition and token is available without the legacy scheduler.

- [ ] **Step 6: Run tests to verify they pass**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_custom_data.py tests/test_nautilus_sidecar_actor.py tests/test_nautilus_market_registry.py tests/test_nautilus_external_data.py tests/test_nautilus_market_view_assembler.py tests/test_nautilus_dependency_boundary.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime src/polysignal_lab/nautilus_bridge tests/test_nautilus_custom_data.py tests/test_nautilus_sidecar_actor.py tests/test_nautilus_market_view_assembler.py
git commit -m "feat: add nautilus custom data bus"
```

---

### Task 4: Alpha Equivalence Harness

**Files:**
- Create: `tests/alpha_equivalence.py`
- Modify: `tests/factories.py`
- Create: `tests/test_alpha_equivalence_harness.py`

**Interfaces:**
- Consumes: legacy `BaseStrategy.evaluate(MarketSnapshot)` and core `evaluate(MarketView)` outputs.
- Produces: `normalize_candidate(candidate) -> dict[str, object]`, `normalize_decision(decision) -> dict[str, object]`, `assert_legacy_core_equivalent(strategy, core, snapshot)`.

- [ ] **Step 1: Write failing harness tests**

Create `tests/test_alpha_equivalence_harness.py`:

```python
from __future__ import annotations

from tests.alpha_equivalence import normalize_candidate, normalize_decision
from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate


def test_normalizers_compare_semantic_fields_only() -> None:
    candidate = SignalCandidate.build(
        strategy="skew_mean_reversion",
        asset="BTC",
        timeframe="5m",
        market_id="market-1",
        market_slug="slug-1",
        condition_id="condition-1",
        token_id="token-up",
        side=Side.UP,
        confidence=0.7,
        entry_reference_price=0.4,
        max_entry_price=0.45,
        seconds_to_close=60,
        data_freshness_ms=10,
        reason_codes=["SKEW_MEAN_REVERSION"],
        metrics={"spread": 0.2},
        snapshot_id="snapshot-host-generated",
    )
    decision = AlphaDecision(
        strategy="skew_mean_reversion",
        asset="BTC",
        timeframe="5m",
        market_id="market-1",
        market_slug="slug-1",
        condition_id="condition-1",
        token_id="token-up",
        side=Side.UP,
        confidence=0.7,
        entry_reference_price=0.4,
        max_entry_price=0.45,
        seconds_to_close=60,
        data_freshness_ms=10,
        reason_codes=("SKEW_MEAN_REVERSION",),
        metrics={"spread": 0.2},
    )

    assert normalize_candidate(candidate) == normalize_decision(decision)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_equivalence_harness.py -v
```

Expected: FAIL because `tests.alpha_equivalence` does not exist.

- [ ] **Step 3: Implement harness**

Create `tests/alpha_equivalence.py` with semantic fields only:

```python
SEMANTIC_FIELDS = (
    "strategy",
    "asset",
    "timeframe",
    "market_id",
    "market_slug",
    "condition_id",
    "token_id",
    "side",
    "confidence",
    "entry_reference_price",
    "max_entry_price",
    "seconds_to_close",
    "data_freshness_ms",
    "reason_codes",
    "metrics",
    "order_intent",
    "expiry_seconds",
    "pair_id",
    "hedge_leg",
)
```

`normalize_candidate()` reads fields from `SignalCandidate`, converting side and order intent to enum values. `normalize_decision()` reads fields from `AlphaDecision`, flattening `decision.order_intent.intent`, `expiry_seconds`, and `pair_id`. `assert_legacy_core_equivalent()` builds a `MarketView` with `market_view_from_snapshot(snapshot)` and compares normalized lists.

- [ ] **Step 4: Run tests to verify they pass**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_equivalence_harness.py tests/test_alpha_ptb_diff.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/alpha_equivalence.py tests/factories.py tests/test_alpha_equivalence_harness.py
git commit -m "test: add alpha equivalence harness"
```

---

### Task 5: Simple and Medium Alpha Cores

**Files:**
- Create: `src/polysignal_lab/alpha/skew_mean_reversion_core.py`
- Create: `src/polysignal_lab/alpha/binary_momentum_core.py`
- Create: `src/polysignal_lab/alpha/fibonacci_core.py`
- Create: `src/polysignal_lab/alpha/one_cent_buy_core.py`
- Create: `src/polysignal_lab/alpha/ninety_nine_cent_sniper_core.py`
- Modify: matching files under `src/polysignal_lab/strategies/`
- Create: `tests/test_alpha_skew_mean_reversion.py`
- Create: `tests/test_alpha_binary_momentum.py`
- Create: `tests/test_alpha_fibonacci.py`
- Create: `tests/test_alpha_one_cent_buy.py`
- Create: `tests/test_alpha_ninety_nine_cent_sniper.py`

**Interfaces:**
- Produces: `SkewMeanReversionAlphaCore`, `BinaryMomentumAlphaCore`, `FibonacciAlphaCore`, `OneCentBuyAlphaCore`, `NinetyNineCentSniperAlphaCore`.
- State events: `OneCentBuyAlphaCore.on_order_accepted()` marks submitted levels; `NinetyNineCentSniperAlphaCore.on_order_accepted()` marks sniped side; `BinaryMomentumAlphaCore.on_order_accepted()` marks entered market. Candidate creation must not permanently consume those guards.

- [ ] **Step 1: Write failing parametrized equivalence tests**

Each new test file contains one controlled fixture and one mutation-timing test where applicable. Example for `tests/test_alpha_one_cent_buy.py`:

```python
from __future__ import annotations

from polysignal_lab.alpha.one_cent_buy_core import OneCentBuyAlphaCore
from polysignal_lab.alpha.types import AlphaOrderEvent
from polysignal_lab.domain.enums import Side
from polysignal_lab.strategies.config import OneCentBuyConfig
from polysignal_lab.strategies.one_cent_buy import OneCentBuyStrategy
from tests.alpha_equivalence import assert_legacy_core_equivalent
from tests.factories import sample_snapshot


def test_one_cent_buy_core_matches_legacy_candidate() -> None:
    config = OneCentBuyConfig(enabled=True, entry_prices=[0.01], min_seconds_after_open=0, max_seconds_after_open=300)
    snapshot = sample_snapshot(up_ask=0.01, down_ask=0.02, seconds_to_close=240)

    assert_legacy_core_equivalent(OneCentBuyStrategy(config), OneCentBuyAlphaCore(config), snapshot)


def test_one_cent_buy_level_marks_only_after_order_acceptance() -> None:
    config = OneCentBuyConfig(enabled=True, entry_prices=[0.01], min_seconds_after_open=0, max_seconds_after_open=300)
    snapshot = sample_snapshot(up_ask=0.01, down_ask=0.02, seconds_to_close=240)
    core = OneCentBuyAlphaCore(config)

    first = core.evaluate_view_from_snapshot_for_test(snapshot)
    second = core.evaluate_view_from_snapshot_for_test(snapshot)

    assert first
    assert second

    core.on_order_accepted(
        AlphaOrderEvent(
            strategy="one_cent_buy",
            market_id=first[0].market_id,
            condition_id=first[0].condition_id,
            token_id=first[0].token_id,
            side=Side.UP,
            order_id="order-1",
            client_order_id="client-1",
            reason=None,
            ts_event=first[0].metrics["created_at_for_test"],
            metrics={"level_price": 0.01},
        )
    )

    assert core.evaluate_view_from_snapshot_for_test(snapshot) == []
```

Use the same test shape for `binary_momentum` and `ninety_nine_cent_sniper`; `skew_mean_reversion` has no mutation-timing test; `fibonacci` adds a `save_state()` / `load_state()` round trip for candles and detector fields.

- [ ] **Step 2: Run tests to verify they fail**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_skew_mean_reversion.py tests/test_alpha_binary_momentum.py tests/test_alpha_fibonacci.py tests/test_alpha_one_cent_buy.py tests/test_alpha_ninety_nine_cent_sniper.py -v
```

Expected: FAIL because the five core modules do not exist.

- [ ] **Step 3: Extract cores by moving formulas, not rewriting formulas**

For each strategy, copy the legacy `evaluate()` decision logic into `Core.evaluate(view: MarketView)`. Replace `_candidate(snapshot, ...)` with a local `_decision(view, ...) -> AlphaDecision | None`. Keep config class names unchanged. Keep helper classes (`ZigZagDetector`, Fibonacci calculator, rolling stats) either in the core module or imported from the legacy module only if that import does not import scheduler, Telegram, SQLite, Nautilus, paper, or snapshots.

- [ ] **Step 4: Turn legacy strategies into adapters**

Each matching `src/polysignal_lab/strategies/<strategy>.py` must construct its core in `__init__`, convert `MarketSnapshot` to `MarketView`, call the core, and convert `AlphaDecision` back to `SignalCandidate`. Callback methods forward to the core event methods. Keep public class names and `name` values unchanged for equivalence tests.

- [ ] **Step 5: Run tests to verify they pass**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_skew_mean_reversion.py tests/test_alpha_binary_momentum.py tests/test_alpha_fibonacci.py tests/test_alpha_one_cent_buy.py tests/test_alpha_ninety_nine_cent_sniper.py tests/test_strategies.py tests/test_strategy_readiness.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/polysignal_lab/alpha src/polysignal_lab/strategies tests/test_alpha_skew_mean_reversion.py tests/test_alpha_binary_momentum.py tests/test_alpha_fibonacci.py tests/test_alpha_one_cent_buy.py tests/test_alpha_ninety_nine_cent_sniper.py
git commit -m "feat: extract simple alpha cores"
```

---

### Task 6: Callback-Heavy Alpha Cores

**Files:**
- Create: `src/polysignal_lab/alpha/late_consensus_core.py`
- Create: `src/polysignal_lab/alpha/vwap_momentum_core.py`
- Modify: `src/polysignal_lab/strategies/late_consensus.py`
- Modify: `src/polysignal_lab/strategies/vwap_momentum.py`
- Create: `tests/test_alpha_late_consensus.py`
- Create: `tests/test_alpha_vwap_momentum.py`

**Interfaces:**
- Produces: `LateConsensusAlphaCore`, `VWAPMomentumAlphaCore`.
- `LateConsensusAlphaCore.on_order_accepted()` updates `_last_entry_at`, `_accepted_counts`, `_last_favorite`.
- `VWAPMomentumAlphaCore.on_order_accepted()` consumes `_can_enter` and pending samples; `on_order_rejected()` reverts pending trade samples; `on_order_filled()` returns a hedge `AlphaDecision`; `on_order_expired()` clears pending hedge.

- [ ] **Step 1: Write failing mutation-timing tests**

Create `tests/test_alpha_late_consensus.py` with tests proving repeated candidate generation does not increment sequence until `on_order_accepted()`. Create `tests/test_alpha_vwap_momentum.py` with tests matching current `tests/test_vwap_momentum.py` invariants: gate rejection does not consume entry guard, accepted signal consumes guard, filled taker order creates a hedge decision, filled GTD hedge does not create a reverse hedge.

- [ ] **Step 2: Run tests to verify they fail**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_late_consensus.py tests/test_alpha_vwap_momentum.py -v
```

Expected: FAIL because both core modules do not exist.

- [ ] **Step 3: Extract LateConsensus core**

Move `src/polysignal_lab/strategies/late_consensus.py:83-249` formula and state into `LateConsensusAlphaCore`. Preserve `entry_sequence` and dedupe suffix behavior by deriving sequence from accepted counts only. The legacy adapter's `notify_signal_accepted()` must call `core.on_order_accepted(AlphaOrderEvent(...))`.

- [ ] **Step 4: Extract VWAPMomentum core**

Move `TradeHistory` and `src/polysignal_lab/strategies/vwap_momentum.py:143-457` logic into `VWAPMomentumAlphaCore`. Replace `follow_up_signals()` with `on_order_filled() -> list[AlphaDecision]`. The legacy adapter keeps `follow_up_signals()` only by translating fill/order objects into the new core event and converting returned decisions back to `SignalCandidate` for current scheduler tests.

- [ ] **Step 5: Add state round-trip tests**

Each test file must assert `save_state()` / `load_state()` preserves the fields named in the spec: LateConsensus `_last_favorite`, `_last_entry_at`, `_accepted_counts`; VWAP `TradeHistory`, `_can_enter`, `_last_trade_signatures`, `_seen_trade_signatures`, `_pending_hedges`.

- [ ] **Step 6: Run tests to verify they pass**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_late_consensus.py tests/test_alpha_vwap_momentum.py tests/test_late_consensus.py tests/test_vwap_momentum.py tests/test_reference_strategy_parity.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/polysignal_lab/alpha/late_consensus_core.py src/polysignal_lab/alpha/vwap_momentum_core.py src/polysignal_lab/strategies/late_consensus.py src/polysignal_lab/strategies/vwap_momentum.py tests/test_alpha_late_consensus.py tests/test_alpha_vwap_momentum.py
git commit -m "feat: extract callback alpha cores"
```

---

### Task 7: Position and Cross-Market Alpha Cores

**Files:**
- Create: `src/polysignal_lab/alpha/dump_hedge_core.py`
- Create: `src/polysignal_lab/alpha/mid_price_sizing_core.py`
- Create: `src/polysignal_lab/alpha/pre_order_market_core.py`
- Create: `src/polysignal_lab/alpha/low_side_dual_reversion_core.py`
- Create: `src/polysignal_lab/alpha/cross_market_core.py`
- Modify: matching legacy strategy files
- Create: `tests/test_alpha_dump_hedge.py`
- Create: `tests/test_alpha_mid_price_sizing.py`
- Create: `tests/test_alpha_pre_order_market.py`
- Create: `tests/test_alpha_low_side_dual_reversion.py`
- Create: `tests/test_alpha_cross_market.py`

**Interfaces:**
- Produces: `DumpHedgeAlphaCore`, `MidPriceSizingAlphaCore`, `PreOrderMarketAlphaCore`, `LowSideDualReversionAlphaCore`, `CrossMarketAlphaCore`.
- `CrossMarketAlphaCore.evaluate_group(view: MarketGroupView) -> list[AlphaDecision]` is the only group core API.

- [ ] **Step 1: Write failing state/event tests**

Tests must prove:

```text
dump_hedge: dump detection candidate creation does not mark final entry before accepted/fill event.
mid_price_sizing: layer count increments only from on_order_filled().
pre_order_market: pre-open candidate creation does not permanently mark _pre_ordered before submitted/accepted event.
low_side_dual_reversion: hedge decisions consume actual position state from fill events.
cross_market_bot: evaluate_group() matches legacy evaluate_group() on relation fixtures and leg failure marks basket failed.
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_dump_hedge.py tests/test_alpha_mid_price_sizing.py tests/test_alpha_pre_order_market.py tests/test_alpha_low_side_dual_reversion.py tests/test_alpha_cross_market.py -v
```

Expected: FAIL because the five core modules do not exist.

- [ ] **Step 3: Extract position-aware cores**

Move the current formula and state fields exactly as inventoried by source:

```text
dump_hedge: _price_stats, _entered_markets, _positions, _dump_detected, _last_price.
mid_price_sizing: _layer_count, _entry_prices.
pre_order_market: _pre_ordered, _entered_markets, _positions, _reconciled.
low_side_dual_reversion: _entered_markets, _positions.
cross_market_bot: _relations, _market_to_relations, _active_baskets.
```

Do not keep scheduler callbacks as business logic. Translate them to alpha event methods and state methods.

- [ ] **Step 4: Preserve legacy adapters for equivalence**

Legacy strategy files keep `evaluate(snapshot)`, `notify_fill()`, and `notify_leg_failure()` signatures, but delegate to alpha cores. `CrossMarketBotStrategy.evaluate_group(context)` builds `MarketGroupView` from `CrossMarketEvaluationContext` and delegates to `CrossMarketAlphaCore.evaluate_group()`.

- [ ] **Step 5: Run tests to verify they pass**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_dump_hedge.py tests/test_alpha_mid_price_sizing.py tests/test_alpha_pre_order_market.py tests/test_alpha_low_side_dual_reversion.py tests/test_alpha_cross_market.py tests/test_cross_market_coordination.py tests/test_reference_strategy_parity.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/polysignal_lab/alpha src/polysignal_lab/strategies tests/test_alpha_dump_hedge.py tests/test_alpha_mid_price_sizing.py tests/test_alpha_pre_order_market.py tests/test_alpha_low_side_dual_reversion.py tests/test_alpha_cross_market.py
git commit -m "feat: extract position alpha cores"
```

---

### Task 8: DecisionPolicyActor Parity

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/decision_policy.py`
- Create: `tests/test_nautilus_decision_policy.py`
- Modify: `tests/test_signal_gate.py` only if shared fixtures need export.

**Interfaces:**
- Consumes: `AlphaDecision`, `MarketView`, existing `SignalGate`, `SignalArbiter`, `ConsensusEngine`, `SignalPipeline` disable semantics.
- Produces: `ApprovedDecision`, `RejectedDecision`, `DecisionPolicyActor.evaluate(decision, view) -> ApprovedDecision | RejectedDecision`, `set_strategy_enabled(name, enabled)`, `save_state()`, `load_state()`.

- [ ] **Step 1: Write failing policy tests**

Create tests covering first-failure order from `SignalGate.evaluate()`: market active, time, book freshness, spot freshness, spread, max entry, GTD expiry, confidence, dedupe, rate limit. Add manual disable and dependency disable tests mirroring `tests/test_signal_pipeline_manual_disable.py`.

- [ ] **Step 2: Run tests to verify they fail**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_decision_policy.py -v
```

Expected: FAIL because `DecisionPolicyActor` does not exist.

- [ ] **Step 3: Implement typed policy output**

`ApprovedDecision` and `RejectedDecision` are frozen dataclasses. Policy converts an `AlphaDecision` to the minimum `SignalCandidate` shape required by existing gate/arbiter/consensus code, applies the same first-failure order, and emits order-oriented output. It must not write SQLite, publish Telegram, build snapshots, or mutate a paper wallet.

- [ ] **Step 4: Preserve rejection reason semantics**

Map existing `RejectedSignal.reason_code` and details into `RejectedDecision.reason_code` and `detail`. Keep dashboard/JSONL strings stable.

- [ ] **Step 5: Run tests to verify they pass**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_decision_policy.py tests/test_signal_gate.py tests/test_signal_arbiter.py tests/test_signal_pipeline_manual_disable.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/decision_policy.py tests/test_nautilus_decision_policy.py
git commit -m "feat: add nautilus decision policy"
```

---

### Task 9: Order Mapping and Single-Market Nautilus Wrappers

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/strategies/base.py`
- Create: 12 single-market wrapper files under `src/polysignal_lab/nautilus_runtime/strategies/`
- Create: `src/polysignal_lab/nautilus_runtime/execution.py`
- Create: `tests/test_nautilus_order_mapping.py`
- Create: `tests/test_nautilus_strategy_wrappers.py`

**Interfaces:**
- Consumes: `ApprovedDecision`, `NautilusOrderSpec`, alpha cores, `MarketViewAssembler`.
- Produces: `PolySignalNautilusStrategy`, `order_spec_from_decision(decision, fixed_stake_usdc)`, and wrappers for `ptb_diff`, `skew_mean_reversion`, `binary_momentum`, `fibonacci_bot`, `one_cent_buy`, `ninety_nine_cent_sniper`, `late_consensus`, `vwap_momentum`, `dump_hedge`, `mid_price_sizing`, `pre_order_market`, `low_side_dual_reversion`.

- [ ] **Step 1: Write failing order mapping tests**

Create `tests/test_nautilus_order_mapping.py` covering:

```text
TAKER_FAK -> IOC/FAK buy limit against best ask, rejects insufficient depth.
TAKER_FOK -> FOK buy limit, full fill required.
PASSIVE_GTD -> GTD limit with expire time from expiry_seconds.
No explicit order intent -> default paper-safe taker order using fixed_stake_usdc / max_entry_price quantity.
```

- [ ] **Step 2: Write failing wrapper tests**

Create `tests/test_nautilus_strategy_wrappers.py` with a fake assembler, fake policy, fake order submitter, and fake Nautilus events. Assert each wrapper subscribes to required data, calls its core, routes decisions to policy, submits only approved decisions, rejects do not mutate core state, and stateful wrappers round-trip via `on_save()`/`on_load()`.

- [ ] **Step 3: Run tests to verify they fail**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_order_mapping.py tests/test_nautilus_strategy_wrappers.py -v
```

Expected: FAIL because runtime wrappers and mapping do not exist.

- [ ] **Step 4: Implement base wrapper**

`PolySignalNautilusStrategy` responsibilities:

```text
on_start(): subscribe instrument data and sidecar DataType subscriptions.
on_data(data): update sidecar registries or trigger condition evaluation.
evaluate_condition(condition_id): assemble MarketView, evaluate core, send each decision to DecisionPolicyActor.
submit_approved(approved): map to Nautilus order instruction and submit through injected submitter or Strategy API.
order callbacks: translate Nautilus order/fill/cancel/expire events to AlphaOrderEvent/AlphaFillEvent.
on_save()/on_load(): encode/decode core state with the shared state codec.
```

- [ ] **Step 5: Implement 12 wrappers**

Each wrapper only wires the config class, core class, strategy name, and required data names. Business formulas stay in alpha cores. VWAP's fill callback directly submits hedge decisions returned by `on_order_filled()`; it must not use `_follow_up_signals`.

- [ ] **Step 6: Run tests to verify they pass**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_order_mapping.py tests/test_nautilus_strategy_wrappers.py tests/test_nautilus_strategy_base.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/strategies src/polysignal_lab/nautilus_runtime/execution.py tests/test_nautilus_order_mapping.py tests/test_nautilus_strategy_wrappers.py
git commit -m "feat: add nautilus strategy wrappers"
```

---

### Task 10: Cross-Market Nautilus Support

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/strategies/cross_market_bot.py`
- Create: `src/polysignal_lab/nautilus_runtime/group_views.py`
- Create: `tests/test_nautilus_cross_market.py`

**Interfaces:**
- Consumes: `CrossMarketAlphaCore.evaluate_group(view: MarketGroupView)`, relation data from legacy config/registry.
- Produces: `MarketGroupViewAssembler`, cross-market wrapper, basket order coordinator, leg failure propagation.

- [ ] **Step 1: Write failing cross-market tests**

Create tests that build two related `MarketView` instances with controlled skew, assert `evaluate_group()` emits the same normalized output as legacy `CrossMarketBotStrategy.evaluate_group()`, assert linked orders share relation IDs, and assert a leg failure marks the basket failed.

- [ ] **Step 2: Run test to verify it fails**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_cross_market.py -v
```

Expected: FAIL because group assembler and wrapper do not exist.

- [ ] **Step 3: Implement group view assembler and wrapper**

`MarketGroupViewAssembler` collects views by relation ID, rejects groups whose source skew exceeds configured `max_source_skew_ms`, and emits `MarketGroupView`. `CrossMarketNautilusStrategy` routes group decisions through `DecisionPolicyActor` and submits baskets with shared `pair_id`/relation tags.

- [ ] **Step 4: Run tests to verify they pass**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_cross_market.py tests/test_alpha_cross_market.py tests/test_cross_market_coordination.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/group_views.py src/polysignal_lab/nautilus_runtime/strategies/cross_market_bot.py tests/test_nautilus_cross_market.py
git commit -m "feat: add nautilus cross market strategy"
```

---

### Task 11: Paper Execution, Position Policy, and Settlement Actor

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/execution.py`
- Create: `src/polysignal_lab/nautilus_runtime/position_policy.py`
- Create: `src/polysignal_lab/nautilus_runtime/settlement.py`
- Create: `tests/test_nautilus_execution.py`
- Create: `tests/test_nautilus_position_policy.py`
- Create: `tests/test_nautilus_settlement_actor.py`

**Interfaces:**
- Consumes: `NautilusOrderSpec`, current `PaperTradingConfig`, current settlement resolver components `SettlementResolver`, `CtfResolutionClient`, `GammaResolutionClient`, `WsResolutionCache`.
- Produces: paper-only execution path inside Nautilus `ExecutionEngine`, `PositionPolicyActor`, `SettlementActor`.

- [ ] **Step 1: Write failing execution tests**

Tests cover FAK partial-depth rejection, FOK incomplete rejection, GTD expiry event, fixed stake sizing, exposure cap rejection before order submission, and fill event conversion to `AlphaFillEvent`.

- [ ] **Step 2: Write failing settlement tests**

Tests mirror current `tests/test_scheduler_settlement_resolution.py` and `tests/test_settlement.py`: chain > Gamma > WS hints order, resolver unknown/error plus local `CANCELLED` refunds, resolver unknown/error plus local `RESOLVED` settles.

- [ ] **Step 3: Run tests to verify they fail**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_execution.py tests/test_nautilus_position_policy.py tests/test_nautilus_settlement_actor.py -v
```

Expected: FAIL because execution, position, and settlement actors are incomplete.

- [ ] **Step 4: Prove or implement paper execution path**

First attempt a test-only Nautilus sandbox construction with Polymarket instruments. If Nautilus cannot simulate Polymarket `BinaryOption` live data in sandbox, implement `PolySignalPaperExecutionClient` in `nautilus_runtime/execution.py`. It must not submit network orders, must not accept credentials, must drive fills from Nautilus market data/cache, and must emit standard order/fill/cancel/expire events to wrappers.

- [ ] **Step 5: Implement position policy**

Move global paper exits from `PaperExitEngine` into `PositionPolicyActor`: take-profit bid, stop-loss bid, and max hold time. Keep strategy-specific exit metrics in alpha cores when they are alpha semantics.

- [ ] **Step 6: Implement settlement actor**

`SettlementActor` subscribes to Nautilus position/account state, checks open positions periodically, resolves through the existing three-source resolver, and settles/refunds through the paper execution client. It must preserve the local `CANCELLED` / `RESOLVED` fallback when the resolver returns unknown/error.

- [ ] **Step 7: Run tests to verify they pass**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_execution.py tests/test_nautilus_position_policy.py tests/test_nautilus_settlement_actor.py tests/test_paper_execution_preflight.py tests/test_scheduler_settlement_resolution.py tests/test_settlement.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/execution.py src/polysignal_lab/nautilus_runtime/position_policy.py src/polysignal_lab/nautilus_runtime/settlement.py tests/test_nautilus_execution.py tests/test_nautilus_position_policy.py tests/test_nautilus_settlement_actor.py
git commit -m "feat: add nautilus paper execution"
```

---

### Task 12: Observability, Telegram, and Dashboard Continuity

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/observability.py`
- Modify: `src/polysignal_lab/publish/telegram_bot.py`
- Modify: `src/polysignal_lab/dashboard/app.py` only if health rendering needs labels.
- Create: `tests/test_nautilus_observability.py`
- Modify: `tests/test_telegram_bot_service.py`
- Modify: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: existing `SQLiteStore`, `JSONLStore`, `TelegramPublisher`, `TelegramBotService`, dashboard table queries.
- Produces: `ObservabilityActor` that writes current table names, JSONL streams, Telegram messages, daily reports, health snapshots, and Telegram control integration for Nautilus strategies/policy.

- [ ] **Step 1: Write failing observability tests**

Create tests asserting approved/rejected/order/fill/position/settlement/health events write the same SQLite tables named by the spec and JSONL stream names used today. Assert `/health?fresh=<cachebuster>` payload includes `nautilus_node`, `polymarket_data_client`, `sidecar_spot_feed`, `sidecar_ptb_feed`, `decision_policy`, `paper_execution`, `settlement_actor`, `observability_actor`.

- [ ] **Step 2: Extend Telegram control tests**

Add a `TelegramBotService` fake Nautilus controller and assert `/status` still uses immediate `处理中…` placeholder then edits final content, and strategy disable toggles call `DecisionPolicyActor.set_strategy_enabled()` or a runtime controller method rather than `SignalPipeline`.

- [ ] **Step 3: Run tests to verify they fail**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_observability.py tests/test_telegram_bot_service.py tests/test_dashboard.py -v
```

Expected: FAIL until `ObservabilityActor` and Nautilus control adapter exist.

- [ ] **Step 4: Implement ObservabilityActor**

`ObservabilityActor` receives typed events only. It must call current `PersistenceService`/`SQLiteStore` methods, append current JSONL stream names, publish through `TelegramPublisher`, generate daily report rows from Nautilus fills/positions, and persist `health_snapshot` system events.

- [ ] **Step 5: Wire Telegram controls to a runtime controller**

Introduce a small protocol used by `TelegramBotService`:

```python
class StrategyControl(Protocol):
    def set_strategy_enabled(self, name: str, enabled: bool) -> None: ...
    def is_strategy_enabled(self, name: str) -> bool: ...
    def status_payload(self) -> Mapping[str, object]: ...
```

Implement adapters for legacy `SignalPipeline` and Nautilus `DecisionPolicyActor`; keep existing placeholder/edit behavior unchanged.

- [ ] **Step 6: Run tests to verify they pass**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_observability.py tests/test_telegram_bot_service.py tests/test_dashboard.py tests/test_storage_reporting_publish.py tests/test_reporting.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/observability.py src/polysignal_lab/publish/telegram_bot.py src/polysignal_lab/dashboard/app.py tests/test_nautilus_observability.py tests/test_telegram_bot_service.py tests/test_dashboard.py
git commit -m "feat: add nautilus observability actor"
```

---

### Task 13: TradingNode Assembly and Production Cutover

**Files:**
- Replace: `src/polysignal_lab/nautilus_runtime/node.py`
- Modify: `src/polysignal_lab/nautilus_runtime/config.py`
- Modify: `src/polysignal_lab/app/main.py`
- Modify: `config/signal_bot.yaml`
- Modify: `docker-compose.yml`
- Create: `tests/test_nautilus_node.py`
- Create: `tests/test_nautilus_cutover.py`

**Interfaces:**
- Consumes: all runtime actors/wrappers from Tasks 3-12.
- Produces: `build_trading_node(settings)`, `run_nautilus_cli(settings)`, formal `polysignal-nautilus` entry point, and production config `runtime.engine: nautilus`.

- [ ] **Step 1: Write failing node construction tests**

Create tests asserting `build_trading_node(Settings())` registers data clients but no live execution client, adds all 13 strategy wrappers, attaches policy/sidecar/settlement/observability actors, and can construct a small test-only node process without Polymarket live execution config.

- [ ] **Step 2: Write failing cutover tests**

Create tests asserting production config has `runtime.engine == "nautilus"`, `PolySignalScheduler._initialize_trading_components()` is not called by Nautilus CLI, production health component names do not include legacy `signal_pipeline` as executor, and source production path no longer constructs `PaperSimulator`, `PaperWallet`, or strategy schedule for Nautilus runtime.

- [ ] **Step 3: Run tests to verify they fail**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_cutover.py -v
```

Expected: FAIL because node assembly and cutover are not wired.

- [ ] **Step 4: Implement node builder with credential-free data proof**

If `PolymarketLiveDataClientFactory` cannot be configured without credential env fallback, default to PolySignal-owned public market data adapter in `nautilus_runtime/market_data.py`. The test must set dummy `POLYMARKET_*` env vars and prove default paper runtime does not read them or activate live execution.

- [ ] **Step 5: Wire all wrappers and actors**

`build_trading_node(settings)` creates the `TradingNode`, registers the data path, paper execution path, all 13 wrappers from `settings.strategies.explicit_strategy_names()`, `DecisionPolicyActor`, `SidecarDataActor`, `PositionPolicyActor`, `SettlementActor`, and `ObservabilityActor`.

- [ ] **Step 6: Flip production config and compose command**

Change `config/signal_bot.yaml`:

```yaml
runtime:
  engine: nautilus
```

Update Docker compose service command to use the Nautilus mode or script for the Nautilus target. Keep dashboard service compatible with existing SQLite tables.

- [ ] **Step 7: Run tests to verify they pass**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_cutover.py tests/test_cli_runtime_modes.py tests/test_nautilus_platform_boundary.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/node.py src/polysignal_lab/nautilus_runtime/config.py src/polysignal_lab/app/main.py config/signal_bot.yaml docker-compose.yml tests/test_nautilus_node.py tests/test_nautilus_cutover.py
git commit -m "feat: cut production runtime to nautilus"
```

---

### Task 14: Verification, Safety, and Legacy Retirement

**Files:**
- Modify: `src/polysignal_lab/app/scheduler.py` only to mark legacy scheduler test-only or remove production selection.
- Modify: `docs/NAUTILUS_BRIDGE_BOUNDARY.md`
- Modify: `tests/test_safety.py`
- Modify: `tests/test_integration_smoke.py`
- Modify: `tests/test_reference_strategy_parity.py`

**Interfaces:**
- Consumes: completed Nautilus runtime.
- Produces: final source/verification evidence that default runtime is Nautilus, paper-safe, and dashboard-compatible.

- [ ] **Step 1: Write final non-regression tests**

Add tests asserting:

```text
all 13 strategies have alpha cores and wrappers;
default package import succeeds without Nautilus installed;
forbidden live execution symbols are absent from default runtime paths;
legacy scheduler is not selected by production config;
reference parity fixtures still pass until legacy wrappers are removed;
read-only smoke evidence reports authenticated_endpoints=false and trading_actions=false.
```

- [ ] **Step 2: Run targeted test suites**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_alpha_types.py tests/test_alpha_state.py tests/test_alpha_*.py tests/test_nautilus_*.py tests/test_reference_strategy_parity.py tests/test_safety.py tests/test_integration_smoke.py -v
```

Expected: PASS.

- [ ] **Step 3: Run full default suite**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest
```

Expected: PASS, except any explicitly documented environment-only failure must be recorded with exact failing test name and reason.

- [ ] **Step 4: Run safety scan**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run polysignal-safety-scan .
```

Expected: `Safety scan passed`.

- [ ] **Step 5: Verify Nautilus environment**

```bash
ldd --version
uv sync --extra nautilus --python 3.12
uv run python -c "import nautilus_trader.adapters.polymarket"
```

Expected: glibc first line reports 2.35 or newer; sync succeeds or records source-build prerequisites; import exits 0.

- [ ] **Step 6: Rebuild formal runtime and verify health**

```bash
docker compose up -d --build --force-recreate
docker compose ps
```

Then read:

```text
http://127.0.0.1:8081/health?fresh=nautilus-full-runtime
```

Expected: health payload names `nautilus_node`, `polymarket_data_client`, `sidecar_spot_feed`, `sidecar_ptb_feed`, `decision_policy`, `paper_execution`, `settlement_actor`, and `observability_actor`; it does not name legacy `signal_pipeline` as the active executor.

- [ ] **Step 7: Update boundary doc with evidence**

Record exact outputs in `docs/NAUTILUS_BRIDGE_BOUNDARY.md`: default import, targeted tests, full suite, safety scan, glibc, uv sync/import Nautilus, Docker rebuild, `docker compose ps`, cache-busted health.

- [ ] **Step 8: Commit**

```bash
git add src/polysignal_lab/app/scheduler.py docs/NAUTILUS_BRIDGE_BOUNDARY.md tests/test_safety.py tests/test_integration_smoke.py tests/test_reference_strategy_parity.py
git commit -m "test: verify nautilus runtime cutover"
```

---

## Self-Review

**Spec coverage:**
- Wave 0 is covered by Task 1 and Task 14 Step 5.
- Wave 1 is covered by Task 3.
- Wave 2 is covered by Tasks 4-7.
- Wave 3 is covered by Task 9.
- Wave 4 is covered by Task 10.
- Wave 5 is covered by Task 8.
- Wave 6 is covered by Task 11.
- Wave 7 is covered by Task 12.
- Wave 8 is covered by Tasks 13-14.
- Safety non-goals are covered by Tasks 1, 13, and 14.
- Operations acceptance is covered by Task 14.

**Placeholder scan:**
- Red-flag placeholder phrases are absent except inside concrete strategy names such as PTBDiff.
- Every task has exact file paths, concrete tests, exact commands, and commit message.

**Type consistency:**
- `AlphaOrderEvent`, `AlphaFillEvent`, `MarketGroupView`, `NautilusOrderSpec`, `StatefulAlphaCore`, and `GroupAlphaCore` are defined before later tasks consume them.
- `DecisionPolicyActor.evaluate(decision, view)` produces `ApprovedDecision | RejectedDecision`, and wrappers consume that output.
- Strategy core class names match the approved spec and the current registry names.
