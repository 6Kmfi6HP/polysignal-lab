"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, typing, typing.assert_never, polysignal_lab.alpha.helpers, polysignal_lab.alpha.helpers.enabled_for_view, polysignal_lab.alpha.helpers.entry_ask_at_or_below, polysignal_lab.alpha.types
Output: compute_tp_sl_thresholds, TpSlThresholds, _EvalContext, PTBDiffAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from polysignal_lab.alpha.helpers import enabled_for_view, entry_ask_at_or_below
from polysignal_lab.alpha.types import AlphaDecision, MarketView, SideBookView
from polysignal_lab.domain.enums import Side
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
