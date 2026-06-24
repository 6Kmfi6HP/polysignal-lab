# Anchor Price Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkboxes for tracking.

**Goal:** Replace snapshot-time opportunistic price-to-beat lookup with a durable anchor price service for short-cycle crypto Up/Down markets.

**Architecture:** Add a persisted `AnchorPrice` model and service that captures Binance spot at market window boundaries, stores verified anchors in SQLite, and makes `PriceToBeatProvider` prefer verified anchor rows before Gamma/raw/text fallback. Snapshot metrics and PTB Diff strict mode distinguish `anchor_service:<source>` from other verified PTB sources.

**Tech Stack:** Python 3.11, Pydantic, SQLite, asyncio, pytest, existing Binance `SpotRegistry`.

## Global Constraints

- Scope: One standalone architecture change. Do not execute with specs 01-04 or 06-08 in the same implementation batch.
- No live trading.
- No dependency on blocked/undocumented endpoints as primary source.
- No full historical price database beyond anchors needed by active/recent markets.
- No consensus algorithm for multiple references beyond simple validation in this spec.
- Worktree branch: `spec-05-anchor-price-service`.
- This worktree may be developed in parallel, but merge after resolving conflicts in `src/polysignal_lab/app/scheduler.py`, `src/polysignal_lab/strategies/config.py`, and storage schema files.
- Runtime code/config changes are not live until Docker is rebuilt and recreated after merge.

---

## File Structure

- Create `src/polysignal_lab/domain/anchor_price.py` for the persisted immutable anchor model.
- Create `src/polysignal_lab/data/anchor_price_service.py` for boundary parsing, lag validation, capture from `SpotRegistry`, health metrics, and store protocol.
- Modify `src/polysignal_lab/storage/sqlite_schema.py` to add `anchor_prices` table, required columns, indexes, and count allow-list entries.
- Modify `src/polysignal_lab/storage/sqlite_store.py` with `upsert_anchor_price()` and `get_verified_anchor_price()`.
- Modify `src/polysignal_lab/data/price_to_beat_provider.py` so anchors are read first and source becomes `anchor_service:<source>`.
- Modify `src/polysignal_lab/data/market_snapshot.py` to expose anchor metrics on snapshots.
- Modify `src/polysignal_lab/app/scheduler.py` and `src/polysignal_lab/app/scheduler_market_data.py` to construct and call `AnchorPriceService`.
- Modify `src/polysignal_lab/strategies/config.py` and `src/polysignal_lab/strategies/ptb_diff.py` for strict anchor-required PTB mode.
- Extend `tests/test_price_to_beat_provider.py`, `tests/test_market_parsing.py`, `tests/test_ptb_diff.py`, `tests/test_storage_reporting_publish.py`, `tests/test_market_data.py`, and add `tests/test_anchor_price_service.py`.

---

### Task 1: Anchor model and boundary helpers

**Files:**
- Create: `src/polysignal_lab/domain/anchor_price.py`
- Create: `src/polysignal_lab/data/anchor_price_service.py`
- Test: `tests/test_anchor_price_service.py`

**Interfaces:**
- Consumes: `polysignal_lab.domain.market.Market`
- Produces: `AnchorPrice`; `AnchorWindow`; `window_for_market(market: Market) -> AnchorWindow | None`

- [x] **Step 1: Write the failing tests**

Create `tests/test_anchor_price_service.py` with:

```python
from datetime import datetime, timezone

from polysignal_lab.data.anchor_price_service import window_for_market
from polysignal_lab.domain.market import Market


def _market(slug: str, timeframe: str = "5m") -> Market:
    start = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 23, 12, 5, tzinfo=timezone.utc)
    return Market(
        market_id="m1",
        condition_id="c1",
        question="BTC Up or Down",
        market_slug=slug,
        asset="BTC",
        timeframe=timeframe,
        start_ts=start,
        end_ts=end,
        outcome_tokens=[],
        raw={},
    )


def test_window_for_market_prefers_event_window() -> None:
    window = window_for_market(_market("btc-updown-5m-1782216000"))
    assert window is not None
    assert window.window_start == datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
    assert window.window_end == datetime(2026, 6, 23, 12, 5, tzinfo=timezone.utc)


def test_window_for_market_derives_from_slug_when_event_start_missing() -> None:
    market = _market("btc-updown-15m-1782216000", timeframe="15m")
    market.start_ts = None
    market.end_ts = None
    window = window_for_market(market)
    assert window is not None
    assert int(window.window_start.timestamp()) == 1782216000
    assert int(window.window_end.timestamp()) == 1782216900
```

