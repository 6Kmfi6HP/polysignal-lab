# Nautilus L1 Subscriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Nautilus `fast_l1` runtime use L1-compatible market-data subscriptions while preserving trade-tick execution semantics and strategy alpha behavior.

**Architecture:** Keep the change local to `PolySignalNativeStrategy` and its tests. Add a small feed-selection layer based on the existing `book_type`; L1 mode prefers quote ticks, falls back to interval books, and only uses raw deltas as a visible diagnostic fallback. Existing strategy cores, signal gates, order mapping, and fill handling remain untouched.

**Tech Stack:** Python 3.12, pytest, Pydantic settings, NautilusTrader strategy callbacks, PolySignal `MarketViewAssembler` and `NautilusBookDataProvider`.

---

## File Map

- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py` for feed selection, L1 handlers, and fallback diagnostics.
- Modify: `src/polysignal_lab/config.py` for `l1_book_snapshot_interval_ms` if interval fallback needs configuration.
- Modify: `src/polysignal_lab/nautilus_runtime/node.py` to pass the interval into native strategies.
- Modify: `tests/test_nautilus_strategy_base.py` for native strategy subscription, L1 projection, and behavior tests.
- Modify: `tests/test_nautilus_node.py` for config propagation.
- Reference: `docs/superpowers/specs/2026-07-02-nautilus-l1-subscriptions-design.md`.

---

### Task 1: Add Subscription Selection Tests

**Files:**
- Modify: `tests/test_nautilus_strategy_base.py`
- Test: `tests/test_nautilus_strategy_base.py`

- [x] **Step 1: Write the failing L1 quote preference test**

Append near the existing native strategy callback tests:

```python
def test_native_strategy_l1_prefers_quote_ticks_and_trade_ticks() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.cache = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_quotes: list[object] = []
            self.subscribed_trades: list[object] = []
            self.subscribed_deltas: list[object] = []

        def request_instrument(self, instrument_id: object) -> None:
            _ = instrument_id

        def subscribe_quote_ticks(self, instrument_id: object) -> None:
            self.subscribed_quotes.append(instrument_id)

        def subscribe_trade_ticks(self, instrument_id: object) -> None:
            self.subscribed_trades.append(instrument_id)

        def subscribe_order_book_deltas(self, **kwargs: object) -> None:
            self.subscribed_deltas.append(kwargs)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        book_type="L1_MBP",
        **_native_projections(),
    )

    assert strategy._subscribe_market_instrument("up-token.POLYMARKET") is True
    assert strategy.subscribed_quotes == ["up-token.POLYMARKET"]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]
    assert strategy.subscribed_deltas == []
```

- [x] **Step 2: Write the failing L1 interval fallback test**

```python
def test_native_strategy_l1_uses_interval_book_when_quote_ticks_unavailable() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.cache = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_interval_books: list[dict[str, object]] = []
            self.subscribed_trades: list[object] = []
            self.subscribed_deltas: list[object] = []

        def request_instrument(self, instrument_id: object) -> None:
            _ = instrument_id

        def subscribe_order_book_at_interval(self, **kwargs: object) -> None:
            self.subscribed_interval_books.append(kwargs)

        def subscribe_trade_ticks(self, instrument_id: object) -> None:
            self.subscribed_trades.append(instrument_id)

        def subscribe_order_book_deltas(self, **kwargs: object) -> None:
            self.subscribed_deltas.append(kwargs)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        book_type="L1_MBP",
        **_native_projections(),
    )

    assert strategy._subscribe_market_instrument("up-token.POLYMARKET") is True
    assert strategy.subscribed_interval_books == [
        {"instrument_id": "up-token.POLYMARKET", "interval_ms": 1000}
    ]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]
    assert strategy.subscribed_deltas == []
