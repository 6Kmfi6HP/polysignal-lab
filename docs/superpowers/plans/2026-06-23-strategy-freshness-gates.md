# Strategy Freshness Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce strategy-specific freshness thresholds at the central signal gate so late-window strategies cannot publish signals using stale or missing orderbook or spot data.

**Architecture:** Add a small immutable `FreshnessPolicy` domain value, copy each strategy's resolved policy onto emitted `SignalCandidate`s, and keep `SignalGate` pure over `(candidate, snapshot)`. Gate checks compute measured lag once, apply the strictest available threshold, and persist structured rejection details through the existing `RejectedSignal` storage and dashboard read path.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest/pytest-asyncio, SQLite/JSONL stores, FastAPI dashboard.

## Global Constraints

- Scope is one standalone architecture change from `docs/superpowers/specs/2026-06-23-02-strategy-freshness-gates-design.md`; do not execute with specs 01 or 03-08 in the same implementation batch.
- No rewrite of individual strategies.
- No new market data source.
- No orderbook reconciliation changes; spec 01 owns book correctness.
- No change to paper fill model except consuming the same freshness decision if useful.
- `STALE_PRICE_TO_BEAT` and `max_anchor_staleness_ms` are only enforceable after snapshots carry anchor provenance, timestamp, and measured lag; current snapshots only expose `price_to_beat` plus `price_to_beat_source`/`price_to_beat_verified` metrics.
- Tests must use no live API calls.
- Run Python tests through the project venv with exact affected test paths, for example `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py -q`.
- Before considering the new version live in formal runtime, rebuild containers with `docker compose up -d --build --force-recreate`, then verify `docker compose ps` and startup logs/health.

---

## Research Notes

- Current global thresholds are 60s in `config/signal_bot.yaml`: `data.polymarket.max_book_staleness_ms: 60000` and `data.binance.max_price_staleness_ms: 60000`.
- Current model defaults already encode stricter intent: `LateConsensusConfig.max_orderbook_staleness_ms = 1_500` and `max_spot_staleness_ms = 1_500`; `VWAPMomentumConfig.max_orderbook_staleness_ms = 60_000`; `PTBExitConfig.market_data_max_lag_sec = 1`.
- Current `SignalGate._book_freshness()` and `_spot_freshness()` conflate missing and stale sources by returning only `STALE_ORDERBOOK` or `STALE_SPOT_PRICE`.
- `BaseStrategy._candidate()` is the single common candidate construction path for existing concrete strategies, so copying policy there avoids scheduler lookups and avoids adding policy data to every strategy `evaluate()` body.
- `RejectedSignal.details` is already persisted by `JSONLStore` and `SQLiteStore.insert_rejected_signal()`, and `/api/rejected-signals` already returns stored rejected rows.

## File Structure

- Create `src/polysignal_lab/domain/freshness.py`: immutable `FreshnessPolicy` value object shared by strategies, candidates, and gate.
- Modify `src/polysignal_lab/domain/signal.py`: add optional `freshness_policy` to `SignalCandidate` and `SignalCandidate.build()`.
- Modify `src/polysignal_lab/strategies/base.py`: expose default `freshness_policy` property and copy it into `_candidate()` results.
- Modify `src/polysignal_lab/strategies/config.py`: add `VWAPMomentumConfig.max_spot_staleness_ms` so VWAP can expose a complete book/spot policy without knowing global config.
- Modify `src/polysignal_lab/strategies/late_consensus.py`, `vwap_momentum.py`, and `ptb_diff.py`: expose configured freshness policies; remove PTB Diff's duplicate freshness rejection while keeping diagnostic metrics.
- Modify `src/polysignal_lab/signal_layer/gate.py`: return structured gate rejection objects, split missing from stale freshness reasons, apply strictest policy/global threshold, and include lag/threshold details.
- Modify tests: `tests/test_signal_gate.py`, `tests/test_late_consensus.py`, `tests/test_vwap_momentum.py`, `tests/test_config.py`, `tests/test_dashboard.py`, and optionally add `tests/test_freshness_policy.py` if the implementer prefers a focused policy test file.

### Task 1: Freshness Policy Candidate Plumbing

**Files:**
- Create: `src/polysignal_lab/domain/freshness.py`
- Modify: `src/polysignal_lab/domain/signal.py:1-92`
- Modify: `src/polysignal_lab/strategies/base.py:1-58`
- Test: `tests/test_signal_gate.py`

**Interfaces:**
- Consumes: existing `SignalCandidate.build` call sites through `BaseStrategy._candidate()`.
- Produces: `FreshnessPolicy(max_orderbook_staleness_ms: int | None = None, max_spot_staleness_ms: int | None = None, max_anchor_staleness_ms: int | None = None)` and `SignalCandidate.freshness_policy: FreshnessPolicy | None` for the gate.

- [ ] **Step 1: Write the failing candidate policy test**

Add these imports to `tests/test_signal_gate.py`:

```python
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import SignalCandidate
```

Append this test to `tests/test_signal_gate.py`:

```python
def test_signal_candidate_carries_freshness_policy() -> None:
    policy = FreshnessPolicy(
        max_orderbook_staleness_ms=1_500,
        max_spot_staleness_ms=1_500,
    )

    signal = SignalCandidate.build(
        strategy="unit",
        asset="BTC",
        timeframe="5m",
        market_id="mkt-1",
        market_slug="btc-updown-5m-test",
        condition_id="condition-1",
        token_id="token-up",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.82,
        max_entry_price=0.92,
        seconds_to_close=90,
        data_freshness_ms=10,
        reason_codes=["UNIT"],
        metrics={},
        freshness_policy=policy,
    )

    assert signal.freshness_policy == policy
    assert signal.model_dump()["freshness_policy"] == {
        "max_orderbook_staleness_ms": 1_500,
        "max_spot_staleness_ms": 1_500,
        "max_anchor_staleness_ms": None,
    }
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_signal_candidate_carries_freshness_policy -q
```

Expected: FAIL with an import or keyword error for `FreshnessPolicy` or `freshness_policy`.

- [ ] **Step 3: Create the freshness domain value**

Create `src/polysignal_lab/domain/freshness.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    max_orderbook_staleness_ms: int | None = None
    max_spot_staleness_ms: int | None = None
    max_anchor_staleness_ms: int | None = None
```

- [ ] **Step 4: Add policy to `SignalCandidate` and builder**

In `src/polysignal_lab/domain/signal.py`, add the import:

```python
from polysignal_lab.domain.freshness import FreshnessPolicy
```

Add this field after `data_freshness_ms` in `SignalCandidate`:

```python
    freshness_policy: FreshnessPolicy | None = None
```

Add this keyword parameter after `metrics` in `SignalCandidate.build()`:

```python
        freshness_policy: FreshnessPolicy | None = None,
```

Add this value to the `return cls(` call immediately after `data_freshness_ms=data_freshness_ms`:

```python
            freshness_policy=freshness_policy,
```

The resulting builder signature section should be:

```python
        seconds_to_close: int | None,
        data_freshness_ms: int | None,
        reason_codes: list[str],
        metrics: dict[str, Any],
        freshness_policy: FreshnessPolicy | None = None,
```

- [ ] **Step 5: Add the strategy policy hook**

In `src/polysignal_lab/strategies/base.py`, add the import:

```python
from polysignal_lab.domain.freshness import FreshnessPolicy
```

Add this property to `BaseStrategy` after the `name: str` line:

```python
    @property
    def freshness_policy(self) -> FreshnessPolicy | None:
        return None
```

Add `freshness_policy=self.freshness_policy` to the `SignalCandidate.build` call in `_candidate()` immediately after `data_freshness_ms=snapshot.freshness.max_ms`:

```python
            freshness_policy=self.freshness_policy,
```

- [ ] **Step 6: Run the candidate policy test to verify it passes**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_signal_candidate_carries_freshness_policy -q
```

Expected: PASS.

- [ ] **Step 7: Run a focused regression for existing candidate callers**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_strategies.py tests/test_signal_gate.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/polysignal_lab/domain/freshness.py src/polysignal_lab/domain/signal.py src/polysignal_lab/strategies/base.py tests/test_signal_gate.py
git commit -m "feat: carry strategy freshness policy on signals"
```

### Task 2: Strategy Policy Exposure

**Files:**
- Modify: `src/polysignal_lab/strategies/config.py:17-149`
- Modify: `src/polysignal_lab/strategies/late_consensus.py:1-40`
- Modify: `src/polysignal_lab/strategies/vwap_momentum.py:1-130`
- Modify: `src/polysignal_lab/strategies/ptb_diff.py:1-90`
- Modify: `tests/test_config.py:1-120`
- Modify: `tests/test_late_consensus.py:1-184`
- Modify: `tests/test_vwap_momentum.py:1-160`

**Interfaces:**
- Consumes: `BaseStrategy.freshness_policy` from Task 1.
- Produces: each emitted late-consensus, VWAP momentum, and PTB diff candidate has a policy derived from its Pydantic config model defaults or explicit YAML.

- [ ] **Step 1: Write failing tests for model-default and strategy policies**

Append to `tests/test_config.py`:

```python
def test_late_consensus_policy_uses_model_defaults_when_yaml_omits_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "signal_bot.yaml"
    config_path.write_text(
        """
strategies:
  late_consensus:
    enabled: true
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(config_path)
    strategies = build_strategies(settings.strategies)

    assert [strategy.name for strategy in strategies] == ["late_consensus"]
    assert strategies[0].freshness_policy is not None
    assert strategies[0].freshness_policy.max_orderbook_staleness_ms == 1_500
    assert strategies[0].freshness_policy.max_spot_staleness_ms == 1_500
```

Append to `tests/test_late_consensus.py`:

```python
def test_late_consensus_signal_carries_configured_freshness_policy() -> None:
    config = _config()
    signal = LateConsensusStrategy(config).evaluate(
        _snapshot(LateConsensusScenario(spot=SpotState(price=101.0, price_to_beat=100.0)))
    )[0]

    assert signal.freshness_policy is not None
    assert signal.freshness_policy.max_orderbook_staleness_ms == config.max_orderbook_staleness_ms
    assert signal.freshness_policy.max_spot_staleness_ms == config.max_spot_staleness_ms
    assert signal.freshness_policy.max_anchor_staleness_ms is None
```

Append to `tests/test_vwap_momentum.py`:

```python
def test_vwap_momentum_signal_carries_configured_freshness_policy(snapshot) -> None:
    config = VWAPMomentumConfig(
        max_orderbook_staleness_ms=1_000,
        max_spot_staleness_ms=2_000,
        min_deviation_pct=0.0,
        max_deviation_pct=1.0,
        min_momentum=0.0,
        min_elapsed_sec=0,
        no_entry_before_end_sec=0,
    )
    strategy = VWAPMomentumStrategy(config)
    now = snapshot.created_at.timestamp()
    for side in (Side.UP, Side.DOWN):
        key = strategy._market_key(snapshot.market.market_id, side)
        price = snapshot.ask_for(side)
        assert price is not None
        strategy.trades.push(key, price * 0.95, 1.0, now - config.momentum_window_sec)

    signals = strategy.evaluate(snapshot)

    assert signals
    assert signals[0].freshness_policy is not None
    assert signals[0].freshness_policy.max_orderbook_staleness_ms == 1_000
    assert signals[0].freshness_policy.max_spot_staleness_ms == 2_000
```