- [x] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_anchor_price_service.py::test_window_for_market_prefers_event_window -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'polysignal_lab.data.anchor_price_service'`.

- [x] **Step 3: Implement model and helpers**

Create `src/polysignal_lab/domain/anchor_price.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AnchorPrice:
    asset: str
    timeframe: str
    market_slug: str
    window_start: datetime
    window_end: datetime
    price: float | None
    source: str
    verified: bool
    captured_at: datetime
    lag_ms: int | None
```

Create `src/polysignal_lab/data/anchor_price_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from polysignal_lab.domain.anchor_price import AnchorPrice
from polysignal_lab.domain.market import Market


@dataclass(frozen=True, slots=True)
class AnchorWindow:
    window_start: datetime
    window_end: datetime


def _timeframe_seconds(timeframe: str) -> int | None:
    if timeframe == "5m":
        return 300
    if timeframe == "15m":
        return 900
    return None


def _slug_epoch(slug: str) -> int | None:
    try:
        return int(str(slug).rsplit("-", 1)[-1])
    except (TypeError, ValueError):
        return None


def window_for_market(market: Market) -> AnchorWindow | None:
    if market.start_ts is not None and market.end_ts is not None:
        return AnchorWindow(market.start_ts, market.end_ts)
    duration = _timeframe_seconds(market.timeframe)
    epoch = _slug_epoch(market.market_slug)
    if duration is None or epoch is None:
        return None
    start = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return AnchorWindow(start, start + timedelta(seconds=duration))
```

- [x] **Step 4: Run test to verify it passes**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_anchor_price_service.py -v`

Expected: PASS for the two boundary tests.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/domain/anchor_price.py src/polysignal_lab/data/anchor_price_service.py tests/test_anchor_price_service.py
git commit -m "feat: add anchor price boundary model"
```

---

### Task 2: Persist anchors in SQLite

**Files:**
- Modify: `src/polysignal_lab/storage/sqlite_schema.py`
- Modify: `src/polysignal_lab/storage/sqlite_store.py`
- Test: `tests/test_storage_reporting_publish.py`

**Interfaces:**
- Consumes: `AnchorPrice`
- Produces: `SQLiteStore.upsert_anchor_price(anchor: AnchorPrice) -> None`; `SQLiteStore.get_verified_anchor_price(asset: str, timeframe: str, market_slug: str) -> AnchorPrice | None`

- [x] **Step 1: Write the failing test**

Add to `tests/test_storage_reporting_publish.py`:

```python
from datetime import datetime, timezone

from polysignal_lab.domain.anchor_price import AnchorPrice
from polysignal_lab.storage.sqlite_store import SQLiteStore


def test_sqlite_anchor_prices_survive_reopen(tmp_path) -> None:
    db_path = tmp_path / "anchors.sqlite3"
    captured_at = datetime(2026, 6, 23, 12, 0, 1, tzinfo=timezone.utc)
    anchor = AnchorPrice(
        asset="BTC",
        timeframe="5m",
        market_slug="btc-updown-5m-1782216000",
        window_start=datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 6, 23, 12, 5, tzinfo=timezone.utc),
        price=64250.25,
        source="binance",
        verified=True,
        captured_at=captured_at,
        lag_ms=750,
    )
    store = SQLiteStore(db_path)
    store.upsert_anchor_price(anchor)
    store.close()

    reopened = SQLiteStore(db_path)
    loaded = reopened.get_verified_anchor_price("btc", "5m", "btc-updown-5m-1782216000")
    assert loaded == anchor
