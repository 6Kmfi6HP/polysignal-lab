# Production Strategy Opt-In and Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Prevent unsupported or uncalibrated strategies from polluting production signals by making production activation explicit and readiness/calibration-aware.

**Architecture:** Keep the existing explicit-YAML-key loader, add strategy readiness metadata and pre-evaluate compatibility filtering, persist skip/status rows separately from gate rejections, split production/lab config profiles, and add calibration aggregates by strategy×asset×timeframe and confidence bucket.

**Tech Stack:** Python 3.11, Pydantic, SQLite, FastAPI dashboard, pytest.

## Global Constraints

- Scope: One standalone architecture change. Do not execute with specs 01-06 or 08 in the same implementation batch.
- No deletion of experimental strategies.
- No strategy performance optimization in this spec.
- No machine-learning consensus engine.
- No live trading risk budget.
- Worktree branch: `spec-07-production-strategy-opt-in-calibration`.
- This worktree may be developed in parallel, but keep readiness metadata separate from spec 09 execution metadata and do not duplicate spec 04/08 health events.
- Runtime config changes are not live until Docker is rebuilt and recreated after merge.

---

## File Structure

- Create `src/polysignal_lab/strategies/readiness.py` for `StrategyReadiness`, compatibility status, required-field checks, and calibration buckets.
- Modify `src/polysignal_lab/strategies/base.py` to expose readiness.
- Modify `src/polysignal_lab/strategies/config.py` to add readiness fields for strategies without assets/timeframes and preserve existing config validation.
- Modify strategy classes as needed to set readiness metadata.
- Modify `config/signal_bot.yaml` for narrowed production defaults.
- Create `config/signal_bot.lab.yaml` preserving all 13 experimental strategies.
- Modify `src/polysignal_lab/app/scheduler_processing.py` to skip incompatible strategies before `evaluate()`.
- Modify `src/polysignal_lab/storage/sqlite_schema.py` and `src/polysignal_lab/storage/sqlite_store.py` to persist strategy status/calibration rows.
- Modify `src/polysignal_lab/paper/report.py`, `src/polysignal_lab/domain/paper_result.py`, and `src/polysignal_lab/dashboard/app.py` for calibration/report API fields.
- Add tests: `tests/test_strategy_readiness.py`, `tests/test_scheduler_strategy_readiness.py`, and extend config/reporting/dashboard/storage tests.

---

### Task 1: Add readiness model and compatibility helper

**Files:**
- Create: `src/polysignal_lab/strategies/readiness.py`
- Modify: `src/polysignal_lab/strategies/base.py`
- Test: `tests/test_strategy_readiness.py`

**Interfaces:**
- Produces: `StrategyReadiness`; `StrategyMarketStatus`; `readiness_for_strategy(strategy) -> StrategyReadiness`; `check_strategy_market(readiness, snapshot) -> StrategyMarketStatus`.

- [x] **Step 1: Write failing tests**

Create `tests/test_strategy_readiness.py`:

```python
from polysignal_lab.strategies.readiness import (
    StrategyReadiness,
    check_strategy_market,
)


class _Market:
    asset = "ETH"
    timeframe = "5m"


class _Snapshot:
    market = _Market()
    up_book = object()
    down_book = object()
    spot = object()
    price_to_beat = None
    metrics = {}


def test_readiness_rejects_unsupported_asset_before_evaluate() -> None:
    readiness = StrategyReadiness(
        name="ptb_diff",
        production_enabled=True,
        supported_assets=("BTC",),
        supported_timeframes=("5m", "15m"),
        required_fields=("price_to_beat",),
        calibration_required=False,
        calibration_status="calibrated",
    )

    status = check_strategy_market(readiness, _Snapshot())

    assert status.status == "unsupported_market"
    assert status.reason == "UNSUPPORTED_ASSET"


def test_readiness_reports_missing_data() -> None:
    readiness = StrategyReadiness(
        name="ptb_diff",
        production_enabled=True,
        supported_assets=("ETH",),
        supported_timeframes=("5m",),
        required_fields=("price_to_beat",),
        calibration_required=False,
        calibration_status="calibrated",
    )

    status = check_strategy_market(readiness, _Snapshot())

    assert status.status == "missing_data"
    assert status.reason == "MISSING_PRICE_TO_BEAT"
```