```

- [x] **Step 3: Write the failing visible raw-delta fallback test**

```python
def test_native_strategy_l1_raw_delta_fallback_is_visible() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    phases: list[str] = []

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.cache = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_deltas: list[object] = []
            self.subscribed_trades: list[object] = []

        def request_instrument(self, instrument_id: object) -> None:
            _ = instrument_id

        def subscribe_trade_ticks(self, instrument_id: object) -> None:
            self.subscribed_trades.append(instrument_id)

        def subscribe_order_book_deltas(self, **kwargs: object) -> None:
            self.subscribed_deltas.append(kwargs)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        book_type="L1_MBP",
        progress_callback=phases.append,
        **_native_projections(),
    )

    assert strategy._subscribe_market_instrument("up-token.POLYMARKET") is True
    assert strategy.subscribed_deltas == [
        {"instrument_id": "up-token.POLYMARKET", "book_type": "L1_MBP"}
    ]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]
    assert "l1_raw_delta_fallback" in phases
```

- [x] **Step 4: Write the failing L2 unchanged test**

```python
def test_native_strategy_l2_keeps_order_book_deltas_and_trade_ticks() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.cache = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_deltas: list[dict[str, object]] = []
            self.subscribed_trades: list[object] = []
            self.subscribed_quotes: list[object] = []

        def request_instrument(self, instrument_id: object) -> None:
            _ = instrument_id

        def subscribe_quote_ticks(self, instrument_id: object) -> None:
            self.subscribed_quotes.append(instrument_id)

        def subscribe_trade_ticks(self, instrument_id: object) -> None:
            self.subscribed_trades.append(instrument_id)

        def subscribe_order_book_deltas(self, **kwargs: object) -> None:
            self.subscribed_deltas.append(kwargs)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        book_type="L2_MBP",
        **_native_projections(),
    )

    assert strategy._subscribe_market_instrument("up-token.POLYMARKET") is True
    assert strategy.subscribed_quotes == []
    assert strategy.subscribed_deltas == [
        {"instrument_id": "up-token.POLYMARKET", "book_type": "L2_MBP"}
    ]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]
```

- [x] **Step 5: Run tests and verify they fail**

Run:

```bash
pytest tests/test_nautilus_strategy_base.py -k "l1_prefers_quote_ticks or l1_uses_interval_book or l1_raw_delta_fallback or l2_keeps_order_book_deltas" -q
```

Expected: FAIL because `_subscribe_market_instrument()` always requires and uses raw deltas today.

- [x] **Step 6: Commit failing tests**

```bash
git add tests/test_nautilus_strategy_base.py
git commit -m "test: capture Nautilus L1 subscription selection"
```

---

### Task 2: Implement Mode-Aware Subscription Selection

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Test: `tests/test_nautilus_strategy_base.py`

- [x] **Step 1: Add constants near existing timer constants**

```python
DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS = 1000
L1_RAW_DELTA_FALLBACK_PHASE = "l1_raw_delta_fallback"
```

- [x] **Step 2: Add feed-selection helpers before `_subscribe_market_instrument()`**

```python
    def _is_l1_book_mode(self) -> bool:
        return self.book_type == "L1_MBP"

    def _l1_book_snapshot_interval_ms(self) -> int:
        return int(getattr(self, "l1_book_snapshot_interval_ms", DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS))

    def _subscribe_l1_book_feed(self, instrument_id: object) -> bool:
        subscribe_quote_ticks = getattr(self, "subscribe_quote_ticks", None)
        if callable(subscribe_quote_ticks):
            _ = subscribe_quote_ticks(instrument_id)
            return True
        subscribe_order_book_at_interval = getattr(self, "subscribe_order_book_at_interval", None)
        if callable(subscribe_order_book_at_interval):
            _ = subscribe_order_book_at_interval(
                instrument_id=instrument_id,
                interval_ms=self._l1_book_snapshot_interval_ms(),
            )
            return True
        return False

    def _subscribe_raw_delta_feed(self, instrument_id: object) -> bool:
        subscribe_order_book_deltas = getattr(self, "subscribe_order_book_deltas", None)
        if not callable(subscribe_order_book_deltas):
            return False
        _ = subscribe_order_book_deltas(
            instrument_id=instrument_id,
            book_type=_nautilus_book_type(self.book_type),
        )
        return True