```

- [x] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py::test_sqlite_anchor_prices_survive_reopen -v`

Expected: FAIL with `AttributeError` for missing `upsert_anchor_price`.

- [x] **Step 3: Add schema and store methods**

In `src/polysignal_lab/storage/sqlite_schema.py`, append a table DDL:

```python
"""
CREATE TABLE IF NOT EXISTS anchor_prices (
    anchor_id TEXT PRIMARY KEY,
    asset TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    market_slug TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    price REAL,
    source TEXT NOT NULL,
    verified INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    lag_ms INTEGER,
    payload_json TEXT NOT NULL
)
"""
```

Add an index:

```python
"CREATE UNIQUE INDEX IF NOT EXISTS idx_anchor_prices_market ON anchor_prices(asset,timeframe,market_slug)",
```

Add required columns and counts:

```python
"anchor_prices": frozenset({
    "anchor_id", "asset", "timeframe", "market_slug", "window_start",
    "window_end", "source", "verified", "captured_at", "payload_json"
}),
```

Include `"anchor_prices"` in `COUNT_TABLES`.

In `src/polysignal_lab/storage/sqlite_store.py`, add:

```python
from datetime import datetime
from polysignal_lab.domain.anchor_price import AnchorPrice
```

and methods:

```python
def upsert_anchor_price(self, anchor: AnchorPrice) -> None:
    p = to_jsonable(anchor)
    anchor_id = f"{anchor.asset.upper()}:{anchor.timeframe}:{anchor.market_slug}"
    with self._lock, self._conn:
        self._conn.execute(
            """INSERT OR REPLACE INTO anchor_prices(
                anchor_id,asset,timeframe,market_slug,window_start,window_end,
                price,source,verified,captured_at,lag_ms,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                anchor_id,
                anchor.asset.upper(),
                anchor.timeframe,
                anchor.market_slug,
                utc_iso(anchor.window_start),
                utc_iso(anchor.window_end),
                anchor.price,
                anchor.source,
                1 if anchor.verified else 0,
                utc_iso(anchor.captured_at),
                anchor.lag_ms,
                self._json(p),
            ),
        )


def get_verified_anchor_price(
    self, asset: str, timeframe: str, market_slug: str
) -> AnchorPrice | None:
    with self._lock:
        row = self._conn.execute(
            """SELECT payload_json FROM anchor_prices
            WHERE asset=? AND timeframe=? AND market_slug=? AND verified=1
            LIMIT 1""",
            (asset.upper(), timeframe, market_slug),
        ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload_json"])
    return AnchorPrice(
        asset=str(payload["asset"]),
        timeframe=str(payload["timeframe"]),
        market_slug=str(payload["market_slug"]),
        window_start=datetime.fromisoformat(str(payload["window_start"])),
        window_end=datetime.fromisoformat(str(payload["window_end"])),
        price=float(payload["price"]) if payload.get("price") is not None else None,
        source=str(payload["source"]),
        verified=bool(payload["verified"]),
        captured_at=datetime.fromisoformat(str(payload["captured_at"])),
        lag_ms=int(payload["lag_ms"]) if payload.get("lag_ms") is not None else None,
    )
```

- [x] **Step 4: Run test to verify it passes**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py::test_sqlite_anchor_prices_survive_reopen -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/storage/sqlite_schema.py src/polysignal_lab/storage/sqlite_store.py tests/test_storage_reporting_publish.py
git commit -m "feat: persist verified anchor prices"
```

---

### Task 3: Capture anchors from SpotRegistry

**Files:**
- Modify: `src/polysignal_lab/data/anchor_price_service.py`
- Modify: `src/polysignal_lab/app/scheduler.py`
- Modify: `src/polysignal_lab/app/scheduler_market_data.py`
- Test: `tests/test_anchor_price_service.py`

**Interfaces:**
- Consumes: `SpotRegistry.history(asset)` and `SQLiteStore.upsert_anchor_price()`
- Produces: `AnchorPriceService.capture_for_market(market: Market) -> AnchorPrice | None`

- [x] **Step 1: Write the failing test**

Add to `tests/test_anchor_price_service.py`:

```python
from polysignal_lab.data.anchor_price_service import AnchorPriceService
from polysignal_lab.data.state import SpotPrice, SpotRegistry


