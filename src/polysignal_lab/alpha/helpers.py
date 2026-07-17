from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

from polysignal_lab.alpha.types import (
    AlphaDecision,
    CachedPositionView,
    MarketView,
    OrderIntentSpec,
    SideBookView,
)
from polysignal_lab.domain.enums import Side

SIDES = (Side.UP, Side.DOWN)


class MarketFilterConfig(Protocol):
    @property
    def enabled(self) -> bool: ...

    @property
    def assets(self) -> Sequence[str]: ...

    @property
    def timeframes(self) -> Sequence[str]: ...


def enabled_for_view(config: MarketFilterConfig, view: MarketView) -> bool:
    if not config.enabled:
        return False
    if view.asset.upper() not in {asset.upper() for asset in config.assets}:
        return False
    return view.timeframe in config.timeframes


def depth_weighted_ask(book: SideBookView, shares: int) -> float | None:
    if shares <= 0 or not book.ask_levels:
        return None
    remaining = float(shares)
    total_cost = 0.0
    for price, size in sorted(book.ask_levels, key=lambda level: level[0]):
        take = min(remaining, size)
        total_cost += take * price
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        return None
    return total_cost / shares


def binary_pair_effective_cost(
    leg1_price: float,
    leg2_price: float,
    *,
    fee_rate: float = 0.01,
    slippage_buffer: float = 0.01,
) -> float:
    return leg1_price + leg2_price + 2.0 * fee_rate + slippage_buffer


@dataclass(frozen=True, slots=True)
class OrderDecisionSpec:
    confidence: float
    max_entry_price: float
    reason_codes: tuple[str, ...]
    metrics: Mapping[str, Any]
    order_intent: OrderIntentSpec | None = None
    hedge_leg: bool = False
    entry_reference_price: float | None = None
    fallback_to_max_entry: bool = False


@dataclass(frozen=True, slots=True)
class PositionHedgeContext:
    filled_side: Side
    hedge_side: Side
    filled_price: float
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class HedgeDecisionContext:
    strategy: str
    view: MarketView
    side: Side
    filled_price: float
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class HedgeDecisionSpec:
    confidence: float
    hedge_price: float
    pair_cost: float
    cap_metric: str
    cap_value: float
    reason_codes: tuple[str, ...]
    order_intent: OrderIntentSpec
    hedge_price_metric: str | None = None


def build_order_decision(
    strategy: str, view: MarketView, side: Side, spec: OrderDecisionSpec
) -> AlphaDecision | None:
    book = view.book_for(side)
    entry_reference_price = spec.entry_reference_price
    if entry_reference_price is None:
        entry_reference_price = book.best_ask
    if entry_reference_price is None and spec.fallback_to_max_entry:
        entry_reference_price = spec.max_entry_price
    if entry_reference_price is None:
        return None
    return AlphaDecision(
        strategy=strategy,
        asset=view.asset,
        timeframe=view.timeframe,
        market_id=view.market_id,
        market_slug=view.market_slug,
        condition_id=view.condition_id,
        token_id=book.token_id,
        side=side,
        confidence=spec.confidence,
        entry_reference_price=entry_reference_price,
        max_entry_price=spec.max_entry_price,
        seconds_to_close=view.seconds_to_close,
        data_freshness_ms=view.freshness.max_ms,
        reason_codes=spec.reason_codes,
        metrics=spec.metrics,
        order_intent=spec.order_intent,
        hedge_leg=spec.hedge_leg,
    )


def build_hedge_order_decision(
    ctx: HedgeDecisionContext, spec: HedgeDecisionSpec
) -> AlphaDecision | None:
    metrics: dict[str, Any] = {
        "pair_cost": round(spec.pair_cost, 4),
        spec.cap_metric: spec.cap_value,
        "filled_leg_price": ctx.filled_price,
        "elapsed_seconds": round(ctx.elapsed_seconds, 2),
    }
    if spec.hedge_price_metric is not None:
        metrics[spec.hedge_price_metric] = spec.hedge_price
    return build_order_decision(
        ctx.strategy,
        ctx.view,
        ctx.side,
        OrderDecisionSpec(
            confidence=spec.confidence,
            max_entry_price=spec.hedge_price,
            reason_codes=spec.reason_codes,
            metrics=metrics,
            order_intent=spec.order_intent,
            hedge_leg=True,
        ),
    )


def entry_ask_at_or_below(
    view: MarketView, side: Side, max_entry_price: float | None = None
) -> float | None:
    entry_price = view.ask_for(side)
    if entry_price is None or entry_price <= 0.0:
        return None
    if max_entry_price is not None and entry_price > max_entry_price:
        return None
    return entry_price


def hedge_context_from_position(
    position: CachedPositionView, now: datetime
) -> PositionHedgeContext:
    return PositionHedgeContext(
        filled_side=position.side,
        hedge_side=position.side.opposite,
        filled_price=position.avg_entry_price,
        elapsed_seconds=(now - position.opened_at).total_seconds()
        if position.opened_at is not None
        else 0.0,
    )
