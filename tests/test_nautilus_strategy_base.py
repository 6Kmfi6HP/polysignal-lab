"""
Input: __future__, __future__.annotations, sys, collections.abc, collections.abc.Callable, collections.abc.Mapping, dataclasses, dataclasses.replace, datetime, datetime.UTC
Output: test_native_strategy_on_save_load_delegates_to_core_via_encode_decode, test_native_strategy_on_save_excludes_runtime_trading_state, test_native_strategy_on_load_does_not_restore_runtime_trading_state, test_runtime_strategy_fok_depth_counts_asks_through_max_entry, test_native_strategy_gate_rejection_does_not_drive_data_plane_readiness, test_native_strategy_records_rejection_when_order_mapping_fails, test_native_strategy_blocks_duplicate_in_flight_signal_submission, test_static_native_strategy_uses_nautilus_subscribe_data_for_custom_data, test_static_native_strategy_does_not_bypass_custom_data_lifecycle, test_native_strategy_generates_signal_from_on_data_callback
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

import sys

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib import import_module
from types import SimpleNamespace
from typing import Any, Protocol, cast

from typing_extensions import override

from factories import sample_market_view
from nautilus_polymarket_fixtures import polymarket_binary_instrument
from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketView,
    OrderIntentSpec,
)
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalPriceToBeatData

from polysignal_lab.nautilus_runtime.state import decode_state, state_key


class _FloatLike:
    def __init__(self, value: float) -> None:
        self.value = value

    def __float__(self) -> float:
        return self.value

    def __str__(self) -> str:
        return str(self.value)


class FakeAssembler:
    def __init__(self, view: object | None):
        self.view = cast(MarketView | None, view)

    def build(
        self,
        condition_id: str,
        *,
        created_at: datetime | None = None,
    ) -> MarketView | None:
        _ = condition_id, created_at
        return self.view


class FakeCore:
    def __init__(self, decisions: list[AlphaDecision]):
        self.decisions = decisions

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        _ = view
        return self.decisions


class _NoopClock:
    def set_timer(self, name: object, interval: object, *, callback: object) -> None:
        _ = name, interval, callback

    def timestamp_ns(self) -> int:
        return 0


class _NativeSubscriptionMethods:
    def subscribe_data(
        self,
        data_type: object,
        client_id: object | None = None,
    ) -> None:
        _ = data_type, client_id

    def unsubscribe_data(
        self,
        data_type: object,
        client_id: object | None = None,
    ) -> None:
        _ = data_type, client_id

    def subscribe_quotes(self, instrument_id: object, *args: object, **kwargs: object) -> None:
        _ = instrument_id, args, kwargs

    def subscribe_trades(self, instrument_id: object, *args: object, **kwargs: object) -> None:
        _ = instrument_id, args, kwargs

    def subscribe_book_deltas(
        self, instrument_id: object, *args: object, **kwargs: object
    ) -> None:
        _ = instrument_id, args, kwargs

    def unsubscribe_quotes(self, instrument_id: object, *args: object, **kwargs: object) -> None:
        _ = instrument_id, args, kwargs

    def unsubscribe_trades(self, instrument_id: object, *args: object, **kwargs: object) -> None:
        _ = instrument_id, args, kwargs

    def unsubscribe_book_deltas(
        self, instrument_id: object, *args: object, **kwargs: object
    ) -> None:
        _ = instrument_id, args, kwargs


class StatefulFakeCore(FakeCore):
    def __init__(
        self,
        decisions: list[AlphaDecision],
        *,
        state: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(decisions)
        self.state: dict[str, object] = dict(
            state or {"alpha_marker": 42, "trades": {"condition-btc-5m": []}}
        )
        self.loaded_payload: dict[str, object] | None = None
        self.save_calls = 0

    def save_state(self) -> Mapping[str, object]:
        self.save_calls += 1
        return dict(self.state)

    def load_state(self, payload: Mapping[str, object]) -> None:
        self.loaded_payload = dict(payload)
        self.state = dict(payload)


def _assembler(view: object | None) -> MarketViewAssembler:
    return cast(MarketViewAssembler, cast(object, FakeAssembler(view)))


class _TestInstrument:
    def __init__(self, token_id: str) -> None:
        self.id = f"{token_id}.POLYMARKET"

    def make_price(self, value: float) -> float:
        return value

    def make_qty(self, value: float) -> float:
        return value


def _test_instrument_id(_condition_id: str, token_id: str) -> str:
    return f"{token_id}.POLYMARKET"


def _test_market_catalog() -> MarketCatalog:
    return MarketCatalog(instrument_id_resolver=_test_instrument_id)


def _native_projections(
    registry: MarketCatalog | None = None,
) -> dict[str, Any]:
    return {
        "registry": registry or _test_market_catalog(),
    }


def _minimal_native_strategy(
    *,
    core: object,
    strategy_name: str = "ptb_diff",
) -> object:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    return PolySignalNativeStrategy(
        core=core,
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name=strategy_name,
        **_native_projections(),
    )


def _load_static_native_strategy(
    monkeypatch,
    strategy_base: type[object],
    strategy_config: object,
) -> type[Any]:
    runtime_module_name = "polysignal_lab.nautilus_runtime.native_strategy"
    missing = object()
    previous_runtime_module = sys.modules.get(runtime_module_name, missing)
    _ = sys.modules.pop(runtime_module_name, None)

    # PolySignalNativeStrategy subclasses pyo3 Strategy; swap that base for unit doubles.
    import nautilus_trader.core.nautilus_pyo3 as real_pyo3

    class _FakePyo3StrategyConfig:
        def __init__(self, strategy_id: object = None, order_id_tag: str | None = None, **_: object) -> None:
            self.strategy_id = strategy_id
            self.order_id_tag = order_id_tag or strategy_config

    class _FakeStrategyId:
        def __init__(self, value: str) -> None:
            self.value = value

        def __str__(self) -> str:
            return self.value

    monkeypatch.setattr(real_pyo3, "Strategy", strategy_base)
    monkeypatch.setattr(real_pyo3, "StrategyConfig", _FakePyo3StrategyConfig)
    monkeypatch.setattr(real_pyo3, "StrategyId", _FakeStrategyId)

    try:
        module = import_module(runtime_module_name)
        return cast(type[Any], module.PolySignalNativeStrategy)
    finally:
        if previous_runtime_module is missing:
            _ = sys.modules.pop(runtime_module_name, None)
        else:
            sys.modules[runtime_module_name] = previous_runtime_module



class _BookViewLike(Protocol):
    best_ask: float | None
    ask_levels: tuple[tuple[float, float], ...]


class _DataHandler(Protocol):
    def on_data(self, data: object) -> object: ...


class _CustomDataStrategy(Protocol):
    custom_subscriptions: list[object]

    def on_data(self, data: object) -> object: ...


class _ObservedOrder(Protocol):
    client_order_id: str | None
    metrics: Mapping[str, object]


class _ObservedFill(Protocol):
    market_id: str
    side: Side
    shares: float
    trade_id: str | None
    last_px: float


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
        order_intent=OrderIntentSpec(
            intent=OrderIntent.PASSIVE_GTD, expiry_seconds=45, pair_id="pair-1"
        ),
        hedge_leg=False,
    )


def test_native_strategy_on_save_load_delegates_to_core_via_encode_decode() -> None:
    core = StatefulFakeCore([])
    strategy = _minimal_native_strategy(core=core, strategy_name="ptb_diff")

    state = strategy.on_save()
    restored_core = StatefulFakeCore([])
    restored = _minimal_native_strategy(core=restored_core, strategy_name="ptb_diff")
    restored.on_load(state)

    assert core.save_calls == 1
    assert set(state) == {state_key("ptb_diff")}
    assert decode_state("ptb_diff", state) == {
        "alpha": {
            "alpha_marker": 42,
            "trades": {"condition-btc-5m": []},
        },
    }
    assert restored_core.loaded_payload == {
        "alpha_marker": 42,
        "trades": {"condition-btc-5m": []},
    }
    assert restored_core.state == restored_core.loaded_payload


def test_native_strategy_on_save_excludes_runtime_trading_state() -> None:
    from polysignal_lab.nautilus_runtime.decision_policy import RejectedDecision

    core = StatefulFakeCore([])
    strategy = _minimal_native_strategy(core=core, strategy_name="vwap_momentum")
    assert not hasattr(strategy, "_metrics_tracker")
    strategy.rejected_decisions.append(
        RejectedDecision(reason_code="TEST", detail={}, decision=None)
    )

    payload = decode_state("vwap_momentum", strategy.on_save())

    assert payload["alpha"] == dict(core.save_state())
    assert "workflow" not in payload
    assert "submitted_orders" not in payload
    assert "approved_signal_metrics" not in payload
    assert "rejected_decisions" not in payload
    assert "fill_state" not in payload
    assert "accepted_state" not in payload


def test_native_strategy_on_load_does_not_restore_runtime_trading_state() -> None:
    from polysignal_lab.nautilus_runtime.decision_policy import RejectedDecision

    core = StatefulFakeCore([])
    strategy = _minimal_native_strategy(core=core, strategy_name="ptb_diff")
    strategy.rejected_decisions.append(
        RejectedDecision(reason_code="TEST", detail={}, decision=None)
    )

    state = strategy.on_save()

    restored_core = StatefulFakeCore([])
    restored = _minimal_native_strategy(core=restored_core, strategy_name="ptb_diff")
    restored.on_load(state)

    assert restored_core.loaded_payload == {
        "alpha_marker": 42,
        "trades": {"condition-btc-5m": []},
    }
    assert not hasattr(restored, "_metrics_tracker")
    assert not hasattr(restored, "_exit_inflight")
    assert not hasattr(restored, "_exit_thresholds_for_instruments")
    assert len(restored.rejected_decisions) == 0


# ── Batch evaluation tests (nautilus runtime) ─────────────────────────────────


from polysignal_lab.nautilus_runtime.decision_policy import (  # noqa: E402
    ApprovedDecision,
    BatchArbitrationResult,
    DecisionPolicy,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.native_strategy import (  # noqa: E402
    PolySignalNativeStrategy,
)


class _MockBook:
    best_ask: float | None = 0.82
    ask_levels: tuple[tuple[float, float], ...] = ((0.82, 50.0),)
    freshness_ms: int | None = 10


class _MockView:
    condition_id: str = "condition-btc-5m"

    def book_for(self, side: Side) -> _BookViewLike:
        _ = side
        return _MockBook()

    @property
    def created_at(self) -> datetime:
        return datetime.now(UTC)


def _real_market_view(
    *,
    up_ask: float = 0.82,
    down_ask: float = 0.18,
    up_ask_levels: tuple[tuple[float, float], ...] | None = None,
    down_ask_levels: tuple[tuple[float, float], ...] | None = None,
    created_at: datetime | None = None,
    start_ts: datetime | None = None,
    end_ts: datetime | None = None,
    seconds_to_close: int = 60,
) -> MarketView:
    view = sample_market_view(
        up_ask=up_ask,
        down_ask=down_ask,
        book_freshness_ms=10,
        spot_freshness_ms=10,
        up_ask_levels=up_ask_levels,
        down_ask_levels=down_ask_levels,
        created_at=created_at,
        start_ts=start_ts,
        end_ts=end_ts,
        seconds_to_close=seconds_to_close,
    )
    return replace(
        view,
        view_id="view-1",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        up=replace(view.up, token_id="up-token"),
        down=replace(view.down, token_id="down-token"),
    )


class RuntimeFakePolicy(DecisionPolicy):
    def evaluate(self, decision: AlphaDecision, view: MarketView) -> ApprovedDecision:
        from polysignal_lab.nautilus_runtime.decision_policy import candidate_from_decision

        publish = candidate_from_decision(decision, view)
        return ApprovedDecision(decision=decision, publish=publish)

    def batch_arbitrate(
        self, decisions: list[tuple[AlphaDecision, MarketView]]
    ) -> BatchArbitrationResult:
        return BatchArbitrationResult(decision for decision, _ in decisions)


def _attach_decision_policy(
    strategy: PolySignalNativeStrategy,
    policy: DecisionPolicy | None = None,
) -> DecisionPolicy:
    strategy.policy = policy or RuntimeFakePolicy()
    return strategy.policy




def test_runtime_strategy_fok_depth_counts_asks_through_max_entry() -> None:
    decision = AlphaDecision(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.50,
        max_entry_price=0.52,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=("TEST",),
        metrics={},
        order_intent=OrderIntentSpec(intent=OrderIntent.TAKER_FOK, pair_id="pair-1"),
        hedge_leg=False,
    )

    from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.submitted = []

        def submit_order(self, order):
            self.submitted.append(order)

    class SpecCapturingStrategy(FakeNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.captured_specs = []

        def _submit_approved(self, approved, *, view):
            book = view.book_for(approved.decision.side)
            spec = order_spec_from_decision(
                approved.decision,
                fixed_stake_usdc=self.fixed_stake_usdc,
                best_ask=book.best_ask,
                view_id=view.view_id,
            )
            self.captured_specs.append(spec)
            return SimpleNamespace(client_order_id="captured")

    readiness: list[tuple[str, bool]] = []
    strategy = SpecCapturingStrategy(
        core=FakeCore([decision]),
        assembler=_assembler(
            _real_market_view(
                up_ask=0.50,
                up_ask_levels=((0.50, 10.0), (0.52, 10.0), (0.53, 100.0)),
            )
        ),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: _TestInstrument(token_id),
        readiness_callback=lambda condition_id, ready, _detail: readiness.append(
            (condition_id, ready)
        ),
        **_native_projections(),
    )
    _policy = _attach_decision_policy(strategy)

    strategy.evaluate_condition("condition-btc-5m")

    assert readiness == [("condition-btc-5m", True)]
    assert len(strategy.captured_specs) == 1
    assert strategy.captured_specs[0].intent == OrderIntent.TAKER_FOK
    assert strategy.captured_specs[0].quantity == 20.0
    assert len(strategy.rejected_decisions) == 0


def test_native_strategy_gate_rejection_does_not_drive_data_plane_readiness() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class StaleOrderBookPolicy(RuntimeFakePolicy):
        def evaluate(
            self,
            decision: AlphaDecision,
            view: MarketView,
        ) -> RejectedDecision:
            approved = super().evaluate(decision, view)
            return RejectedDecision(
                reason_code="STALE_ORDERBOOK",
                detail={
                    "lag_ms": 400_000,
                    "source": "orderbook",
                    "threshold_ms": 300_000,
                },
                decision=approved.decision,
                publish=approved.publish,
            )

    readiness: list[tuple[str, bool]] = []

    up_decision = _decision()
    down_decision = replace(
        up_decision,
        token_id="down-token",
        side=Side.DOWN,
    )
    core = FakeCore([up_decision, down_decision])
    view = _real_market_view()
    policy = StaleOrderBookPolicy()
    strategy = PolySignalNativeStrategy(
        core=core,
        assembler=_assembler(view),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        readiness_callback=lambda condition_id, ready, _detail: readiness.append(
            (condition_id, ready)
        ),
        **_native_projections(),
    )
    _policy = _attach_decision_policy(strategy, policy)

    strategy.evaluate_condition("condition-btc-5m")
    core.decisions = []
    strategy.evaluate_condition("condition-btc-5m")

    assert readiness == [
        ("condition-btc-5m", True),
        ("condition-btc-5m", True),
    ]


def test_native_strategy_records_rejection_when_order_mapping_fails() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.submitted = []

        def submit_order(self, order):
            self.submitted.append(order)

    decision = AlphaDecision(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.50,
        max_entry_price=0.52,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=("TEST",),
        metrics={},
        order_intent=OrderIntentSpec(intent=OrderIntent.TAKER_FOK, pair_id="pair-1"),
        hedge_leg=False,
    )

    strategy = FakeNativeStrategy(
        core=FakeCore([decision]),
        assembler=_assembler(
            _real_market_view(
                up_ask=0.55,
                up_ask_levels=((0.55, 100.0),),
            )
        ),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: _TestInstrument(token_id),
        **_native_projections(),
    )
    _policy = _attach_decision_policy(strategy)

    strategy.evaluate_condition("condition-btc-5m")

    assert strategy.submitted == []
    assert len(strategy.rejected_decisions) != 0


def test_native_strategy_blocks_duplicate_in_flight_signal_submission() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class ReenteringCore(FakeCore):
        def on_order_filled(self, event):
            _ = event
            return [_decision()]

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.submitted: list[str] = []
            self.active_dedupe_keys: set[str] = set()

        def _is_signal_submitted(self, dedupe_key: str) -> bool:
            return dedupe_key in self.active_dedupe_keys

        def _submit_approved(self, approved, *, view):
            view_id = getattr(view, "view_id", "") or ""
            dedupe_key = approved.decision.dedupe_key()
            self.submitted.append(dedupe_key)
            self.active_dedupe_keys.add(dedupe_key)
            return SimpleNamespace(
                id=f"order-{len(self.submitted)}",
                tags={"signal_id": approved.decision.signal_id(view_id)},
            )

        def on_order_filled(self, event: object) -> None:
            super().on_order_filled(event)
            self.active_dedupe_keys.clear()

    strategy = FakeNativeStrategy(
        core=ReenteringCore([_decision()]),
        assembler=_assembler(_real_market_view()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        fixed_stake_usdc=10.0,
        **_native_projections(),
    )
    _policy = _attach_decision_policy(strategy)

    strategy.evaluate_condition("condition-btc-5m")
    strategy.evaluate_condition("condition-btc-5m")

    assert strategy.submitted == ["BTC:5m:btc-5m:UP:ptb_diff:entry"]
    assert [rejected.reason_code for rejected in strategy.rejected_decisions] == [
        "DUPLICATE_IN_FLIGHT_SIGNAL"
    ]

    strategy.on_order_filled(
        SimpleNamespace(
            order_id="order-1",
            fill_price=0.5,
            shares=1.0,
            tags={},
            ts_event=datetime.now(UTC),
        )
    )
    strategy.evaluate_condition("condition-btc-5m")
    assert strategy.submitted == [
        "BTC:5m:btc-5m:UP:ptb_diff:entry",
        "BTC:5m:btc-5m:UP:ptb_diff:entry",
    ]

def test_static_native_strategy_uses_nautilus_subscribe_data_for_custom_data(
    monkeypatch,
) -> None:
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )

    class FakeBase:
        def __init__(self, *, config: object) -> None:
            self.config = config
            self.custom_subscriptions = []
            self.clock = _NoopClock()

        def subscribe_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def subscribe_quotes(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def subscribe_trades(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def unsubscribe_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def unsubscribe_quotes(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def unsubscribe_trades(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def subscribe_data(
            self, data_type: object, *args: object, **kwargs: object
        ) -> None:
            _ = args
            self.custom_subscriptions.append((data_type, kwargs.get("client_id")))

    strategy_type = _load_static_native_strategy(monkeypatch, FakeBase, "cfg")

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )

    strategy = strategy_type(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
    )

    strategy.on_start()

    assert cast(list[object], getattr(strategy, "custom_subscriptions")) != []


def test_static_native_strategy_does_not_bypass_custom_data_lifecycle(monkeypatch) -> None:
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
        PolySignalPriceToBeatData,
    )
    from nautilus_trader.core.nautilus_pyo3 import PolymarketRtdsCryptoPrice

    class FakeMsgBus:
        def __init__(self) -> None:
            self.calls: list[tuple[object, Callable[[object], object]]] = []

        def subscribe(
            self, *, topic: object, handler: Callable[[object], object]
        ) -> None:
            self.calls.append((topic, handler))

    class FakeBase:
        def __init__(self, *, config: object) -> None:
            self.config = config
            self.custom_subscriptions = []
            self._msgbus = FakeMsgBus()
            self.clock = _NoopClock()

        def subscribe_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def subscribe_quotes(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def subscribe_trades(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def unsubscribe_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def unsubscribe_quotes(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def unsubscribe_trades(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def subscribe_data(
            self, data_type: object, *args: object, **kwargs: object
        ) -> None:
            _ = args
            self.custom_subscriptions.append((data_type, kwargs.get("client_id")))

    strategy_type = _load_static_native_strategy(monkeypatch, FakeBase, "cfg")

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )

    strategy = strategy_type(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
    )

    strategy.on_start()

    assert cast(FakeMsgBus, getattr(strategy, "_msgbus")).calls == []
    custom_subscriptions = cast(list[tuple[object, object | None]], getattr(strategy, "custom_subscriptions"))
    assert {
        getattr(data_type, "type_name", data_type): str(client_id)
        for data_type, client_id in custom_subscriptions
    } == {
        PolymarketRtdsCryptoPrice.__name__: "POLYMARKET-5M",
        PolySignalPriceToBeatData.__name__: "None",
        PolySignalMarketMetaData.__name__: "None",
        PolySignalMarketUniverseData.__name__: "None",
    }

    strategy.on_data(
        PolymarketRtdsCryptoPrice("BTCUSD", "100000.0", 0, 0, 1, 1)
    )

    spot = strategy.custom_data.spot_for("BTC")
    assert spot is not None
    assert spot.price == 100000.0




def test_native_strategy_generates_signal_from_on_data_callback() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        @property
        def order_factory(self) -> FakeOrderFactoryForNative:
            return FakeOrderFactoryForNative()

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.submitted = []
            self.subscriptions = []

        def submit_order(self, order: object) -> None:
            self.submitted.append(order)

        def subscribe_data(
            self,
            data_type: object,
            client_id: object | None = None,
        ) -> None:
            self.subscriptions.append((data_type, client_id))

    class FakeOrderFactoryForNative:
        def limit(self, **kwargs: object) -> dict[str, object]:
            return dict(kwargs)

    class UnknownDataEvent:
        condition_id = "condition-btc-5m"

    progress: list[str] = []
    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(_real_market_view()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: _TestInstrument(token_id),
        progress_callback=lambda phase: progress.append(phase),
        **_native_projections(),
    )
    _policy = _attach_decision_policy(strategy)

    # Generic assembler fallback is removed; unknown CustomData is dropped.
    _ = cast(_DataHandler, cast(object, strategy)).on_data(UnknownDataEvent())
    assert progress == ["dropped_frame"]
    assert strategy.submitted == []

    strategy.evaluate_condition("condition-btc-5m")

    assert len(strategy.submitted) == 1
    assert str(strategy.submitted[0]["instrument_id"]) == "up-token.POLYMARKET"
    assert (
        getattr(
            strategy.submitted[0]["time_in_force"],
            "name",
            strategy.submitted[0]["time_in_force"],
        )
        == "GTD"
    )


def test_native_strategy_owns_decision_policy() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=_test_market_catalog(),
    )

    assert isinstance(strategy.policy, DecisionPolicy)


def test_native_strategy_constructor_requires_injected_projections() -> None:
    import pytest

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(
        RuntimeError,
        match="requires injected registry and assembler projections",
    ):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=_assembler(None),
            condition_ids=(),
            strategy_name="ptb_diff",
        )


def test_native_strategy_constructor_requires_injected_assembler() -> None:
    import pytest

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(
        RuntimeError,
        match="requires injected registry and assembler projections",
    ):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=cast(Any, None),
            condition_ids=(),
            strategy_name="ptb_diff",
            registry=_test_market_catalog(),
        )


def test_native_strategy_on_start_subscribes_all_custom_data_with_injected_projections() -> (
    None
):
    from polysignal_lab.nautilus_runtime.custom_data_types import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
        PolySignalPriceToBeatData,
    )
    from nautilus_trader.core.nautilus_pyo3 import PolymarketRtdsCryptoPrice
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.custom_subscriptions: list[object] = []

        def subscribe_data(
            self,
            data_type: object,
            client_id: object | None = None,
        ) -> None:
            _ = client_id
            self.custom_subscriptions.append(data_type)

        def _start_evaluation_heartbeat(self) -> None:
            return None

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=_test_market_catalog(),
    )

    strategy.on_start()

    type_names = [
        getattr(item, "type_name", getattr(item, "__name__", item))
        for item in strategy.custom_subscriptions
    ]
    assert PolySignalMarketMetaData.__name__ in type_names
    assert PolySignalMarketUniverseData.__name__ in type_names
    assert PolymarketRtdsCryptoPrice.__name__ in type_names
    assert PolySignalPriceToBeatData.__name__ in type_names
    rtds_subs = [
        item
        for item in strategy.custom_subscriptions
        if getattr(item, "type_name", None) == PolymarketRtdsCryptoPrice.__name__
    ]
    assert rtds_subs
    assert all(
        isinstance(getattr(item, "metadata", None), dict)
        and "symbol" in getattr(item, "metadata")
        for item in rtds_subs
    )


def test_native_strategy_on_start_sets_evaluation_heartbeat() -> None:
    from datetime import UTC, datetime, timedelta

    from polysignal_lab.nautilus_runtime.native_strategy import (
        EVALUATION_HEARTBEAT_TIMER_NAME,
        PolySignalNativeStrategy,
    )

    class FakeClock:
        def __init__(self) -> None:
            self.timer = None
            self.canceled: list[str] = []
            self.now_ns = 1_782_144_000_000_000_000

        def timestamp_ns(self) -> int:
            return self.now_ns

        def set_timer(self, name, interval, *, callback):
            self.timer = (name, interval, callback)

        def cancel_timer(self, name):
            self.canceled.append(name)

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        @property
        def clock(self) -> FakeClock:
            return self.fake_clock

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.custom_subscriptions: list[object] = []
            self.evaluated: list[str] = []
            self.fake_clock = FakeClock()

        def subscribe_data(
            self,
            data_type: object,
            client_id: object | None = None,
        ) -> None:
            self.custom_subscriptions.append((data_type, client_id))

        def evaluate_condition(
            self,
            condition_id: str,
            *,
            trading_state: object | None = None,
        ) -> None:
            _ = trading_state
            self.evaluated.append(condition_id)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m", "condition-btc-retired"),
        strategy_name="ptb_diff",
        registry=_test_market_catalog(),
    )
    strategy._active_condition_ids = {"condition-btc-5m"}

    strategy.on_start()

    assert strategy.clock.timer is not None
    name, interval, callback = strategy.clock.timer
    assert name == EVALUATION_HEARTBEAT_TIMER_NAME
    assert interval == timedelta(seconds=10)

    callback(object())

    assert strategy.evaluated == ["condition-btc-5m"]
    strategy._last_market_data_evaluation_at["condition-btc-5m"] = datetime.fromtimestamp(
        strategy.clock.timestamp_ns() / 1_000_000_000,
        UTC,
    )
    # Within the market-data debounce window the evaluation is a no-op.
    strategy._evaluate_market_data_condition(
        "condition-btc-5m",
        event=SimpleNamespace(ts_event=1),
    )
    assert strategy.evaluated == ["condition-btc-5m"]
    strategy.clock.now_ns += 600_000_000  # past the debounce window
    strategy._evaluate_market_data_condition(
        "condition-btc-5m",
        event=SimpleNamespace(ts_event=1),
    )
    assert strategy._last_market_data_evaluation_at["condition-btc-5m"] == datetime.fromtimestamp(
        strategy.clock.timestamp_ns() / 1_000_000_000,
        UTC,
    )
    callback(object())

    assert strategy.evaluated == ["condition-btc-5m", "condition-btc-5m"]
    strategy.clock.now_ns += 11_000_000_000
    callback(object())

    assert strategy.evaluated == [
        "condition-btc-5m",
        "condition-btc-5m",
        "condition-btc-5m",
    ]

    strategy.on_stop()

    assert strategy.clock.canceled == [EVALUATION_HEARTBEAT_TIMER_NAME]

    strategy.on_start()

    strategy.on_stop()
    assert strategy.clock.canceled == [
        EVALUATION_HEARTBEAT_TIMER_NAME,
        EVALUATION_HEARTBEAT_TIMER_NAME,
    ]


def test_native_strategy_stop_unsubscribes_market_and_custom_data() -> None:
    from polysignal_lab.nautilus_runtime.custom_data_types import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
        PolySignalPriceToBeatData,
    )
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        market_unsubscriptions: list[tuple[str, str]]
        custom_unsubscriptions: list[tuple[str, str]]

        @override
        def unsubscribe_quotes(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.market_unsubscriptions.append(("quotes", str(instrument_id)))

        @override
        def unsubscribe_trades(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.market_unsubscriptions.append(("trades", str(instrument_id)))

        @override
        def unsubscribe_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.market_unsubscriptions.append(("book", str(instrument_id)))

        @override
        def unsubscribe_data(
            self,
            data_type: object,
            client_id: object | None = None,
        ) -> None:
            _ = client_id
            self.custom_unsubscriptions.append(
                (str(getattr(data_type, "type_name", data_type)), str(client_id))
            )

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    strategy = FakeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
    )
    strategy.market_unsubscriptions = []
    strategy.custom_unsubscriptions = []
    strategy._subscription_state.subscribed_instrument_ids.update(
        {"up-token.POLYMARKET", "down-token.POLYMARKET"}
    )
    strategy._subscriptions_started = True

    strategy.on_stop()

    assert strategy.market_unsubscriptions == [
        ("quotes", "up-token.POLYMARKET"),
        ("trades", "up-token.POLYMARKET"),
        ("book", "up-token.POLYMARKET"),
        ("quotes", "down-token.POLYMARKET"),
        ("trades", "down-token.POLYMARKET"),
        ("book", "down-token.POLYMARKET"),
    ]
    names = {name for name, _ in strategy.custom_unsubscriptions}
    assert names == {
        "PolymarketRtdsCryptoPrice",
        PolySignalPriceToBeatData.__name__,
        PolySignalMarketMetaData.__name__,
        PolySignalMarketUniverseData.__name__,
    }
    assert strategy._subscription_state.subscribed_instrument_ids == set()


def test_native_strategy_stop_before_heartbeat_creation_is_safe() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeClock:
        def __init__(self) -> None:
            self.canceled: list[str] = []

        def cancel_timer(self, name: object) -> None:
            self.canceled.append(str(name))

    class FakeNativeStrategy(PolySignalNativeStrategy):
        fake_clock: FakeClock

        @property
        def clock(self) -> FakeClock:
            return self.fake_clock

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=_test_market_catalog(),
    )
    strategy.fake_clock = FakeClock()

    strategy.on_stop()

    assert strategy.clock.canceled == []


def test_native_strategy_backtest_does_not_schedule_unbounded_evaluation_heartbeat() -> None:
    from polysignal_lab.config import Settings
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.runtime_configs import PolySignalStrategyConfig

    class FakeClock:
        def __init__(self) -> None:
            self.timer: tuple[object, object, object] | None = None
            self.canceled: list[str] = []

        def set_timer(self, name: object, interval: object, *, callback: object) -> None:
            self.timer = (name, interval, callback)

        def cancel_timer(self, name: object) -> None:
            self.canceled.append(str(name))

    class FakeBacktestStrategy(PolySignalNativeStrategy):
        fake_clock: FakeClock

        @property
        def clock(self) -> FakeClock:
            return self.fake_clock

    settings = Settings()
    settings.runtime.nautilus.execution_mode = "backtest"
    settings.strategies.set_explicit_strategy_names(("one_cent_buy",))
    strategy = FakeBacktestStrategy(
        PolySignalStrategyConfig.build(settings, (), (), strategy_name="one_cent_buy")
    )
    strategy.fake_clock = FakeClock()

    strategy._start_evaluation_heartbeat()

    assert strategy.clock.timer is None
    strategy.on_stop()
    assert strategy.clock.canceled == []


def test_native_strategy_reports_progress_on_internal_evaluation_heartbeat() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    progress_events: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(_MockView()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        **_native_projections(),
        progress_callback=progress_events.append,
    )

    strategy._on_evaluation_heartbeat(object())

    assert progress_events == ["evaluation_heartbeat"]


def test_native_strategy_reports_progress_on_start_without_market_data() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        pass

    progress_events: list[str] = []
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        **_native_projections(),
        progress_callback=progress_events.append,
    )

    strategy.on_start()

    assert "start" in progress_events


def test_native_strategy_drops_unknown_project_owned_data_with_metric() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    observed: list[tuple[str, object]] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        **_native_projections(),
    )
    strategy.progress_callback = lambda phase: observed.append((phase, None))

    strategy.on_data(object())

    assert ("dropped_frame", None) in observed


def test_malformed_project_owned_data_does_not_poison_later_valid_market_metadata() -> None:
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketMetaData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        **_native_projections(),
    )

    strategy.on_data(object())
    strategy.on_data(
        PolySignalMarketMetaData(
            market_id="market-1",
            market_slug="btc-updown-5m-market-1",
            condition_id="condition-1",
            asset="BTC",
            timeframe="5m",
            start_ts_ns=1,
            end_ts_ns=2,
            up_token_id="up-1",
            down_token_id="down-1",
            ts_event=11,
            ts_init=12,
        )
    )

    assert strategy.registry.by_condition("condition-1") is not None


def test_native_strategy_unknown_quote_tick_instrument_is_dropped_with_metric() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    phases: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        **_native_projections(),
    )
    strategy.progress_callback = phases.append

    strategy.on_quote(
        SimpleNamespace(
            instrument_id="unknown.POLYMARKET",
            bid_price=0.1,
            ask_price=0.2,
        )
    )

    assert "dropped_frame" in phases


def test_native_strategy_partial_market_data_mappings_are_dropped_without_evaluation() -> None:
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class MissingInstrumentCatalog(MarketCatalog):
        def instrument_id_for_token(self, token_id: str) -> str | None:
            _ = token_id
            return None

    cases: tuple[tuple[str, Callable[[PolySignalNativeStrategy, object], None], object], ...] = (
        (
            "quote_tick",
            lambda strategy, data: strategy.on_quote(data),
            SimpleNamespace(
                instrument_id="up-token.POLYMARKET",
                bid_price=0.1,
                ask_price=0.2,
            ),
        ),
        (
            "order_book",
            lambda strategy, data: strategy.on_book(data),
            SimpleNamespace(instrument_id="up-token.POLYMARKET", bids=[], asks=[]),
        ),
        (
            "order_book_deltas",
            lambda strategy, data: strategy.on_book_deltas(data),
            SimpleNamespace(instrument_id="up-token.POLYMARKET"),
        ),
        (
            "trade_tick",
            lambda strategy, data: strategy.on_trade(data),
            SimpleNamespace(
                instrument_id="up-token.POLYMARKET",
                price=0.2,
                size=3.0,
                aggressor_side="BUY",
            ),
        ),
    )

    for registry in (MissingInstrumentCatalog(),):
        registry.register(
            MarketPairMeta(
                market_id="btc-5m",
                market_slug="btc-updown-5m",
                condition_id="condition-btc-5m",
                asset="BTC",
                timeframe="5m",
                start_ts=None,
                end_ts=None,
                up=InstrumentTokenMeta("up-token", Side.UP),
                down=InstrumentTokenMeta("down-token", Side.DOWN),
            )
        )
        for name, handle, data in cases:
            phases: list[str] = []
            evaluated: list[str] = []
            strategy = PolySignalNativeStrategy(
                core=FakeCore([]),
                assembler=_assembler(None),
                condition_ids=("condition-btc-5m",),
                strategy_name="ptb_diff",
                **_native_projections(registry),
                progress_callback=phases.append,
            )
            def record_evaluation(condition_id: str) -> None:
                evaluated.append(condition_id)

            strategy.evaluate_condition = record_evaluation  # type: ignore[method-assign]

            handle(strategy, data)

            assert "dropped_frame" in phases, name
            assert "market_data_evaluation" not in phases, name
            assert evaluated == [], name


def test_native_strategy_unknown_market_data_instruments_are_dropped_with_metric() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    cases = (
        (
            "order_book",
            lambda strategy, data: strategy.on_book(data),
            SimpleNamespace(instrument_id="unknown-book.POLYMARKET", bids=[], asks=[]),
        ),
        (
            "order_book_deltas",
            lambda strategy, data: strategy.on_book_deltas(data),
            SimpleNamespace(instrument_id="unknown-deltas.POLYMARKET"),
        ),
        (
            "trade_tick",
            lambda strategy, data: strategy.on_trade(data),
            SimpleNamespace(
                instrument_id="unknown-trade.POLYMARKET",
                price=0.2,
                size=3.0,
                aggressor_side="BUY",
            ),
        ),
    )

    for name, handle, data in cases:
        phases: list[str] = []
        strategy = PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=_assembler(None),
            condition_ids=("condition-btc-5m",),
            strategy_name="ptb_diff",
            **_native_projections(),
            progress_callback=phases.append,
        )

        handle(strategy, data)

        assert "dropped_frame" in phases, name


def test_native_strategy_drops_unknown_project_owned_data_with_condition_id() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class UnknownProjectData:
        condition_id = "condition-btc-5m"

    observed: list[tuple[str, object]] = []
    calls: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        **_native_projections(),
    )
    strategy.progress_callback = lambda phase: observed.append((phase, None))
    strategy.evaluate_condition = lambda condition_id: calls.append(condition_id)  # type: ignore[method-assign]

    strategy.on_data(UnknownProjectData())

    assert ("dropped_frame", None) in observed
    assert calls == []


def test_native_strategy_readiness_gate_skips_missing_required_market_view_inputs() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    calls: list[object] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        **_native_projections(),
    )
    strategy.core.evaluate = lambda view: calls.append(view) or []  # type: ignore[method-assign]
    strategy.assembler.build = lambda _condition_id, *, created_at=None: SimpleNamespace(
        condition_id="condition-btc-5m",
        up_book=None,
        down_book=None,
        spot=None,
        price_to_beat=None,
    )
    phases: list[str] = []
    readiness: list[tuple[str, bool]] = []
    strategy.progress_callback = phases.append
    strategy.readiness_callback = lambda condition_id, ready, _detail: readiness.append(
        (condition_id, ready)
    )

    strategy.evaluate_condition("condition-btc-5m")

    assert calls == []
    assert "readiness_miss" in phases
    assert readiness == [("condition-btc-5m", False)]


def test_native_strategy_missing_view_fails_closed_without_resubscription() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    phases: list[str] = []
    readiness: list[tuple[str, bool]] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        progress_callback=phases.append,
        readiness_callback=lambda condition_id, ready, _detail: readiness.append(
            (condition_id, ready)
        ),
        **_native_projections(),
    )
    strategy.evaluate_condition("condition-btc-5m")

    assert "readiness_miss" in phases
    assert readiness == [("condition-btc-5m", False)]


def test_native_strategy_routes_decisions_through_owned_policy_decide() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    decision = _decision()
    submitted: list[object] = []
    decided: list[tuple[AlphaDecision, object]] = []

    class ActorPolicy(RuntimeFakePolicy):
        def decide(
            self,
            decision: AlphaDecision,
            view: MarketView,
        ) -> ApprovedDecision:
            decided.append((decision, view))
            return super().evaluate(decision, view)

    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        **_native_projections(),
    )
    strategy._submit_approved = lambda approved, *, view: submitted.append((approved, view))  # type: ignore[method-assign]
    policy = ActorPolicy()
    _policy = _attach_decision_policy(strategy, policy)
    view = _real_market_view()

    strategy._handle_decision(decision, view)

    assert len(decided) == 1
    assert decided[0][0] == decision
    assert cast(MarketView, decided[0][1]).condition_id == view.condition_id
    assert len(submitted) == 1
    assert cast(tuple[ApprovedDecision, MarketView], submitted[0])[1] == view


def test_cache_market_data_provider_uses_observed_receipt_time_for_freshness() -> None:
    from polysignal_lab.nautilus_runtime.cache_market_data import (
        NautilusCacheMarketDataProvider,
    )

    class Level:
        def __init__(self, price: float, size: float) -> None:
            self.price = price
            self.size = size

    class NautilusLikeOrderBook:
        ts_last = 1_800_000_000_000_000_000

        def bids(self) -> list[Level]:
            return [Level(0.49, 10.0)]

        def asks(self) -> list[Level]:
            return [Level(0.51, 20.0), Level(0.52, 10.0)]

    class Cache:
        def order_book(self, instrument_id: object) -> NautilusLikeOrderBook:
            assert str(instrument_id) == "up-token.POLYMARKET"
            return NautilusLikeOrderBook()

        def trade_ticks(self, instrument_id: object) -> list[object]:
            _ = instrument_id
            return []

    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    provider = NautilusCacheMarketDataProvider(cast(Any, Cache()), catalog=registry)

    received_at = datetime.fromtimestamp(1_800_000_119, UTC)
    provider.observe_book_received("up-token", received_at=received_at)
    now = datetime.fromtimestamp(1_800_000_120, UTC)
    book = provider.book_for_token("up-token", now=now)

    assert book is not None
    assert book.best_bid == 0.49
    assert book.best_ask == 0.51
    assert book.ask_levels == ((0.51, 20.0), (0.52, 10.0))
    assert book.received_at == received_at
    assert book.freshness_ms == 1_000


def test_cache_market_data_provider_treats_missing_trade_ticks_as_empty() -> None:
    from polysignal_lab.nautilus_runtime.cache_market_data import (
        NautilusCacheMarketDataProvider,
    )

    class Cache:
        def order_book(self, instrument_id: object) -> object | None:
            _ = instrument_id
            return None

        def trade_ticks(self, instrument_id: object) -> object:
            _ = instrument_id
            raise LookupError("no cached trades")

    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    provider = NautilusCacheMarketDataProvider(cast(Any, Cache()), catalog=registry)

    assert provider.trades_for_token("up-token") == ()


def test_cache_market_data_provider_treats_absent_trade_ticks_api_as_empty() -> None:
    from polysignal_lab.nautilus_runtime.cache_market_data import (
        NautilusCacheMarketDataProvider,
    )

    class Cache:
        def order_book(self, instrument_id: object) -> object | None:
            _ = instrument_id
            return None

    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    provider = NautilusCacheMarketDataProvider(cast(Any, Cache()), catalog=registry)

    assert provider.trades_for_token("up-token") == ()


def test_native_strategy_resolved_instrument_requires_cache_instrument_api() -> None:
    import pytest

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class Cache:
        pass

    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        **_native_projections(),
    )
    strategy._cache_override = Cache()

    with pytest.raises(ValueError, match="Cache.instrument"):
        strategy._resolved_instrument("up-token")


def test_native_strategy_does_not_submit_when_approved_decision_view_lacks_book() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class MissingBookView(MarketView):
        def book_for(self, side: Side):
            _ = side
            raise ValueError("Quote maps must not be empty")

    decision = _decision()
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        **_native_projections(),
    )
    _policy = _attach_decision_policy(strategy)
    base_view = _real_market_view()
    view = cast(Any, MissingBookView)(
        **{
            name: getattr(base_view, name)
            for name in base_view.__dataclass_fields__
        }
    )

    strategy._handle_decision(decision, view)

    assert [item.reason_code for item in strategy.rejected_decisions] == [
        "ORDER_MAPPING_FAILED"
    ]


def _real_market_view_with_empty_quote_depth() -> MarketView:
    from polysignal_lab.alpha.types import FreshnessView, SideBookView, SpotView

    now = datetime.now(UTC)
    return MarketView(
        view_id="view-empty-depth",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        asset="BTC",
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        created_at=now,
        seconds_to_close=60,
        up=SideBookView(
            token_id="up-token",
            best_bid=None,
            best_ask=None,
            spread=None,
            freshness_ms=10,
            ask_levels=(),
        ),
        down=SideBookView(
            token_id="down-token",
            best_bid=None,
            best_ask=None,
            spread=None,
            freshness_ms=10,
            ask_levels=(),
        ),
        spot=SpotView(
            asset="BTC",
            symbol="BTCUSD",
            price=100_000.0,
            source="test",
            freshness_ms=10,
        ),
        price_to_beat=None,
        up_trades=(),
        down_trades=(),
        metrics={},
        freshness=FreshnessView(up_book_ms=10, down_book_ms=10, spot_ms=10, max_ms=10),
    )


def test_native_strategy_readiness_gate_skips_real_market_view_with_empty_quote_depth() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    calls: list[object] = []
    phases: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(_real_market_view_with_empty_quote_depth()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        progress_callback=phases.append,
        **_native_projections(),
    )
    strategy.core.evaluate = lambda view: calls.append(view) or []  # type: ignore[method-assign]

    strategy.evaluate_condition("condition-btc-5m")

    assert calls == []
    assert "readiness_miss" in phases


def test_native_strategy_constructor_without_registry_fails_clearly() -> None:
    import pytest

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(
        RuntimeError,
        match="requires injected registry and assembler projections",
    ):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=_assembler(None),
            condition_ids=(),
            strategy_name="ptb_diff",
            instrument_id_resolver=lambda token_id: _TestInstrument(token_id),
        )


def test_native_strategy_bounds_rejected_decisions_to_prevent_memory_leak() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        **_native_projections(),
    )

    for _ in range(2000):
        strategy.rejected_decisions.append("rejected")
    # With unbounded list this will have 2000 entries, with bounded maxlen <= 1000
    assert len(strategy.rejected_decisions) <= 1000


def test_native_strategy_on_start_subscribes_built_in_market_data_by_instrument() -> (
    None
):
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []
            self.custom_subscriptions = []
            self.instrument_requests = []

        def request_instrument(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.instrument_requests.append(str(instrument_id))

        def subscribe_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(instrument_id)

        def subscribe_trades(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(instrument_id)

        def subscribe_data(self, data_type, *args, **kwargs):
            self.custom_subscriptions.append(data_type)

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
    )

    strategy.on_start()

    assert [str(value) for value in strategy.book_subscriptions] == [
        "up-token.POLYMARKET",
        "down-token.POLYMARKET",
    ]
    assert [str(value) for value in strategy.trade_subscriptions] == [
        "up-token.POLYMARKET",
        "down-token.POLYMARKET",
    ]
    assert cast(_CustomDataStrategy, cast(object, strategy)).custom_subscriptions != []


def test_native_strategy_book_deltas_subscription_is_engine_managed() -> None:
    """
    Issue #21: pyo3 LiveNode only maintains Cache order books for
    managed subscriptions; without managed=True every MarketView build
    returned None and readiness never cleared.
    """
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_delta_kwargs = []
            self.custom_subscriptions = []

        def subscribe_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_delta_kwargs.append(kwargs)

        def subscribe_data(self, data_type, *args, **kwargs):
            self.custom_subscriptions.append(data_type)

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
    )

    strategy.on_start()

    assert strategy.book_delta_kwargs, "expected book delta subscriptions"
    assert all(
        kwargs.get("managed") is True for kwargs in strategy.book_delta_kwargs
    )


def test_market_data_evaluation_is_debounced_per_condition() -> None:
    """
    Issue #21: full MarketView evaluation on every book delta saturated
    the event loop; bursts within the debounce window must evaluate once.
    """
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.strategy import market_data_events as mde

    clock = {"now": datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)}
    evaluated: list[str] = []
    strategy = SimpleNamespace(
        _framework_now=lambda: clock["now"],
        _note_runtime_progress=lambda phase: None,
        _last_market_data_evaluation_at={},
        evaluate_condition=lambda condition_id: evaluated.append(condition_id),
    )

    for _ in range(10):
        mde.evaluate_market_data_condition(strategy, "cond-1")
    assert evaluated == ["cond-1"]

    clock["now"] += timedelta(seconds=1)
    mde.evaluate_market_data_condition(strategy, "cond-1")
    assert evaluated == ["cond-1", "cond-1"]

    # A different condition is not blocked by cond-1's window.
    mde.evaluate_market_data_condition(strategy, "cond-2")
    assert evaluated == ["cond-1", "cond-1", "cond-2"]


def test_native_strategy_subscribes_market_data_per_strategy_instance() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.market_view_assembler import MarketViewAssembler

    from polysignal_lab.nautilus_runtime.cache_market_data import NautilusCacheMarketDataProvider
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData

    seen: list[tuple[str, str]] = []

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, *, label: str, **kwargs):
            super().__init__(**kwargs)
            self.label = label
            self.book_subscriptions: list[str] = []
            self.trade_subscriptions: list[str] = []
            self.instrument_requests: list[str] = []
            self.book_unsubscriptions: list[str] = []
            self.trade_unsubscriptions: list[str] = []

        def request_instrument(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.instrument_requests.append(str(instrument_id))

        def subscribe_book_deltas(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trades(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.trade_subscriptions.append(str(instrument_id))

        def unsubscribe_book_deltas(
            self,
            instrument_id: object,
            *args: object,
            **kwargs: object,
        ) -> None:
            _ = args, kwargs
            self.book_unsubscriptions.append(str(instrument_id))

        def unsubscribe_trades(
            self,
            instrument_id: object,
            *args: object,
            **kwargs: object,
        ) -> None:
            _ = args, kwargs
            self.trade_unsubscriptions.append(str(instrument_id))

        def evaluate_condition(self, condition_id: str) -> None:
            if condition_id not in self._active_condition_ids:
                return
            seen.append((self.label, condition_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    cache = SimpleNamespace(
        trade_ticks=lambda instrument_id: (
            [
                SimpleNamespace(
                    price=0.51,
                    size=7.0,
                    aggressor_side="BUYER",
                    ts_event=datetime.now(UTC),
                )
            ]
            if str(instrument_id) == "up-token.POLYMARKET"
            else []
        )
    )
    books = NautilusCacheMarketDataProvider(cache, catalog=registry)
    assembler = MarketViewAssembler(
        catalog=registry,
        books=books,
        custom_data=StrategyCustomDataState(),
    )
    first = FakeNativeStrategy(
        label="first",
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
    )
    second = FakeNativeStrategy(
        label="second",
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="late_consensus",
        registry=registry,
    )

    first.on_start()
    second.on_start()

    assert first.book_subscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert first.trade_subscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert second.book_subscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert second.trade_subscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]

    first.on_trade(
        SimpleNamespace(
            instrument_id="up-token.POLYMARKET",
            price=0.51,
            size=7.0,
            aggressor_side="BUYER",
            ts_event=datetime.now(UTC),
        )
    )

    assert [(trade.price, trade.size) for trade in books.trades_for_token("up-token")] == [
        (0.51, 7.0)
    ]
    assert seen == [("first", "condition-btc-5m")]

    exited = PolySignalMarketUniverseData(
        epoch=2,
        active_condition_ids=(),
        entered_condition_ids=(),
        exited_condition_ids=("condition-btc-5m",),
        condition_to_up_token={},
        condition_to_down_token={},
        condition_to_asset={},
        condition_to_timeframe={},
        ts_event=1,
        ts_init=1,
    )
    first.on_data(exited)

    assert first.book_unsubscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert first.trade_unsubscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert second.book_unsubscriptions == []
    assert second.trade_unsubscriptions == []

    seen.clear()
    first.on_trade(
        SimpleNamespace(
            instrument_id="up-token.POLYMARKET",
            price=0.52,
            size=3.0,
            aggressor_side="BUYER",
            ts_event=datetime.now(UTC),
        )
    )
    assert seen == []

    second.on_data(exited)

    assert second.book_unsubscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert second.trade_unsubscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]


def test_native_strategy_universe_update_subscribes_entered_market_once() -> None:
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []
            self.instrument_requests = []

        def request_instrument(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.instrument_requests.append(str(instrument_id))

        def subscribe_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trades(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
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


def test_native_strategy_universe_update_recovers_still_active_missing_subscription() -> (
    None
):
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []

        def subscribe_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trades(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
    )

    strategy.on_start()
    strategy._subscription_state.subscribe_intent_condition_ids.clear()

    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=2,
            active_condition_ids=("condition-a",),
            entered_condition_ids=(),
            exited_condition_ids=(),
            condition_to_up_token={"condition-a": "up-a"},
            condition_to_down_token={"condition-a": "down-a"},
            condition_to_asset={"condition-a": "BTC"},
            condition_to_timeframe={"condition-a": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_subscriptions.count("up-a.POLYMARKET") == 1
    assert strategy.book_subscriptions.count("down-a.POLYMARKET") == 1
    assert strategy.trade_subscriptions.count("up-a.POLYMARKET") == 1
    assert strategy.trade_subscriptions.count("down-a.POLYMARKET") == 1
    assert strategy._subscription_state.subscribe_intent_condition_ids == {"condition-a"}



def test_native_strategy_universe_update_skips_duplicate_wired_condition() -> (
    None
):
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []

        def subscribe_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trades(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
    )

    strategy.on_start()
    initial_book_count = len(strategy.book_subscriptions)
    initial_trade_count = len(strategy.trade_subscriptions)

    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=2,
            active_condition_ids=("condition-a",),
            entered_condition_ids=(),
            exited_condition_ids=(),
            condition_to_up_token={"condition-a": "up-a"},
            condition_to_down_token={"condition-a": "down-a"},
            condition_to_asset={"condition-a": "BTC"},
            condition_to_timeframe={"condition-a": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert len(strategy.book_subscriptions) == initial_book_count
    assert len(strategy.trade_subscriptions) == initial_trade_count



def test_native_strategy_ptb_update_does_not_request_provider_owned_instruments() -> None:
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalPriceToBeatData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.instrument_requests = []
            self.book_subscriptions = []
            self.trade_subscriptions = []

        def request_instrument(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.instrument_requests.append(str(instrument_id))

        def subscribe_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trades(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
    )

    strategy.on_start()

    strategy.on_data(
        PolySignalPriceToBeatData(
            condition_id="condition-a",
            value=100000.0,
            source="anchor",
            verified=True,
            from_anchor_service=True,
            anchor_source="chainlink",
            anchor_lag_ms=0,
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.instrument_requests == []
def test_native_strategy_active_market_without_metadata_stays_pending_until_metadata_arrives() -> (
    None
):
    from polysignal_lab.nautilus_runtime.custom_data_types import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []

        def subscribe_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trades(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=_test_market_catalog(),
        instrument_id_resolver=lambda token_id: _TestInstrument(token_id),
    )

    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=2,
            active_condition_ids=("condition-b",),
            entered_condition_ids=(),
            exited_condition_ids=(),
            condition_to_up_token={"condition-b": "up-b"},
            condition_to_down_token={"condition-b": "down-b"},
            condition_to_asset={"condition-b": "BTC"},
            condition_to_timeframe={"condition-b": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=("condition-b",),
            entered_condition_ids=(),
            exited_condition_ids=(),
            condition_to_up_token={"condition-b": "up-b"},
            condition_to_down_token={"condition-b": "down-b"},
            condition_to_asset={"condition-b": "BTC"},
            condition_to_timeframe={"condition-b": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_subscriptions == []
    assert strategy.trade_subscriptions == []
    assert strategy._subscription_state.pending_metadata_condition_ids == {
        "condition-b"
    }

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

    assert strategy.book_subscriptions == ["up-b.POLYMARKET", "down-b.POLYMARKET"]
    assert strategy.trade_subscriptions == ["up-b.POLYMARKET", "down-b.POLYMARKET"]
    assert strategy._subscription_state.pending_metadata_condition_ids == set()
    assert strategy._subscription_state.subscribe_intent_condition_ids == {"condition-b"}

def test_native_strategy_waits_for_actor_owned_market_universe(
    monkeypatch,
) -> None:
    from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeCache:
        def __init__(self) -> None:
            self.instruments: dict[str, object] = {}

        def instrument(self, instrument_id: object) -> object | None:
            return self.instruments.get(str(instrument_id))

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        now: datetime

        @property
        def clock(self) -> _NoopClock:
            return self.fake_clock

        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)  # type: ignore[arg-type]
            self.fake_clock = _NoopClock()
            self.now = datetime(2026, 7, 18, 12, tzinfo=UTC)
            self._cache_override = FakeCache()
            self.instrument_venue_subscriptions: list[tuple[str, str | None]] = []
            self.instrument_venue_requests: list[tuple[str, str | None]] = []
            self.custom_data_subscriptions: list[tuple[object, str | None]] = []
            self.book_subscriptions: list[str] = []
            self.trade_subscriptions: list[str] = []
            self.quote_subscriptions: list[str] = []

        def subscribe_instruments(self, venue: object, *args: object, **kwargs: object) -> None:
            _ = args
            client_id = kwargs.get("client_id")
            self.instrument_venue_subscriptions.append(
                (str(venue), None if client_id is None else str(client_id))
            )

        @override
        def _framework_now(self) -> datetime:
            return self.now

        def request_instruments(self, venue: object, *args: object, **kwargs: object) -> None:
            _ = args
            client_id = kwargs.get("client_id")
            self.instrument_venue_requests.append(
                (str(venue), None if client_id is None else str(client_id))
            )

        @override
        def subscribe_data(
            self,
            data_type: object,
            client_id: object | None = None,
        ) -> None:
            self.custom_data_subscriptions.append(
                (data_type, None if client_id is None else str(client_id))
            )

        def subscribe_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_quotes(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.quote_subscriptions.append(str(instrument_id))

        def subscribe_trades(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.trade_subscriptions.append(str(instrument_id))

    monkeypatch.setattr(
        FakeNativeStrategy,
        "trader_id",
        property(lambda _self: "TEST-TRADER"),
    )
    registry = MarketCatalog(
        instrument_id_resolver=lambda condition_id, token_id: (
            f"{condition_id}-{token_id}.POLYMARKET"
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=registry,
    )
    strategy._spot_data_source = "disabled"

    strategy.on_start()

    assert strategy.instrument_venue_subscriptions == []
    assert strategy.instrument_venue_requests == []
    assert all(client_id is None for _, client_id in strategy.custom_data_subscriptions)

    instruments = (
        polymarket_binary_instrument("uptoken", "Up"),
        polymarket_binary_instrument("downtoken", "Down"),
    )
    for instrument in instruments:
        strategy._cache_override.instruments[str(instrument.id)] = instrument
        strategy.on_instrument(instrument)

    # Provider instruments are Cache inputs; the rotation Actor owns Market/universe state.
    assert strategy.registry.by_condition("0xcondition1") is None
    assert strategy._active_condition_ids == set()
    assert strategy.book_subscriptions == []
    assert strategy.trade_subscriptions == []
    assert strategy.quote_subscriptions == []

    from polysignal_lab.nautilus_runtime.custom_data_types import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
    )

    strategy.on_data(
        PolySignalMarketMetaData(
            market_id="market1",
            market_slug="btc-updown-5m-1784376000",
            condition_id="0xcondition1",
            asset="BTC",
            timeframe="5m",
            start_ts_ns=int(datetime(2026, 7, 18, 12, tzinfo=UTC).timestamp() * 1e9),
            end_ts_ns=int(datetime(2026, 7, 18, 12, 5, tzinfo=UTC).timestamp() * 1e9),
            up_token_id="uptoken",
            down_token_id="downtoken",
            up_outcome="Up",
            down_outcome="Down",
            ts_event=1,
            ts_init=1,
        )
    )
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=1,
            active_condition_ids=("0xcondition1",),
            entered_condition_ids=("0xcondition1",),
            condition_to_up_token={"0xcondition1": "uptoken"},
            condition_to_down_token={"0xcondition1": "downtoken"},
            condition_to_asset={"0xcondition1": "BTC"},
            condition_to_timeframe={"0xcondition1": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert registry.by_condition("0xcondition1") is not None
    assert strategy._active_condition_ids == {  # pyright: ignore[reportUnknownMemberType]
        "0xcondition1"
    }
    expected = [str(instrument.id) for instrument in instruments]
    assert strategy.book_subscriptions == expected
    assert strategy.trade_subscriptions == expected
    assert strategy.quote_subscriptions == expected

    for instrument in instruments:
        strategy.on_instrument(instrument)

    assert strategy.book_subscriptions == expected
    assert strategy.trade_subscriptions == expected
    assert strategy.quote_subscriptions == expected


def test_native_strategy_ignores_expired_provider_instrument_pair(
    monkeypatch: Any,  # pyright: ignore[reportExplicitAny, reportAny]
) -> None:
    from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeCache:
        def __init__(self) -> None:
            self.instruments: dict[str, object] = {}

        def instrument(self, instrument_id: object) -> object | None:
            return self.instruments.get(str(instrument_id))

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        fake_clock: _NoopClock
        now: datetime
        _cache_override: FakeCache

        @property
        def clock(self) -> _NoopClock:
            return self.fake_clock

        def __init__(  # pyright: ignore[reportInconsistentConstructor]
            self,
            **kwargs: Any,  # pyright: ignore[reportExplicitAny, reportAny]
        ) -> None:
            super().__init__(**kwargs)  # pyright: ignore[reportAny]
            self.fake_clock = _NoopClock()
            self.now = datetime(2026, 7, 18, 12, 5, tzinfo=UTC)
            self._cache_override = FakeCache()
            self.subscriptions: list[str] = []

        @override
        def _framework_now(self) -> datetime:
            return self.now

        @override
        def subscribe_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscriptions.append(str(instrument_id))

        @override
        def subscribe_quotes(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscriptions.append(str(instrument_id))

        @override
        def subscribe_trades(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscriptions.append(str(instrument_id))

    monkeypatch.setattr(  # pyright: ignore[reportAny]
        FakeNativeStrategy,
        "trader_id",
        property(lambda _self: "TEST-TRADER"),  # pyright: ignore[reportAny]
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=MarketCatalog(
            instrument_id_resolver=lambda condition_id, token_id: (
                f"{condition_id}-{token_id}.POLYMARKET"
            )
        ),
    )
    instruments = (
        polymarket_binary_instrument("uptoken", "Up"),
        polymarket_binary_instrument("downtoken", "Down"),
    )

    for instrument in instruments:
        instrument_id = getattr(instrument, "id")  # pyright: ignore[reportAny]
        strategy._cache_override.instruments[str(instrument_id)] = instrument  # pyright: ignore[reportPrivateUsage, reportAny]
        strategy.on_instrument(instrument)

    registry = cast(MarketCatalog, strategy.registry)
    assert registry.by_condition("0xcondition1") is None
    assert strategy._active_condition_ids == set()  # pyright: ignore[reportUnknownMemberType]
    assert strategy.subscriptions == []


def test_native_strategy_retires_expired_preloaded_pair_before_first_leg(
    monkeypatch: Any,  # pyright: ignore[reportExplicitAny, reportAny]
) -> None:
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketCatalog,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeCache:
        def __init__(self) -> None:
            self.instruments: dict[str, object] = {}

        def instrument(self, instrument_id: object) -> object | None:
            return self.instruments.get(str(instrument_id))

    class FakeClock(_NoopClock):
        @override
        def timestamp_ns(self) -> int:
            return int(datetime(2026, 7, 18, 12, 5, tzinfo=UTC).timestamp() * 1e9)

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        fake_clock: FakeClock
        _cache_override: FakeCache

        @property
        def clock(self) -> FakeClock:
            return self.fake_clock

        def __init__(  # pyright: ignore[reportInconsistentConstructor]
            self,
            **kwargs: Any,  # pyright: ignore[reportExplicitAny, reportAny]
        ) -> None:
            super().__init__(**kwargs)  # pyright: ignore[reportAny]
            self.fake_clock = FakeClock()
            self._cache_override = FakeCache()
            self.subscriptions: list[str] = []
            self.instrument_requests: list[str] = []

        @override
        def _framework_now(self) -> datetime:
            return datetime(2026, 7, 18, 12, 5, tzinfo=UTC)

        def request_instrument(self, instrument_id: object) -> None:
            self.instrument_requests.append(str(instrument_id))

        def subscribe_instruments(self, venue: object, *args: object, **kwargs: object) -> None:
            _ = venue, args, kwargs

        def request_instruments(self, venue: object, *args: object, **kwargs: object) -> None:
            _ = venue, args, kwargs

        @override
        def subscribe_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscriptions.append(str(instrument_id))

        @override
        def subscribe_quotes(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscriptions.append(str(instrument_id))

        @override
        def subscribe_trades(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscriptions.append(str(instrument_id))

    monkeypatch.setattr(  # pyright: ignore[reportAny]
        FakeNativeStrategy,
        "trader_id",
        property(lambda _self: "TEST-TRADER"),  # pyright: ignore[reportAny]
    )
    registry = MarketCatalog(
        instrument_id_resolver=lambda condition_id, token_id: (
            f"{condition_id}-{token_id}.POLYMARKET"
        )
    )
    registry.register(
        MarketPairMeta(
            market_id="market-1",
            market_slug="btc-updown-5m-expired",
            condition_id="0xcondition1",
            asset="BTC",
            timeframe="5m",
            start_ts=datetime(2026, 7, 18, 12, tzinfo=UTC),
            end_ts=datetime(2026, 7, 18, 12, 5, tzinfo=UTC),
            up=InstrumentTokenMeta("uptoken", Side.UP),
            down=InstrumentTokenMeta("downtoken", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("0xcondition1",),
        strategy_name="ptb_diff",
        registry=registry,
    )

    strategy.on_start()
    first_leg = polymarket_binary_instrument("uptoken", "Up")
    strategy._cache_override.instruments[str(getattr(first_leg, "id"))] = first_leg  # pyright: ignore[reportPrivateUsage, reportAny]
    strategy.on_instrument(first_leg)

    assert strategy._active_condition_ids == set()  # pyright: ignore[reportUnknownMemberType]
    assert strategy.subscriptions == []
    assert strategy.instrument_requests == []


def test_native_strategy_subscribes_only_after_instrument_in_cache() -> None:
    """provider → Cache / on_instrument → subscribe (never request then immediate wire)."""
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeCache:
        def __init__(self) -> None:
            self.loaded: set[str] = set()

        def instrument(self, instrument_id):
            key = str(instrument_id)
            return SimpleNamespace(id=instrument_id) if key in self.loaded else None

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._cache_override = FakeCache()
            self.instrument_requests: list[tuple[str, str | None]] = []
            self.book_subscriptions: list[tuple[str, str | None]] = []
            self.trade_subscriptions: list[tuple[str, str | None]] = []
            self.quote_subscriptions: list[tuple[str, str | None]] = []

        def request_instrument(
            self,
            instrument_id: object,
            *args: object,
            **kwargs: object,
        ) -> None:
            _ = args
            client_id = kwargs.get("client_id")
            self.instrument_requests.append(
                (str(instrument_id), None if client_id is None else str(client_id))
            )

        def subscribe_book_deltas(
            self,
            instrument_id: object,
            *args: object,
            **kwargs: object,
        ) -> None:
            _ = args
            client_id = kwargs.get("client_id")
            self.book_subscriptions.append(
                (str(instrument_id), None if client_id is None else str(client_id))
            )

        def subscribe_quotes(
            self,
            instrument_id: object,
            *args: object,
            **kwargs: object,
        ) -> None:
            _ = args
            client_id = kwargs.get("client_id")
            self.quote_subscriptions.append(
                (str(instrument_id), None if client_id is None else str(client_id))
            )

        def subscribe_trades(
            self,
            instrument_id: object,
            *args: object,
            **kwargs: object,
        ) -> None:
            _ = args
            client_id = kwargs.get("client_id")
            self.trade_subscriptions.append(
                (str(instrument_id), None if client_id is None else str(client_id))
            )

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=registry,
    )

    universe = PolySignalMarketUniverseData(
        epoch=2,
        active_condition_ids=("condition-a",),
        entered_condition_ids=(),
        exited_condition_ids=(),
        condition_to_up_token={"condition-a": "up-a"},
        condition_to_down_token={"condition-a": "down-a"},
        condition_to_asset={"condition-a": "BTC"},
        condition_to_timeframe={"condition-a": "5m"},
        ts_event=1,
        ts_init=1,
    )

    strategy.on_data(universe)

    # Cache empty → pending intent only; provider owns instrument loading.
    assert strategy.instrument_requests == []
    assert strategy.book_subscriptions == []
    assert strategy.trade_subscriptions == []
    assert strategy.quote_subscriptions == []
    assert strategy._subscription_state.subscribe_intent_condition_ids == {"condition-a"}
    assert "up-a.POLYMARKET" in strategy._subscription_state.pending_instrument_ids
    assert "down-a.POLYMARKET" in strategy._subscription_state.pending_instrument_ids

    # Simulate provider load: instrument enters Cache then on_instrument fires.
    for iid in ("up-a.POLYMARKET", "down-a.POLYMARKET"):
        strategy._cache_override.loaded.add(iid)
        strategy.on_instrument(SimpleNamespace(id=iid))

    assert strategy.book_subscriptions == [
        ("up-a.POLYMARKET", "POLYMARKET-5M"),
        ("down-a.POLYMARKET", "POLYMARKET-5M"),
    ]
    assert strategy.trade_subscriptions == [
        ("up-a.POLYMARKET", "POLYMARKET-5M"),
        ("down-a.POLYMARKET", "POLYMARKET-5M"),
    ]
    assert strategy.quote_subscriptions == [
        ("up-a.POLYMARKET", "POLYMARKET-5M"),
        ("down-a.POLYMARKET", "POLYMARKET-5M"),
    ]
    assert strategy._subscription_state.pending_instrument_ids == set()



def test_native_strategy_exited_market_is_gated_even_if_late_tick_arrives() -> None:
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    seen: list[str] = []
    readiness: list[tuple[str, bool]] = []

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def _handle_decision(self, decision, view):
            _ = decision
            seen.append(view.condition_id)

    view = _MockView()
    view.condition_id = "condition-a"
    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(view),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        readiness_callback=lambda condition_id, ready, _detail: readiness.append(
            (condition_id, ready)
        ),
        **_native_projections(),
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
    assert readiness == [("condition-a", True)]


def test_native_strategy_exited_market_fill_follow_up_is_gated() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class Book:
        best_ask: float | None = 0.50
        ask_levels: tuple[tuple[float, float], ...] = ((0.50, 20.0),)

    class View(_MockView):
        condition_id = "condition-a"

        def book_for(self, side: Side) -> _BookViewLike:
            _ = side
            return Book()

    class ExitedFollowUpCore:
        def __init__(self) -> None:
            self.fill_condition_ids: list[str] = []

        def evaluate(self, view: MarketView) -> list[AlphaDecision]:
            _ = view
            return []

        def on_order_filled(self, event: object) -> list[AlphaDecision]:
            self.fill_condition_ids.append(str(getattr(event, "condition_id")))
            return [
                AlphaDecision(
                    strategy="ptb_diff",
                    asset="BTC",
                    timeframe="5m",
                    market_id="btc-5m-a",
                    market_slug="btc-updown-5m-a",
                    condition_id="condition-a",
                    token_id="up-a",
                    side=Side.UP,
                    confidence=0.8,
                    entry_reference_price=0.50,
                    max_entry_price=0.52,
                    seconds_to_close=60,
                    data_freshness_ms=20,
                    reason_codes=("FOLLOW_UP",),
                    metrics={},
                    order_intent=OrderIntentSpec(
                        intent=OrderIntent.TAKER_FOK, pair_id="pair-condition-a"
                    ),
                    hedge_leg=False,
                )
            ]

    class FakeOrderFactory:
        def limit(self, **kwargs):
            return kwargs

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._order_factory_override = FakeOrderFactory()
            self.submitted = []

        def submit_order(self, order):
            self.submitted.append(order)

    core = ExitedFollowUpCore()
    strategy = FakeNativeStrategy(
        core=core,
        assembler=_assembler(View()),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: _TestInstrument(token_id),
        **_native_projections(),
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

    strategy.on_order_filled(
        SimpleNamespace(
            order_id="order-a-1",
            client_order_id="client-a-1",
            market_id="btc-5m-a",
            condition_id="condition-a",
            token_id="up-a",
            side=Side.UP,
            last_qty=10.0,
            last_px=0.5,
            trade_id="trade-a-1",
            liquidity_side="TAKER",
            tags=[
                "strategy=ptb_diff",
                "market_id=btc-5m-a",
                "condition_id=condition-a",
                "token_id=up-a",
            ],
            ts_event=datetime.now(UTC),
        )
    )

    assert core.fill_condition_ids == []
    assert strategy.submitted == []


def test_native_strategy_exited_market_unsubscribes_when_hooks_exist() -> None:
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []
            self.book_unsubscriptions = []
            self.trade_unsubscriptions = []

        def subscribe_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trades(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

        def unsubscribe_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_unsubscriptions.append(str(instrument_id))

        def unsubscribe_trades(self, instrument_id, *args, **kwargs):
            self.trade_unsubscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
    )

    strategy.on_start()
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=(),
            entered_condition_ids=(),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={},
            condition_to_down_token={},
            condition_to_asset={},
            condition_to_timeframe={},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.book_unsubscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_unsubscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy._subscription_state.subscribe_intent_condition_ids == set()

    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=4,
            active_condition_ids=("condition-a",),
            entered_condition_ids=("condition-a",),
            exited_condition_ids=(),
            condition_to_up_token={"condition-a": "up-a"},
            condition_to_down_token={"condition-a": "down-a"},
            condition_to_asset={"condition-a": "BTC"},
            condition_to_timeframe={"condition-a": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_subscriptions.count("up-a.POLYMARKET") == 2
    assert strategy.book_subscriptions.count("down-a.POLYMARKET") == 2
    assert strategy.trade_subscriptions.count("up-a.POLYMARKET") == 2
    assert strategy.trade_subscriptions.count("down-a.POLYMARKET") == 2
    assert strategy._subscription_state.subscribe_intent_condition_ids == {"condition-a"}


def test_native_strategy_exited_l1_market_unsubscribes_quote_ticks() -> None:
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.quote_subscriptions = []
            self.trade_subscriptions = []
            self.quote_unsubscriptions = []
            self.trade_unsubscriptions = []

        def subscribe_quotes(self, instrument_id, *args, **kwargs):
            self.quote_subscriptions.append(str(instrument_id))

        def subscribe_trades(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

        def unsubscribe_quotes(self, instrument_id, *args, **kwargs):
            self.quote_unsubscriptions.append(str(instrument_id))

        def unsubscribe_trades(self, instrument_id, *args, **kwargs):
            self.trade_unsubscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        book_type="L1_MBP",
        registry=registry,
    )

    strategy.on_start()
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=(),
            entered_condition_ids=(),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={},
            condition_to_down_token={},
            condition_to_asset={},
            condition_to_timeframe={},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.quote_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.quote_unsubscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_unsubscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]


def test_native_strategy_exited_market_unsubscribes_without_book_type_kwarg() -> None:
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_unsubscriptions = []
            self.trade_unsubscriptions = []

        def subscribe_book_deltas(self, instrument_id, *args, **kwargs):
            _ = instrument_id, args, kwargs

        def subscribe_trades(self, instrument_id, *args, **kwargs):
            _ = instrument_id, args, kwargs

        def unsubscribe_book_deltas(
            self,
            instrument_id: object,
            *args: object,
            **kwargs: object,
        ) -> None:
            _ = args, kwargs
            self.book_unsubscriptions.append(str(instrument_id))

        def unsubscribe_trades(
            self,
            instrument_id: object,
            *args: object,
            **kwargs: object,
        ) -> None:
            _ = args, kwargs
            self.trade_unsubscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
    )

    strategy.on_start()
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=(),
            entered_condition_ids=(),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={},
            condition_to_down_token={},
            condition_to_asset={},
            condition_to_timeframe={},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_unsubscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_unsubscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]


def test_native_strategy_exited_market_is_noop_when_unsubscribe_disabled() -> None:
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_unsubscriptions = []
            self.trade_unsubscriptions = []

        def subscribe_book_deltas(self, instrument_id, *args, **kwargs):
            _ = instrument_id

        def subscribe_trades(self, instrument_id, *args, **kwargs):
            _ = instrument_id

        def unsubscribe_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_unsubscriptions.append(str(instrument_id))

        def unsubscribe_trades(self, instrument_id, *args, **kwargs):
            self.trade_unsubscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
        unsubscribe_exited=False,
    )

    strategy.on_start()
    strategy._subscription_state.pending_metadata_condition_ids.add("condition-a")

    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=(),
            entered_condition_ids=(),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={},
            condition_to_down_token={},
            condition_to_asset={},
            condition_to_timeframe={},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_unsubscriptions == []
    assert strategy.trade_unsubscriptions == []
    assert strategy._subscription_state.pending_metadata_condition_ids == set()
    assert strategy._subscription_state.subscribe_intent_condition_ids == {"condition-a"}


def test_native_strategy_exited_market_without_unsubscribe_hooks_clears_wire_state() -> (
    None
):
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []

        def subscribe_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trades(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
    )

    strategy.on_start()
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=(),
            entered_condition_ids=(),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={},
            condition_to_down_token={},
            condition_to_asset={},
            condition_to_timeframe={},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy._active_condition_ids == set()
    assert strategy._subscription_state.subscribe_intent_condition_ids == set()

    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=4,
            active_condition_ids=("condition-a",),
            entered_condition_ids=("condition-a",),
            exited_condition_ids=(),
            condition_to_up_token={"condition-a": "up-a"},
            condition_to_down_token={"condition-a": "down-a"},
            condition_to_asset={"condition-a": "BTC"},
            condition_to_timeframe={"condition-a": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_subscriptions == [
        "up-a.POLYMARKET",
        "down-a.POLYMARKET",
        "up-a.POLYMARKET",
        "down-a.POLYMARKET",
    ]
    assert strategy.trade_subscriptions == [
        "up-a.POLYMARKET",
        "down-a.POLYMARKET",
        "up-a.POLYMARKET",
        "down-a.POLYMARKET",
    ]


def test_native_strategy_exited_market_trade_tick_stays_gated() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    seen: list[str] = []

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def subscribe_book_deltas(self, instrument_id, *args, **kwargs):
            _ = instrument_id, args, kwargs

        def subscribe_trades(self, instrument_id, *args, **kwargs):
            _ = instrument_id, args, kwargs

        def _handle_decision(self, decision, view):
            _ = decision
            seen.append(view.condition_id)

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )

    view = _MockView()
    view.condition_id = "condition-a"
    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(view),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
    )

    strategy.on_start()
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=(),
            entered_condition_ids=(),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={},
            condition_to_down_token={},
            condition_to_asset={},
            condition_to_timeframe={},
            ts_event=1,
            ts_init=1,
        )
    )

    strategy.on_trade(
        SimpleNamespace(
            instrument_id="up-a.POLYMARKET",
            price=0.51,
            size=7.0,
            aggressor_side="BUYER",
            ts_event=datetime.now(UTC),
        )
    )

    assert seen == []


def test_native_strategy_routes_spot_custom_data_to_matching_asset_conditions_only() -> (
    None
):
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from nautilus_trader.core.nautilus_pyo3 import PolymarketRtdsCryptoPrice
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    seen = []
    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    registry.register(
        MarketPairMeta(
            market_id="eth-5m",
            market_slug="eth-updown-5m",
            condition_id="condition-eth-5m",
            asset="ETH",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("eth-up", Side.UP),
            down=InstrumentTokenMeta("eth-down", Side.DOWN),
        )
    )

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

        def evaluate_condition(
            self,
            condition_id: str,
            *,
            trading_state: object | None = None,
        ) -> None:
            _ = trading_state
            seen.append(condition_id)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m", "condition-eth-5m"),
        strategy_name="ptb_diff",
        registry=registry,
    )

    _ = cast(_DataHandler, cast(object, strategy)).on_data(
        PolymarketRtdsCryptoPrice("BTCUSD", "100000.0", 0, 0, 1, 2)
    )

    assert seen == ["condition-btc-5m"]
    assert strategy.custom_data.spot_for("BTC") is not None


def test_native_strategy_routes_ptb_custom_data_to_matching_active_condition_only() -> (
    None
):
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalPriceToBeatData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class RecordingAssembler(FakeAssembler):
        def __init__(self) -> None:
            super().__init__(None)
            self.seen: list[str] = []

        def build(
            self,
            condition_id: str,
            *,
            created_at: datetime | None = None,
        ) -> MarketView | None:
            _ = created_at
            self.seen.append(condition_id)
            return None

    assembler = RecordingAssembler()
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=cast(MarketViewAssembler, cast(object, assembler)),
        condition_ids=("condition-active",),
        strategy_name="ptb_diff",
        registry=_test_market_catalog(),
    )

    _ = cast(_DataHandler, cast(object, strategy)).on_data(
        PolySignalPriceToBeatData(
            condition_id="condition-active",
            value=99950.0,
            source="anchor",
            verified=True,
            from_anchor_service=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            ts_event=1,
            ts_init=2,
        )
    )
    _ = cast(_DataHandler, cast(object, strategy)).on_data(
        PolySignalPriceToBeatData(
            condition_id="condition-inactive",
            value=100050.0,
            source="anchor",
            verified=True,
            from_anchor_service=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            ts_event=3,
            ts_init=4,
        )
    )

    assert assembler.seen == ["condition-active"]
    active_ptb = strategy.custom_data.ptb_for("condition-active")
    inactive_ptb = strategy.custom_data.ptb_for("condition-inactive")
    assert active_ptb is not None
    assert active_ptb.value == 99950.0
    assert inactive_ptb is not None
    assert inactive_ptb.value == 100050.0




def test_native_strategy_trade_tick_callback_reads_cache_trades_without_shared_trade_history_write() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.market_view_assembler import MarketViewAssembler

    from polysignal_lab.nautilus_runtime.cache_market_data import NautilusCacheMarketDataProvider
    from nautilus_trader.core.nautilus_pyo3 import PolymarketRtdsCryptoPrice
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeLevel:
        def __init__(self, price: float, size: float) -> None:
            self.price = price
            self.size = size

    class FakeOrderBook:
        def __init__(self, bids, asks) -> None:
            self.bids = bids
            self.asks = asks
            self.last_trade_price = None
            self.last_trade_size = None
            self.last_trade_timestamp = None
            self.received_at = datetime.now(UTC)

    class FakeTrade:
        price = 0.51
        size = 7.0
        aggressor_side = "BUYER"
        ts_event = datetime.now(UTC)

    class FakeCache:
        def __init__(self) -> None:
            self.books = {
                "up-token.POLYMARKET": FakeOrderBook(
                    bids=[FakeLevel(0.49, 20.0)],
                    asks=[FakeLevel(0.50, 20.0)],
                ),
                "down-token.POLYMARKET": FakeOrderBook(
                    bids=[FakeLevel(0.48, 20.0)],
                    asks=[FakeLevel(0.51, 20.0)],
                ),
            }
            self.trades = {"up-token.POLYMARKET": [FakeTrade()]}

        def order_book(self, instrument_id):
            return self.books[str(instrument_id)]

        def trade_ticks(self, instrument_id):
            return self.trades.get(str(instrument_id), [])

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    custom_data = StrategyCustomDataState()
    custom_data.apply(
        PolymarketRtdsCryptoPrice("BTCUSD", "100000.0", 0, 0, 1, 2)
    )
    custom_data.apply(
        PolySignalPriceToBeatData(
            condition_id="condition-btc-5m",
            value=99950.0,
            source="anchor",
            verified=True,
            from_anchor_service=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            ts_event=1_700_000_000_000_000_000,
            ts_init=1_700_000_000_000_000_000,
        )
    )
    fake_cache = FakeCache()
    books = NautilusCacheMarketDataProvider(fake_cache, catalog=registry)
    assembler = MarketViewAssembler(
        catalog=registry,
        books=books,
        custom_data=custom_data,
    )

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._cache_override = fake_cache
            self.evaluated: list[str] = []

        def evaluate_condition(
            self,
            condition_id: str,
            *,
            trading_state: object | None = None,
        ) -> None:
            _ = trading_state
            self.evaluated.append(condition_id)
            super().evaluate_condition(condition_id)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
    )

    strategy.on_book_deltas(SimpleNamespace(instrument_id="up-token.POLYMARKET"))
    strategy.evaluated.clear()
    # Reset the market-data debounce so the trade tick evaluates immediately.
    strategy._last_market_data_evaluation_at.clear()
    strategy.on_trade(
        SimpleNamespace(
            instrument_id="up-token.POLYMARKET",
            price=0.51,
            size=7.0,
            aggressor_side="BUYER",
            ts_event=datetime.now(UTC),
        )
    )

    trades = books.trades_for_token("up-token")
    assert len(trades) == 1
    assert trades[0].price == 0.51
    assert strategy.evaluated == ["condition-btc-5m"]


def test_native_strategy_on_order_accepted_preserves_ephemeral() -> None:
    from types import SimpleNamespace

    from polysignal_lab.alpha.one_cent_buy_core import OneCentBuyAlphaCore
    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.domain.strategy_config import OneCentBuyConfig

    class RecordingObservability:
        def __init__(self) -> None:
            self.decisions: list[tuple[str, bool]] = []
            self.rejections: list[object] = []
            self.orders: list[object] = []
            self.fills: list[object] = []
            self.positions: list[object] = []

        def record_decision(self, decision, accepted: bool) -> None:
            self.decisions.append((decision.strategy, accepted))

        def record_rejected_decision(self, rejected: object) -> None:
            self.rejections.append(rejected)

        def record_nautilus_order_event(self, event: object, metrics: object | None = None) -> None:
            if metrics is not None:
                try:
                    event.metrics = dict(metrics)  # type: ignore[attr-defined]
                except Exception:
                    pass
            self.orders.append(event)

        def record_nautilus_fill_event(self, event: object, metrics: object | None = None) -> None:
            if metrics is not None:
                try:
                    event.metrics = dict(metrics)  # type: ignore[attr-defined]
                except Exception:
                    pass
            self.fills.append(event)

        def record_nautilus_position(self, position: object) -> None:
            self.positions.append(position)

    class FakeOrderFactoryForNative:
        def limit(self, **kwargs):
            return kwargs

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._order_factory_override = FakeOrderFactoryForNative()
            self.submitted = []

        def submit_order(self, order: object) -> None:
            self.submitted.append(order)

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    observability = RecordingObservability()
    core = OneCentBuyAlphaCore(
        OneCentBuyConfig(entry_prices=(0.01,), shares_per_level=10)
    )
    now = datetime.now(UTC)
    view = _real_market_view(
        up_ask=0.05,
        down_ask=0.01,
        up_ask_levels=((0.05, 100.0),),
        down_ask_levels=((0.01, 100.0),),
        created_at=now,
        start_ts=now - timedelta(seconds=60),
        end_ts=now + timedelta(seconds=60),
        seconds_to_close=60,
    )
    strategy = FakeNativeStrategy(
        core=core,
        assembler=_assembler(view),
        condition_ids=("condition-btc-5m",),
        strategy_name="one_cent_buy",
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: _TestInstrument(token_id),
        registry=registry,
        observability=observability,
    )
    _policy = _attach_decision_policy(strategy)

    strategy.evaluate_condition("condition-btc-5m")

    assert len(strategy.submitted) == 1
    submitted = strategy.submitted[0]
    accepted = SimpleNamespace(
        instrument_id="up-token.POLYMARKET",
        order_id="order-accepted-1",
        client_order_id="client-accepted-1",
        quantity=10.0,
        price=0.01,
        status="ACCEPTED",
        tags=submitted["tags"],
        ts_event=datetime.now(UTC),
    )

    strategy._cache_override = SimpleNamespace(
        order=lambda _client_order_id: SimpleNamespace(tags=submitted["tags"])
    )
    strategy.on_order_accepted(accepted)

    assert observability.decisions == [("one_cent_buy", True)]
    assert len(observability.orders) == 1
    accepted_order = cast(_ObservedOrder, observability.orders[0])
    assert accepted_order.client_order_id == "client-accepted-1"
    assert accepted_order.metrics["level_price"] == 0.01
    assert observability.rejections == []

def test_native_strategy_attributes_inactive_registered_down_order_and_fill_from_catalog() -> (
    None
):
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy


    class CapturingCore(FakeCore):
        def __init__(self) -> None:
            super().__init__([])
            self.orders: list[object] = []
            self.fills: list[object] = []

        def on_order_submitted(self, event: object) -> None:
            self.orders.append(event)

        def on_order_filled(self, event: object) -> list[AlphaDecision]:
            self.fills.append(event)
            return []

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-exited-5m",
            market_slug="btc-exited-updown-5m",
            condition_id="condition-btc-exited-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-exited-token", Side.UP),
            down=InstrumentTokenMeta("down-exited-token", Side.DOWN),
        )
    )
    core = CapturingCore()
    strategy = PolySignalNativeStrategy(
        core=core,
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=registry,
    )
    down_instrument_id = _test_instrument_id("condition-btc-exited-5m", "down-exited-token")
    event = SimpleNamespace(
        order_id="inactive-order-1",
        client_order_id="inactive-client-1",
        instrument_id=down_instrument_id,
        quantity=3.0,
        price=0.37,
        last_qty=3.0,
        last_px=0.37,
        trade_id="inactive-trade-1",
        liquidity_side="TAKER",
        tags=[],
        ts_event=datetime.now(UTC),
    )

    recorded: list[dict[str, object]] = []

    class RecordingObs:
        def record_nautilus_order_event(self, event: object, metrics: object | None = None) -> None:
            _ = event
            if isinstance(metrics, dict):
                recorded.append(metrics)

        def record_nautilus_fill_event(self, event: object, metrics: object | None = None) -> None:
            _ = event
            if isinstance(metrics, dict):
                recorded.append(metrics)

    strategy.observability = RecordingObs()

    class Cache:
        def order(self, client_order_id: object) -> object:
            _ = client_order_id
            return SimpleNamespace(
                tags=(
                    "strategy=ptb_diff",
                    "market_id=btc-exited-5m",
                    "condition_id=condition-btc-exited-5m",
                    "token_id=down-exited-token",
                )
            )

    strategy._cache_override = Cache()
    strategy.on_order_submitted(event)
    strategy.on_order_filled(event)

    # Attribution comes from catalog + metrics dict, not core on_order_* callbacks.
    assert core.orders == []
    assert core.fills == []
    assert len(recorded) == 2
    assert recorded[0]["market_id"] == "btc-exited-5m"
    assert recorded[0]["condition_id"] == "condition-btc-exited-5m"
    assert recorded[0]["token_id"] == "down-exited-token"
    assert recorded[1]["fill_price"] == 0.37


def test_order_submitted_observability_failure_does_not_block_core_event() -> None:
    import sqlite3
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FailingObservability:
        def record_nautilus_order_event(self, event: object, metrics: object | None = None) -> None:
            _ = event
            raise sqlite3.OperationalError("database is locked")

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._order_factory_override = object()

    phases: list[str] = []
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        observability=FailingObservability(),
        progress_callback=phases.append,
        **_native_projections(),
    )

    strategy.on_order_submitted(
        SimpleNamespace(
            order_id="order-1",
            client_order_id="C-001",
            instrument_id="up-token.POLYMARKET",
            side="UP",
            status="SUBMITTED",
            tags=[],
            ts_event=datetime.now(UTC),
        )
    )

    # Observability failures are isolated; core on_order_* surface deleted.
    assert "telemetry_side_effect_failed" in phases or "order_event" in phases

def test_native_strategy_surfaces_approved_signal_to_observability() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class RecordingObservability:
        def __init__(self) -> None:
            self.decisions: list[tuple[str, bool]] = []
            self.rejections: list[object] = []
            self.signals: list[object] = []
            self.published: list[tuple[object, float]] = []

        def record_decision(self, decision, accepted: bool) -> None:
            self.decisions.append((decision.strategy, accepted))

        def record_signal(self, signal: object) -> None:
            self.signals.append(signal)

        def notify_accepted_signal(self, signal: object, stake_usdc: float) -> None:
            self.published.append((signal, stake_usdc))

        def record_rejected_decision(self, rejected: object) -> None:
            self.rejections.append(rejected)

        def record_nautilus_order_event(self, event: object, metrics: object | None = None) -> None:
            _ = event

        def record_nautilus_fill_event(self, event: object, metrics: object | None = None) -> None:
            _ = event

        def record_nautilus_position(self, position: object) -> None:
            _ = position


    class FakeOrderFactory:
        def limit(self, **kwargs):
            return kwargs

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._order_factory_override = FakeOrderFactory()
            self.submitted: list[object] = []

        def submit_order(self, order: object) -> None:
            self.submitted.append(order)

    observability = RecordingObservability()
    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(_real_market_view()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: _TestInstrument(token_id),
        observability=observability,
        **_native_projections(),
    )
    _policy = _attach_decision_policy(strategy)

    strategy.evaluate_condition("condition-btc-5m")

    assert len(strategy.submitted) == 1
    assert len(observability.signals) == 1
    assert observability.decisions == [("ptb_diff", True)]
    assert len(observability.published) == 1
    published_signal, published_stake = observability.published[0]
    assert getattr(published_signal, "signal_id") == getattr(
        observability.signals[0], "signal_id"
    )
    assert published_stake == 10.0
    assert observability.rejections == []



def test_native_strategy_does_not_swallow_durable_signal_persistence_failure() -> None:
    import sqlite3

    import pytest

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FailingSignalObservability:
        def record_decision(self, decision, accepted: bool) -> None:
            _ = decision, accepted

        def record_signal(self, signal: object) -> None:
            _ = signal
            raise sqlite3.OperationalError("database is locked")

    class FakeOrderFactory:
        def limit(self, **kwargs):
            return kwargs

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._order_factory_override = FakeOrderFactory()

        def submit_order(self, order: object) -> None:
            _ = order

    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(_real_market_view()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: _TestInstrument(token_id),
        observability=FailingSignalObservability(),
        **_native_projections(),
    )
    _policy = _attach_decision_policy(strategy)

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        strategy.evaluate_condition("condition-btc-5m")


def test_native_strategy_rejection_persistence_failure_does_not_block_evaluate() -> None:
    import sqlite3

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FailingRejectedObservability:
        def record_decision(self, decision, accepted: bool) -> None:
            _ = decision, accepted

        def record_rejected_decision(self, rejected: object) -> None:
            _ = rejected
            raise sqlite3.OperationalError("database is locked")

    class RejectingPolicy(DecisionPolicy):
        def evaluate(
            self,
            decision: AlphaDecision,
            view: MarketView,
        ) -> RejectedDecision:
            _ = decision, view
            return RejectedDecision(reason_code="TEST_REJECTED", detail={})

        def batch_arbitrate(
            self, decisions: list[tuple[AlphaDecision, MarketView]]
        ) -> BatchArbitrationResult:
            return BatchArbitrationResult(decision for decision, _ in decisions)

    phases: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(_real_market_view()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        observability=FailingRejectedObservability(),
        progress_callback=phases.append,
        **_native_projections(),
    )
    _policy = _attach_decision_policy(strategy, RejectingPolicy())

    strategy.evaluate_condition("condition-btc-5m")

    assert "telemetry_side_effect_failed" in phases


def test_native_strategy_fill_and_position_callbacks_bridge_to_observability() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class RecordingObservability:
        def __init__(self) -> None:
            self.decisions: list[tuple[str, bool]] = []
            self.rejections: list[object] = []
            self.orders: list[object] = []
            self.fills: list[object] = []
            self.positions: list[object] = []

        def record_decision(self, decision, accepted: bool) -> None:
            self.decisions.append((decision.strategy, accepted))

        def record_rejected_decision(self, rejected: object) -> None:
            self.rejections.append(rejected)

        def record_nautilus_order_event(self, event: object, metrics: object | None = None) -> None:
            if metrics is not None:
                try:
                    event.metrics = dict(metrics)  # type: ignore[attr-defined]
                except Exception:
                    pass
            self.orders.append(event)

        def record_nautilus_fill_event(self, event: object, metrics: object | None = None) -> None:
            if metrics is not None:
                try:
                    event.metrics = dict(metrics)  # type: ignore[attr-defined]
                except Exception:
                    pass
            self.fills.append(event)

        def record_nautilus_position(self, position: object) -> None:
            self.positions.append(position)

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._order_factory_override = object()

    observability = RecordingObservability()
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        observability=observability,
        **_native_projections(),
    )

    fill = SimpleNamespace(
        order_id="order-1",
        client_order_id="order-1",
        market_id="btc-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        last_qty=10.0,
        last_px=0.5,
        trade_id="trade-1",
        liquidity_side="TAKER",
        tags=["strategy=ptb_diff", "condition_id=condition-btc-5m"],
        ts_event=datetime.now(UTC),
    )
    opened = SimpleNamespace(
        id="pos-1",
        instrument_id="up-token.POLYMARKET",
        signed_qty=10.0,
        avg_px_open=0.5,
        realized_pnl=0.0,
        is_closed=False,
    )
    closed = SimpleNamespace(
        id="pos-1",
        instrument_id="up-token.POLYMARKET",
        signed_qty=0.0,
        avg_px_open=0.5,
        realized_pnl=1.0,
        is_closed=True,
    )

    strategy._cache_override = SimpleNamespace(
        order=lambda _client_order_id: SimpleNamespace(tags=fill.tags)
    )
    strategy.on_order_filled(fill)
    strategy.on_position_opened(opened)
    strategy.on_position_closed(closed)

    assert len(observability.fills) == 1
    fill_event = cast(_ObservedFill, observability.fills[0])
    assert fill_event.trade_id == "trade-1"
    assert fill_event.last_px == 0.5
    assert observability.positions == [opened, closed]






def test_native_strategy_notifies_core_before_fill_handler() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class HedgeAwareCore:
        def __init__(self) -> None:
            self.events: list[tuple[str, str, Side, float]] = []

        def evaluate(self, view: MarketView) -> list[AlphaDecision]:
            return []

        def on_notify_fill(self, market_id: str, side: Side, shares: float) -> None:
            self.events.append(("notify", market_id, side, shares))

        def on_order_filled(self, event: object) -> list[AlphaDecision]:
            fill = cast(_ObservedFill, event)
            self.events.append(("filled", fill.market_id, fill.side, fill.shares))
            return []

    core = HedgeAwareCore()
    strategy = PolySignalNativeStrategy(
        core=core,
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        **_native_projections(),
    )

    event = SimpleNamespace(
        order_id="order-1",
        client_order_id="order-1",
        market_id="btc-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        last_qty=10.0,
        last_px=0.5,
        trade_id="trade-1",
        liquidity_side="TAKER",
        tags=["strategy=vwap_momentum", "condition_id=condition-btc-5m"],
        ts_event=datetime.now(UTC),
    )
    strategy._cache_override = SimpleNamespace(
        order=lambda _client_order_id: SimpleNamespace(tags=event.tags)
    )
    strategy.on_order_filled(event)

    # on_notify_fill still fires; on_order_filled core callback removed.
    assert core.events == [
        ("notify", "btc-5m", Side.UP, 10.0),
    ]


# ── L1 subscription selection tests ──────────────────────────────────────────


def test_native_strategy_l1_subscribes_data_names_without_snapshot_request() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._cache_override = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_quotes: list[str] = []
            self.subscribed_trades: list[str] = []
            self.subscribed_deltas: list[str] = []
            self.snapshot_requests: list[str] = []

        def subscribe_quotes(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscribed_quotes.append(str(instrument_id))

        def subscribe_trades(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscribed_trades.append(str(instrument_id))

        def subscribe_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscribed_deltas.append(str(instrument_id))

        def request_order_book_snapshot(self, instrument_id):
            self.snapshot_requests.append(str(instrument_id))

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        book_type="L1_MBP",
        **_native_projections(),
    )

    strategy._subscribe_market_instrument("up-token.POLYMARKET")

    assert strategy.subscribed_quotes == ["up-token.POLYMARKET"]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]
    assert strategy.subscribed_deltas == ["up-token.POLYMARKET"]
    assert strategy.snapshot_requests == []


def test_native_strategy_l1_subscribes_all_data_names() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    phases: list[str] = []

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._cache_override = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_deltas: list[str] = []
            self.subscribed_trades: list[str] = []

        def subscribe_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscribed_deltas.append(str(instrument_id))

        def subscribe_trades(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscribed_trades.append(str(instrument_id))

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        book_type="L1_MBP",
        progress_callback=phases.append,
        **_native_projections(),
    )

    strategy._subscribe_market_instrument("up-token.POLYMARKET")

    assert strategy.subscribed_deltas == ["up-token.POLYMARKET"]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]
    assert "l1_raw_delta_fallback" not in phases


def test_native_strategy_l2_subscribes_all_data_names() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(_NativeSubscriptionMethods, PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._cache_override = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_quotes: list[str] = []
            self.subscribed_trades: list[str] = []
            self.subscribed_deltas: list[str] = []

        def subscribe_quotes(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscribed_quotes.append(str(instrument_id))

        def subscribe_trades(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscribed_trades.append(str(instrument_id))

        def subscribe_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = args, kwargs
            self.subscribed_deltas.append(str(instrument_id))

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        book_type="L2_MBP",
        **_native_projections(),
    )

    strategy._subscribe_market_instrument("up-token.POLYMARKET")

    assert strategy.subscribed_quotes == ["up-token.POLYMARKET"]
    assert strategy.subscribed_deltas == ["up-token.POLYMARKET"]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]


def test_native_strategy_does_not_define_custom_market_data_subscription_group() -> None:
    import inspect

    import polysignal_lab.nautilus_runtime.native_strategy as native_strategy

    source = inspect.getsource(native_strategy)

    assert "class _MarketDataSubscriptionGroup" not in source
    assert "_polysignal_market_data_subscription_group" not in source
    assert "_market_data_subscription_group" not in source
