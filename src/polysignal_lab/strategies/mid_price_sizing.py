"""
MidPriceSizingStrategy — 中段价位马丁/反马丁仓位管理策略 (策略8)

核心逻辑:
- 在中段价位 (~0.45) 附近, 结合信号概率入场
- MARTINGALE 模式: 价格相对于持仓均价不利移动 >= adverse_step(0.05) 时加仓
- ANTI_MARTINGALE 模式: 价格相对于持仓均价有利移动 >= favorable_step(0.05) 时加仓
- max_layers = 3 硬约束, 不允许无限倍增
- stop_loss: bid <= 0.30 时止损; take_profit: bid >= 0.70 时止盈
"""

from __future__ import annotations

from enum import StrEnum
from statistics import mean
from typing import Any

from pydantic import BaseModel, Field

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.strategies.base import BaseStrategy


# ---------------------------------------------------------------------------
# 仓位管理模式枚举
# ---------------------------------------------------------------------------

class SizingMode(StrEnum):
    """仓位管理模式"""
    MARTINGALE = "MARTINGALE"
    # 价格向不利方向移动时加仓 (摊平成本)
    ANTI_MARTINGALE = "ANTI_MARTINGALE"
    # 价格向有利方向移动时加仓 (顺势加仓)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

class MidPriceSizingConfig(BaseModel):
    """中段价位马丁/反马丁仓位管理策略配置"""
    enabled: bool = True
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])

    # 仓位管理模式
    mode: SizingMode = SizingMode.MARTINGALE

    # 入场中心价位 & 范围
    entry_center: float = 0.45
    entry_band: float = 0.05

    # 基础名义金额 (USDC)
    base_notional: float = 5.0

    # 加仓步长 (价格差)
    adverse_step: float = 0.05      # 不利移动阈值
    favorable_step: float = 0.05    # 有利移动阈值

    # 最大加仓层数 (硬约束)
    max_layers: int = 3

    # 马丁格尔乘数 (capped, 非几何)
    martingale_multiplier: float = 1.0

    # 反马丁格尔乘数
    anti_martingale_multiplier: float = 1.5

    # 最小信号概率优势 (对 side 的置信度需求)
    min_signal_probability_edge: float = 0.03

    # 最高可接受买入价格
    max_price: float = 0.60

    # 止损 / 止盈价位
    stop_price: float = 0.30
    take_profit_price: float = 0.70


# ---------------------------------------------------------------------------
# 策略实现
# ---------------------------------------------------------------------------

