from __future__ import annotations

from dataclasses import replace

from polysignal_lab.alpha.types import (
    AlphaCore,
    AlphaDecision,
    CachedOrderView,
    CachedPositionView,
    MarketView,
    TradingStateView,
)
from polysignal_lab.domain.enums import Side


def evaluate_core(core: AlphaCore, view: MarketView) -> list[AlphaDecision]:
    return list(core.evaluate(view))


def with_active_order(
    view: MarketView,
    strategy: str,
    *,
    side: Side = Side.UP,
    hedge_leg: bool = False,
    price: float | None = None,
    client_order_id: str = "order-1",
    ts_event=None,
) -> MarketView:
    order = CachedOrderView(
        client_order_id=client_order_id,
        instrument_id=f"{view.book_for(side).token_id}.POLYMARKET",
        strategy=strategy,
        market_id=view.market_id,
        condition_id=view.condition_id,
        side=side,
        pair_id=f"{view.market_id}:pair",
        position_id=None,
        status="ACCEPTED",
        price=view.ask_for(side) if price is None else price,
        filled_quantity=0.0,
        average_fill_price=None,
        ts_event=view.created_at if ts_event is None else ts_event,
        hedge_leg=hedge_leg,
        reduce_only=False,
        is_open=True,
        is_inflight=False,
        take_profit_price=None,
        stop_loss_price=None,
    )
    return replace(
        view,
        trading=TradingStateView(
            orders=(*view.trading.orders, order),
            positions=view.trading.positions,
        ),
    )


def with_open_position(
    view: MarketView,
    strategy: str,
    *,
    side: Side = Side.UP,
    avg_entry_price: float = 0.40,
    quantity: float = 10.0,
) -> MarketView:
    position = CachedPositionView(
        position_id="position-1",
        instrument_id=f"{view.book_for(side).token_id}.POLYMARKET",
        strategy=strategy,
        market_id=view.market_id,
        condition_id=view.condition_id,
        side=side,
        pair_id=f"{view.market_id}:pair",
        quantity=quantity,
        avg_entry_price=avg_entry_price,
        opened_at=view.created_at,
    )
    filled = CachedOrderView(
        client_order_id="entry-1",
        instrument_id=position.instrument_id,
        strategy=strategy,
        market_id=view.market_id,
        condition_id=view.condition_id,
        side=side,
        pair_id=position.pair_id,
        position_id=None,
        status="FILLED",
        price=avg_entry_price,
        filled_quantity=quantity,
        average_fill_price=avg_entry_price,
        ts_event=view.created_at,
        hedge_leg=False,
        reduce_only=False,
        is_open=False,
        is_inflight=False,
        take_profit_price=None,
        stop_loss_price=None,
    )
    return replace(
        view,
        trading=TradingStateView(orders=(filled,), positions=(position,)),
    )
