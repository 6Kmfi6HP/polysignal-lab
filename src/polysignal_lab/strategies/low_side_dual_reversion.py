"""
LowSideDualReversionStrategy — 弱势双边均值回归 (pair-cost)

核心逻辑:
  - 在 YES/NO 两侧同时挂 0.35/0.40/0.45 的被动 GTD 限价买单
  - 只有 pair_effective_cost(y_bid, n_bid) <= pair_cost_cap(0.98) 的组合才挂单
  - 一腿成交后, 若对侧深度加权 ask 使 pair cost <= cap, 立即 FAK 买入对侧
  - 超时 watchdog: 若 max_unhedged_seconds(20s) 内未补对侧, 在 stop_loss_hedge_cap(1.03) 下强平
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy


class LowSideDualReversionConfig(BaseModel):
    """LowSideDualReversion 策略配置"""
    enabled: bool = True
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    # 被动买单价格阶梯
    bid_prices: tuple[float, ...] = (0.35, 0.40, 0.45)
    # 每层挂单数量
    shares_per_level: int = 5
    # 双边组合有效成本上限
    pair_cost_cap: float = 0.98
    # 最长单腿持仓时间（秒），超时触发强平
    max_unhedged_seconds: float = 20.0
    # 止损强平时的 pair_cost 上限
    stop_loss_hedge_cap: float = 1.03
    # 收盘前多久取消所有挂单
    cancel_before_close_seconds: float = 15.0
    # 交易费率（用于 pair_effective_cost 计算）
    fee_rate: float = 0.01
    # 滑点缓冲（用于 pair_effective_cost 计算）
    slippage_buffer: float = 0.01


class LowSideDualReversionStrategy(BaseStrategy):
    """弱势双边均值回归策略 (pair-cost)

    在 YES/NO 两侧同时挂被动 GTD 限价买单（0.35/0.40/0.45），
    仅当 pair_effective_cost <= pair_cost_cap(0.98) 时才挂单。
    一腿成交后通过深度加权 ask 即时补对侧，超时则强平止损。
    """

    name = "low_side_dual_reversion"

    def __init__(self, config: LowSideDualReversionConfig):
        self.config = config
        # 已入场市场集合 set[market_id]
        self._entered_markets: set[str] = set()
        # 单腿持仓状态: market_id -> {side, entry_price, filled_at, hedged}
        self._positions: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # 辅助计算
    # ------------------------------------------------------------------

    def _pair_effective_cost(self, leg1_price: float, leg2_price: float) -> float:
        """计算双边组合有效成本 = leg1 + leg2 + 2*fee + slippage_buffer"""
        return (
            leg1_price
            + leg2_price
            + 2.0 * self.config.fee_rate
            + self.config.slippage_buffer
        )

    def _depth_weighted_ask(self, book, shares: int) -> float | None:
        """获取深度加权平均 ask 价格（买入 shares 股所需的平均成交价）

        从最优 ask 开始逐层累计, 返回平均买入成本。
        如果深度不足以买入 shares 股, 返回 None。
        """
        if not book or not book.asks:
            return None
        remaining = shares
        total_cost = 0.0
        for level in sorted(book.asks, key=lambda x: x.price):
            take = min(remaining, level.size)
            total_cost += take * level.price
            remaining -= take
            if remaining <= 0:
                break
        if remaining > 0:
            return None  # 深度不足
        return total_cost / shares

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

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

        # === 步骤 1: 如果已有单腿持仓, 尝试补对侧或止损 ===
        position = self._positions.get(market_id)
        if position and not position.get("hedged", False):
            return self._try_hedge(snapshot, market_id, position)

        # === 步骤 2: 收盘前取消窗口 — 不产生新信号 ===
        if (
            snapshot.seconds_to_close is not None
            and snapshot.seconds_to_close <= self.config.cancel_before_close_seconds
        ):
            return []

        # 已入场且已完全对冲, 不再重复信号
        if market_id in self._entered_markets:
            return []

        # === 步骤 3: 搜索最优可挂单价位 ===
        signals: list[SignalCandidate] = []
        best_cost = float("inf")
        best_price: float | None = None

        for bid_price in self.config.bid_prices:
            cost = self._pair_effective_cost(bid_price, bid_price)
            if cost > self.config.pair_cost_cap:
                continue

            # 确保是被动买单（bid 低于当前 ask）
            up_ask = snapshot.ask_for(Side.UP)
            down_ask = snapshot.ask_for(Side.DOWN)
            if up_ask is not None and bid_price >= up_ask:
                continue
            if down_ask is not None and bid_price >= down_ask:
                continue

            if cost < best_cost:
                best_cost = cost
                best_price = bid_price

        if best_price is None:
            return []

        # 生成双边信号
        for side in (Side.UP, Side.DOWN):
            signal = self._candidate(
                snapshot=snapshot,
                side=side,
                confidence=0.60,
                max_entry_price=best_price,
                reason_codes=[
                    "DUAL_REVERSION_BID",
                    f"PRICE_{best_price}",
                ],
                metrics={
                    "pair_cost": round(best_cost, 4),
                    "pair_cost_cap": self.config.pair_cost_cap,
                    "bid_price": best_price,
                    "shares": self.config.shares_per_level,
                },
            )
            if signal:
                signals.append(signal)

        return signals

    # ------------------------------------------------------------------
    # 对冲 / 止损
    # ------------------------------------------------------------------

    def _try_hedge(
        self,
        snapshot: MarketSnapshot,
        market_id: str,
        position: dict[str, Any],
    ) -> list[SignalCandidate]:
        """单腿持仓后尝试补对侧对冲, 超时则强平止损"""
        now = self._utc_now()
        filled_side: Side = position["side"]
        hedge_side: Side = filled_side.opposite
        filled_price: float = position["entry_price"]
        filled_at: datetime = position["filled_at"]
        elapsed = (now - filled_at).total_seconds()

        signals: list[SignalCandidate] = []

        # --- 方案 A: 深度加权 ask 对冲 ---
        hedge_book = snapshot.book_for(hedge_side)
        depth_ask = self._depth_weighted_ask(hedge_book, self.config.shares_per_level)
        if depth_ask is not None:
            cost = self._pair_effective_cost(filled_price, depth_ask)
            if cost <= self.config.pair_cost_cap:
                signal = self._candidate(
                    snapshot=snapshot,
                    side=hedge_side,
                    confidence=0.70,
                    max_entry_price=depth_ask,
                    reason_codes=[
                        "DUAL_REVERSION_HEDGE",
                        f"HEDGE_{hedge_side.value}",
                    ],
                    metrics={
                        "pair_cost": round(cost, 4),
                        "pair_cost_cap": self.config.pair_cost_cap,
                        "filled_leg_price": filled_price,
                        "hedge_weighted_ask": depth_ask,
                        "elapsed_seconds": round(elapsed, 2),
                    },
                )
                if signal:
                    signals.append(signal)

        # --- 方案 B: 超时强平止损 ---
        if elapsed >= self.config.max_unhedged_seconds:
            stop_ask = snapshot.ask_for(hedge_side)
            if stop_ask is not None:
                cost = self._pair_effective_cost(filled_price, stop_ask)
                if cost <= self.config.stop_loss_hedge_cap:
                    signal = self._candidate(
                        snapshot=snapshot,
                        side=hedge_side,
                        confidence=0.50,
                        max_entry_price=stop_ask,
                        reason_codes=[
                            "DUAL_REVERSION_STOP_LOSS",
                            f"UNHEDGED_{elapsed:.0f}s",
                        ],
                        metrics={
                            "pair_cost": round(cost, 4),
                            "stop_loss_cap": self.config.stop_loss_hedge_cap,
                            "filled_leg_price": filled_price,
                            "elapsed_seconds": round(elapsed, 2),
                        },
                    )
                    if signal:
                        signals.append(signal)

        return signals
