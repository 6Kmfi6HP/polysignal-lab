"""OneCentBuyStrategy — 1c Buy 极端低价被动限价捕捉策略

在 YES/NO 两侧分别挂 0.01/0.02/0.03 的 post-only 限价买单,
成交后按 take_profit_ladder 设置止盈梯级。

Paper Trading 适配:
  - 通过 evaluate() 返回 SignalCandidate 表示入场意愿
  - 使用 self._submitted_levels 跟踪已提交的价位避免重复
  - 止盈信息在 metrics 中传递给 PaperExitEngine
"""

from __future__ import annotations

from dataclasses import dataclass, field

from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.readiness import StrategyReadiness


@dataclass
class OneCentBuyConfig:
    """OneCentBuyStrategy 配置"""

    entry_prices: tuple[float, ...] = (0.01, 0.02, 0.03)
    """每个侧要挂的买入限价层级"""

    shares_per_level: int = 10
    """每个价格级别的合约数量"""

    cancel_before_close_seconds: float = 20.0
    """到期前多少秒取消订单"""

    min_seconds_after_open: float = 0.0
    """入场时间窗口下限（市场开始后秒数）"""

    max_seconds_after_open: float = 280.0
    """入场时间窗口上限"""

    take_profit_ladder: list[tuple[float, float]] = field(
        default_factory=lambda: [(0.10, 0.50), (0.15, 1.00)]
    )
    """止盈梯级: [(price, cumulative_fraction)] — 价格达到 price 时卖出 cumulative_fraction 的持仓"""


class OneCentBuyStrategy(BaseStrategy):
    """极端低价被动限价捕捉策略

    核心逻辑:
      1. 对 YES/NO 两侧分别在 0.01/0.02/0.03 提交被动限价买单
      2. 仅当距到期还有一定时间且在入场窗口内时操作
      3. 每个价位仅提交一次（通过 _submitted_levels 跟踪）
      4. 成交后的止盈通过 metrics 中的 take_profit_ladder 传递给 PaperExitEngine
    """

    name = "one_cent_buy"

    def __init__(self, config: OneCentBuyConfig | None = None) -> None:
        self.config = config or OneCentBuyConfig()
        # {(market_id, side.value, price) → True} 记录已提交的价位
        self._submitted_levels: set[tuple[str, str, float]] = set()

    def reset(self) -> None:
        """重置状态（测试／重载用）"""
        self._submitted_levels.clear()

    @property
    def readiness(self) -> StrategyReadiness:
        return StrategyReadiness(
            name=self.name,
            production_enabled=bool(self.config.enabled),
            supported_assets=("BTC", "ETH", "SOL", "XRP"),
            supported_timeframes=("5m", "15m"),
            required_fields=("up_book", "down_book", "market_end_ts"),
            calibration_required=True,
            calibration_status="unknown",
        )

    def _elapsed_seconds(self, snapshot: MarketSnapshot) -> float | None:
        """计算自市场开始以来的秒数

        如果 start_ts 和 end_ts 均可用, 则计算 duration - seconds_to_close。
        否则返回 None（由调用方决定是否跳过）。
        """
        seconds_to_close = snapshot.seconds_to_close
        if seconds_to_close is None:
            return None
        if snapshot.market.start_ts is not None and snapshot.market.end_ts is not None:
            duration = (snapshot.market.end_ts - snapshot.market.start_ts).total_seconds()
            return duration - seconds_to_close
        return None

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        signals: list[SignalCandidate] = []

        seconds_to_close = snapshot.seconds_to_close
        if seconds_to_close is None:
            return []

        # 条件 1: 距到期必须大于 cancel_before_close_seconds
        if seconds_to_close <= self.config.cancel_before_close_seconds:
            return []

        # 条件 2: 入场时间窗口
        elapsed = self._elapsed_seconds(snapshot)
        if elapsed is None:
            return []
        if elapsed < self.config.min_seconds_after_open or elapsed > self.config.max_seconds_after_open:
            return []

        market_id = snapshot.market.market_id

        # 遍历 YES/NO 两侧
        for side in [Side.UP, Side.DOWN]:
            book = snapshot.book_for(side)
            if book is None or book.best_ask is None:
                continue

            for price in self.config.entry_prices:
                level_key = (market_id, side.value, price)
                if level_key in self._submitted_levels:
                    # 已提交过该价位, 跳过
                    continue

                # 挂单条件: 当前 ask 高于我们的入场价才有被动限价的意义
                # 如果 ask 已经低于或等于 price, 说明市场已在这个价位成交,
                # 我们不需要再挂单（或者应该追高, 但策略是被动的所以跳过）
                if book.best_ask <= price:
                    continue

                # 标记已提交
                self._submitted_levels.add(level_key)

                # 置信度: 越低价信心越高（极端价越可能被 fill）
                idx = self.config.entry_prices.index(price)
                confidence = 0.45 - 0.05 * idx  # 0.45, 0.40, 0.35

                signal = self._candidate(
                    snapshot=snapshot,
                    side=side,
                    confidence=confidence,
                    max_entry_price=price,
                    reason_codes=[
                        "ONE_CENT_BUY",
                        "PASSIVE_LIMIT",
                        f"LEVEL_{price:.2f}",
                    ],
                    metrics={
                        "limit_price": price,
                        "entry_level_index": idx,
                        "shares_per_level": self.config.shares_per_level,
                        "take_profit_ladder": str(self.config.take_profit_ladder),
                        "elapsed_sec": elapsed,
                        "seconds_to_close": seconds_to_close,
                        "best_ask": book.best_ask,
                        "best_bid": book.best_bid,
                    },
                    order_intent=OrderIntent.PASSIVE_GTD,
                    expiry_seconds=int(seconds_to_close - self.config.cancel_before_close_seconds),
                )
                if signal is not None:
                    signals.append(signal)

        return signals
