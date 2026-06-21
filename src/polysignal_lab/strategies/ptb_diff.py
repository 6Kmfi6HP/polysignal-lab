from __future__ import annotations

from polysignal_lab.config import PTBDiffConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy


def compute_tp_sl_thresholds(entry_prob: float, stop_loss_pct: float, tp_rr: float, tp_cap: float) -> dict:
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
        """
        基于 PTB 差价和 4 组条件 (C1-C4) 评估入场信号。
        附加概率空间 TP/SL 阈值到 signal.metrics 中。
        """
        # --- 基础过滤 ---
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

        # --- 逐条件检查 (C1 -> C4) ---
        for condition in self.config.conditions:
            # 方向匹配
            wanted_side = Side.UP if condition.side.upper() == "UP" else Side.DOWN

            # 时间检查：剩余秒数 <= time_sec
            if seconds > condition.time_sec:
                continue

            # 差价检查
            if wanted_side == Side.UP:
                if diff < condition.min_diff_usd:
                    continue
            else:  # DOWN
                if diff > -condition.min_diff_usd:
                    continue

            # 获取买单价格（入场概率）
            entry_price = snapshot.ask_for(wanted_side)
            if entry_price is None or entry_price <= 0.0:
                continue

            # 概率范围检查
            if not (condition.min_prob <= entry_price <= condition.max_prob):
                continue

            # 数据新鲜度检查
            now = snapshot.created_at
            max_lag_ms = exit_cfg.market_data_max_lag_sec * 1000

            side_book = snapshot.book_for(wanted_side)
            if side_book is not None and side_book.freshness_ms(now) > max_lag_ms:
                continue

            if snapshot.spot.freshness_ms(now) > max_lag_ms:
                continue

            # --- 计算 TP/SL 阈值 ---
            tp_sl = compute_tp_sl_thresholds(
                entry_prob=entry_price,
                stop_loss_pct=exit_cfg.stop_loss_prob_pct,
                tp_rr=exit_cfg.take_profit_rr,
                tp_cap=exit_cfg.take_profit_cap,
            )

            # --- 置信度 ---
            confidence = min(0.98, 0.55 + min(0.25, abs(diff) / 500) + min(0.18, abs(0.5 - entry_price) / 0.5))

            # --- 构建原因码 ---
            if diff > 0:
                reason_codes = ["SPOT_ABOVE_PTB", "DIFF_THRESHOLD_OK", "PROB_IN_RANGE", "ORDERBOOK_FRESH"]
            else:
                reason_codes = ["SPOT_BELOW_PTB", "DIFF_THRESHOLD_OK", "PROB_IN_RANGE", "ORDERBOOK_FRESH"]

            reason_codes.append(condition.name)

            signal = self._candidate(
                snapshot,
                wanted_side,
                confidence,
                max_entry_price=condition.max_prob,
                reason_codes=reason_codes,
                metrics={
                    "spot_price": snapshot.spot.price,
                    "price_to_beat": snapshot.price_to_beat,
                    "diff_usd": diff,
                    "abs_diff_usd": abs(diff),
                    "condition": condition.name,
                    "entry_prob": entry_price,
                    # TP/SL 阈值（供 PaperSimulator 使用）
                    "tp_sl_stop_prob": tp_sl["stop_prob"],
                    "tp_sl_tp_prob": tp_sl["tp_trigger_prob"],
                    "tp_sl_risk_abs": tp_sl["risk_abs"],
                    "tp_sl_stop_loss_pct": exit_cfg.stop_loss_prob_pct,
                    "tp_sl_take_profit_rr": exit_cfg.take_profit_rr,
                    "tp_sl_take_profit_cap": exit_cfg.take_profit_cap,
                    "spread": side_book.spread if side_book else None,
                },
            )
            if signal:
                return [signal]

        return []
