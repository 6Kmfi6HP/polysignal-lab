from __future__ import annotations


import pytest

from polysignal_lab.alpha.types import CachedOrderView, TradingStateView
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.strategy import condition_evaluation


class _Strategy:
    def __init__(self) -> None:
        self.progress: list[str] = []
        self.cancelled: list[str] = []
        self.cache = object()
        setattr(self, "cancel_" + "orders", self.cancel_legacy_orders)

    def _note_runtime_progress(self, phase: str) -> None:
        self.progress.append(phase)

    def cancel_legacy_orders(self, client_order_ids: tuple[str, ...], **kwargs: object) -> None:
        _ = kwargs
        self.cancelled.extend(client_order_ids)


def _registry() -> MarketCatalog:
    registry = MarketCatalog(
        instrument_id_resolver=lambda _condition_id, token_id: f"{token_id}.POLYMARKET"
    )
    registry.register(
        MarketPairMeta(
            market_id="mkt-1",
            market_slug="btc-updown-5m",
            condition_id="condition-1",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta(token_id="token-up", side=Side.UP),
            down=InstrumentTokenMeta(token_id="token-down", side=Side.DOWN),
        )
    )
    return registry


def _order(*, client_order_id: str, reduce_only: bool = False) -> CachedOrderView:
    return CachedOrderView(
        client_order_id=client_order_id,
        instrument_id="token-up.POLYMARKET",
        strategy="test",
        market_id="mkt-1",
        condition_id="condition-1",
        side=Side.UP,
        pair_id=None,
        position_id="position-1" if reduce_only else None,
        status="ACCEPTED",
        price=0.5,
        filled_quantity=0.0,
        average_fill_price=None,
        ts_event=None,
        hedge_leg=False,
        reduce_only=reduce_only,
        is_open=True,
        is_inflight=True,
        take_profit_price=None,
        stop_loss_price=None,
    )


def test_expired_condition_cancels_open_entry_orders_but_not_reduce_only() -> None:
    strategy = _Strategy()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        condition_evaluation,
        "trading_state_from_cache",
        lambda *a, **k: TradingStateView(
            orders=(
                _order(client_order_id="entry-1"),
                _order(client_order_id="entry-2"),
                _order(client_order_id="reduce-1", reduce_only=True),
            )
        ),
    )
    try:
        condition_evaluation._cancel_expired_entry_orders(
            strategy,
            "condition-1",
            registry=_registry(),  # type: ignore[arg-type]
        )
    finally:
        monkeypatch.undo()

    assert strategy.cancelled == ["entry-1", "entry-2"]
    assert "reduce-1" not in strategy.cancelled
    assert "expired_entry_orders_cancelled" in strategy.progress