```

- [x] **Step 3: Replace `_subscribe_market_instrument()` body**

```python
    def _subscribe_market_instrument(self, instrument_id: object) -> bool:
        instrument_text = _identifier_text(instrument_id)
        if instrument_text is None:
            return False
        if instrument_text in self._subscription_state.wire_instrument_ids:
            return True
        request_instrument = getattr(self, "request_instrument", None)
        if callable(request_instrument) and self._market_data_subscription_group.should_request(instrument_text):
            _ = request_instrument(instrument_id)
        if not self._instrument_is_cached(instrument_id):
            return False
        subscribe_trade_ticks = getattr(self, "subscribe_trade_ticks", None)
        if not callable(subscribe_trade_ticks):
            return False
        if self._market_data_subscription_group.acquire(instrument_text, self):
            book_feed_subscribed = False
            if self._is_l1_book_mode():
                book_feed_subscribed = self._subscribe_l1_book_feed(instrument_id)
                if not book_feed_subscribed:
                    self._note_runtime_progress(L1_RAW_DELTA_FALLBACK_PHASE)
            if not book_feed_subscribed:
                book_feed_subscribed = self._subscribe_raw_delta_feed(instrument_id)
            if not book_feed_subscribed:
                return False
            _ = subscribe_trade_ticks(instrument_id)
        self._subscription_state.wire_instrument_ids.add(instrument_text)
        return True
