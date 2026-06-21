"""NinetyNineCentSniperStrategy — 99c Sniper 临近结算高概率狙击策略

在到期前短时间窗口内（默认 ≤ 90s）, 当外部概率 ≥ 0.995 且 Token 卖价 ≤ 0.99 时,
使用 FAK 立即买入近乎确定的结算结果。

Paper Trading 适配:
  - 通过 evaluate() 返回 SignalCandidate
  - 使用 _sniped_markets 跟踪已狙击的市场侧避免重复
  - 止损逻辑（若 best_bid ≤ stop_price 则不再生成新信号）
"""

from __future__ import annotations

from dataclasses import dataclass

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy


@dataclass
class NinetyNineCentSniperConfig:
    """NinetyNineCentSniperStrategy 配置"""

    max_entry_price: float = 0.99
    """最大入场价格 — 仅当 best_ask ≤ 此值时入场"""

    min_external_probability: float = 0.995
    """最小外部概率 — 确认结算几乎确定"""

    min_seconds_before_close: float = 0.0
    """狙击时间窗口下限（到期前秒数）"""

    max_seconds_before_close: float = 90.0
    """狙击时间窗口上限"""

    max_notional_per_trade: float = 25.0
    """每笔最大名义金额（USD）"""

    stop_price: float = 0.94
    """止损价格 — 若 best_bid ≤ 此值则不再入场"""

    require_effectively_settled: bool = True
    """需要外部确认事件已近乎确定"""


class NinetyNineCentSniperStrategy(BaseStrategy):
    """临近结算高概率狙击策略

    核心逻辑:
      1. 在到期前最后 N 秒内扫描市场
      2. 当 Token 卖价 ≤ 0.99 且外部概率 ≥ 0.995 时入场
      3. 如果 require_effectively_settled 为 True, 额外验证对侧价格也已极端
      4. 每个市场侧仅狙击一次
      5. 如果 best_bid 已跌破止损价, 认为风险过高, 不再入场
    """

    name = "ninety_nine_cent_sniper"

    def __init__(self, config: NinetyNineCentSniperConfig | None = None) -> None:
        self.config = config or NinetyNineCentSniperConfig()
        # {(market_id, side.value) → True} 记录已狙击的市场侧
        self._sniped_markets: set[tuple[str, str]] = set()

    def reset(self) -> None:
        """重置状态（测试用）"""
        self._sniped_markets.clear()

    def _get_external_probability(
        self, snapshot: MarketSnapshot, side: Side
    ) -> float | None:
        """获取外部概率估算

        优先级:
          1. snapshot.metrics['external_probability'] — 外部系统提供的概率
          2. snapshot.metrics['spot_price'] — 可用的现货参考价
          3. 订单簿 midpoint — 市场隐含概率
        """
        # 尝试 metrics 中的外部概率
        prob = snapshot.metrics.get("external_probability")
        if prob is not None:
            return float(prob)

        # 尝试从订单簿 midpoint 估算
        book = snapshot.book_for(side)
        if book is not None and book.mid is not None:
            return book.mid

        return None

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        signals: list[SignalCandidate] = []

        seconds_to_close = snapshot.seconds_to_close
        if seconds_to_close is None:
            return []

        # 条件 1: 时间窗口检查
        if not (
            self.config.min_seconds_before_close
            <= seconds_to_close
            <= self.config.max_seconds_before_close
        ):
            return []

        market_id = snapshot.market.market_id

        # 遍历 YES/NO 两侧
        for side in [Side.UP, Side.DOWN]:
            side_key = (market_id, side.value)

            # 已狙击过该侧, 跳过
            if side_key in self._sniped_markets:
                continue

            book = snapshot.book_for(side)
            if book is None or book.best_ask is None:
                continue

            # 条件 2: 卖价 ≤ 最大入场价格
            if book.best_ask > self.config.max_entry_price:
                continue

            # 条件 3: 外部概率 ≥ 最小值
            prob = self._get_external_probability(snapshot, side)
            if prob is None or prob < self.config.min_external_probability:
                continue

            # 条件 4: 止损检查 — 如果 best_bid 已经跌破止损价, 风险过高
            if book.best_bid is not None and book.best_bid <= self.config.stop_price:
                continue

            # 条件 5: 验证有效确定 (require_effectively_settled)
            if self.config.require_effectively_settled:
                # 检查对侧卖价是否也极端（确认市场共识一致）
                opposite_side = side.opposite
                opp_book = snapshot.book_for(opposite_side)
                if opp_book is None or opp_book.best_ask is None:
                    continue
                # 对侧卖价应该非常低（接近 0）, 表明共识一致
                if opp_book.best_ask > 0.05:
                    continue

            # 所有条件满足 — 狙击
            self._sniped_markets.add(side_key)

            signal = self._candidate(
                snapshot=snapshot,
                side=side,
                confidence=0.96,  # 高置信度 — 近乎确定的交易
                max_entry_price=min(
                    self.config.max_entry_price, book.best_ask * 1.01
                ),
                reason_codes=[
                    "NINETY_NINE_SNIPE",
                    "EFFECTIVELY_SETTLED",
                    "HIGH_PROBABILITY",
                ],
                metrics={
                    "best_ask": book.best_ask,
                    "best_bid": book.best_bid,
                    "midpoint": book.mid,
                    "external_probability": prob,
                    "seconds_to_close": seconds_to_close,
                    "max_notional": self.config.max_notional_per_trade,
                    "stop_price": self.config.stop_price,
                    "require_effectively_settled": self.config.require_effectively_settled,
                    "opposite_ask": opp_book.best_ask if self.config.require_effectively_settled else None,
                },
            )
            if signal is not None:
                signals.append(signal)

        return signals
