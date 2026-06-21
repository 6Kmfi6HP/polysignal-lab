"""
FibonacciStrategyBot — 斐波那契回撤策略 (策略9)

核心逻辑:
- 使用 ZigZag 百分比阈值识别 swing high/low
- 根据 Swing 计算 Fibonacci 回撤位 (23.6%/38.2%/50%/61.8%/78.6%)
- 现货价格进入 Fibonacci zone 时买入对应 Up/Down token
- 需要动量确认: require_momentum_confirmation = True
- 仓位权重按 Fibonacci 数列分配
"""

from __future__ import annotations

from collections import deque
from typing import Any

from pydantic import BaseModel, Field

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.strategies.base import BaseStrategy, RollingPriceStats


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

class FibonacciBotConfig(BaseModel):
    """斐波那契回撤策略配置"""
    enabled: bool = True
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])

    # ZigZag 百分比阈值: 价格变动超过此阈值才被认定为 swing 点
    zigzag_pct: float = 0.005

    # 回撤区间的宽度比例 (用于判断价格是否进入斐波那契 zone)
    zone_width_pct: float = 0.001

    # 斐波那契回撤比率
    ratios: tuple[float, ...] = (0.236, 0.382, 0.500, 0.618, 0.786)

    # 斐波那契扩展比率 (用于扩展趋势目标)
    extension_ratios: tuple[float, ...] = (1.000, 1.272, 1.618)

    # 仓位权重分配 (斐波那契数列: 1, 1, 2, 3, 5)
    fib_size_weights: tuple[int, ...] = (1, 1, 2, 3, 5)

    # token 最高可接受买入价格
    max_token_price: float = 0.60

    # 单笔最大名义金额
    max_notional: float = 25.0

    # 是否需要动量确认
    require_momentum_confirmation: bool = True

    # 动量确认窗口 (多少个价格点)
    momentum_window: int = 8

    # 最小动量阈值 (z-score 绝对值)
    min_momentum_zscore: float = 1.0

    # 回撤位到 token 价格的映射偏移系数
    # token_ask ≈ fib_level + offset 时触发
    offset_from_fib: float = 0.02


# ---------------------------------------------------------------------------
# ZigZag 检测器
# ---------------------------------------------------------------------------

class ZigZagDetector:
    """基于百分比阈值的 ZigZag 高低点检测器

    追踪价格序列的趋势方向变化, 当价格反转幅度超过 zigzag_pct 时,
    记录上一个趋势极值点为 swing high 或 swing low.
    """

    def __init__(self, threshold_pct: float):
        self.threshold_pct = threshold_pct
        self._prices: deque[float] = deque(maxlen=200)
        self._swing_highs: deque[float] = deque(maxlen=10)
        self._swing_lows: deque[float] = deque(maxlen=10)
        # 当前趋势方向: 'up' 或 'down'
        self._current_trend: str | None = None
        # 当前趋势中的极值价格
        self._extreme_price: float | None = None

    def push(self, price: float) -> None:
        """输入新价格, 更新 swing 点"""
        self._prices.append(price)
        n = len(self._prices)
        if n < 2:
            return

        # --- 初始化趋势方向 ---
        if n == 2:
            self._current_trend = 'up' if price > self._prices[0] else 'down'
            self._extreme_price = price
            return

        # --- 判断方向变化 ---
        prev = self._prices[-2]
        if price > prev:
            new_direction = 'up'
        elif price < prev:
            new_direction = 'down'
        else:
            return  # 价格未变, 跳过

        if new_direction == self._current_trend:
            # 同方向: 更新极值
            if (new_direction == 'up' and price > self._extreme_price) or \
               (new_direction == 'down' and price < self._extreme_price):
                self._extreme_price = price
        else:
            # 方向反转: 检查是否超过阈值
            if self._extreme_price is not None and self._extreme_price > 0:
                change_pct = abs(price - self._extreme_price) / self._extreme_price
                if change_pct >= self.threshold_pct:
                    # 记录上一个极值为 swing 点
                    if self._current_trend == 'up':
                        self._swing_highs.append(self._extreme_price)
                    else:
                        self._swing_lows.append(self._extreme_price)

                    # 切换到新趋势
                    self._current_trend = new_direction
                    self._extreme_price = price

    def _finalize_last_extreme(self) -> None:
        """(公开辅助) 如果当前趋势的极值尚未录为 swing 点, 强制结束。

        通常在策略 evaluate 时调用, 确保最近趋势被记录。
        """
        if self._current_trend is None or self._extreme_price is None:
            return
        # 检查是否已经是最新 swing
        if self._current_trend == 'up':
            if not self._swing_highs or self._extreme_price != self._swing_highs[-1]:
                self._swing_highs.append(self._extreme_price)
        else:
            if not self._swing_lows or self._extreme_price != self._swing_lows[-1]:
                self._swing_lows.append(self._extreme_price)

    @property
    def high(self) -> float | None:
        """最近的一个 swing high"""
        return self._swing_highs[-1] if self._swing_highs else None

    @property
    def lows(self) -> deque[float]:
        return self._swing_lows

    @property
    def highs(self) -> deque[float]:
        return self._swing_highs

    @property
    def low(self) -> float | None:
        """最近的一个 swing low"""
        return self._swing_lows[-1] if self._swing_lows else None

    def has_swing(self) -> bool:
        """是否已检测到足够的 swing 点用于斐波那契计算"""
        return bool(self._swing_highs) and bool(self._swing_lows)

    def current_swing_high(self) -> float | None:
        """最近一个有效的 swing high (用于下跌趋势)"""
        return self._swing_highs[-1] if self._swing_highs else None

    def current_swing_low(self) -> float | None:
        """最近一个有效的 swing low (用于上涨趋势)"""
        return self._swing_lows[-1] if self._swing_lows else None

    def last_was_up(self) -> bool | None:
        """最近 swing 方向是否为向上 (swing high)"""
        if not self._swing_highs and not self._swing_lows:
            return None
        if self._swing_highs and not self._swing_lows:
            return True
        if self._swing_lows and not self._swing_highs:
            return False
        # 比较最近的两个 swing 点
        last_high_time = 0
        last_low_time = 0
        # 由于我们只有 swing 点, 检查 _current_trend
        return self._current_trend == 'up'