class _Store:
    def __init__(self) -> None:
        self.anchors = []

    def upsert_anchor_price(self, anchor):
        self.anchors.append(anchor)


def test_capture_for_market_persists_verified_spot_anchor() -> None:
    store = _Store()
    spots = SpotRegistry()
    market = _market("btc-updown-5m-1782216000")
    spots.update(SpotPrice(asset="BTC", price=64250.25, exchange="binance", event_time=market.start_ts))
    service = AnchorPriceService(spots=spots, store=store, max_lag_ms=1_000)

    anchor = service.capture_for_market(market)

    assert anchor is not None
    assert anchor.verified is True
    assert anchor.source == "binance"
    assert anchor.price == 64250.25
    assert store.anchors == [anchor]
```

- [x] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_anchor_price_service.py::test_capture_for_market_persists_verified_spot_anchor -v`

Expected: FAIL with missing `AnchorPriceService`.

- [x] **Step 3: Implement capture service**

Add protocols and service to `src/polysignal_lab/data/anchor_price_service.py`:

```python
class AnchorPriceStore(Protocol):
    def upsert_anchor_price(self, anchor: AnchorPrice) -> None: ...
    def get_verified_anchor_price(
        self, asset: str, timeframe: str, market_slug: str
    ) -> AnchorPrice | None: ...


class AnchorPriceService:
    def __init__(self, spots, store: AnchorPriceStore, max_lag_ms: int = 2_000) -> None:
        self.spots = spots
        self.store = store
        self.max_lag_ms = max_lag_ms
        self._latest_by_key: dict[str, AnchorPrice] = {}

    def capture_for_market(self, market: Market) -> AnchorPrice | None:
        window = window_for_market(market)
        if window is None:
            return None
        samples = list(self.spots.history(market.asset))
        if not samples:
            return None
        best = min(
            samples,
            key=lambda spot: abs((spot.event_time - window.window_start).total_seconds()),
        )
        lag_ms = int(abs((best.event_time - window.window_start).total_seconds()) * 1000)
        anchor = AnchorPrice(
            asset=market.asset.upper(),
            timeframe=market.timeframe,
            market_slug=market.market_slug,
            window_start=window.window_start,
            window_end=window.window_end,
            price=best.price if lag_ms <= self.max_lag_ms else None,
            source="binance",
            verified=lag_ms <= self.max_lag_ms,
            captured_at=best.received_at,
            lag_ms=lag_ms,
        )
        self.store.upsert_anchor_price(anchor)
        self._latest_by_key[f"{anchor.asset}:{anchor.timeframe}"] = anchor
        return anchor

    def health_metrics(self) -> dict[str, dict[str, int | float | str | bool | None]]:
        return {
            key: {
                "source": anchor.source,
                "lag_ms": anchor.lag_ms,
                "verified": anchor.verified,
                "market_slug": anchor.market_slug,
            }
            for key, anchor in self._latest_by_key.items()
        }
```

In `scheduler.py`, construct after `self.sqlite` and before `MarketSnapshotBuilder` final wiring:

```python
self.anchor_prices = AnchorPriceService(self.ctx.spots, self.sqlite)
self.ptb = PriceToBeatProvider(
    anchor_store=self.sqlite,
    use_crypto_price_api=settings.data.polymarket.use_crypto_price_api,
)
```

In `scheduler_market_data.refresh_markets_once`, after markets are known and before snapshots are built, call:

```python
for market in scheduler.ctx.markets.active():
    scheduler.anchor_prices.capture_for_market(market)
```