- [ ] **Step 2: Run policy tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_config.py::test_late_consensus_policy_uses_model_defaults_when_yaml_omits_fields tests/test_late_consensus.py::test_late_consensus_signal_carries_configured_freshness_policy tests/test_vwap_momentum.py::test_vwap_momentum_signal_carries_configured_freshness_policy -q
```

Expected: FAIL because concrete strategies still expose no policy, and `VWAPMomentumConfig` lacks `max_spot_staleness_ms`.

- [ ] **Step 3: Add VWAP spot freshness config**

In `src/polysignal_lab/strategies/config.py`, update `VWAPMomentumConfig`:

```python
class VWAPMomentumConfig(BaseModel):
    name: Literal["vwap_momentum"] = "vwap_momentum"
    enabled: bool = True
    assets: list[str] = Field(default_factory=lambda: ["BTC"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    min_price: float = 0.35
    max_price: float = 0.85
    vwap_window_sec: int = 30
    momentum_window_sec: int = 120
    min_deviation_pct: float = 0.015
    max_deviation_pct: float = 0.05
    min_momentum: float = 0.05
    min_z_score: float = 1.2
    min_elapsed_sec: int = 45
    no_entry_before_end_sec: int = 20
    max_spread: float = 0.03
    max_orderbook_staleness_ms: int = 60_000
    max_spot_staleness_ms: int = 60_000
```

- [ ] **Step 4: Add late-consensus policy property**

In `src/polysignal_lab/strategies/late_consensus.py`, add the import:

```python
from polysignal_lab.domain.freshness import FreshnessPolicy
```

Add this property to `LateConsensusStrategy` after `__init__()`:

```python
    @property
    def freshness_policy(self) -> FreshnessPolicy:
        return FreshnessPolicy(
            max_orderbook_staleness_ms=self.config.max_orderbook_staleness_ms,
            max_spot_staleness_ms=self.config.max_spot_staleness_ms,
        )
```

- [ ] **Step 5: Add VWAP policy property**

In `src/polysignal_lab/strategies/vwap_momentum.py`, add the import:

```python
from polysignal_lab.domain.freshness import FreshnessPolicy
```

Add this property to `VWAPMomentumStrategy` after `reset_entry_guard()`:

```python
    @property
    def freshness_policy(self) -> FreshnessPolicy:
        return FreshnessPolicy(
            max_orderbook_staleness_ms=self.config.max_orderbook_staleness_ms,
            max_spot_staleness_ms=self.config.max_spot_staleness_ms,
        )
```

- [ ] **Step 6: Add PTB diff policy property**

In `src/polysignal_lab/strategies/ptb_diff.py`, add the import:

```python
from polysignal_lab.domain.freshness import FreshnessPolicy
```

Add this property to `PTBDiffStrategy` after `__init__()`:

```python
    @property
    def freshness_policy(self) -> FreshnessPolicy:
        max_lag_ms = self.config.exit_config.market_data_max_lag_sec * 1000
        return FreshnessPolicy(
            max_orderbook_staleness_ms=max_lag_ms,
            max_spot_staleness_ms=max_lag_ms,
        )
```

- [ ] **Step 7: Run strategy policy tests to verify they pass**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_config.py::test_late_consensus_policy_uses_model_defaults_when_yaml_omits_fields tests/test_late_consensus.py::test_late_consensus_signal_carries_configured_freshness_policy tests/test_vwap_momentum.py::test_vwap_momentum_signal_carries_configured_freshness_policy -q
```

Expected: PASS.

- [ ] **Step 8: Run strategy regression tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_config.py tests/test_late_consensus.py tests/test_vwap_momentum.py tests/test_ptb_diff.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/polysignal_lab/strategies/config.py src/polysignal_lab/strategies/late_consensus.py src/polysignal_lab/strategies/vwap_momentum.py src/polysignal_lab/strategies/ptb_diff.py tests/test_config.py tests/test_late_consensus.py tests/test_vwap_momentum.py
git commit -m "feat: expose strategy freshness policies"
```

### Task 3: Structured Freshness Gate Decisions

**Files:**
- Modify: `src/polysignal_lab/signal_layer/gate.py:1-155`
- Modify: `tests/test_signal_gate.py:1-120`

**Interfaces:**
- Consumes: `SignalCandidate.freshness_policy` from Task 1.
- Produces: gate rejections with reason codes `MISSING_ORDERBOOK`, `MISSING_SPOT_PRICE`, `STALE_ORDERBOOK`, and `STALE_SPOT_PRICE`; details include `lag_ms`, `threshold_ms`, `source`, and `policy_source` for freshness checks.

- [ ] **Step 1: Write failing gate tests for stale, missing, and global fallback behavior**

Append these imports to `tests/test_signal_gate.py`:

```python
from datetime import timedelta

from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig
from polysignal_lab.domain.enums import MarketStatus
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.utils import utc_now
```

Append these helpers and tests to `tests/test_signal_gate.py`:

```python
def _freshness_signal(policy: FreshnessPolicy | None = None) -> SignalCandidate:
    return SignalCandidate.build(
        strategy="unit",
        asset="BTC",
        timeframe="5m",
        market_id="mkt-1",
        market_slug="btc-updown-5m-test",
        condition_id="condition-1",
        token_id="token-up",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.82,
        max_entry_price=0.92,
        seconds_to_close=90,
        data_freshness_ms=10,
        freshness_policy=policy,
        reason_codes=["UNIT"],
        metrics={"max_spread": 0.20},
    )


def _freshness_snapshot(*, book_age_ms: int | None, spot_age_ms: int | None) -> MarketSnapshot:
    now = utc_now()
    market = Market(
        market_id="mkt-1",
        market_slug="btc-updown-5m-test",
        condition_id="condition-1",
        question_id="question-1",
        question="BTC Up or Down?",
        asset="BTC",
        timeframe="5m",
        start_ts=now - timedelta(seconds=210),
        end_ts=now + timedelta(seconds=90),
        status=MarketStatus.ACTIVE,
        resolution_source="test",
        outcome_tokens=[
            OutcomeToken(token_id="token-up", side=Side.UP, outcome_name="Up", market_id="mkt-1"),
            OutcomeToken(token_id="token-down", side=Side.DOWN, outcome_name="Down", market_id="mkt-1"),
        ],
    )
    up_book = None
    if book_age_ms is not None:
        up_book = OrderBook(
            market_id="mkt-1",
            token_id="token-up",
            bids=[BookLevel(price=0.80, size=100.0)],
            asks=[BookLevel(price=0.82, size=100.0)],
            received_at=now - timedelta(milliseconds=book_age_ms),
        )
    spot = None
    if spot_age_ms is not None:
        spot = SpotPrice(
            asset="BTC",
            symbol="BTCUSDT",
            price=100_000.0,
            received_at=now - timedelta(milliseconds=spot_age_ms),
            event_time=now - timedelta(milliseconds=spot_age_ms),
        )
    return MarketSnapshot(
        snapshot_id="snap-freshness",
        created_at=now,
        market=market,
        up_book=up_book,
        down_book=None,
        spot=spot,
        freshness=FreshnessState(
            up_book_ms=book_age_ms,
            down_book_ms=None,
            spot_ms=spot_age_ms,
            max_ms=max(x for x in (book_age_ms, spot_age_ms) if x is not None) if book_age_ms is not None or spot_age_ms is not None else None,
        ),
    )


def test_gate_rejects_strategy_policy_stale_orderbook_with_details() -> None:
    gate = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    )
    signal = _freshness_signal(
        FreshnessPolicy(max_orderbook_staleness_ms=1_500, max_spot_staleness_ms=1_500)
    )
    snapshot = _freshness_snapshot(book_age_ms=2_000, spot_age_ms=100)

    decision = gate.evaluate(signal, snapshot)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "STALE_ORDERBOOK"
    assert decision.rejected.details["lag_ms"] == 2_000
    assert decision.rejected.details["threshold_ms"] == 1_500
    assert decision.rejected.details["source"] == "orderbook"
    assert decision.rejected.details["policy_source"] == "strategy_and_global"


def test_gate_uses_global_threshold_when_strategy_has_no_policy() -> None:
    gate = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    )
    signal = _freshness_signal(policy=None)
    snapshot = _freshness_snapshot(book_age_ms=2_000, spot_age_ms=100)

    decision = gate.evaluate(signal, snapshot)

    assert decision.accepted is True