# ---------------------------------------------------------------------------
# 斐波那契计算器
# ---------------------------------------------------------------------------

class FibonacciCalculator:
    """根据 swing high/low 计算斐波那契回撤位"""

    def __init__(self, ratios: tuple[float, ...]):
        self.ratios = ratios

    def retracement_levels(
        self,
        swing_high: float,
        swing_low: float,
    ) -> dict[float, float]:
        """计算从 swing_low 到 swing_high 的斐波那契回撤价位

        格式: {ratio: price_level}
        """
        diff = swing_high - swing_low
        if diff <= 0:
            return {}
        return {
            ratio: swing_high - ratio * diff
            for ratio in self.ratios
        }

    def extension_levels(
        self,
        swing_high: float,
        swing_low: float,
        extension_ratios: tuple[float, ...],
    ) -> dict[float, float]:
        """计算斐波那契扩展价位 (向上突破用)"""
        diff = swing_high - swing_low
        if diff <= 0:
            return {}
        return {
            ratio: swing_high + (ratio - 1.0) * diff
            for ratio in extension_ratios
        }

    @staticmethod
    def is_in_zone(
        current_price: float,
        fib_level_price: float,
        zone_width_pct: float,
    ) -> bool:
        """检查当前价格是否进入了斐波那契价位周围的 zone

        zone = fib_level_price * zone_width_pct
        如果 abs(current_price - fib_level_price) <= zone, 视为进入 zone
        """
        zone = fib_level_price * zone_width_pct
        if zone <= 0:
            return current_price == fib_level_price
        return abs(current_price - fib_level_price) <= zone


# ---------------------------------------------------------------------------
# 策略实现
# ---------------------------------------------------------------------------

