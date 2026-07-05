# Nautilus Shadow Wallet Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Nautilus runtime reports, housekeeping, and fill handling use Nautilus cache/portfolio as the only runtime truth source, with no scheduler `PaperWallet` shadow ledger fed from Nautilus fills.

**Architecture:** Keep legacy scheduler paper trading intact outside Nautilus mode. In Nautilus mode, `node.py` still builds a `PolySignalScheduler` for configuration, discovery, publishing, health, and reports, but it must not mirror Nautilus fills into `PaperWallet`, must not run legacy settlement over that wallet, and report equity must prefer `NautilusCacheReader` whenever present. Existing fill notification through `paper_fill_notifier` remains; `paper_fill_mirror` may remain as a dormant optional `ObservabilityActor` extension point, but `node.py` must not wire it.

**Tech Stack:** Python 3.11 default runtime, optional NautilusTrader on Python 3.12+, pytest, Pydantic domain models, `uv run pytest`.

## Global Constraints

- Default Python 3.11 runtime must not require importing NautilusTrader.
- NautilusTrader is optional and only available for Python `>=3.12`.
- Legacy non-Nautilus paper trading keeps `PaperWallet`, `PaperSimulator`, `PaperSettlementEngine`, and existing scheduler behavior.
- Nautilus mode must use `NautilusCacheReader` for report equity/open-position counts when `scheduler.nautilus_cache_reader` exists.
- Nautilus mode must keep Telegram/publish fill notifications through `paper_fill_notifier`; only scheduler wallet mirroring is removed.
- No `paper_fill_mirror` wiring from `node.py` in Nautilus mode.
- No `scheduler_compat` import from `node.py`.
- Keep line length compatible with Black line length 100.
- Run only targeted tests listed in each task during implementation; run the final targeted suite before completion.

---

## Scope Boundary

This executable plan fixes the live Nautilus shadow-wallet problem only.

Separate implementation plans are required for these independent findings:

1. `matching.py` private/direct sandbox path: boundary bypass, not part of this plan.
2. Self-built Polymarket REST/WS and `domain/orderbook.py`: legacy/default Python 3.11 data layer remains necessary; Nautilus runtime already must not wire `NautilusDataIngestor` as default data owner.
3. `AsyncRateLimiter` and `ChannelRateLimiter`: low severity; they serve different public REST polling and Telegram channel-frequency domains and are not Nautilus network-layer duplicates.

---

## File Structure

- Modify: `src/polysignal_lab/app/scheduler_reporting.py`
  - Responsibility: build report equity inputs. Change it to prefer `NautilusCacheReader` before legacy `scheduler.wallet`.
- Modify: `src/polysignal_lab/nautilus_runtime/node.py`
  - Responsibility: assemble and run Nautilus runtime. Remove scheduler fill-mirror wiring, remove settlement compatibility initialization, mark the scheduler as TradingNode-owned, skip legacy wallet settlement in Nautilus housekeeping, and stop without legacy scheduler wallet persistence.
- Modify: `tests/test_nautilus_node.py`
  - Responsibility: assert Nautilus context no longer wires shadow wallet/mirror behavior and housekeeping skips legacy settlement when cache reader is present.
- Create: `tests/test_nautilus_reporting_cache_source.py`
  - Responsibility: assert daily-report equity inputs prefer Nautilus cache/portfolio over scheduler wallet in Nautilus mode and preserve legacy fallback without cache reader.
- Modify: `tests/test_nautilus_dependency_boundary.py`
  - Responsibility: prevent `node.py` from re-importing scheduler shadow-wallet compatibility.
- Existing but not modified in this plan: `src/polysignal_lab/nautilus_runtime/scheduler_compat.py`
  - Responsibility after this plan: unused by default Nautilus runtime. It may still serve legacy repair/test setup until a separate cleanup plan removes or relocates it.

---

### Task 1: Make Report Equity Cache-First in Nautilus Mode