- [x] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_strategy_readiness.py -v`

Expected: FAIL with missing module.

- [x] **Step 3: Implement readiness model**

Create `src/polysignal_lab/strategies/readiness.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from polysignal_lab.domain.snapshot import MarketSnapshot

CalibrationStatus = Literal["unknown", "insufficient_data", "calibrated"]
StrategyStatus = Literal["active", "disabled", "unsupported_market", "missing_data", "uncalibrated"]


@dataclass(frozen=True, slots=True)
class StrategyReadiness:
    name: str
    production_enabled: bool
    supported_assets: tuple[str, ...]
    supported_timeframes: tuple[str, ...]
    required_fields: tuple[str, ...]
    calibration_required: bool
    calibration_status: CalibrationStatus


@dataclass(frozen=True, slots=True)
class StrategyMarketStatus:
    strategy: str
    asset: str
    timeframe: str
    status: StrategyStatus
    reason: str | None


def _has_required(snapshot: MarketSnapshot, field: str) -> bool:
    if field == "up_book":
        return snapshot.up_book is not None
    if field == "down_book":
        return snapshot.down_book is not None
    if field == "spot":
        return snapshot.spot is not None
    if field == "price_to_beat":
        return snapshot.price_to_beat is not None
    if field == "spot_history":
        return bool(snapshot.metrics.get("spot_history_count"))
    if field == "market_end_ts":
        return snapshot.market.end_ts is not None
    return bool(snapshot.metrics.get(field))


def check_strategy_market(
    readiness: StrategyReadiness, snapshot: MarketSnapshot
) -> StrategyMarketStatus:
    asset = snapshot.market.asset.upper()
    timeframe = snapshot.market.timeframe
    if not readiness.production_enabled:
        return StrategyMarketStatus(readiness.name, asset, timeframe, "disabled", "STRATEGY_DISABLED")
    if asset not in readiness.supported_assets:
        return StrategyMarketStatus(readiness.name, asset, timeframe, "unsupported_market", "UNSUPPORTED_ASSET")
    if timeframe not in readiness.supported_timeframes:
        return StrategyMarketStatus(readiness.name, asset, timeframe, "unsupported_market", "UNSUPPORTED_TIMEFRAME")
    for field in readiness.required_fields:
        if not _has_required(snapshot, field):
            return StrategyMarketStatus(readiness.name, asset, timeframe, "missing_data", f"MISSING_{field.upper()}")
    if readiness.calibration_required and readiness.calibration_status != "calibrated":
        return StrategyMarketStatus(readiness.name, asset, timeframe, "uncalibrated", "CALIBRATION_REQUIRED")
    return StrategyMarketStatus(readiness.name, asset, timeframe, "active", None)
```

Modify `BaseStrategy`:

```python
from polysignal_lab.strategies.readiness import StrategyReadiness

@property
def readiness(self) -> StrategyReadiness:
    return StrategyReadiness(
        name=self.name,
        production_enabled=True,
        supported_assets=tuple(getattr(self.config, "assets", ("BTC", "ETH", "SOL", "XRP"))),
        supported_timeframes=tuple(getattr(self.config, "timeframes", ("5m", "15m"))),
        required_fields=("up_book", "down_book"),
        calibration_required=False,
        calibration_status="calibrated",
    )
```

If a strategy lacks `self.config`, override `readiness` in that strategy.

- [x] **Step 4: Run readiness tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_strategy_readiness.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/strategies/readiness.py src/polysignal_lab/strategies/base.py tests/test_strategy_readiness.py
git commit -m "feat: add strategy readiness checks"
```

---

### Task 2: Annotate all strategies without changing alpha logic