class FibonacciStrategyBot(BaseStrategy):
    """斐波那契回撤策略

    使用 ZigZag 检测器识别价格 swing, 计算斐波那契回撤位,
    当现货价格进入回撤 zone 时买入对应的 Up/Down token。

    每个 symbol (现货交易对) 维护独立的价格历史、ZigZag 检测器和斐波那契计算器。
    """

    name = "fibonacci_bot"

    def __init__(self, config: FibonacciBotConfig):
        self.config = config
        # 每个 symbol 的价格历史
        self._candles: dict[str, deque[float]] = {}
        # 每个 symbol 的 ZigZag 检测器
        self._zigzag: dict[str, ZigZagDetector] = {}
        # 斐波那契计算器
        self._fib_calc = FibonacciCalculator(self.config.ratios)
        # 动量统计
        self._momentum = RollingPriceStats(window_size=self.config.momentum_window)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _ensure_candles(self, symbol: str) -> deque[float]:
        """确保 symbol 的价格队列存在"""
        if symbol not in self._candles:
            self._candles[symbol] = deque(maxlen=100)
        return self._candles[symbol]

    def _ensure_zigzag(self, symbol: str) -> ZigZagDetector:
        """确保 symbol 的 ZigZag 检测器存在"""
        if symbol not in self._zigzag:
            self._zigzag[symbol] = ZigZagDetector(threshold_pct=self.config.zigzag_pct)
        return self._zigzag[symbol]

    # ------------------------------------------------------------------
    # 动量确认
    # ------------------------------------------------------------------

    def _check_momentum(self, symbol: str, current_price: float) -> bool:
        """检查动量是否需要确认

        如果 require_momentum_confirmation == False, 跳过动量检查。
        否则检查 z-score 是否超过阈值。
        """
        if not self.config.require_momentum_confirmation:
            return True

        stats = self._momentum.stats(symbol)
        z = stats.get("z_score")
        if z is None or stats.get("count", 0) < self.config.momentum_window:
            return False

        return abs(z) >= self.config.min_momentum_zscore

    # ------------------------------------------------------------------
    # 计算 token side 推荐
    # ------------------------------------------------------------------

    def _determine_side(
        self,
        spot_price: float,
        fib_level_price: float,
        swing_high: float,
        swing_low: float,
    ) -> Side | None:
        """根据现货价格在斐波那契 zone 中的位置决定买入哪个 token

        如果价格在回撤 zone 中 (价格从高点到低点的回撤):
        - 价格向下跌破 swing_low → 买入 DOWN
        - 价格在回撤 zone 中上涨 → 买入 UP

        简化版: 如果当前价格靠近 swing_low (下方支撑区), 买入 UP (看涨)
                如果当前价格靠近 swing_high (上方阻力区), 买入 DOWN (看跌)
        """
        if spot_price <= fib_level_price:
            # 价格低于回撤位, 处于支撑区, 倾向买入 UP
            return Side.UP
        else:
            # 价格高于回撤位, 处于阻力区, 倾向买入 DOWN
            return Side.DOWN

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

        # 需要现货价格支撑
        if snapshot.spot is None or snapshot.spot.price <= 0:
            return []

        spot_price = snapshot.spot.price
        symbol = snapshot.spot.symbol

        # --- 更新价格历史 ---
        candles = self._ensure_candles(symbol)
        candles.append(spot_price)

        # --- 更新动量统计 ---
        self._momentum.push(symbol, spot_price)

        # --- 动量确认 ---
        if not self._check_momentum(symbol, spot_price):
            return []

        # --- 更新 ZigZag 检测 ---
        zigzag = self._ensure_zigzag(symbol)
        zigzag.push(spot_price)
        zigzag._finalize_last_extreme()
        # --- 检查是否有足够的 swing 点 ---
        if not zigzag.has_swing():
            return []

        swing_high = zigzag.current_swing_high()
        swing_low = zigzag.current_swing_low()
        if swing_high is None or swing_low is None:
            return []
        if swing_high <= swing_low:
            return []

        # --- 计算斐波那契回撤位 ---
        fib_levels = self._fib_calc.retracement_levels(swing_high, swing_low)
        if not fib_levels:
            return []

        # --- 检查现货价格是否进入某个斐波那契 zone ---
        signals: list[SignalCandidate] = []
        for idx, (ratio, fib_price) in enumerate(fib_levels.items()):
            if not FibonacciCalculator.is_in_zone(
                spot_price, fib_price, self.config.zone_width_pct,
            ):
                continue

            # 确定 side
            side = self._determine_side(spot_price, fib_price, swing_high, swing_low)
            if side is None:
                continue

            # 检查 token ask 价格
            book = snapshot.book_for(side)
            if book is None or book.best_ask is None:
                continue
            token_ask = book.best_ask
            if token_ask > self.config.max_token_price:
                continue

            # 计算仓位权重
            weight_idx = min(idx, len(self.config.fib_size_weights) - 1)
            weight = self.config.fib_size_weights[weight_idx]

            # 置信度: 比率越低 (回撤越浅) 置信度越高 (趋势更强)
            # 0.236 → ~0.75, 0.786 → ~0.55
            confidence = max(
                0.45,
                min(0.85, 0.70 + (0.236 - ratio) / 0.236 * 0.15),
            )

            metrics: dict[str, Any] = {
                "spot_price": spot_price,
                "swing_high": swing_high,
                "swing_low": swing_low,
                "fib_ratio": ratio,
                "fib_price": round(fib_price, 8),
                "zone_width_pct": self.config.zone_width_pct,
                "token_ask": token_ask,
                "weight": weight,
                "momentum_confirmed": self.config.require_momentum_confirmation,
            }

            # 添加动量 z-score 到 metrics
            mom_stats = self._momentum.stats(symbol)
            metrics["momentum_z"] = mom_stats.get("z_score")
            metrics["momentum_vwap"] = mom_stats.get("vwap")

            reason_codes = [
                "FIBONACCI_ZONE",
                f"RATIO_{ratio:.3f}",
                f"SIDE_{side.value}",
                f"WEIGHT_{weight}",
            ]

            signal = self._candidate(
                snapshot=snapshot,
                side=side,
                confidence=confidence,
                max_entry_price=min(token_ask + self.config.offset_from_fib, self.config.max_token_price),
                reason_codes=reason_codes,
                metrics=metrics,
            )
            if signal:
                signals.append(signal)

        return signals