**Files:**
- Create: `tests/test_nautilus_reporting_cache_source.py`
- Modify: `src/polysignal_lab/app/scheduler_reporting.py:326-379`
- Test: `tests/test_nautilus_reporting_cache_source.py`

**Interfaces:**
- Consumes: `scheduler.nautilus_cache_reader` with optional methods `read_account_projection()`, `snapshot_portfolio_projection()`, and `read_positions()`.
- Produces: `_report_equity_inputs(scheduler) -> tuple[float, float, int]` where Nautilus cache/portfolio wins when present; legacy wallet remains fallback when no cache reader exists.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_nautilus_reporting_cache_source.py` with this exact content:

```python
from __future__ import annotations

from types import SimpleNamespace

from polysignal_lab.app.scheduler_reporting import _report_equity_inputs


def _settings(starting_balance: float = 1_000.0) -> SimpleNamespace:
    return SimpleNamespace(
        paper_trading=SimpleNamespace(starting_balance_usdc=starting_balance),
    )


def test_report_equity_inputs_prefers_nautilus_cache_reader_over_shadow_wallet() -> None:
    wallet = SimpleNamespace(
        starting_balance=999.0,
        equity=111.0,
        open_position_count=9,
    )
    cache_reader = SimpleNamespace(
        snapshot_portfolio_projection=lambda: {"equity": 1_234.5},
        read_account_projection=lambda: {
            "balances": [{"currency": "USDC", "total": 2_222.0}],
        },
        read_positions=lambda: [
            {"is_closed": False, "position_id": "P-1"},
            {"is_closed": True, "position_id": "P-2"},
            {"is_closed": False, "position_id": "P-3"},
        ],
    )
    scheduler = SimpleNamespace(
        settings=_settings(),
        wallet=wallet,
        nautilus_cache_reader=cache_reader,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_234.5, 2)


def test_report_equity_inputs_uses_nautilus_account_balance_when_portfolio_equity_missing() -> None:
    cache_reader = SimpleNamespace(
        snapshot_portfolio_projection=lambda: {"equity": 0.0},
        read_account_projection=lambda: {
            "balances": [
                {"currency": "BTC", "total": 99.0},
                {"currency": "USDC", "total": 987.65},
            ],
        },
        read_positions=lambda: [{"is_closed": False, "position_id": "P-1"}],
    )
    scheduler = SimpleNamespace(
        settings=_settings(),
        wallet=SimpleNamespace(starting_balance=50.0, equity=50.0, open_position_count=50),
        nautilus_cache_reader=cache_reader,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 987.65, 1)


def test_report_equity_inputs_keeps_legacy_wallet_fallback_without_cache_reader() -> None:
    scheduler = SimpleNamespace(
        settings=_settings(),
        wallet=SimpleNamespace(starting_balance=1_000.0, equity=1_025.0, open_position_count=3),
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_025.0, 3)
```

- [ ] **Step 2: Run tests to verify the new cache-priority assertions fail**

Run:

```bash
uv run pytest tests/test_nautilus_reporting_cache_source.py -v
```

Expected: first two tests fail because current `_report_equity_inputs` returns wallet values before reading `nautilus_cache_reader`; third test passes.

- [ ] **Step 3: Replace `_report_equity_inputs` and add helper**

In `src/polysignal_lab/app/scheduler_reporting.py`, replace the existing `_report_equity_inputs` body with this code:

```python
def _report_equity_inputs(scheduler: PolySignalScheduler) -> tuple[float, float, int]:
    starting_equity = float(scheduler.settings.paper_trading.starting_balance_usdc)
    cache_reader = _nautilus_cache_reader(scheduler)
    if cache_reader is not None:
        return _report_equity_inputs_from_nautilus_cache(
            cache_reader,
            starting_equity=starting_equity,
        )

    wallet = getattr(scheduler, "wallet", None)
    if wallet is not None:
        return (
            float(getattr(wallet, "starting_balance")),
            float(getattr(wallet, "equity")),
            int(getattr(wallet, "open_position_count")),
        )

    return starting_equity, starting_equity, 0
