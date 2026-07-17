"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, typing, typing.Any, typing.Mapping, polysignal_lab.alpha.helpers, polysignal_lab.alpha.helpers.enabled_for_view, polysignal_lab.alpha.state
Output: _EvalContext, _HedgeDecisionContext, VWAPMomentumAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from polysignal_lab.alpha.helpers import enabled_for_view
from polysignal_lab.alpha.state import json_safe_state
from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketView,
    OrderIntentSpec,
)
from polysignal_lab.alpha.vwap_state import encode_vwap_state, restore_vwap_state_fields
from polysignal_lab.alpha.vwap_trade_history import (
    TradeSample,
    latest_price,
    momentum,
    samples_from_trade_views,
    vwap,
)
from polysignal_lab.domain.enums import OrderIntent, Side


@dataclass(frozen=True)
class _EvalContext:
    """Pre-validated evaluation context for VWAP evaluate()."""

    seconds_to_close: int
    elapsed_sec: float | None
    cfg: Any  # VWAPMomentumConfig — kept as Any to avoid import coupling


@dataclass(frozen=True)
class _HedgeDecisionContext:
    asset: str
    timeframe: str
    market_id: str
    market_slug: str
    condition_id: str
    token_id: str
    side: Side
    confidence: float
    seconds_to_close: int | None
    data_freshness_ms: int | None
    contracts: float