def test_gate_distinguishes_missing_orderbook_from_stale_orderbook() -> None:
    gate = SignalGate(SignalConfig(dedupe_enabled=False), PolymarketDataConfig(), BinanceDataConfig())
    signal = _freshness_signal(
        FreshnessPolicy(max_orderbook_staleness_ms=1_500, max_spot_staleness_ms=1_500)
    )
    snapshot = _freshness_snapshot(book_age_ms=None, spot_age_ms=100)

    decision = gate.evaluate(signal, snapshot)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "MISSING_ORDERBOOK"
    assert decision.rejected.details["lag_ms"] is None
    assert decision.rejected.details["threshold_ms"] == 1_500


def test_gate_distinguishes_missing_spot_from_stale_spot() -> None:
    gate = SignalGate(SignalConfig(dedupe_enabled=False), PolymarketDataConfig(), BinanceDataConfig())
    signal = _freshness_signal(
        FreshnessPolicy(max_orderbook_staleness_ms=1_500, max_spot_staleness_ms=1_500)
    )
    missing = gate.evaluate(signal, _freshness_snapshot(book_age_ms=100, spot_age_ms=None))
    stale = gate.evaluate(signal, _freshness_snapshot(book_age_ms=100, spot_age_ms=2_000))

    assert missing.rejected is not None
    assert missing.rejected.reason_code == "MISSING_SPOT_PRICE"
    assert missing.rejected.details["threshold_ms"] == 1_500
    assert stale.rejected is not None
    assert stale.rejected.reason_code == "STALE_SPOT_PRICE"
    assert stale.rejected.details["lag_ms"] == 2_000
    assert stale.rejected.details["threshold_ms"] == 1_500
```

- [ ] **Step 2: Run gate freshness tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_gate_rejects_strategy_policy_stale_orderbook_with_details tests/test_signal_gate.py::test_gate_uses_global_threshold_when_strategy_has_no_policy tests/test_signal_gate.py::test_gate_distinguishes_missing_orderbook_from_stale_orderbook tests/test_signal_gate.py::test_gate_distinguishes_missing_spot_from_stale_spot -q
```

Expected: FAIL because current gate returns plain reason strings, uses only global thresholds, and conflates missing with stale.

- [ ] **Step 3: Replace plain reason returns with structured gate rejections**

In `src/polysignal_lab/signal_layer/gate.py`, update imports:

```python
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.signal_layer.deduper import SignalDeduper
from polysignal_lab.signal_layer.rate_limit import ChannelRateLimiter
```

Add these definitions below `GateDecision`:

```python
GateDetails = dict[str, str | float | int | None]
GateCheck = Callable[[SignalCandidate, MarketSnapshot], "GateRejection | None"]


@dataclass(frozen=True, slots=True)
class GateRejection:
    reason_code: str
    details: GateDetails = field(default_factory=dict)
```

Change the `checks` list declaration in `evaluate()`:

```python
        checks: list[GateCheck] = [
            self._market_active,
            self._time_window,
            self._book_freshness,
            self._spot_freshness,
            self._spread,
            self._max_entry,
            self._gtd_expiry,
            self._confidence,
            self._dedupe,
            self._rate_limit,
        ]
```

Change the loop body to use `GateRejection`:

```python
        for check in checks:
            rejection = check(candidate, snapshot)
            if rejection:
                reason = rejection.reason_code
                log.info(
                    "GATE_REJECT %s %s market=%s side=%s reason=%s",
                    check.__name__,
                    reason,
                    candidate.market_id[:16],
                    candidate.side.value,
                    reason,
                )
                return GateDecision(
                    False,
                    rejected=RejectedSignal(
                        candidate=candidate,
                        gate_name=check.__name__,
                        reason_code=reason,
                        details=self._rejection_details(candidate, rejection),
                    ),
                )
```

Change `_rejection_details()` signature and body:

```python
    def _rejection_details(
        self, candidate: SignalCandidate, rejection: GateRejection
    ) -> dict[str, str | float | int | None]:
        details: dict[str, str | float | int | None] = {
            "reason_code": rejection.reason_code,
            "signal_id": candidate.signal_id,
            "strategy": candidate.strategy,
            "asset": candidate.asset,
            "timeframe": candidate.timeframe,
            "market_id": candidate.market_id,
            "side": candidate.side.value,
            "confidence": candidate.confidence,
            "entry_reference_price": candidate.entry_reference_price,
            "max_entry_price": candidate.max_entry_price,
            "seconds_to_close": candidate.seconds_to_close,
            "dedupe_key": candidate.dedupe_key,
        }
        details.update(rejection.details)
        return details
```

- [ ] **Step 4: Add freshness threshold helpers**

Add these methods to `SignalGate` before `_market_active()`:

```python
    def _policy_threshold(
        self,
        policy: FreshnessPolicy | None,
        policy_value: int | None,
        global_value: int,
    ) -> tuple[int, str]:
        if policy is None or policy_value is None:
            return global_value, "global"
        return min(global_value, policy_value), "strategy_and_global"

    @staticmethod
    def _freshness_details(
        *,
        source: str,
        lag_ms: int | None,
        threshold_ms: int,
        policy_source: str,
    ) -> GateDetails:
        return {
            "source": source,
            "lag_ms": lag_ms,
            "threshold_ms": threshold_ms,
            "policy_source": policy_source,
        }
```

- [ ] **Step 5: Update freshness checks**

Replace `_book_freshness()` and `_spot_freshness()` with:

```python
    def _book_freshness(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        threshold_ms, policy_source = self._policy_threshold(
            candidate.freshness_policy,
            candidate.freshness_policy.max_orderbook_staleness_ms if candidate.freshness_policy else None,
            self.poly_config.max_book_staleness_ms,
        )
        book = snapshot.book_for(candidate.side)
        if book is None:
            return GateRejection(
                "MISSING_ORDERBOOK",
                self._freshness_details(
                    source="orderbook",
                    lag_ms=None,
                    threshold_ms=threshold_ms,
                    policy_source=policy_source,
                ),
            )
        lag_ms = book.freshness_ms(snapshot.created_at)
        if lag_ms > threshold_ms:
            return GateRejection(
                "STALE_ORDERBOOK",
                self._freshness_details(
                    source="orderbook",
                    lag_ms=lag_ms,
                    threshold_ms=threshold_ms,
                    policy_source=policy_source,
                ),
            )
        return None

    def _spot_freshness(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        threshold_ms, policy_source = self._policy_threshold(
            candidate.freshness_policy,
            candidate.freshness_policy.max_spot_staleness_ms if candidate.freshness_policy else None,
            self.binance_config.max_price_staleness_ms,
        )
        if snapshot.spot is None:
            return GateRejection(
                "MISSING_SPOT_PRICE",
                self._freshness_details(
                    source="spot_price",
                    lag_ms=None,
                    threshold_ms=threshold_ms,
                    policy_source=policy_source,
                ),
            )
        lag_ms = snapshot.spot.freshness_ms(snapshot.created_at)
        if lag_ms > threshold_ms:
            return GateRejection(
                "STALE_SPOT_PRICE",
                self._freshness_details(
                    source="spot_price",
                    lag_ms=lag_ms,
                    threshold_ms=threshold_ms,
                    policy_source=policy_source,
                ),
            )
        return None
```

- [ ] **Step 6: Update remaining checks to return `GateRejection`**

Replace each plain string return with a `GateRejection` using the concrete reason code:

```python
    def _market_active(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        return None if snapshot.market.is_active else GateRejection("MARKET_NOT_ACTIVE")

    def _time_window(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if candidate.order_intent == OrderIntent.PASSIVE_GTD and candidate.expiry_seconds is not None:
            return None
        if candidate.seconds_to_close is None or candidate.seconds_to_close <= 0:
            return GateRejection("OUTSIDE_ENTRY_WINDOW")
        return None

    def _spread(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if candidate.order_intent == OrderIntent.PASSIVE_GTD:
            return None
        book = snapshot.book_for(candidate.side)
        max_spread = candidate.metrics.get("max_spread", 0.12)
        if book and book.spread is not None and book.spread <= max_spread:
            return None
        return GateRejection("SPREAD_TOO_WIDE")

    def _max_entry(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if candidate.order_intent == OrderIntent.PASSIVE_GTD:
            return None
        ask = snapshot.ask_for(candidate.side)
        if ask is None or ask > candidate.max_entry_price:
            return GateRejection("ASK_ABOVE_MAX_ENTRY")
        return None

    def _gtd_expiry(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if candidate.order_intent != OrderIntent.PASSIVE_GTD:
            return None
        if candidate.expiry_seconds is None or candidate.expiry_seconds <= 0:
            return GateRejection("MISSING_GTD_EXPIRY")
        if candidate.expiry_seconds > 86400:
            return GateRejection("GTD_EXPIRY_EXCEEDS_24H")
        return None

    def _confidence(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        return None if candidate.confidence >= self.signal_config.min_confidence_to_publish else GateRejection("CONFIDENCE_TOO_LOW")

    def _dedupe(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if self.signal_config.dedupe_enabled and self.deduper.is_duplicate(candidate):
            return GateRejection("DUPLICATE_SIGNAL")
        return None

    def _rate_limit(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if not self.rate_limiter.allow(candidate.market_id):
            return GateRejection("CHANNEL_RATE_LIMIT")
        return None
```

- [ ] **Step 7: Update tests that call private checks directly**

In `tests/test_order_intent.py`, existing tests compare private gate checks to strings. Change these assertions:

```python
    reason = gate._max_entry(sig, snap)
    assert reason is None
```

Keep unchanged for `None` checks. For non-`None` checks, use `reason.reason_code`:

```python
    reason = gate._max_entry(sig, snap)
    assert reason is not None
    assert reason.reason_code == "ASK_ABOVE_MAX_ENTRY"
```