```

Add this helper immediately below `_report_equity_inputs`:

```python
def _report_equity_inputs_from_nautilus_cache(
    cache_reader: object,
    *,
    starting_equity: float,
) -> tuple[float, float, int]:
    ending_equity = starting_equity
    open_positions = 0

    read_account_projection = getattr(cache_reader, "read_account_projection", None)
    snapshot_portfolio_projection = getattr(cache_reader, "snapshot_portfolio_projection", None)
    read_positions = getattr(cache_reader, "read_positions", None)

    portfolio_projection = (
        snapshot_portfolio_projection()
        if callable(snapshot_portfolio_projection)
        else None
    )
    account_projection = (
        read_account_projection()
        if callable(read_account_projection)
        else None
    )
    ending_equity = (
        _projection_float(cast(dict[str, object] | None, portfolio_projection), "equity")
        or ending_equity
    )
    if ending_equity == starting_equity and isinstance(account_projection, dict):
        balances = account_projection.get("balances")
        if isinstance(balances, list):
            for balance in balances:
                if not isinstance(balance, dict):
                    continue
                if str(balance.get("currency", "")).upper() != "USDC":
                    continue
                total = _projection_float(balance, "total")
                if total is not None:
                    ending_equity = total
                    break
    positions = read_positions() if callable(read_positions) else []
    if isinstance(positions, list):
        open_positions = sum(
            1
            for position in positions
            if isinstance(position, dict) and not bool(position.get("is_closed"))
        )
    return starting_equity, ending_equity, open_positions
```

- [ ] **Step 4: Run report and cache reader tests**

Run:

```bash
uv run pytest \
  tests/test_nautilus_reporting_cache_source.py \
  tests/test_nautilus_cache_reader.py \
  -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit passing report change**

Run:

```bash
git add src/polysignal_lab/app/scheduler_reporting.py tests/test_nautilus_reporting_cache_source.py
git commit -m "fix: use Nautilus cache for report equity"
```

Expected: commit succeeds with only the reporting code and reporting tests staged.

---

### Task 2: Remove Shadow Wallet Wiring From Nautilus Runtime Context

**Files:**
- Modify: `tests/test_nautilus_node.py:459-568`
- Modify: `tests/test_nautilus_node.py:819-858`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py:51-54`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py:748-775`
- Test: selected tests in `tests/test_nautilus_node.py`

**Interfaces:**
- Consumes: `node._prepare_nautilus_runtime_context(settings) -> tuple[PolySignalScheduler, tuple[Market, ...], ObservabilityActor]`.
- Produces: `_nautilus_runtime_owned_by_trading_node` marker on scheduler.
- Produces: Nautilus observability with `paper_fill_notifier` only; no node-wired `paper_fill_mirror`.

- [ ] **Step 1: Update `test_build_nautilus_runtime_discovers_market_universe_for_trading_node` expectation**

In `tests/test_nautilus_node.py`, inside `test_build_nautilus_runtime_discovers_market_universe_for_trading_node`, replace this assertion:

```python
    assert callable(getattr(captured["observability"], "paper_fill_mirror", None))
```

with:

```python
    assert getattr(captured["observability"], "paper_fill_mirror", None) is None
```

Keep these existing assertions unchanged:

```python
    assert callable(getattr(captured["observability"], "paper_fill_notifier", None))
    assert callable(getattr(captured["observability"], "accepted_signal_notifier", None))
```

- [ ] **Step 2: Replace the runtime-context shadow wallet test**

In `tests/test_nautilus_node.py`, replace `test_prepare_nautilus_runtime_context_initializes_settlement_compat_state` with this exact test:

```python
async def test_prepare_nautilus_runtime_context_does_not_wire_shadow_wallet_mirror(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.market import Market, OutcomeToken

    market = Market(
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="up-token", side=Side.UP, outcome_name="Up", market_id="btc-5m"),
            OutcomeToken(token_id="down-token", side=Side.DOWN, outcome_name="Down", market_id="btc-5m"),
        ],
    )

    settings = Settings()
    scheduler = node_mod.PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler.market_universe.refresh_once = AsyncMock(return_value=[market])
    scheduler.publisher = _fake_telegram_publisher()

    monkeypatch.setattr(node_mod, "PolySignalScheduler", lambda _settings=None: scheduler)

    sched, discovered_markets, observability = await node_mod._prepare_nautilus_runtime_context(settings)

    assert sched is scheduler
    assert discovered_markets == (market,)
    assert getattr(scheduler, "_nautilus_runtime_owned_by_trading_node") is True
    assert not hasattr(scheduler, "_nautilus_runtime_compat_only")
    assert callable(getattr(observability, "paper_fill_notifier", None))
    assert getattr(observability, "paper_fill_mirror", None) is None
```

- [ ] **Step 3: Run selected tests to verify they fail before implementation**

Run:

```bash
uv run pytest \
  tests/test_nautilus_node.py::test_build_nautilus_runtime_discovers_market_universe_for_trading_node \
  tests/test_nautilus_node.py::test_prepare_nautilus_runtime_context_does_not_wire_shadow_wallet_mirror \
  -v
```

Expected: selected tests fail because `node.py` still wires `paper_fill_mirror` and still initializes scheduler compatibility state.

- [ ] **Step 4: Remove scheduler compatibility imports**

In `src/polysignal_lab/nautilus_runtime/node.py`, delete this import block:

```python
from polysignal_lab.nautilus_runtime.scheduler_compat import (
    init_scheduler_paper_components,
    mirror_nautilus_fill_into_scheduler,
)
```

- [ ] **Step 5: Delete the node-level fill mirror function**

In `src/polysignal_lab/nautilus_runtime/node.py`, delete `_mirror_nautilus_paper_fill` entirely:

```python
def _mirror_nautilus_paper_fill(
    scheduler: PolySignalScheduler,
    payload: Mapping[str, object],
) -> None:
    try:
        _ = mirror_nautilus_fill_into_scheduler(scheduler, payload)
    except Exception as exc:
        scheduler.logger.warning(
            "Nautilus paper fill mirror failed for %s: %s",
            payload.get("paper_fill_id") or payload.get("client_order_id") or payload.get("order_id") or "unknown",
            exc,
        )
```

- [ ] **Step 6: Delete settlement compatibility preparation**

In `src/polysignal_lab/nautilus_runtime/node.py`, delete `_initialize_nautilus_settlement_compat` entirely:

```python
async def _initialize_nautilus_settlement_compat(
    scheduler: PolySignalScheduler,
) -> None:
    init_scheduler_paper_components(scheduler)
    restore_wallet = getattr(scheduler, "_restore_wallet_state", None)
    if callable(restore_wallet):
        await cast(Callable[[], Awaitable[object]], restore_wallet)()
```

- [ ] **Step 7: Mark scheduler as TradingNode-owned and stop wiring mirror**

In `_prepare_nautilus_runtime_context`, replace:

```python
    _initialize_nautilus_scheduler_components(scheduler)
    await _initialize_nautilus_settlement_compat(scheduler)
```

with:

```python
    _initialize_nautilus_scheduler_components(scheduler)
    setattr(scheduler, "_nautilus_runtime_owned_by_trading_node", True)
```

In the `ObservabilityActor(...)` call, replace:

```python
        paper_fill_notifier=lambda payload: _notify_nautilus_paper_fill(scheduler, payload),
        paper_fill_mirror=lambda payload: _mirror_nautilus_paper_fill(scheduler, payload),
```

with:

```python
        paper_fill_notifier=lambda payload: _notify_nautilus_paper_fill(scheduler, payload),
```

- [ ] **Step 8: Run selected tests to verify they pass**

Run:

```bash
uv run pytest \
  tests/test_nautilus_node.py::test_build_nautilus_runtime_discovers_market_universe_for_trading_node \
  tests/test_nautilus_node.py::test_prepare_nautilus_runtime_context_does_not_wire_shadow_wallet_mirror \
  -v
```

Expected: selected tests pass.

- [ ] **Step 9: Commit passing runtime context change**

Run:

```bash
git add src/polysignal_lab/nautilus_runtime/node.py tests/test_nautilus_node.py
git commit -m "fix: remove Nautilus fill shadow wallet wiring"
```

Expected: commit succeeds with node and node tests staged.

---

### Task 3: Skip Legacy Settlement and Legacy Stop in Nautilus Mode

**Files:**
- Modify: `tests/test_nautilus_node.py:860-956`
- Modify: `tests/test_nautilus_node.py:1613-1638`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py:493-518`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py:932-942`
- Test: selected tests in `tests/test_nautilus_node.py`

**Interfaces:**
- Consumes: `_nautilus_runtime_owned_by_trading_node` marker introduced in Task 2.
- Consumes: `scheduler.nautilus_cache_reader` set by `_build_nautilus_runtime_bundle`.
- Produces: `_stop_nautilus_scheduler` that does not call legacy `scheduler.stop()` for TradingNode-owned Nautilus mode.
- Produces: `_run_nautilus_housekeeping_once` that does not call legacy settlement when a Nautilus cache reader exists.

- [ ] **Step 1: Replace the mirrored-fill settlement housekeeping test**

In `tests/test_nautilus_node.py`, replace `test_run_nautilus_housekeeping_once_settles_mirrored_fill_position` with this exact test:

```python
async def test_run_nautilus_housekeeping_once_skips_legacy_settlement_with_cache_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    import polysignal_lab.app.scheduler_runtime as runtime_mod

    calls: list[str] = []

    async def fail_legacy_settlements(_scheduler: object) -> None:
        calls.append("settlement")
        raise AssertionError("Nautilus housekeeping must not settle legacy wallet positions")

    async def generate_iteration_report(_scheduler: object, last_report_date: object) -> str:
        calls.append(f"report:{last_report_date}")
        return "2026-07-05"

    monkeypatch.setattr(runtime_mod, "_check_iteration_settlements", fail_legacy_settlements)
    monkeypatch.setattr(runtime_mod, "_generate_iteration_report", generate_iteration_report)

    scheduler = SimpleNamespace(nautilus_cache_reader=object())

    result = await node_mod._run_nautilus_housekeeping_once(scheduler, "2026-07-04")

    assert result == "2026-07-05"
    assert calls == ["report:2026-07-04"]
```

- [ ] **Step 2: Add a stop test for TradingNode-owned scheduler**

Append this test near `test_stop_nautilus_scheduler_skips_legacy_wallet_persist_without_wallet`:

```python
async def test_stop_nautilus_scheduler_skips_legacy_stop_for_trading_node_owned_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod

    calls: list[str] = []

    monkeypatch.setattr(
        node_mod.scheduler_health,
        "persist_health_snapshot",
        lambda scheduler: calls.append("health"),
    )

    async def legacy_stop() -> None:
        calls.append("legacy_stop")
        raise AssertionError("Nautilus TradingNode-owned scheduler must not call legacy stop")

    scheduler = SimpleNamespace(
        _nautilus_runtime_owned_by_trading_node=True,
        wallet=object(),
        stop=legacy_stop,
    )

    await node_mod._stop_nautilus_scheduler(scheduler)

    assert scheduler._running is False
    assert calls == ["health"]
```

- [ ] **Step 3: Run selected tests to verify they fail before implementation**

Run:

```bash
uv run pytest \
  tests/test_nautilus_node.py::test_run_nautilus_housekeeping_once_skips_legacy_settlement_with_cache_reader \
  tests/test_nautilus_node.py::test_stop_nautilus_scheduler_skips_legacy_stop_for_trading_node_owned_scheduler \
  -v
```