- [x] **Step 4: Run test to verify it passes**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_anchor_price_service.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/data/anchor_price_service.py src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_market_data.py tests/test_anchor_price_service.py
git commit -m "feat: capture anchors from spot registry"
```

---

### Task 4: Anchor-first PTB provider and snapshot metrics

**Files:**
- Modify: `src/polysignal_lab/data/price_to_beat_provider.py`
- Modify: `src/polysignal_lab/data/market_snapshot.py`
- Test: `tests/test_price_to_beat_provider.py`
- Test: `tests/test_market_parsing.py`

**Interfaces:**
- Consumes: `AnchorPriceStore.get_verified_anchor_price()`
- Produces: `PriceToBeatResult.anchor_source`, `anchor_lag_ms`, `from_anchor_service`

- [x] **Step 1: Write the failing tests**

Add to `tests/test_price_to_beat_provider.py`:

```python
from datetime import datetime, timezone

from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.domain.anchor_price import AnchorPrice


class _AnchorStore:
    def __init__(self, anchor):
        self.anchor = anchor

    def get_verified_anchor_price(self, asset, timeframe, market_slug):
        return self.anchor


async def test_ptb_provider_prefers_verified_anchor_over_metadata(sample_market) -> None:
    anchor = AnchorPrice(
        asset="BTC",
        timeframe="5m",
        market_slug=sample_market.market_slug,
        window_start=datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 6, 23, 12, 5, tzinfo=timezone.utc),
        price=64000.0,
        source="binance",
        verified=True,
        captured_at=datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc),
        lag_ms=100,
    )
    sample_market.price_to_beat = 64100.0
    provider = PriceToBeatProvider(anchor_store=_AnchorStore(anchor))

    result = await provider.get(sample_market)

    assert result.value == 64000.0
    assert result.source == "anchor_service:binance"
    assert result.verified is True
    assert result.anchor_source == "binance"
    assert result.anchor_lag_ms == 100
    assert result.from_anchor_service is True
```

- [x] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_price_to_beat_provider.py::test_ptb_provider_prefers_verified_anchor_over_metadata -v`

Expected: FAIL because `PriceToBeatProvider` does not accept `anchor_store`.

- [x] **Step 3: Implement anchor precedence**

Modify `PriceToBeatResult`:

```python
@dataclass(frozen=True)
class PriceToBeatResult:
    value: float | None
    source: str
    verified: bool
    reason: str | None = None
    anchor_source: str | None = None
    anchor_lag_ms: int | None = None
    from_anchor_service: bool = False
```

Modify provider constructor and first branch of `get()`:

```python
def __init__(self, client: _CryptoPriceClient | None = None, *, anchor_store=None, use_crypto_price_api: bool = False):
    self.client = client or httpx.AsyncClient(timeout=10.0)
    self.anchor_store = anchor_store
    self.use_crypto_price_api = use_crypto_price_api

async def get(self, market: Market) -> PriceToBeatResult:
    if self.anchor_store is not None:
        anchor = self.anchor_store.get_verified_anchor_price(
            market.asset, market.timeframe, market.market_slug
        )
        if anchor is not None and anchor.price is not None:
            return PriceToBeatResult(
                value=anchor.price,
                source=f"anchor_service:{anchor.source}",
                verified=True,
                anchor_source=anchor.source,
                anchor_lag_ms=anchor.lag_ms,
                from_anchor_service=True,
            )
```

Modify `MarketSnapshotBuilder.build()` metrics:

```python
metrics={
    "price_to_beat_source": ptb.source,
    "price_to_beat_verified": ptb.verified,
    "price_to_beat_from_anchor_service": ptb.from_anchor_service,
    "anchor_price_source": ptb.anchor_source,
    "anchor_price_lag_ms": ptb.anchor_lag_ms,
},
```

- [x] **Step 4: Run tests to verify behavior**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_price_to_beat_provider.py tests/test_market_parsing.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/data/price_to_beat_provider.py src/polysignal_lab/data/market_snapshot.py tests/test_price_to_beat_provider.py tests/test_market_parsing.py
git commit -m "feat: prefer verified anchor price for ptb"
```

---

### Task 5: PTB Diff strict anchor-required mode

**Files:**
- Modify: `src/polysignal_lab/strategies/config.py`
- Modify: `src/polysignal_lab/strategies/ptb_diff.py`
- Test: `tests/test_ptb_diff.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: snapshot metric `price_to_beat_from_anchor_service`
- Produces: `PTBDiffConfig.require_anchor_price_source: bool = False`