Apply the same `reason is not None` plus `.reason_code` pattern for `MISSING_GTD_EXPIRY` and `GTD_EXPIRY_EXCEEDS_24H` assertions in that file.

- [ ] **Step 8: Run gate and direct-check tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py tests/test_order_intent.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/polysignal_lab/signal_layer/gate.py tests/test_signal_gate.py tests/test_order_intent.py
git commit -m "feat: enforce structured freshness gate checks"
```

### Task 4: PTB Diff Gate Cutover and Rejected Details Persistence

**Files:**
- Modify: `src/polysignal_lab/strategies/ptb_diff.py:125-197`
- Modify: `tests/test_signal_gate.py:1-220`
- Modify: `tests/test_dashboard.py:14-55`

**Interfaces:**
- Consumes: `PTBDiffStrategy.freshness_policy` from Task 2 and structured gate details from Task 3.
- Produces: PTB Diff no longer silently drops candidates for raw book/spot age in `evaluate()`; the central gate rejects them and persists structured details visible through `/api/rejected-signals`.

- [ ] **Step 1: Write failing PTB gate cutover test**

Append to `tests/test_signal_gate.py`:

```python
async def test_ptb_diff_stale_spot_candidate_is_rejected_by_gate(snapshot, settings) -> None:
    stale_snapshot = snapshot.model_copy(
        update={
            "spot": snapshot.spot.model_copy(
                update={"received_at": snapshot.created_at - timedelta(seconds=3)}
            ),
            "freshness": snapshot.freshness.model_copy(update={"spot_ms": 3_000, "max_ms": 3_000}),
        }
    )
    strategy = PTBDiffStrategy(settings.strategies.ptb_diff)
    signals = strategy.evaluate(stale_snapshot)

    assert signals

    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(signals[0], stale_snapshot)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "STALE_SPOT_PRICE"
    assert decision.rejected.details["lag_ms"] == 3_000
    assert decision.rejected.details["threshold_ms"] == settings.strategies.ptb_diff.exit_config.market_data_max_lag_sec * 1000
```

- [ ] **Step 2: Run PTB cutover test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_ptb_diff_stale_spot_candidate_is_rejected_by_gate -q
```

Expected: FAIL because `PTBDiffStrategy.evaluate()` currently returns `[]` when spot lag exceeds `market_data_max_lag_sec`.

- [ ] **Step 3: Remove PTB Diff duplicate freshness rejection while keeping metrics**

In `src/polysignal_lab/strategies/ptb_diff.py`, replace this block:

```python
            now = snapshot.created_at
            max_lag_ms = exit_cfg.market_data_max_lag_sec * 1000
            orderbook_freshness_ms = side_book.freshness_ms(now)
            spot_freshness_ms = snapshot.spot.freshness_ms(now)
            if orderbook_freshness_ms > max_lag_ms:
                continue

            if spot_freshness_ms > max_lag_ms:
                continue
```

with:

```python
            now = snapshot.created_at
            max_lag_ms = exit_cfg.market_data_max_lag_sec * 1000
            orderbook_freshness_ms = side_book.freshness_ms(now)
            spot_freshness_ms = snapshot.spot.freshness_ms(now)
```

Keep `"max_lag_ms"`, `"orderbook_freshness_ms"`, and `"spot_freshness_ms"` in the candidate metrics block so accepted or rejected rows still expose diagnostic measurements.

- [ ] **Step 4: Add dashboard persistence test for structured details**

In `tests/test_dashboard.py`, change `_client_with_store()` after `lifecycle = sample_storage_lifecycle(signal)`:

```python
    rejected = lifecycle.rejected.model_copy(
        update={
            "reason_code": "STALE_SPOT_PRICE",
            "details": {
                **lifecycle.rejected.details,
                "reason_code": "STALE_SPOT_PRICE",
                "source": "spot_price",
                "lag_ms": 3_000,
                "threshold_ms": 2_000,
                "policy_source": "strategy_and_global",
            },
        }
    )
```

Then replace:

```python
    store.insert_rejected_signal(lifecycle.rejected)
```

with:

```python
    store.insert_rejected_signal(rejected)
```

In `test_dashboard_readonly_endpoints_return_stored_data()`, add these assertions after `assert rejected.json()[0]["candidate"]["signal_id"] == signal["signal_id"]`:

```python
    assert rejected.json()[0]["reason_code"] == "STALE_SPOT_PRICE"
    assert rejected.json()[0]["details"]["lag_ms"] == 3_000
    assert rejected.json()[0]["details"]["threshold_ms"] == 2_000
    assert rejected.json()[0]["details"]["policy_source"] == "strategy_and_global"
```

- [ ] **Step 5: Run PTB and dashboard tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_ptb_diff_stale_spot_candidate_is_rejected_by_gate tests/test_dashboard.py::test_dashboard_readonly_endpoints_return_stored_data -q
```

Expected: PASS.

- [ ] **Step 6: Run storage/reporting regression tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py tests/test_dashboard.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/polysignal_lab/strategies/ptb_diff.py tests/test_signal_gate.py tests/test_dashboard.py
git commit -m "refactor: route ptb freshness through signal gate"
```

