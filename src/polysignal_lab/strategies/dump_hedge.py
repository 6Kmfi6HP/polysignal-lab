"""
DumpHedgeStrategy — 急跌对冲

核心逻辑:
  - 第一阶段: 检测某侧 token 在 lookback_seconds(30s) 内跌幅 >= move_threshold(15%)
  - 检测窗口: 开盘后 detection_window_minutes(5min) 内
  - 检测到 dump 后: FAK 买入被抛售侧
  - 第二阶段: 在满足 pair_cost_cap(0.95) 时 FAK 买入对侧
  - 止损: 超过 stop_loss_max_wait_seconds(90s) 后, 以 stop_loss_pair_cap(1.05) 强平
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy, RollingPriceStats

# 交易费率常量（用于 pair_effective_cost 计算）
_FEE_RATE = 0.01
_SLIPPAGE_BUFFER = 0.01


class DumpHedgeConfig(BaseModel):
    """DumpHedge 策略配置"""
    enabled: bool = True
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    # 暴跌检测阈值（百分比 0.15 = 15%）
    move_threshold: float = 0.15
    # 回看窗口（秒）
    lookback_seconds: float = 30.0
    # 仅开盘后 detection_window_minutes 分钟内检测 dump
    detection_window_minutes: float = 5.0
    # 每腿买入股数
    leg_shares: int = 10
    # 对冲时的 pair cost 上限
    pair_cost_cap: float = 0.95
    # 最长等待对侧的秒数，超时后强平
    stop_loss_max_wait_seconds: float = 90.0
    # 止损强平时的 pair cost 上限
    stop_loss_pair_cap: float = 1.05


class DumpHedgeStrategy(BaseStrategy):
    """急跌对冲策略

    开盘窗口内检测某侧 token 的急跌事件（回看 30s 跌幅 >= 15%），
    发现后 FAK 买入该侧。然后在对侧成本合理时补对侧对冲，
    超时则强平止损。
    """

    name = "dump_hedge"

    def __init__(self, config: DumpHedgeConfig):
        self.config = config
        # 滚动价格统计（窗口 16 笔就够了，时间窗口由调用方控制频率）
        self._price_stats = RollingPriceStats(window_size=16)
        # 已入场市场集合 set[market_id]
        self._entered_markets: set[str] = set()
        # 单腿持仓状态: market_id -> {side, entry_price, filled_at, hedged}
        self._positions: dict[str, dict[str, Any]] = {}
        # 已检测到 dump 的市场（避免重复触发）
        self._dump_detected: set[str] = set()
        # 每 token 最近一次 push 的价格缓存（用于计算变动幅度）
        self._last_price: dict[str, float] = {}

    # ------------------------------------------------------------------
    # 辅助计算
    # ------------------------------------------------------------------

    @staticmethod
    def _pair_effective_cost(leg1_price: float, leg2_price: float) -> float:
        """计算双边组合有效成本 = leg1 + leg2 + 2*fee + slippage_buffer"""
        return (
            leg1_price
            + leg2_price
            + 2.0 * _FEE_RATE
            + _SLIPPAGE_BUFFER
        )

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _is_in_detection_window(self, snapshot: MarketSnapshot) -> bool:
        """检查是否在开盘后检测窗口内"""
        start_ts = snapshot.market.start_ts
        if start_ts is None:
            return False
        now = self._utc_now()
        elapsed = (now - start_ts).total_seconds()
        window_sec = self.config.detection_window_minutes * 60.0
        return 0 <= elapsed <= window_sec

    # ------------------------------------------------------------------
    # 核心评估
    # ------------------------------------------------------------------

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        if not self.config.enabled:
            return []
        if snapshot.market.asset not in [a.upper() for a in self.config.assets]:
            return []
        if snapshot.market.timeframe not in self.config.timeframes:
            return []

        market_id = snapshot.market.market_id

        # === 步骤 1: 如果已有单腿持仓, 尝试对冲或止损 ===
        position = self._positions.get(market_id)
        if position and not position.get("hedged", False):
            return self._try_hedge_or_stop(snapshot, market_id, position)

        # 已入场且已完全对冲, 不再产生新信号
        if market_id in self._entered_markets:
            return []

        # === 步骤 2: 更新价格统计 ===
        for side in (Side.UP, Side.DOWN):
            token = snapshot.market.token_for(side)
            key = token.token_id
            ask = snapshot.ask_for(side)
            if ask is not None:
                self._price_stats.push(key, ask, size=1.0)
                self._last_price[key] = ask

        # === 步骤 3: 检测急跌事件（仅检测窗口内） ===
        if not self._is_in_detection_window(snapshot):
            return []

        if market_id in self._dump_detected:
            return []

        signals: list[SignalCandidate] = []

        for side in (Side.UP, Side.DOWN):
            token = snapshot.market.token_for(side)
            key = token.token_id
            stats = self._price_stats.stats(key)
            if stats["count"] < 2:
                continue

            vwap = stats["vwap"]
            current_ask = snapshot.ask_for(side)
            if vwap is None or current_ask is None or vwap == 0:
                continue

            # 计算相对 vwap 的跌幅
            drop_ratio = (vwap - current_ask) / vwap
            if drop_ratio >= self.config.move_threshold:
                self._dump_detected.add(market_id)
                signal = self._candidate(
                    snapshot=snapshot,
                    side=side,
                    confidence=0.75,
                    max_entry_price=current_ask,
                    reason_codes=[
                        "DUMP_DETECTED",
                        f"DROP_{drop_ratio:.1%}",
                        f"SIDE_{side.value}",
                    ],
                    metrics={
                        "vwap": round(vwap, 4),
                        "current_ask": round(current_ask, 4),
                        "drop_ratio": round(drop_ratio, 4),
                        "move_threshold": self.config.move_threshold,
                        "shares": self.config.leg_shares,
                    },
                )
                if signal:
                    signals.append(signal)

        return signals

    # ------------------------------------------------------------------
    # 对冲 / 止损
    # ------------------------------------------------------------------

    def _try_hedge_or_stop(
        self,
        snapshot: MarketSnapshot,
        market_id: str,
        position: dict[str, Any],
    ) -> list[SignalCandidate]:
        """单腿持仓后尝试 FAK 买入对侧对冲, 超时则强平止损"""
        now = self._utc_now()
        filled_side: Side = position["side"]
        hedge_side: Side = filled_side.opposite
        filled_price: float = position["entry_price"]
        filled_at: datetime = position["filled_at"]
        elapsed = (now - filled_at).total_seconds()
        signals: list[SignalCandidate] = []

        hedge_ask = snapshot.ask_for(hedge_side)

        # --- 方案 A: 对侧成本合理, 直接对冲 ---
        if hedge_ask is not None:
            cost = self._pair_effective_cost(filled_price, hedge_ask)
            if cost <= self.config.pair_cost_cap:
                signal = self._candidate(
                    snapshot=snapshot,
                    side=hedge_side,
                    confidence=0.70,
                    max_entry_price=hedge_ask,
                    reason_codes=[
                        "DUMP_HEDGE",
                        f"HEDGE_{hedge_side.value}",
                    ],
                    metrics={
                        "pair_cost": round(cost, 4),
                        "pair_cost_cap": self.config.pair_cost_cap,
                        "filled_leg_price": filled_price,
                        "hedge_ask": hedge_ask,
                        "elapsed_seconds": round(elapsed, 2),
                    },
                )
                if signal:
                    signals.append(signal)

        # --- 方案 B: 超时强平止损 ---
        if elapsed >= self.config.stop_loss_max_wait_seconds:
            stop_ask = snapshot.ask_for(hedge_side)
            if stop_ask is not None:
                cost = self._pair_effective_cost(filled_price, stop_ask)
                if cost <= self.config.stop_loss_pair_cap:
                    signal = self._candidate(
                        snapshot=snapshot,
                        side=hedge_side,
                        confidence=0.50,
                        max_entry_price=stop_ask,
                        reason_codes=[
                            "DUMP_HEDGE_STOP_LOSS",
                            f"WAITED_{elapsed:.0f}s",
                        ],
                        metrics={
                            "pair_cost": round(cost, 4),
                            "stop_loss_cap": self.config.stop_loss_pair_cap,
                            "filled_leg_price": filled_price,
                            "elapsed_seconds": round(elapsed, 2),
                        },
                    )
                    if signal:
                        signals.append(signal)

        return signals