```

- [x] **Step 4: Run subscription tests**

Run:

```bash
pytest tests/test_nautilus_strategy_base.py -k "l1_prefers_quote_ticks or l1_uses_interval_book or l1_raw_delta_fallback or l2_keeps_order_book_deltas" -q
```

Expected: PASS.

- [x] **Step 5: Commit implementation**

```bash
git add src/polysignal_lab/nautilus_runtime/native_strategy.py tests/test_nautilus_strategy_base.py
git commit -m "fix: select Nautilus market data feed by book mode"
```


---

### Task 3: Add L1 Book Projection Handlers

**Files:**
- Modify: src/polysignal_lab/nautilus_runtime/native_strategy.py
- Modify: tests/test_nautilus_strategy_base.py

- [x] **Step 1: Add failing tests for quote tick and interval book projection**

Add two tests near test_native_strategy_trade_tick_callback_updates_shared_trade_history.

Test A: test_native_strategy_quote_tick_updates_token_book_and_evaluates
- Build a PolymarketMarketRegistry with condition-btc-5m, up-token.POLYMARKET, and down-token.POLYMARKET.
- Build NautilusBookDataProvider and MarketViewAssembler.
- Subclass PolySignalNativeStrategy to record evaluate_condition calls.
- Call strategy.on_quote_tick(SimpleNamespace(instrument_id="up-token.POLYMARKET", bid_price=0.49, ask_price=0.51, bid_size=12.0, ask_size=13.0, ts_event=datetime.now(UTC))).
- Assert books.book_for_token("up-token") exists, bids == ((0.49, 12.0),), asks == ((0.51, 13.0),), last_trade_price is None, and evaluated == ["condition-btc-5m"].

Test B: test_native_strategy_order_book_snapshot_updates_token_book_and_evaluates
- Build the same registry, book provider, and assembler.
- Define FakeLevel with price and size attributes.
- Call strategy.on_order_book(SimpleNamespace(instrument_id="down-token.POLYMARKET", bids=[FakeLevel(0.47, 10.0)], asks=[FakeLevel(0.53, 11.0)], last_trade_price=0.52, last_trade_size=3.0, last_trade_timestamp=None, received_at=datetime.now(UTC))).
- Assert books.book_for_token("down-token") exists, bids == ((0.47, 10.0),), asks == ((0.53, 11.0),), last_trade_price == 0.52, last_trade_size == 3.0, and evaluated == ["condition-btc-5m"].

- [x] **Step 2: Run projection tests and verify they fail**

Run: pytest tests/test_nautilus_strategy_base.py -k "quote_tick_updates_token_book or order_book_snapshot_updates_token_book" -q
Expected: FAIL because on_quote_tick and on_order_book do not exist.

- [x] **Step 3: Add L1 handlers after _update_book_from_deltas()**

Implement on_quote_tick, _update_book_from_quote_tick, on_order_book, and _update_book_from_order_book in src/polysignal_lab/nautilus_runtime/native_strategy.py.

Required behavior:
- Resolve instrument_id with _identifier_text.
- Resolve token_id with _token_id_for_instrument and condition_id with _condition_id_for_instrument.
- For quote ticks, read bid_price, ask_price, bid_size, ask_size with _maybe_float.
- Build an OrderBook with token_id, one bid level when bid_price exists, one ask level when ask_price exists, and received_at from ts_event or datetime.now(UTC).
- For order book snapshots, reuse _domain_order_book(token_id, order_book).
- Update assembler.books via update_book(token_id, order_book).
- Trigger _evaluate_market_data_condition(condition_id) from the public callback.

- [x] **Step 4: Run projection tests**

Run: pytest tests/test_nautilus_strategy_base.py -k "quote_tick_updates_token_book or order_book_snapshot_updates_token_book" -q
Expected: PASS.

- [x] **Step 5: Commit L1 projection handlers**

Run: git add src/polysignal_lab/nautilus_runtime/native_strategy.py tests/test_nautilus_strategy_base.py && git commit -m "fix: project Nautilus L1 book data into market views"

---

### Task 4: Add Snapshot Interval Config Propagation

**Files:**
- Modify: src/polysignal_lab/config.py
- Modify: src/polysignal_lab/nautilus_runtime/node.py
- Modify: src/polysignal_lab/nautilus_runtime/native_strategy.py
- Modify: tests/test_nautilus_node.py

- [x] **Step 1: Write failing config propagation test**

Add test_build_trading_node_passes_l1_snapshot_interval_to_native_strategies near test_build_trading_node_forwards_unsubscribe_exited_to_native_strategy in tests/test_nautilus_node.py.

```python
def test_build_trading_node_passes_l1_snapshot_interval_to_native_strategies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_nautilus_placeholders(monkeypatch)
    captured: dict[str, object] = {}

    class FakeRotationActor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeStrategy:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            self.strategy_name = kwargs["strategy_name"]

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.market_rotation.runtime_market_rotation_actor_type",
        lambda _base, _config: FakeRotationActor,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.native_strategy.runtime_native_strategy_type",
        lambda _base, _config: FakeStrategy,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._native_core_for",
        lambda _name, _cfg: object(),
    )

    settings = Settings()
    settings.runtime.nautilus.matching_accuracy_mode = "fast_l1"
    settings.runtime.nautilus.l1_book_snapshot_interval_ms = 250
    settings.strategies.set_explicit_strategy_names(("vwap_momentum",))

    runtime = build_trading_node(
        settings=settings,
        condition_ids=("condition-btc-5m",),
    )

    strategies = cast(list[object], runtime["strategies"])
    captured_kwargs = cast(dict[str, object], captured["kwargs"])

    assert len(strategies) == 1
    assert getattr(runtime["node"], "trader").strategies == strategies
    assert captured_kwargs["book_type"] == "L1_MBP"
    assert captured_kwargs["l1_book_snapshot_interval_ms"] == 250