**Files:**
- Modify: `src/polysignal_lab/strategies/base.py`
- Modify: `src/polysignal_lab/strategies/ninety_nine_cent_sniper.py`
- Modify: `src/polysignal_lab/strategies/one_cent_buy.py`
- Modify: other strategy files only when required fields differ from base defaults.
- Test: `tests/test_strategy_readiness.py`
- Test: existing strategy tests.

**Interfaces:**
- Produces: readiness for all 13 strategies.

- [x] **Step 1: Write coverage test**

Add to `tests/test_strategy_readiness.py`:

```python
from polysignal_lab.config import Settings
from polysignal_lab.strategies.factory import build_strategies


def test_all_loaded_strategies_expose_readiness() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")
    strategies = build_strategies(settings.strategies)

    names = {strategy.name for strategy in strategies}
    readiness = {strategy.name: strategy.readiness for strategy in strategies}

    assert names == set(readiness)
    assert readiness["ninety_nine_cent_sniper"].supported_assets == ("BTC", "ETH", "SOL", "XRP")
    assert readiness["one_cent_buy"].supported_timeframes == ("5m", "15m")
```

- [x] **Step 2: Run test to verify current metadata gaps**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_strategy_readiness.py::test_all_loaded_strategies_expose_readiness -v`

Expected: FAIL until readiness overrides exist for strategies without config assets/timeframes.

- [x] **Step 3: Add strategy overrides**

In `NinetyNineCentSniperStrategy` and `OneCentBuyStrategy`, add:

```python
@property
def readiness(self) -> StrategyReadiness:
    return StrategyReadiness(
        name=self.name,
        production_enabled=True,
        supported_assets=("BTC", "ETH", "SOL", "XRP"),
        supported_timeframes=("5m", "15m"),
        required_fields=("up_book", "down_book", "market_end_ts"),
        calibration_required=True,
        calibration_status="unknown",
    )
```

For `PTBDiffStrategy`, override required fields:

```python
required_fields=("up_book", "down_book", "spot", "price_to_beat", "market_end_ts")
```

For `VWAPMomentumStrategy`, override required fields:

```python
required_fields=("up_book", "down_book", "spot", "spot_history", "market_end_ts")
```

- [x] **Step 4: Run strategy tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_strategy_readiness.py tests/test_strategies.py tests/test_ptb_diff.py tests/test_vwap_momentum.py tests/test_late_consensus.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/strategies tests/test_strategy_readiness.py
git commit -m "feat: annotate strategy readiness metadata"
```

---

### Task 3: Split production and lab config profiles

**Files:**
- Modify: `config/signal_bot.yaml`
- Create: `config/signal_bot.lab.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Production config narrows enabled strategies.
- Lab config preserves all 13 current strategies.

- [x] **Step 1: Write config tests**

Add to `tests/test_config.py`:

```python
from polysignal_lab.config import Settings
from polysignal_lab.strategies.factory import build_strategies


def test_production_config_uses_reviewed_strategy_subset() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")
    names = [strategy.name for strategy in build_strategies(settings.strategies)]
    assert names == ["vwap_momentum", "late_consensus", "ptb_diff"]


def test_lab_config_preserves_experimental_strategy_breadth() -> None:
    settings = Settings.from_yaml("config/signal_bot.lab.yaml")
    names = {strategy.name for strategy in build_strategies(settings.strategies)}
    assert names == {
        "vwap_momentum",
        "late_consensus",
        "ptb_diff",
        "binary_momentum",
        "cross_market_bot",
        "dump_hedge",
        "fibonacci_bot",
        "low_side_dual_reversion",
        "mid_price_sizing",
        "ninety_nine_cent_sniper",
        "one_cent_buy",
        "pre_order_market",
        "skew_mean_reversion",
    }
```

- [x] **Step 2: Run test to verify production currently fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_config.py::test_production_config_uses_reviewed_strategy_subset -v`

Expected: FAIL because production currently enables all 13 strategies.

- [x] **Step 3: Change configs**

Copy current `config/signal_bot.yaml` to `config/signal_bot.lab.yaml` and set:

```yaml
app:
  environment: lab
```

In production `config/signal_bot.yaml`, keep only:

```yaml
strategies:
  vwap_momentum:
    enabled: true
    assets: [BTC]
    timeframes: [5m, 15m]
  late_consensus:
    enabled: true
    assets: [BTC, ETH, SOL, XRP]
    timeframes: [5m, 15m]
  ptb_diff:
    enabled: true
    assets: [BTC]
    timeframes: [5m, 15m]
    require_verified_ptb_source: true
```

Preserve all current tuned numeric fields for these three strategies from the existing production file.

- [x] **Step 4: Run config tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_config.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add config/signal_bot.yaml config/signal_bot.lab.yaml tests/test_config.py
git commit -m "feat: split production and lab strategy profiles"
```

---

### Task 4: Skip incompatible strategy-market pairs before evaluate

**Files:**
- Modify: `src/polysignal_lab/app/scheduler_processing.py`
- Modify: `src/polysignal_lab/storage/sqlite_schema.py`
- Modify: `src/polysignal_lab/storage/sqlite_store.py`
- Test: `tests/test_scheduler_strategy_readiness.py`

**Interfaces:**
- Consumes: `check_strategy_market()`.
- Produces: `SQLiteStore.insert_strategy_status(status: StrategyMarketStatus) -> None`.

- [x] **Step 1: Write scheduler test**

Create `tests/test_scheduler_strategy_readiness.py`:

```python
from polysignal_lab.app import scheduler_processing
from polysignal_lab.strategies.readiness import StrategyReadiness


class _UnsupportedStrategy:
    name = "unsupported"

    @property
    def readiness(self):
        return StrategyReadiness(
            name=self.name,
            production_enabled=True,
            supported_assets=("BTC",),
            supported_timeframes=("5m",),
            required_fields=("up_book",),
            calibration_required=False,
            calibration_status="calibrated",
        )

    def evaluate(self, snapshot):
        raise AssertionError("unsupported strategy should not be evaluated")


async def test_unsupported_strategy_is_skipped_before_evaluate(fake_scheduler, eth_snapshot) -> None:
    fake_scheduler.strategies = [_UnsupportedStrategy()]
    fake_scheduler.snapshot_builder.build = lambda market: eth_snapshot

    accepted = await scheduler_processing.evaluate_once(fake_scheduler)

    assert accepted == []
    assert fake_scheduler.sqlite.strategy_statuses[-1].status == "unsupported_market"
```

- [x] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_strategy_readiness.py -v`

Expected: FAIL because status persistence and skip logic are missing.

- [x] **Step 3: Add storage and skip logic**

Add `strategy_status` table with columns:

```sql
status_id TEXT PRIMARY KEY,
strategy TEXT NOT NULL,
asset TEXT NOT NULL,
timeframe TEXT NOT NULL,
status TEXT NOT NULL,
reason TEXT,
created_at TEXT NOT NULL,
payload_json TEXT NOT NULL
```

Add store method:

```python
def insert_strategy_status(self, status: Any) -> None:
    p = to_jsonable(status)
    status_id = stable_hash(p["strategy"], p["asset"], p["timeframe"], p["status"], utc_iso())
    with self._lock, self._conn:
        self._conn.execute(
            """INSERT INTO strategy_status(status_id,strategy,asset,timeframe,status,reason,created_at,payload_json)
            VALUES(?,?,?,?,?,?,?,?)""",
            (status_id, p["strategy"], p["asset"], p["timeframe"], p["status"], p.get("reason"), utc_iso(), self._json(p)),
        )
```

In `evaluate_once`, before `strategy.evaluate(snapshot)`:

```python
from polysignal_lab.strategies.readiness import check_strategy_market

status = check_strategy_market(strategy.readiness, snapshot)
if status.status != "active":
    scheduler.logs.append("strategy_status", status)
    scheduler.sqlite.insert_strategy_status(status)
    continue
```

