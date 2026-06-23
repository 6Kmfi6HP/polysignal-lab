from __future__ import annotations

from typing import NotRequired, TypedDict, assert_never

from polysignal_lab.config import PTBDiffConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy


class TpSlThresholds(TypedDict):
    stop_prob: float
    tp_trigger_prob: float | None
    risk_abs: float
    balanced_stop: NotRequired[float]


def compute_tp_sl_thresholds(entry_prob: float, stop_loss_pct: float, tp_rr: float, tp_cap: float) -> TpSlThresholds:
    """
    计算概率空间 TP/SL 阈值。
    
    返回 dict:
      - stop_prob:      止损概率阈值
      - tp_trigger_prob:止盈触发概率 (None if not reachable)
      - risk_abs:       风险绝对值 (entry_prob - stop_prob)
      - balanced_stop:  如果 TP 被封顶后重新平衡的止损
    
    PolyBullLabs 原始逻辑：
      stop_prob = entry_prob * (1 - STOP_LOSS_PROB_PCT)
      risk_abs = entry_prob - stop_prob
      tp_trigger_prob = min(TP_CAP, entry_prob + risk_abs * TP_RR)
      如果 TP 被封顶，收紧止损以保持 RR。
    """
    if entry_prob <= 0.0:
        return {"stop_prob": 0.0, "tp_trigger_prob": None, "risk_abs": 0.0}

    stop_prob = max(0.0, entry_prob * (1.0 - stop_loss_pct))
    risk_abs = max(0.0, entry_prob - stop_prob)
    raw_tp = entry_prob + risk_abs * tp_rr

    if raw_tp <= entry_prob:
        # 无有效止盈
        return {
            "stop_prob": stop_prob,
            "tp_trigger_prob": None,
            "risk_abs": risk_abs,
            "balanced_stop": stop_prob,
        }

    tp_trigger_prob = min(tp_cap, raw_tp)

    # 如果 TP 被封顶，收紧止损以保持 RR
    if tp_trigger_prob < raw_tp:
        balanced_risk = (tp_trigger_prob - entry_prob) / tp_rr
        balanced_stop = max(0.0, entry_prob - balanced_risk)
        if balanced_stop > stop_prob:
            stop_prob = balanced_stop

    return {
        "stop_prob": stop_prob,
        "tp_trigger_prob": tp_trigger_prob,
        "risk_abs": risk_abs,
        "balanced_stop": stop_prob,
    }


class PTBDiffStrategy(BaseStrategy):
    name = "ptb_diff"

    def __init__(self, config: PTBDiffConfig):
        self.config = config

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        if not self.config.enabled:
            return []
        if snapshot.market.asset not in [a.upper() for a in self.config.assets]:
            return []
        if snapshot.market.timeframe not in self.config.timeframes:
            return []
        if snapshot.spot is None or snapshot.price_to_beat is None:
            return []
        if self.config.require_verified_ptb_source and snapshot.metrics.get("price_to_beat_verified") is not True:
            return []

        seconds = snapshot.seconds_to_close
        if seconds is None or seconds <= 0:
            return []

        diff = snapshot.spot.price - snapshot.price_to_beat  # 有正负
        exit_cfg = self.config.exit_config

        for trigger in self.config.triggers:
            wanted_side = trigger.side
            if not self._diff_supports_side(diff, wanted_side):
                continue

            if not (trigger.min_seconds_to_close <= seconds <= trigger.max_seconds_to_close):
                continue

            if abs(diff) < trigger.min_diff_usd:
                continue

            entry_price = snapshot.ask_for(wanted_side)
            if entry_price is None or entry_price <= 0.0:
                continue

            if entry_price > trigger.max_token_price:
                continue

            if trigger.min_token_price > 0.0:
                # Refs-style: direct range check on token ask price (entry_price IS probability)
                # Matches C1_MIN_PROB <= prob <= C1_MAX_PROB from PolyBullLabs reference
                if not (trigger.min_token_price <= entry_price <= trigger.max_token_price):
                    continue
                directional_probability = entry_price
                probability_edge = max(0.0, entry_price - trigger.min_token_price)
            else:
                # Legacy: directional-probability edge check
                directional_probability = self._directional_probability(diff, wanted_side)
                probability_edge = max(0.0, directional_probability - entry_price)
                if probability_edge < trigger.min_probability_edge:
                    continue

            side_book = snapshot.book_for(wanted_side)
            if side_book is None or side_book.best_bid is None or side_book.best_ask is None:
                continue

            if side_book.spread is None or side_book.spread > self.config.max_spread:
                continue

            now = snapshot.created_at
            max_lag_ms = exit_cfg.market_data_max_lag_sec * 1000
            orderbook_freshness_ms = side_book.freshness_ms(now)
            spot_freshness_ms = snapshot.spot.freshness_ms(now)
            if orderbook_freshness_ms > max_lag_ms:
                continue

            if spot_freshness_ms > max_lag_ms:
                continue

            tp_sl = compute_tp_sl_thresholds(
                entry_prob=entry_price,
                stop_loss_pct=exit_cfg.stop_loss_prob_pct,
                tp_rr=exit_cfg.take_profit_rr,
                tp_cap=exit_cfg.take_profit_cap,
            )

            confidence = min(0.98, 0.55 + min(0.25, abs(diff) / 500) + min(0.18, probability_edge))
            prob_ok_code = "PTB_PROB_RANGE_OK" if trigger.min_token_price > 0.0 else "PTB_PROBABILITY_EDGE_OK"
            reason_codes = [
                self._spot_reason(wanted_side),
                "PTB_DIFF_THRESHOLD_OK",
                "PTB_TOKEN_PRICE_OK",
                prob_ok_code,
                "PTB_TIME_WINDOW_OK",
                "PTB_ORDERBOOK_FRESH",
                "PTB_SPREAD_OK",
                trigger.name,
            ]

            signal = self._candidate(
                snapshot,
                wanted_side,
                confidence,
                max_entry_price=trigger.max_token_price,
                reason_codes=reason_codes,
                metrics={
                    "spot_price": snapshot.spot.price,
                    "price_to_beat": snapshot.price_to_beat,
                    "diff_usd": diff,
                    "abs_diff_usd": abs(diff),
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
                    "seconds_to_close": seconds,
                    "min_seconds_to_close": trigger.min_seconds_to_close,
                    "max_seconds_to_close": trigger.max_seconds_to_close,
                    "tp_sl_stop_prob": tp_sl["stop_prob"],
                    "tp_sl_tp_prob": tp_sl["tp_trigger_prob"],
                    "tp_sl_risk_abs": tp_sl["risk_abs"],
                    "tp_sl_stop_loss_pct": exit_cfg.stop_loss_prob_pct,
                    "tp_sl_take_profit_rr": exit_cfg.take_profit_rr,
                    "tp_sl_take_profit_cap": exit_cfg.take_profit_cap,
                    "spread": side_book.spread,
                    "max_spread": self.config.max_spread,
                    "orderbook_freshness_ms": orderbook_freshness_ms,
                    "spot_freshness_ms": spot_freshness_ms,
                },
            )
            if signal:
                return [signal]

        return []

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