class VWAPMomentumAlphaCore:
    """PolyBullLabs VWAP / Deviation / Momentum signal strategy (pure core).

    Trade truth comes only from Cache-projected ``MarketView.up_trades`` /
    ``down_trades``. This core does not keep a local trade ledger.
    """

    name = "vwap_momentum"

    def __init__(self, config) -> None:
        self.config = config

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        hedge = self._pending_hedge_decision(view)
        if hedge:
            return hedge

        ctx = self._validate_and_prepare(view)
        if ctx is None:
            return []

        now_ts = view.created_at.timestamp()
        up_trades = samples_from_trade_views(view.up_trades, now_ts=now_ts)
        down_trades = samples_from_trade_views(view.down_trades, now_ts=now_ts)

        up_price = latest_price(up_trades)
        down_price = latest_price(down_trades)
        if up_price is None or down_price is None:
            return []

        fav_side = Side.UP if up_price >= down_price else Side.DOWN
        fav_price = up_price if fav_side == Side.UP else down_price
        fav_trades = up_trades if fav_side == Side.UP else down_trades

        decision = self._check_entry(view, ctx, fav_side, fav_price, fav_trades)
        if decision is None:
            return []
        return [decision]

    def _validate_and_prepare(self, view: MarketView) -> _EvalContext | None:
        cfg = self.config
        if not enabled_for_view(cfg, view):
            return None

        seconds_to_close = view.seconds_to_close
        if seconds_to_close is None:
            return None

        dt_duration: float | None = None
        if view.start_ts and view.end_ts:
            dt_duration = (view.end_ts - view.start_ts).total_seconds()
        elif view.end_ts:
            if view.timeframe == "5m":
                dt_duration = 300.0
            elif view.timeframe == "15m":
                dt_duration = 900.0

        elapsed_sec: float | None = None
        if dt_duration is not None and dt_duration > 0:
            elapsed_sec = dt_duration - seconds_to_close

        return _EvalContext(
            seconds_to_close=seconds_to_close,
            elapsed_sec=elapsed_sec,
            cfg=cfg,
        )

    def _check_entry(
        self,
        view: MarketView,
        ctx: _EvalContext,
        fav_side: Side,
        fav_price: float,
        fav_trades: tuple[TradeSample, ...],
    ) -> AlphaDecision | None:
        cfg = ctx.cfg

        if not (cfg.min_price <= fav_price <= cfg.max_price):
            return None

        if ctx.elapsed_sec is not None and ctx.elapsed_sec < cfg.min_elapsed_sec:
            return None

        if ctx.seconds_to_close <= cfg.no_entry_before_end_sec:
            return None

        now_ts = view.created_at.timestamp()
        vwap_value = vwap(fav_trades, cfg.vwap_window_sec, now_ts)
        if vwap_value is None or vwap_value <= 0:
            return None

        deviation_pct = (fav_price - vwap_value) / vwap_value
        if not (cfg.min_deviation_pct < deviation_pct < cfg.max_deviation_pct):
            return None

        momentum_value = momentum(fav_trades, cfg.momentum_window_sec, now_ts)
        if momentum_value is None:
            return None
        if momentum_value <= cfg.min_momentum:
            return None

        if view.trading.has_market_activity(self.name, view.market_id):
            return None

        entry_reference_price = view.ask_for(fav_side)
        if entry_reference_price is None:
            return None

        confidence = self._compute_confidence(deviation_pct, momentum_value)
        return self._build_decision(
            view,
            ctx,
            fav_side,
            fav_price,
            vwap_value,
            deviation_pct,
            momentum_value,
            confidence,
            entry_reference_price,
        )

    @staticmethod
    def _build_decision(
        view: MarketView,
        ctx: _EvalContext,
        fav_side: Side,
        fav_price: float,
        vwap_value: float,
        deviation_pct: float,
        momentum_value: float,
        confidence: float,
        entry_reference_price: float,
    ) -> AlphaDecision:
        opposite_book = view.book_for(fav_side.opposite)
        return AlphaDecision(
            strategy="vwap_momentum",
            asset=view.asset,
            timeframe=view.timeframe,
            market_id=view.market_id,
            market_slug=view.market_slug,
            condition_id=view.condition_id,
            token_id=view.book_for(fav_side).token_id,
            side=fav_side,
            confidence=confidence,
            entry_reference_price=entry_reference_price,
            max_entry_price=min(ctx.cfg.max_price, fav_price + 0.05),
            seconds_to_close=ctx.seconds_to_close,
            data_freshness_ms=view.freshness.max_ms,
            reason_codes=(
                "VWAP_DEVIATION_OK",
                "MOMENTUM_OK",
                "FAVORITE_SELECTED",
                "ENTRY_WINDOW_OK",
            ),
            metrics={
                "vwap": vwap_value,
                "deviation_pct": deviation_pct,
                "deviation_percent": deviation_pct * 100.0,
                "momentum_pct": momentum_value,
                "momentum": momentum_value,
                "favorite_side": fav_side.value,
                "fav_price": fav_price,
                "elapsed_sec": ctx.elapsed_sec,
                "seconds_to_close": ctx.seconds_to_close,
                "opposite_token_id": opposite_book.token_id,
                "condition_id": view.condition_id,
                "created_at_for_test": view.created_at,
            },
        )

    def _pending_hedge_decision(self, view: MarketView) -> list[AlphaDecision]:
        position = view.trading.unhedged_leg(self.name, view.market_id)
        if position is None or view.trading.has_hedge_order(self.name, view.market_id):
            return []
        hedge_side = position.side.opposite
        contracts = position.quantity
        ask = view.ask_for(hedge_side)
        if ask is None:
            return []
        book = view.book_for(hedge_side)
        return [
            self._build_hedge_decision(
                _HedgeDecisionContext(
                    asset=view.asset,
                    timeframe=view.timeframe,
                    market_id=view.market_id,
                    market_slug=view.market_slug,
                    condition_id=view.condition_id,
                    token_id=book.token_id,
                    side=hedge_side,
                    confidence=0.70,
                    seconds_to_close=view.seconds_to_close,
                    data_freshness_ms=view.freshness.max_ms,
                    contracts=contracts,
                )
            )
        ]

    def _build_hedge_decision(self, ctx: _HedgeDecisionContext) -> AlphaDecision:
        return AlphaDecision(
            strategy=self.name,
            asset=ctx.asset,
            timeframe=ctx.timeframe,
            market_id=ctx.market_id,
            market_slug=ctx.market_slug,
            condition_id=ctx.condition_id,
            token_id=ctx.token_id,
            side=ctx.side,
            confidence=ctx.confidence,
            entry_reference_price=self.config.hedge_price,
            max_entry_price=self.config.hedge_price,
            seconds_to_close=ctx.seconds_to_close,
            data_freshness_ms=ctx.data_freshness_ms,
            reason_codes=("VWAP_GTD_HEDGE",),
            metrics={
                "contracts": ctx.contracts,
                "hedge_price": self.config.hedge_price,
                "hedge_source": "vwap_entry_fill",
            },
            order_intent=OrderIntentSpec(
                intent=OrderIntent.PASSIVE_GTD,
                expiry_seconds=self.config.hedge_expiry_seconds,
                pair_id=f"{ctx.market_id}:vwap",
            ),
            hedge_leg=True,
        )

    @staticmethod
    def _compute_confidence(deviation_pct: float, momentum_value: float) -> float:
        base = 0.50
        dev_contrib = max(0.0, min(0.25, abs(deviation_pct) * 2.0))
        mom_contrib = max(0.0, min(0.20, momentum_value * 3.0))
        return min(0.95, base + dev_contrib + mom_contrib)

    def save_state(self) -> Mapping[str, object]:
        # Trade history is owned by Nautilus Cache; core state is empty.
        return json_safe_state(encode_vwap_state({}))

    def load_state(self, payload: Mapping[str, object]) -> None:
        restore_vwap_state_fields(payload)
