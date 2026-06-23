"""
PreOrderMarketStrategy — 预挂单盘前布局

核心逻辑:
  - 在 market.start_ts 前 seconds_before_open(180s) 时, 双边挂 0.45/0.40 限价买单
  - 订单设置为 GTD, expiration = start_ts + seconds_after_open_expiry(30s)
  - 开盘后 reconcile: 若只有一侧成交, 尝试 pair-or-exit
    - 如果 pair_effective_cost(leg_avg, opp_ask) <= 1.00, FAK 买入对侧
    - 否则 FAK 卖出现有持仓（由上层 position management 处理）
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy

# 交易费率常量
_FEE_RATE = 0.01
_SLIPPAGE_BUFFER = 0.01


class PreOrderMarketConfig(BaseModel):
    """PreOrderMarket 策略配置"""
    enabled: bool = True
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    # 在开盘前多少秒开始挂单
    seconds_before_open: float = 180.0
    # 开盘后多少秒订单到期
    seconds_after_open_expiry: float = 30.0
    # 挂单价格和数量阶梯: [(price, shares), ...]
    ladder: list[tuple[float, int]] = Field(default_factory=lambda: [(0.45, 5), (0.40, 5)])
    # 对冲时的 pair cost 上限
    pair_cost_cap: float = 0.98
    # reconcile 时接受的最大 pair cost（用于 decide pair-or-exit）
    reconcile_max_pair_cost: float = 1.00


class PreOrderMarketStrategy(BaseStrategy):
    """预挂单盘前布局策略

    在 market.start_ts 前 seconds_before_open(180s) 时, 在 YES/NO 两侧
    同时挂 GTD 限价买单（如 0.45 和 0.40）。开盘后若仅一侧成交，
    尝试在对侧成本合理时买入对冲，否则由上层 PositionManager 处理退出。
    """

    name = "pre_order_market"

    def __init__(self, config: PreOrderMarketConfig):
        self.config = config
        # 已预挂单的市场集合 set[market_id]
        self._pre_ordered: set[str] = set()
        # 已入场市场集合 set[market_id]
        self._entered_markets: set[str] = set()
        # 单腿持仓状态: market_id -> {side, entry_price, filled_at, hedged}
        self._positions: dict[str, dict[str, Any]] = {}
        # 开盘后已经过 reconcile 的市场
        self._reconciled: set[str] = set()

    def notify_fill(self, market_id: str, side: Side, fill_price: float, shares: float) -> None:
        position = self._positions.get(market_id)
        if position is not None:
            if position["side"] != side:
                position["hedged"] = True
                self._entered_markets.add(market_id)
            return
        self._positions[market_id] = {
            "side": side,
            "entry_price": fill_price,
            "filled_at": self._utc_now(),
            "hedged": False,
        }
        self._entered_markets.add(market_id)

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

    def _has_started(self, snapshot: MarketSnapshot) -> bool:
        """检查市场是否已开盘（start_ts <= now）"""
        start_ts = snapshot.market.start_ts
        if start_ts is None:
            return True  # 没有 start_ts 的市场视为已开盘
        return self._utc_now() >= start_ts

    def _is_in_pre_order_window(self, snapshot: MarketSnapshot) -> bool:
        """检查是否在预挂单窗口内

        窗口 = [start_ts - seconds_before_open, start_ts + seconds_after_open_expiry)
        """
        start_ts = snapshot.market.start_ts
        if start_ts is None:
            return False  # 没有 start_ts 的市场无法预挂单
        now = self._utc_now()
        window_start = start_ts.timestamp() - self.config.seconds_before_open
        window_end = start_ts.timestamp() + self.config.seconds_after_open_expiry
        now_ts = now.timestamp()
        return window_start <= now_ts < window_end

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

        # === 步骤 1: 如果已有单腿持仓, 尝试开盘后 reconcile ===
        position = self._positions.get(market_id)
        if position and not position.get("hedged", False):
            return self._reconcile_after_open(snapshot, market_id, position)

        # 已完全入场 / 已预挂单, 不再重复
        if market_id in self._entered_markets:
            return []

        # === 步骤 2: 检查是否在预挂单窗口内 ===
        if not self._is_in_pre_order_window(snapshot):
            return []

        # 防止重复发单
        if market_id in self._pre_ordered:
            return []

        # === 步骤 3: 双边预挂单 ===
        self._pre_ordered.add(market_id)
        signals: list[SignalCandidate] = []
        now = self._utc_now()

        for price, shares in self.config.ladder:
            for side in (Side.UP, Side.DOWN):
                # 确保价格是有效的被动限价单（低于当前 ask）
                ask = snapshot.ask_for(side)
                if ask is not None and price >= ask:
                    continue

                # 计算该 pair 的有效成本
                cost = self._pair_effective_cost(price, price)

                signal = self._candidate(
                    snapshot=snapshot,
                    side=side,
                    confidence=0.55,
                    max_entry_price=price,
                    reason_codes=[
                        "PRE_ORDER_BID",
                        f"PRICE_{price}",
                    ],
                    metrics={
                        "pair_cost": round(cost, 4),
                        "expiry_after_open": round(self.config.seconds_after_open_expiry),
                        "pre_order_shares": shares,
                        "expiry_ts": snapshot.market.start_ts.timestamp() + self.config.seconds_after_open_expiry,
                    },
                    order_intent=OrderIntent.PASSIVE_GTD,
                    expiry_seconds=int(max(0.0, (snapshot.market.start_ts - now).total_seconds()) + self.config.seconds_after_open_expiry),
                    pair_id=f"{market_id}:pre",
                )
                if signal:
                    signals.append(signal)

        return signals

    # ------------------------------------------------------------------
    # 开盘后 reconcile
    # ------------------------------------------------------------------

    def _reconcile_after_open(
        self,
        snapshot: MarketSnapshot,
        market_id: str,
        position: dict[str, Any],
    ) -> list[SignalCandidate]:
        """开盘后只有一侧成交时, 尝试 pair-or-exit

        - 如果 pair_effective_cost(leg_avg, opp_ask) <= reconcile_max_pair_cost,
          FAK 买入对侧
        - 否则不发出买入信号（由上层管理退出）
        """
        if market_id in self._reconciled:
            return []

        filled_side: Side = position["side"]
        hedge_side: Side = filled_side.opposite
        filled_price: float = position["entry_price"]

        hedge_ask = snapshot.ask_for(hedge_side)
        if hedge_ask is None:
            return []

        cost = self._pair_effective_cost(filled_price, hedge_ask)

        # 只有成本 <= reconcile_max_pair_cost 时才买入对侧
        if cost > self.config.reconcile_max_pair_cost:
            self._reconciled.add(market_id)
            return []

        self._reconciled.add(market_id)
        signal = self._candidate(
            snapshot=snapshot,
            side=hedge_side,
            confidence=0.55,
            max_entry_price=hedge_ask,
            reason_codes=[
                "PRE_ORDER_RECONCILE",
                f"HEDGE_{hedge_side.value}",
            ],
            metrics={
                "pair_cost": round(cost, 4),
                "reconcile_max_pair_cost": self.config.reconcile_max_pair_cost,
                "filled_leg_price": filled_price,
                "hedge_ask": hedge_ask,
            },
            order_intent=OrderIntent.TAKER_FAK,
            pair_id=f"{market_id}:pre",
            hedge_leg=True,
        )
        return [signal] if signal else []