Expected: selected tests fail because housekeeping still calls legacy settlement and `_stop_nautilus_scheduler` does not yet recognize `_nautilus_runtime_owned_by_trading_node`.

- [ ] **Step 4: Replace `_stop_nautilus_scheduler`**

In `src/polysignal_lab/nautilus_runtime/node.py`, replace `_stop_nautilus_scheduler` with:

```python
async def _stop_nautilus_scheduler(scheduler: object) -> None:
    if bool(getattr(scheduler, "_nautilus_runtime_owned_by_trading_node", False)):
        setattr(scheduler, "_running", False)
        try:
            scheduler_health.persist_health_snapshot(cast(PolySignalScheduler, scheduler))
        except Exception as exc:
            cast(logging.Logger, getattr(scheduler, "logger", logger)).warning(
                "Failed to persist Nautilus health snapshot: %s",
                exc,
            )
        return

    stop = getattr(scheduler, "stop", None)
    if hasattr(scheduler, "wallet") and callable(stop):
        await cast(Callable[[], Awaitable[object]], stop)()
        return

    setattr(scheduler, "_running", False)
    try:
        scheduler_health.persist_health_snapshot(cast(PolySignalScheduler, scheduler))
    except Exception as exc:
        cast(logging.Logger, getattr(scheduler, "logger", logger)).warning(
            "Failed to persist Nautilus health snapshot: %s",
            exc,
        )
```

- [ ] **Step 5: Replace `_run_nautilus_housekeeping_once`**

In `src/polysignal_lab/nautilus_runtime/node.py`, replace `_run_nautilus_housekeeping_once` with:

```python
async def _run_nautilus_housekeeping_once(
    scheduler: PolySignalScheduler,
    last_report_date: date | None,
) -> date | None:
    from polysignal_lab.app.scheduler_runtime import (
        _check_iteration_settlements,
        _generate_iteration_report,
    )

    if getattr(scheduler, "nautilus_cache_reader", None) is None:
        await _check_iteration_settlements(scheduler)
    return await _generate_iteration_report(scheduler, last_report_date)
```

- [ ] **Step 6: Run selected tests to verify they pass**

Run:

```bash
uv run pytest \
  tests/test_nautilus_node.py::test_run_nautilus_housekeeping_once_skips_legacy_settlement_with_cache_reader \
  tests/test_nautilus_node.py::test_stop_nautilus_scheduler_skips_legacy_stop_for_trading_node_owned_scheduler \
  tests/test_nautilus_node.py::test_stop_nautilus_scheduler_skips_legacy_wallet_persist_without_wallet \
  -v
```

Expected: selected tests pass.

- [ ] **Step 7: Commit passing housekeeping/stop change**

Run:

```bash
git add src/polysignal_lab/nautilus_runtime/node.py tests/test_nautilus_node.py
git commit -m "fix: skip legacy settlement in Nautilus housekeeping"
```

Expected: commit succeeds with node and node tests staged.

---

### Task 4: Add Boundary Test Against Reintroducing Scheduler Compat in Node

**Files:**
- Modify: `tests/test_nautilus_dependency_boundary.py`
- Test: `tests/test_nautilus_dependency_boundary.py`

**Interfaces:**
- Consumes: source text of `src/polysignal_lab/nautilus_runtime/node.py`.
- Produces: regression guard that `node.py` does not import or call scheduler shadow-wallet compatibility.

- [ ] **Step 1: Add the boundary test**

`tests/test_nautilus_dependency_boundary.py` already imports `Path`. Append this exact test:

```python
def test_nautilus_node_does_not_import_scheduler_compat_shadow_wallet() -> None:
    source = Path("src/polysignal_lab/nautilus_runtime/node.py").read_text()

    assert "scheduler_compat" not in source
    assert "init_scheduler_paper_components" not in source
    assert "mirror_nautilus_fill_into_scheduler" not in source
    assert "paper_fill_mirror=lambda" not in source
```