class MidPriceSizingStrategy(BaseStrategy):
    """中段价位马丁/反马丁仓位管理策略

    在中段价位 (~0.45) 附近入场, 根据价格相对于持仓均价的变化,
    按马丁格尔 (不利方向加仓) 或反马丁格尔 (有利方向加仓) 模式管理仓位。

    追踪每个 (market_id, side) 的层数和入场均价的平均值。
    """

    name = "mid_price_sizing"

    def __init__(self, config: MidPriceSizingConfig):
        self.config = config
        # 层数追踪: key = f"{market_id}:{side.value}" -> int
        self._layer_count: dict[str, int] = {}
        # 入场均价追踪: key = f"{market_id}:{side.value}" -> list[float]
        # 每层的入场价格保存在列表中
        self._entry_prices: dict[str, list[float]] = {}

    # ------------------------------------------------------------------
    # 内部 key 构造
    # ------------------------------------------------------------------

    @staticmethod
    def _pos_key(market_id: str, side: Side) -> str:
        return f"{market_id}:{side.value}"

    def _avg_cost(self, key: str) -> float | None:
        """计算 (market_id, side) 的加权平均入场成本

        如果没有任何入场记录, 返回 None。
        """
        prices = self._entry_prices.get(key, [])
        if not prices:
            return None
        return mean(prices)

    # ------------------------------------------------------------------
    # 公开方法 (供外部重置用)
    # ------------------------------------------------------------------

    def reset_position(self, market_id: str, side: Side | None = None) -> None:
        """重置指定 (market_id, side) 或整个 market 的仓位状态"""
        if side is not None:
            key = self._pos_key(market_id, side)
            self._layer_count.pop(key, None)
            self._entry_prices.pop(key, None)
        else:
            for s in (Side.UP, Side.DOWN):
                key = self._pos_key(market_id, s)
                self._layer_count.pop(key, None)
                self._entry_prices.pop(key, None)

    # ------------------------------------------------------------------
    # 评估入口
    # ------------------------------------------------------------------

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        if not self.config.enabled:
            return []
        if snapshot.market.asset not in [a.upper() for a in self.config.assets]:
            return []
        if snapshot.market.timeframe not in self.config.timeframes:
            return []

        # --- Regime gate: 检查 ask 是否在中段、现货价是否有意义 ---
        signals = self._regime_gate(snapshot)
        if not signals:
            return []

        # 对于每个可能的 side (UP 和 DOWN), 分别评估
        result: list[SignalCandidate] = []
        for side in (Side.UP, Side.DOWN):
            sig = self._evaluate_side(snapshot, side)
            if sig:
                result.extend(sig)

        return result

    # ------------------------------------------------------------------
    # Regime gate
    # ------------------------------------------------------------------

    def _regime_gate(self, snapshot: MarketSnapshot) -> bool:
        """Regime gate: 整体市场环境检查

        条件:
        1. ask 在中段价位附近 (entry_center ± entry_band)
        2. 现货价格存在且有意义 (> 0)
        3. 收盘前有足够时间 (> 60s)
        """
        # 检查 UP/DOWN ask 是否在中段范围
        for side in (Side.UP, Side.DOWN):
            ask = snapshot.ask_for(side)
            if ask is None:
                return False
            if not (
                self.config.entry_center - self.config.entry_band
                <= ask
                <= self.config.entry_center + self.config.entry_band
            ):
                return False

        # 检查现货价格
        if snapshot.spot is None or snapshot.spot.price <= 0:
            return False

        # 检查剩余时间
        if snapshot.seconds_to_close is not None and snapshot.seconds_to_close < 60:
            return False

        return True

    # ------------------------------------------------------------------
    # 单侧评估
    # ------------------------------------------------------------------

    def _evaluate_side(
        self,
        snapshot: MarketSnapshot,
        side: Side,
    ) -> list[SignalCandidate]:
        market_id = snapshot.market.market_id
        key = self._pos_key(market_id, side)
        current_layers = self._layer_count.get(key, 0)
        current_avg = self._avg_cost(key)
        ask = snapshot.ask_for(side)
        bid = snapshot.bid_for(side)

        if ask is None or bid is None:
            return []

        # --- 检查止盈/止损 ---
        if current_layers > 0:
            if current_avg is not None:
                # 止损: 当前 bid 低于止损价位
                if bid <= self.config.stop_price:
                    return self._make_signal(
                        snapshot, side, ask, confidence=0.30,
                        reason_codes=["STOP_LOSS", f"BID_{bid:.4f}"],
                        metrics={
                            "action": "CLOSE_STOP_LOSS",
                            "current_layers": current_layers,
                            "avg_cost": current_avg,
                            "bid": bid,
                            "stop_price": self.config.stop_price,
                        },
                    )

                # 止盈: 当前 bid 高于止盈价位
                if bid >= self.config.take_profit_price:
                    return self._make_signal(
                        snapshot, side, ask, confidence=0.30,
                        reason_codes=["TAKE_PROFIT", f"BID_{bid:.4f}"],
                        metrics={
                            "action": "CLOSE_TAKE_PROFIT",
                            "current_layers": current_layers,
                            "avg_cost": current_avg,
                            "bid": bid,
                            "take_profit_price": self.config.take_profit_price,
                        },
                    )

        # --- 检查最大层数约束 ---
        if current_layers >= self.config.max_layers:
            return []

        # --- 入层逻辑 ---
        if current_layers == 0:
            # 第 0 层: 初始入场条件
            return self._evaluate_entry(snapshot, side, key, ask)

        # --- 加仓逻辑 (第 1, 2 层) ---
        if current_avg is not None:
            return self._evaluate_addition(snapshot, side, key, ask, current_layers, current_avg)

        return []

    # ------------------------------------------------------------------
    # 初始入场
    # ------------------------------------------------------------------

    def _evaluate_entry(
        self,
        snapshot: MarketSnapshot,
        side: Side,
        key: str,
        ask: float,
    ) -> list[SignalCandidate]:
        """初始入场条件检查"""
        if ask > self.config.entry_center + self.config.entry_band:
            # ask 超出中段入场范围, 不入场
            return []

        # 满足条件, 生成入场信号
        return self._make_signal(
            snapshot, side, ask, confidence=0.65,
            reason_codes=["ENTRY", f"LAYER_1_OF_{self.config.max_layers}"],
            metrics={
                "action": "ENTRY",
                "layer": 1,
                "max_layers": self.config.max_layers,
                "base_notional": self.config.base_notional,
                "entry_center": self.config.entry_center,
                "entry_band": self.config.entry_band,
            },
        )

    # ------------------------------------------------------------------
    # 加仓评估
    # ------------------------------------------------------------------

    def _evaluate_addition(
        self,
        snapshot: MarketSnapshot,
        side: Side,
        key: str,
        ask: float,
        current_layers: int,
        avg_cost: float,
    ) -> list[SignalCandidate]:
        """根据当前仓位均价决定是否加仓"""
        if self.config.mode == SizingMode.MARTINGALE:
            # 马丁格尔: 价格向不利方向移动 >= adverse_step
            price_move = ask - avg_cost  # 对于 BUY 仓位, 价格上涨是有利, 下跌是不利
            if side == Side.UP:
                # 对 UP 做多: ask 下降是不利方向 (我们买贵了)
                adverse_move = avg_cost - ask if ask < avg_cost else 0.0
            else:
                # 对 DOWN 做多: ask 上升是不利方向
                adverse_move = ask - avg_cost if ask > avg_cost else 0.0

            if adverse_move >= self.config.adverse_step:
                conf = min(
                    0.75,
                    0.55 + (adverse_move / (self.config.adverse_step * 3)) * 0.20,
                )
                return self._make_signal(
                    snapshot, side, ask, confidence=conf,
                    reason_codes=[
                        "MARTINGALE_ADD",
                        f"LAYER_{current_layers + 1}_OF_{self.config.max_layers}",
                    ],
                    metrics={
                        "action": "MARTINGALE_ADD",
                        "adverse_move": round(adverse_move, 4),
                        "adverse_step": self.config.adverse_step,
                        "avg_cost": avg_cost,
                        "current_layers": current_layers,
                        "layer": current_layers + 1,
                        "multiplier": self.config.martingale_multiplier,
                    },
                )

        elif self.config.mode == SizingMode.ANTI_MARTINGALE:
            # 反马丁格尔: 价格向有利方向移动 >= favorable_step
            if side == Side.UP:
                favorable_move = ask - avg_cost if ask > avg_cost else 0.0
            else:
                favorable_move = avg_cost - ask if ask < avg_cost else 0.0

            if favorable_move >= self.config.favorable_step:
                conf = min(
                    0.80,
                    0.60 + (favorable_move / (self.config.favorable_step * 3)) * 0.20,
                )
                return self._make_signal(
                    snapshot, side, ask, confidence=conf,
                    reason_codes=[
                        "ANTI_MARTINGALE_ADD",
                        f"LAYER_{current_layers + 1}_OF_{self.config.max_layers}",
                    ],
                    metrics={
                        "action": "ANTI_MARTINGALE_ADD",
                        "favorable_move": round(favorable_move, 4),
                        "favorable_step": self.config.favorable_step,
                        "avg_cost": avg_cost,
                        "current_layers": current_layers,
                        "layer": current_layers + 1,
                        "multiplier": self.config.anti_martingale_multiplier,
                    },
                )

        return []

    # ------------------------------------------------------------------
    # 信号构造
    # ------------------------------------------------------------------

    def _make_signal(
        self,
        snapshot: MarketSnapshot,
        side: Side,
        max_entry_price: float,
        confidence: float,
        reason_codes: list[str],
        metrics: dict[str, Any],
    ) -> list[SignalCandidate]:
        """构造信号并附加策略元数据"""
        signal = self._candidate(
            snapshot=snapshot,
            side=side,
            confidence=max(0.0, min(1.0, confidence)),
            max_entry_price=min(max_entry_price, self.config.max_price),
            reason_codes=reason_codes,
            metrics={
                **metrics,
                "mode": self.config.mode.value,
            },
        )
        return [signal] if signal else []
