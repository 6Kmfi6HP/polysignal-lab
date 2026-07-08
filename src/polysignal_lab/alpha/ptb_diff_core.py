"""
Input: __future__, __future__.annotations, typing, typing.TYPE_CHECKING, typing.assert_never, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision, polysignal_lab.alpha.types.FreshnessView, polysignal_lab.alpha.types.MarketView, polysignal_lab.alpha.types.SideBookView
Output: compute_tp_sl_thresholds, market_view_from_snapshot, decision_to_signal, TpSlThresholds, _EvalContext, PTBDiffAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from polysignal_lab.alpha.helpers import enabled_for_view, entry_ask_at_or_below
from polysignal_lab.alpha.types import AlphaDecision, FreshnessView, MarketView, SideBookView, SpotView
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
if TYPE_CHECKING:
    from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.domain.strategy_config import PTBDiffConfig, PTBExitConfig, PTBTriggerConfig


class TpSlThresholds(dict[str, float | None]):
    pass


@dataclass(frozen=True)
class _EvalContext:
    """Shared evaluation context extracted from a MarketView.

    Fields are pre-validated and ready for per-trigger evaluation.
    """

    view: MarketView
    seconds: int
    diff: float
    spot_source: str
    exit_cfg: PTBExitConfig
    max_spread: float


def compute_tp_sl_thresholds(entry_prob: float, stop_loss_pct: float, tp_rr: float, tp_cap: float) -> TpSlThresholds:
    if entry_prob <= 0.0:
        return TpSlThresholds(stop_prob=0.0, tp_trigger_prob=None, risk_abs=0.0)

    stop_prob = max(0.0, entry_prob * (1.0 - stop_loss_pct))
    risk_abs = max(0.0, entry_prob - stop_prob)
    raw_tp = entry_prob + risk_abs * tp_rr

    if raw_tp <= entry_prob:
        return TpSlThresholds(stop_prob=stop_prob, tp_trigger_prob=None, risk_abs=risk_abs)

    tp_trigger_prob = min(tp_cap, raw_tp)

    if tp_trigger_prob < raw_tp:
        balanced_risk = (tp_trigger_prob - entry_prob) / tp_rr
        balanced_stop = max(0.0, entry_prob - balanced_risk)
        if balanced_stop < entry_prob:
            stop_prob = balanced_stop
            risk_abs = entry_prob - stop_prob
            return TpSlThresholds(
                stop_prob=stop_prob,
                tp_trigger_prob=tp_trigger_prob,
                risk_abs=risk_abs,
                balanced_stop=balanced_stop,
            )

    return TpSlThresholds(stop_prob=stop_prob, tp_trigger_prob=tp_trigger_prob, risk_abs=risk_abs)


class PTBDiffAlphaCore:
    name = "ptb_diff"

    def __init__(self, config: PTBDiffConfig):
        self.config = config

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        ctx = self._prepare_context(view)
        if ctx is None:
            return []

        for trigger in self.config.triggers:
            decision = self._evaluate_trigger(ctx, trigger)
            if decision is not None:
                return [decision]
        return []

    def _prepare_context(self, view: MarketView) -> _EvalContext | None:
        """Validate inputs and extract shared evaluation context."""
        cfg = self.config
        if not enabled_for_view(cfg, view):
            return None
        if view.spot is None or view.price_to_beat is None:
            return None
        if cfg.require_verified_ptb_source and view.metrics.get("price_to_beat_verified") is not True:
            return None
        if cfg.require_anchor_price_source and not view.metrics.get("price_to_beat_from_anchor_service"):
            return None
        spot_source = str(view.metrics.get("spot_source") or view.spot.source)
        if cfg.require_chainlink_spot_source and spot_source not in cfg.chainlink_spot_sources:
            return None

        seconds = view.seconds_to_close
        if seconds is None or seconds <= 0:
            return None

        return _EvalContext(
            view=view,
            seconds=seconds,
            diff=view.spot.price - view.price_to_beat,
            spot_source=spot_source,
            exit_cfg=cfg.exit_config,
            max_spread=cfg.max_spread,
        )

    def _evaluate_trigger(self, ctx: _EvalContext, trigger: PTBTriggerConfig) -> AlphaDecision | None:
        """Evaluate a single trigger and return a decision if all conditions are met."""
        view = ctx.view
        wanted_side = trigger.side
        if not self._diff_supports_side(ctx.diff, wanted_side):
            return None
        if not (trigger.min_seconds_to_close <= ctx.seconds <= trigger.max_seconds_to_close):
            return None
        if abs(ctx.diff) < trigger.min_diff_usd:
            return None

        entry_price = entry_ask_at_or_below(view, wanted_side, trigger.max_token_price)
        if entry_price is None:
            return None

        prob_result = self._resolve_probability(ctx.diff, wanted_side, entry_price, trigger)
        if prob_result is None:
            return None
        directional_probability, probability_edge, prob_ok_code = prob_result

        side_book = view.book_for(wanted_side)
        if side_book.best_bid is None or side_book.best_ask is None:
            return None
        if side_book.spread is None or side_book.spread > ctx.max_spread:
            return None

        return self._build_decision(ctx, trigger, wanted_side, entry_price,
                                    directional_probability, probability_edge, prob_ok_code, side_book)

    @staticmethod
    def _resolve_probability(diff: float, side: Side, entry_price: float,
                             trigger: PTBTriggerConfig) -> tuple[float, float, str] | None:
        """Calculate directional probability and edge for a trigger."""
        if trigger.min_token_price > 0.0:
            if not (trigger.min_token_price <= entry_price <= trigger.max_token_price):
                return None
            probability_edge = max(0.0, entry_price - trigger.min_token_price)
            return entry_price, probability_edge, "PTB_PROB_RANGE_OK"
        else:
            directional_probability = PTBDiffAlphaCore._directional_probability(diff, side)
            probability_edge = max(0.0, directional_probability - entry_price)
            if probability_edge < trigger.min_probability_edge:
                return None
            return directional_probability, probability_edge, "PTB_PROBABILITY_EDGE_OK"

    def _build_decision(
        self,
        ctx: _EvalContext,
        trigger: PTBTriggerConfig,
        wanted_side: Side,
        entry_price: float,
        directional_probability: float,
        probability_edge: float,
        prob_ok_code: str,
        side_book: SideBookView,
    ) -> AlphaDecision:
        """Construct the final AlphaDecision from evaluation results."""
        view = ctx.view
        spot = view.spot
        if spot is None:
            raise AssertionError("PTB decision requires spot context")
        tp_sl = compute_tp_sl_thresholds(
            entry_prob=entry_price,
            stop_loss_pct=ctx.exit_cfg.stop_loss_prob_pct,
            tp_rr=ctx.exit_cfg.take_profit_rr,
            tp_cap=ctx.exit_cfg.take_profit_cap,
        )
        confidence = min(0.98, 0.55 + min(0.25, abs(ctx.diff) / 500) + min(0.18, probability_edge))
        return AlphaDecision(
            strategy=self.name,
            asset=view.asset,
            timeframe=view.timeframe,
            market_id=view.market_id,
            market_slug=view.market_slug,
            condition_id=view.condition_id,
            token_id=side_book.token_id,
            side=wanted_side,
            confidence=confidence,
            entry_reference_price=entry_price,
            max_entry_price=trigger.max_token_price,
            seconds_to_close=ctx.seconds,
            data_freshness_ms=view.freshness.max_ms,
            reason_codes=(
                self._spot_reason(wanted_side),
                "PTB_DIFF_THRESHOLD_OK",
                "PTB_TOKEN_PRICE_OK",
                prob_ok_code,
                "PTB_TIME_WINDOW_OK",
                "PTB_SPREAD_OK",
                trigger.name,
            ),
            metrics={
                "spot_price": spot.price,
                "spot_source": ctx.spot_source,
                "price_to_beat": view.price_to_beat,
                "price_to_beat_source": view.metrics.get("price_to_beat_source"),
                "price_to_beat_verified": view.metrics.get("price_to_beat_verified"),
                "diff_usd": ctx.diff,
                "abs_diff_usd": abs(ctx.diff),
                "trigger": trigger.name,
                "trigger_side": trigger.side.value,
                "entry_prob": entry_price,
                "token_ask": entry_price,
                "directional_probability": directional_probability,
                "max_token_price": trigger.max_token_price,
                "min_token_price": trigger.min_token_price,
                "probability_edge": probability_edge,
                "min_probability_edge": trigger.min_probability_edge,
                "min_diff_usd": trigger.min_diff_usd,
                "seconds_to_close": ctx.seconds,
                "min_seconds_to_close": trigger.min_seconds_to_close,
                "max_seconds_to_close": trigger.max_seconds_to_close,
                "tp_sl_stop_prob": tp_sl["stop_prob"],
                "tp_sl_tp_prob": tp_sl["tp_trigger_prob"],
                "tp_sl_risk_abs": tp_sl["risk_abs"],
                "tp_sl_stop_loss_pct": ctx.exit_cfg.stop_loss_prob_pct,
                "tp_sl_take_profit_rr": ctx.exit_cfg.take_profit_rr,
                "tp_sl_take_profit_cap": ctx.exit_cfg.take_profit_cap,
                "spread": side_book.spread,
                "max_spread": ctx.max_spread,
                "orderbook_freshness_ms": side_book.freshness_ms,
                "max_lag_ms": ctx.exit_cfg.market_data_max_lag_sec * 1000,
                "spot_freshness_ms": spot.freshness_ms,
            },
        )

    @staticmethod
    def _diff_supports_side(diff_usd: float, side: Side) -> bool:
        match side:
            case Side.UP:
                return diff_usd > 0
            case Side.DOWN:
                return diff_usd < 0
            case unreachable:
                assert_never(unreachable)

    @staticmethod
    def _directional_probability(diff_usd: float, side: Side) -> float:
        match side:
            case Side.UP:
                return 1.0 if diff_usd > 0 else 0.0
            case Side.DOWN:
                return 1.0 if diff_usd < 0 else 0.0
            case unreachable:
                assert_never(unreachable)

    @staticmethod
    def _spot_reason(side: Side) -> str:
        match side:
            case Side.UP:
                return "PTB_SPOT_ABOVE_PTB"
            case Side.DOWN:
                return "PTB_SPOT_BELOW_PTB"
            case unreachable:
                assert_never(unreachable)


def market_view_from_snapshot(snapshot: MarketSnapshot) -> MarketView | None:
    def book_view(side: Side) -> SideBookView | None:
        book = snapshot.book_for(side)
        try:
            token = snapshot.market.token_for(side)
        except KeyError:
            return None
        return SideBookView(
            token_id=token.token_id,
            best_bid=book.best_bid if book else None,
            best_ask=book.best_ask if book else None,
            spread=book.spread if book else None,
            freshness_ms=book.freshness_ms(snapshot.created_at) if book else None,
            min_order_size=book.min_order_size if book else None,
            tick_size=book.tick_size if book else None,
            last_trade_price=book.last_trade_price if book else None,
            last_trade_size=book.last_trade_size if book else None,
            last_trade_timestamp=book.last_trade_timestamp if book else None,
            received_at=book.received_at if book else None,
            ask_levels=tuple((level.price, level.size) for level in book.asks) if book else (),
        )

    spot = None
    if snapshot.spot is not None:
        spot = SpotView(
            asset=snapshot.spot.asset,
            symbol=snapshot.spot.symbol,
            price=snapshot.spot.price,
            source=snapshot.spot.source,
            freshness_ms=snapshot.spot.freshness_ms(snapshot.created_at),
        )
    up = book_view(Side.UP)
    down = book_view(Side.DOWN)
    if up is None or down is None:
        return None

    return MarketView(
        view_id=snapshot.snapshot_id,
        market_id=snapshot.market.market_id,
        market_slug=snapshot.market.market_slug,
        condition_id=snapshot.market.condition_id,
        asset=snapshot.market.asset,
        timeframe=snapshot.market.timeframe,
        start_ts=snapshot.market.start_ts,
        end_ts=snapshot.market.end_ts,
        created_at=snapshot.created_at,
        seconds_to_close=snapshot.seconds_to_close,
        up=up,
        down=down,
        spot=spot,
        price_to_beat=snapshot.price_to_beat,
        up_trades=tuple(snapshot.metrics.get("up_trades") or ()),
        down_trades=tuple(snapshot.metrics.get("down_trades") or ()),
        metrics=snapshot.metrics,
        freshness=FreshnessView(
            up_book_ms=snapshot.freshness.up_book_ms,
            down_book_ms=snapshot.freshness.down_book_ms,
            spot_ms=snapshot.freshness.spot_ms,
            max_ms=snapshot.freshness.max_ms,
        ),
    )


def decision_to_signal(decision: AlphaDecision, snapshot_id: str | None, freshness_policy) -> SignalCandidate:
    return SignalCandidate.build(
        strategy=decision.strategy,
        asset=decision.asset,
        timeframe=decision.timeframe,
        market_id=decision.market_id,
        market_slug=decision.market_slug,
        condition_id=decision.condition_id,
        token_id=decision.token_id,
        side=decision.side,
        confidence=decision.confidence,
        entry_reference_price=decision.entry_reference_price,
        max_entry_price=decision.max_entry_price,
        seconds_to_close=decision.seconds_to_close,
        data_freshness_ms=decision.data_freshness_ms,
        freshness_policy=freshness_policy,
        reason_codes=list(decision.reason_codes),
        metrics=dict(decision.metrics),
        snapshot_id=snapshot_id,
        order_intent=decision.order_intent.intent if decision.order_intent else None,
        expiry_seconds=decision.order_intent.expiry_seconds if decision.order_intent else None,
        pair_id=decision.order_intent.pair_id if decision.order_intent else None,
        hedge_leg=decision.hedge_leg,
    )