- [ ] **Step 2: Run the boundary test**

Run:

```bash
uv run pytest tests/test_nautilus_dependency_boundary.py::test_nautilus_node_does_not_import_scheduler_compat_shadow_wallet -v
```

Expected: PASS after Tasks 2 and 3.

- [ ] **Step 3: Commit the boundary guard**

Run:

```bash
git add tests/test_nautilus_dependency_boundary.py
git commit -m "test: guard Nautilus node against shadow wallet imports"
```

Expected: commit succeeds with dependency-boundary test staged.

---

### Task 5: Final Targeted Verification

**Files:**
- Modify: none
- Test: targeted Nautilus/reporting tests

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verification that the shadow-wallet removal did not break cache projections, node assembly, or default Nautilus sandbox routing.

- [ ] **Step 1: Run reporting and cache tests**

Run:

```bash
uv run pytest \
  tests/test_nautilus_reporting_cache_source.py \
  tests/test_nautilus_cache_reader.py \
  -v
```

Expected: all selected tests pass.

- [ ] **Step 2: Run node and boundary tests**

Run:

```bash
uv run pytest \
  tests/test_nautilus_node.py \
  tests/test_nautilus_dependency_boundary.py \
  -v
```

Expected: all selected tests pass.

- [ ] **Step 3: Run optional Nautilus integration smoke when Nautilus is available**

Run:

```bash
uv run pytest tests/test_nautilus_default_runtime_integration.py -v
```

Expected on Python 3.11 or without NautilusTrader: tests skip with message `nautilus_trader requires Python 3.12+` or `nautilus_trader is not installed`. Expected on Python 3.12+ with NautilusTrader installed: tests pass.

- [ ] **Step 4: Run Python compile checks for touched modules**

Run:

```bash
uv run python -m py_compile \
  src/polysignal_lab/app/scheduler_reporting.py \
  src/polysignal_lab/nautilus_runtime/node.py
```

Expected: command exits 0 with no output.

- [ ] **Step 5: Commit final fix if verification exposed one**

If Task 5 required a code or test fix, run:

```bash
git add src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/nautilus_runtime/node.py tests/test_nautilus_node.py tests/test_nautilus_reporting_cache_source.py tests/test_nautilus_dependency_boundary.py
git commit -m "fix: complete Nautilus shadow wallet removal"
```

Expected: commit succeeds only if Task 5 made additional changes. If Task 5 made no changes, do not create an empty commit.

---

## Self-Review

**Spec coverage:**
- Report equity/open-position source priority is covered by Task 1.
- Nautilus runtime fill mirror removal is covered by Task 2.
- Legacy settlement skip in Nautilus housekeeping is covered by Task 3.
- Legacy scheduler stop bypass in TradingNode-owned Nautilus mode is covered by Task 3.
- Guard against reintroducing `scheduler_compat` into `node.py` is covered by Task 4.
- Final verification is covered by Task 5.
- `matching.py`, self-built Polymarket clients, `domain/orderbook.py`, and rate limiters are intentionally outside this executable plan because they are independent subsystems with different acceptance criteria.

**Placeholder scan:**
- No placeholder marker strings.
- No placeholder functions.
- No commits of intentionally failing tests.
- Every test step includes exact code and command.
- Every implementation step includes exact code replacement or exact deletion target.
- Existing test updates name exact test functions and exact assertion replacements.

**Type consistency:**
- `_report_equity_inputs(scheduler) -> tuple[float, float, int]` remains unchanged.
- `_report_equity_inputs_from_nautilus_cache(cache_reader: object, *, starting_equity: float) -> tuple[float, float, int]` is introduced and only used by `_report_equity_inputs`.
- `_nautilus_runtime_owned_by_trading_node` is the only new scheduler marker.
- `paper_fill_notifier` remains wired; `paper_fill_mirror` is not wired by `node.py`.