- [x] **Step 4: Run scheduler readiness tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_strategy_readiness.py tests/test_storage_reporting_publish.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/app/scheduler_processing.py src/polysignal_lab/storage/sqlite_schema.py src/polysignal_lab/storage/sqlite_store.py tests/test_scheduler_strategy_readiness.py tests/test_storage_reporting_publish.py
git commit -m "feat: persist strategy readiness skips"
```

---

### Task 5: Add calibration aggregates and dashboard/API fields

**Files:**
- Modify: `src/polysignal_lab/domain/paper_result.py`
- Modify: `src/polysignal_lab/paper/report.py`
- Modify: `src/polysignal_lab/storage/sqlite_store.py`
- Modify: `src/polysignal_lab/dashboard/app.py`
- Test: `tests/test_reporting.py`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Produces report field `calibration_breakdown: dict[str, dict[str, object]]` keyed as `strategy|asset|timeframe|confidence_bucket`.

- [x] **Step 1: Write reporting test**

Add to `tests/test_reporting.py`:

```python
def test_daily_report_includes_strategy_asset_timeframe_calibration(report_service_with_results) -> None:
    report = report_service_with_results.generate_daily_report()

    row = report.calibration_breakdown["ptb_diff|BTC|5m|high"]
    assert row["strategy"] == "ptb_diff"
    assert row["asset"] == "BTC"
    assert row["timeframe"] == "5m"
    assert row["sample_size"] >= 1
    assert row["calibration_status"] in {"insufficient_data", "calibrated"}
    assert "average_return" in row
```

- [x] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py::test_daily_report_includes_strategy_asset_timeframe_calibration -v`

Expected: FAIL because `calibration_breakdown` does not exist.

- [x] **Step 3: Implement calibration rows**

In `DailyReport`, add:

```python
calibration_breakdown: dict[str, dict[str, object]] = Field(default_factory=dict)
```

In report generation, build rows with:

```python
def _confidence_bucket(confidence: float | None) -> str:
    value = float(confidence or 0.0)
    if value >= 0.75:
        return "high"
    if value >= 0.55:
        return "medium"
    return "low"
```

For each closed paper result payload, aggregate by `strategy|asset|timeframe|bucket`:

```python
row = calibration.setdefault(key, {
    "strategy": strategy,
    "asset": asset,
    "timeframe": timeframe,
    "confidence_bucket": bucket,
    "sample_size": 0,
    "wins": 0,
    "losses": 0,
    "average_entry_price": 0.0,
    "average_return": 0.0,
    "calibration_status": "insufficient_data",
})
```

Set `calibration_status` to `"calibrated"` only when `sample_size >= 30`; otherwise keep `"insufficient_data"`.

Expose `calibration_breakdown` in `/api/overview` via latest report and add `/api/leaderboard` rows without replacing existing fields.

- [x] **Step 4: Run reporting/dashboard tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py tests/test_dashboard.py tests/test_storage_reporting_publish.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/domain/paper_result.py src/polysignal_lab/paper/report.py src/polysignal_lab/storage/sqlite_store.py src/polysignal_lab/dashboard/app.py tests/test_reporting.py tests/test_dashboard.py tests/test_storage_reporting_publish.py
git commit -m "feat: report strategy calibration matrix"
```

---

### Task 6: Final verification

**Files:**
- Modify only for failures found by targeted verification.

- [x] **Step 1: Run targeted suite**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_config.py tests/test_strategy_readiness.py tests/test_scheduler_strategy_readiness.py tests/test_reporting.py tests/test_storage_reporting_publish.py tests/test_dashboard.py -v
```

Expected: PASS.

- [x] **Step 2: Run Docker verification after merge to runtime branch**

Run:

```bash
docker compose up -d --build --force-recreate
docker compose ps
```

Expected: compose services are recreated and production logs show the narrowed strategy count.

- [x] **Step 3: Commit final plan/test adjustments**

```bash
git add src config tests docs/superpowers/plans/2026-06-23-07-production-strategy-opt-in-calibration.md
git commit -m "test: cover production strategy readiness"
```