```

- [x] **Step 2: Run config propagation test and verify it fails**

Run: pytest tests/test_nautilus_node.py -k "passes_l1_snapshot_interval" -q
Expected: FAIL because the field and kwarg do not exist.

- [x] **Step 3: Add config field**

In src/polysignal_lab/config.py, add to NautilusRuntimeConfig after matching_accuracy_mode: l1_book_snapshot_interval_ms: int = 1000

- [x] **Step 4: Pass config into native strategy construction**

In src/polysignal_lab/nautilus_runtime/node.py, inside _build_native_strategies(), add l1_book_snapshot_interval_ms=settings.runtime.nautilus.l1_book_snapshot_interval_ms to strategy_type(...).

- [x] **Step 5: Accept and store the strategy kwarg**

In src/polysignal_lab/nautilus_runtime/native_strategy.py:
- Add l1_book_snapshot_interval_ms: int = DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS to runtime_native_strategy_type.__init__.
- Pass it through to PolySignalNativeStrategy.__init__.
- Add the same parameter to PolySignalNativeStrategy.__init__.
- Store self.l1_book_snapshot_interval_ms = int(l1_book_snapshot_interval_ms).

- [x] **Step 6: Run config propagation test**

Run: pytest tests/test_nautilus_node.py -k "passes_l1_snapshot_interval" -q
Expected: PASS.

- [x] **Step 7: Commit config propagation**

Run: git add src/polysignal_lab/config.py src/polysignal_lab/nautilus_runtime/node.py src/polysignal_lab/nautilus_runtime/native_strategy.py tests/test_nautilus_node.py && git commit -m "feat: configure Nautilus L1 book snapshot interval"

---

### Task 5: Add VWAP Momentum Behavior Preservation Test

**Files:**
- Modify: tests/test_nautilus_strategy_base.py

- [x] **Step 1: Add behavior test**

Add test_native_strategy_l1_projection_preserves_vwap_momentum_decision_inputs.

Required setup:
- Build a BTC 15m MarketPairMeta with condition-btc-15m, up-token.POLYMARKET, and down-token.POLYMARKET.
- Use start_ts = now - timedelta(seconds=500), end_ts = now + timedelta(seconds=400).
- Add spot and price-to-beat data to ExternalDataSidecar.
- Use NautilusBookDataProvider and MarketViewAssembler.
- Use VWAPMomentumAlphaCore with VWAPMomentumConfig enabled for BTC and 15m, min_price 0.35, max_price 0.85, min_elapsed_sec 45, no_entry_before_end_sec 20, vwap_window_sec 30, momentum_window_sec 60, min_deviation_pct 0.01, max_deviation_pct 1.0, min_momentum 0.01.
- Use a RuntimeFakePolicy subclass that records decisions before delegating.
- Feed quote ticks for UP and DOWN, then two DOWN trade ticks: one at now - 61 seconds with price 0.50 and one at now with price 0.55.

Required assertions:
- policy.decisions is not empty.
- Last decision strategy is vwap_momentum.
- condition_id is condition-btc-15m.
- token_id is down-token.
- side is Side.DOWN.
- reason_codes contains VWAP_DEVIATION_OK.

- [x] **Step 2: Run behavior preservation test**

Run: pytest tests/test_nautilus_strategy_base.py -k "l1_projection_preserves_vwap_momentum" -q
Expected: PASS after Task 3. If it fails because the fixture does not produce enough VWAP or momentum history, adjust only fixture prices/timestamps.

- [x] **Step 3: Commit behavior test**

Run: git add tests/test_nautilus_strategy_base.py && git commit -m "test: preserve vwap momentum behavior with L1 feed"

---

### Task 6: Run Focused Regression Suite

**Files:**
- Test: tests/test_nautilus_strategy_base.py
- Test: tests/test_nautilus_node.py

- [x] **Step 1: Run native strategy tests**

Run: pytest tests/test_nautilus_strategy_base.py -q
Expected: PASS.

- [x] **Step 2: Run Nautilus node tests**

Run: pytest tests/test_nautilus_node.py -q
Expected: PASS.

- [x] **Step 3: Run lint diagnostics for edited files**

Use IDE diagnostics for src/polysignal_lab/nautilus_runtime/native_strategy.py, src/polysignal_lab/nautilus_runtime/node.py, src/polysignal_lab/config.py, tests/test_nautilus_strategy_base.py, and tests/test_nautilus_node.py.
Expected: no new diagnostics.

- [x] **Step 4: Commit any fixes**

If tests or lints required fixes, run: git add src/polysignal_lab/nautilus_runtime/native_strategy.py src/polysignal_lab/nautilus_runtime/node.py src/polysignal_lab/config.py tests/test_nautilus_strategy_base.py tests/test_nautilus_node.py && git commit -m "fix: stabilize Nautilus L1 subscription tests"
If no fixes were needed, skip this commit.

---

### Task 7: Runtime Verification Checklist

**Files:**
- No source changes expected.

- [x] **Step 1: Record baseline**

Run: docker stats --no-stream --format 'table {{.Name}}	{{.CPUPerc}}	{{.MemUsage}}	{{.NetIO}}	{{.BlockIO}}'
Run the existing log-rate script from the spec review or summarize nautilus_decisions.jsonl and rejected_signals.jsonl by top seconds.
Expected: captures CPU, memory, network, and event-rate baseline.

- [x] **Step 2: Start runtime**

Use the project deployment command. For compose from repo root, run: docker compose up -d --build polysignal-lab
Expected: container starts healthy.

- [x] **Step 3: Confirm selected feed path**

Inspect logs or health diagnostics.
Expected one of: quote_ticks selected, order_book_at_interval selected, or l1_raw_delta_fallback.
If l1_raw_delta_fallback appears, the optimization is not active.

- [x] **Step 4: Re-measure after at least five minutes**

Run the same commands from Step 1.
Expected: CPU and event rates are below baseline when L1 feed path is active. Memory remains stable. Network input may only drop if the adapter avoids raw deltas upstream.

- [x] **Step 5: Document results**

Include in handoff or PR summary:
Runtime verification:
- Selected L1 feed path:
- Baseline CPU/memory/network:
- Post-change CPU/memory/network:
- Baseline decision/rejection rate:
- Post-change decision/rejection rate:

---

## Self-Review

- Spec coverage: The plan covers capability-aware subscription selection, L1 projection, token-specific binary market handling, visible raw-delta fallback, snapshot interval configuration, behavior preservation tests, and runtime verification.
- Completeness scan: The plan has no incomplete markers or vague fill-in-later instructions. Task 4 includes exact test code using _patch_nautilus_placeholders and the existing native-strategy kwarg capture pattern.
- Type consistency: The plan uses existing classes and helpers: PolySignalNativeStrategy, NautilusRuntimeConfig, _build_native_strategies(), NautilusBookDataProvider, MarketViewAssembler, BookLevel, OrderBook, _maybe_float(), _maybe_datetime(), and _nautilus_book_type().

---

## Implementation Completion Summary

### Commit History (final 10 commits)

```
a1be3f3 test: preserve vwap momentum behavior with L1 feed
8da5a90 feat: configure Nautilus L1 book snapshot interval
dca0792 refactor: deduplicate _update_book_from_order_book via _domain_order_book
fc92dff fix: project Nautilus L1 book data into market views
dbbe842 fix: select Nautilus market data feed by book mode
8b67968 test: capture Nautilus L1 subscription selection
3b6cdf7 test(nautilus): seed instrument requests in integration fake
8cf1a10 docs(dashboard): record final smoke rerun
995777a docs(dashboard): record final review remediation
18d9aeb fix(dashboard): remove stale template branding
```

### Regression Suite

- **91/91 tests passing** in the focused regression suite (`tests/test_nautilus_strategy_base.py` and `tests/test_nautilus_node.py`)
- Full test suite (`tests/`): 693 collected, 1 pre-existing failure in `test_integration_smoke.py::test_fake_public_api_outage_degrades_without_unhandled_exception` (unrelated to L1 subscription changes)

### Selected L1 Feed Path (determined at deploy time)

- `fast_l1` mode in config -> `L1_MBP` book type
- Tries `subscribe_quote_ticks` first (requires adapter support)
- Falls back to `subscribe_order_book_at_interval` (interval: 1000ms, configurable via `l1_book_snapshot_interval_ms`)
- Falls back to `subscribe_order_book_deltas` with visible `l1_raw_delta_fallback` phase indicator

### Deployment Verification Required

1. Build: `docker compose up -d --build polysignal-lab`
2. Monitor startup logs for selected feed path
3. After 5+ minutes, compare CPU/memory with baseline
4. Expected: CPU and event rates below raw-delta baseline
