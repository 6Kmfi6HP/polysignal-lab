from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.strategy.order_events import (
    handle_order_filled,
    handle_position_closed,
)


def _registry() -> MarketCatalog:
    registry = MarketCatalog(
        instrument_id_resolver=lambda _condition_id, token_id: f"{token_id}.POLYMARKET"
    )
    registry.register(
        MarketPairMeta(
            market_id="market-1",
            market_slug="btc-updown-5m",
            condition_id="condition-1",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("token-up", Side.UP),
            down=InstrumentTokenMeta("token-down", Side.DOWN),
        )
    )
    return registry


class _Core:
    def __init__(self) -> None:
        self.fill_calls = 0

    def on_order_filled(self, _event: object) -> None:
        self.fill_calls += 1

class _Metrics:
    def metrics_for_event(self, _event: object) -> dict[str, object]:
        return {}

    def forget(self, _event: object, _order: object) -> None:
        return None


class _Strategy:
    def __init__(self) -> None:
        self.core = _Core()
        self.registry = _registry()
        self.strategy_name = "mid_price_sizing"
        self._active_condition_ids = {"condition-1"}
        self._metrics_tracker = _Metrics()
        self.positions: list[object] = []

    def _note_runtime_progress(self, _phase: str) -> None:
        return None

    def _record_nautilus_order(self, _event: object, _metrics: object) -> None:
        return None

    def _record_nautilus_fill(self, _event: object, _metrics: object) -> None:
        return None

    def _record_nautilus_position(self, position: object) -> None:
        self.positions.append(position)

    def _require_assembler(self) -> object:
        raise AssertionError("reduce-only fills must not build a new decision")

    def _handle_decision(self, _decision: object, _view: object) -> None:
        raise AssertionError("reduce-only fills must not create a new decision")


def test_reduce_only_fill_does_not_count_as_new_alpha_entry() -> None:
    strategy = _Strategy()

    handle_order_filled(
        strategy,
        SimpleNamespace(
            client_order_id="client-1",
            instrument_id="token-up.POLYMARKET",
            trade_id="trade-1",
            last_qty=10.0,
            last_px=0.70,
            liquidity_side="TAKER",
            tags=[
                "strategy=mid_price_sizing",
                "market_id=market-1",
                "condition_id=condition-1",
                "token_id=token-up",
                "reduce_only=true",
            ],
            ts_event=datetime(2026, 7, 11, 12, 0, tzinfo=UTC),
        ),
    )

    assert strategy.core.fill_calls == 0


def test_position_closed_only_records_native_projection() -> None:
    strategy = _Strategy()
    position = SimpleNamespace(instrument_id="token-up.POLYMARKET")

    handle_position_closed(strategy, position)

    assert strategy.positions == [position]
    assert not hasattr(strategy.core, "reset_position")