### Task 5: End-to-End Regression and Runtime Safety Checks

**Files:**
- Modify: `tests/test_signal_gate.py:1-260`
- Modify: `tests/test_late_consensus.py:167-184`
- Modify: `tests/test_vwap_momentum.py:1-180`
- No production source changes unless a previous task's focused regression exposes a real defect.

**Interfaces:**
- Consumes: all previous task outputs.
- Produces: proof that late-window strategy candidates with stale book or spot data are centrally rejected, legacy no-policy candidates still use global thresholds, and project safety checks remain green.

- [ ] **Step 1: Add late-consensus gate integration regression**

Append to `tests/test_late_consensus.py`:

```python
def test_late_consensus_stale_spot_is_rejected_by_signal_gate() -> None:
    from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
    from polysignal_lab.signal_layer.gate import SignalGate

    strategy = LateConsensusStrategy(_config())
    snapshot = _snapshot(
        LateConsensusScenario(
            spot=SpotState(price=101.0, price_to_beat=100.0, staleness_ms=2_000)
        )
    )
    signal = strategy.evaluate(snapshot)[0]

    decision = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    ).evaluate(signal, snapshot)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "STALE_SPOT_PRICE"
    assert decision.rejected.details["lag_ms"] == 2_000
    assert decision.rejected.details["threshold_ms"] == 1_500
```

- [ ] **Step 2: Add stale orderbook integration regression**

Append to `tests/test_late_consensus.py`:

```python
def test_late_consensus_stale_orderbook_is_rejected_by_signal_gate() -> None:
    from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
    from polysignal_lab.signal_layer.gate import SignalGate

    strategy = LateConsensusStrategy(_config())
    snapshot = _snapshot(
        LateConsensusScenario(
            books=ConsensusBooks(staleness_ms=2_000),
            spot=SpotState(price=101.0, price_to_beat=100.0),
        )
    )
    signal = strategy.evaluate(snapshot)[0]

    decision = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    ).evaluate(signal, snapshot)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "STALE_ORDERBOOK"
    assert decision.rejected.details["lag_ms"] == 2_000
    assert decision.rejected.details["threshold_ms"] == 1_500
```

- [ ] **Step 3: Run late-consensus integration regressions**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_late_consensus.py::test_late_consensus_stale_spot_is_rejected_by_signal_gate tests/test_late_consensus.py::test_late_consensus_stale_orderbook_is_rejected_by_signal_gate -q
```

Expected: PASS.

- [ ] **Step 4: Run all affected unit tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py tests/test_order_intent.py tests/test_late_consensus.py tests/test_vwap_momentum.py tests/test_ptb_diff.py tests/test_config.py tests/test_dashboard.py tests/test_storage_reporting_publish.py -q
```

Expected: PASS.

- [ ] **Step 5: Run safety scan**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run polysignal-safety-scan
```

Expected: exit code 0 and no blocked live-trading capability findings.

- [ ] **Step 6: Run full test suite**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest
```

Expected: PASS for the full suite.

- [ ] **Step 7: Commit**

```bash
git add tests/test_signal_gate.py tests/test_late_consensus.py tests/test_vwap_momentum.py tests/test_config.py tests/test_dashboard.py tests/test_storage_reporting_publish.py
git commit -m "test: cover strategy freshness gate regressions"
```

## Self-Review

Spec coverage:

- `SignalCandidate` carries a resolvable policy: Task 1 adds `freshness_policy`; Task 2 ensures concrete strategies emit it.
- Strictest threshold among global and strategy config: Task 3 uses `min(global, strategy)` and tests global fallback.
- Missing versus stale reason codes: Task 3 adds `MISSING_ORDERBOOK` and `MISSING_SPOT_PRICE` tests and gate logic.
- PTB anchor lag: Global Constraints explicitly preserve the current-state caveat; PTB policy uses orderbook/spot lag only because current snapshots lack anchor lag fields.
- Rejection details: Task 3 stores lag/threshold/source/policy source; Task 4 proves dashboard/API visibility through persisted rejected rows.
- Strategy duplicate checks: Task 4 removes PTB Diff duplicate raw freshness rejection; late-consensus already delegates staleness to the pipeline.
- Late-window stale data regression: Task 5 covers late-consensus stale spot and stale orderbook.

Placeholder scan:

- No red-flag placeholder markers or omitted code steps are present in this plan.
- Every changed behavior step includes concrete file paths, code blocks, commands, and expected outcomes.

Type consistency:

- `FreshnessPolicy` fields are consistently named `max_orderbook_staleness_ms`, `max_spot_staleness_ms`, and `max_anchor_staleness_ms`.
- `SignalCandidate.build()` and `BaseStrategy._candidate()` use the same `freshness_policy` keyword.
- `GateRejection.reason_code` is the single reason-code source passed into `RejectedSignal.reason_code` and merged into `RejectedSignal.details`.