- [x] **Step 1: Write the failing test**

Add to `tests/test_ptb_diff.py`:

```python
from polysignal_lab.strategies.config import PTBDiffConfig
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy


def test_ptb_diff_strict_anchor_mode_rejects_verified_metadata(snapshot_factory) -> None:
    snapshot = snapshot_factory(
        price_to_beat=64000.0,
        metrics={
            "price_to_beat_verified": True,
            "price_to_beat_source": "market_metadata",
            "price_to_beat_from_anchor_service": False,
        },
    )
    strategy = PTBDiffStrategy(PTBDiffConfig(require_anchor_price_source=True))

    assert strategy.evaluate(snapshot) == []
```

- [x] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_ptb_diff.py::test_ptb_diff_strict_anchor_mode_rejects_verified_metadata -v`

Expected: FAIL because config field is unknown.

- [x] **Step 3: Implement strict mode**

In `PTBDiffConfig`, add:

```python
require_anchor_price_source: bool = False
```

In `PTBDiffStrategy.evaluate()`, after the generic verified PTB check:

```python
if self.config.require_anchor_price_source and not snapshot.metrics.get("price_to_beat_from_anchor_service"):
    return []
```

If the strategy already accumulates reason metrics before candidate creation, use reason code `ANCHOR_PRICE_REQUIRED` in that path.

- [x] **Step 4: Run tests to verify behavior**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_ptb_diff.py tests/test_config.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/strategies/config.py src/polysignal_lab/strategies/ptb_diff.py tests/test_ptb_diff.py tests/test_config.py
git commit -m "feat: require anchor source for ptb diff"
```

---

### Task 6: Anchor health and final verification

**Files:**
- Modify: `src/polysignal_lab/data/anchor_price_service.py`
- Modify: `src/polysignal_lab/dashboard/app.py` only if spec 04 health is already merged
- Test: `tests/test_anchor_price_service.py`
- Test: `tests/test_dashboard.py` only if dashboard health consumes anchor metrics

**Interfaces:**
- Consumes: `AnchorPriceService.health_metrics()`
- Produces: serializable anchor lag/source health data

- [x] **Step 1: Write health test**

Add to `tests/test_anchor_price_service.py`:

```python
def test_anchor_service_health_reports_latest_lag_and_source() -> None:
    store = _Store()
    spots = SpotRegistry()
    market = _market("btc-updown-5m-1782216000")
    spots.update(SpotPrice(asset="BTC", price=64250.25, exchange="binance", event_time=market.start_ts))
    service = AnchorPriceService(spots=spots, store=store, max_lag_ms=1_000)
    service.capture_for_market(market)

    metrics = service.health_metrics()

    assert metrics["BTC:5m"]["source"] == "binance"
    assert metrics["BTC:5m"]["verified"] is True
    assert metrics["BTC:5m"]["lag_ms"] == 0
```

- [x] **Step 2: Run all focused tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_anchor_price_service.py tests/test_price_to_beat_provider.py tests/test_market_parsing.py tests/test_ptb_diff.py tests/test_storage_reporting_publish.py tests/test_market_data.py -v`

Expected: PASS.

- [x] **Step 3: Defer final Docker verification to after merge to runtime branch**

Run after merging this worktree into the formal runtime branch:

```bash
docker compose up -d --build --force-recreate
docker compose ps
```

Expected: all services are running or healthy according to compose output, and scheduler logs show no startup calls to the blocked Polymarket crypto-price endpoint.

- [x] **Step 4: Commit final test/docs adjustments**

```bash
git add src tests config docs/superpowers/plans/2026-06-23-05-anchor-price-service-implementation.md
git commit -m "test: cover anchor price service integration"
```
