"""BinaryMomentumStrategy — MACD/RSI/VWAP 二元动量策略

使用现货价格序列计算 MACD(12,26,9) 和 RSI(14),
使用 Token 订单簿计算 VWAP,
根据多指标一致性判断 UP/DOWN 方向并生成信号。

Paper Trading 适配:
  - 通过 evaluate() 返回 SignalCandidate
  - 使用 self._spot_prices 和 self._vwap_stats 维护状态
  - 使用 self._entered_markets 跟踪已入场市场避免重复入场
  - TP/SL 信息在 metrics 中由 PaperExitEngine 处理
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy, RollingPriceStats


@dataclass
class BinaryMomentumConfig:
    """BinaryMomentumStrategy 配置"""

    # --- MACD ---
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # --- RSI ---
    rsi_period: int = 14
    rsi_upper: int = 75
    rsi_lower: int = 25
    rsi_up_min: int = 50
    rsi_down_max: int = 50

    # --- VWAP ---
    vwap_deviation: float = 0.002
    """价格偏离 VWAP 的最小比例阈值"""

    # --- 风控 ---
    max_token_price: float = 0.70
    """Token 价格上限（高于此值不入场）"""

    max_notional: float = 25.0
    """每笔最大名义金额"""

    stop_loss_pct: float = 0.20
    """止损比例（相对入场价）"""

    take_profit_pct: float = 0.25
    """止盈比例（相对入场价）"""


class BinaryMomentumStrategy(BaseStrategy):
    """二元动量策略

    结合三个技术指标判断市场动量方向:
      - MACD(12,26,9): 趋势方向 — MACD_hist > 0 且 MACD_line > Signal → 看多
      - RSI(14): 过滤极端超买超卖, 同时确认方向
      - VWAP: 确认价格相对于价值区间的偏离方向

    UP 信号条件: MACD_hist > 0 AND MACD_line > MACD_signal
                  AND RSI in [50, 75]
                  AND token_mid > VWAP * (1 + deviation)

    DOWN 信号条件: MACD_hist < 0 AND MACD_line < MACD_signal
                    AND RSI in [25, 50]
                    AND token_mid < VWAP * (1 - deviation)
    """

    name = "binary_momentum"

    def __init__(self, config: BinaryMomentumConfig | None = None) -> None:
        self.config = config or BinaryMomentumConfig()
        # 现货价格序列 — 用于 MACD/RSI 计算 (maxlen 足够容纳 slow + signal + margin)
        maxlen = self.config.macd_slow + self.config.macd_signal + 20
        self._spot_prices: deque[float] = deque(maxlen=maxlen)
        # Token 价格统计 — 用于 VWAP 计算
        self._vwap_stats = RollingPriceStats(window_size=self.config.macd_slow * 2)
        # 已入场: {market_id: side_value}
        self._entered_markets: dict[str, str] = {}

    def reset(self) -> None:
        """重置所有状态（测试用）"""
        self._spot_prices.clear()
        self._vwap_stats = RollingPriceStats(window_size=self.config.macd_slow * 2)
        self._entered_markets.clear()

    # ------------------------------------------------------------------
    # 技术指标计算
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_ema(data: list[float], period: int) -> list[float]:
        """计算指数移动平均序列

        用前 period 个值的 SMA 作为初始值, 然后递归计算 EMA。
        返回长度为 len(data) - period + 1 的列表。
        """
        if len(data) < period:
            return []
        k = 2.0 / (period + 1.0)
        ema = sum(data[:period]) / period
        result: list[float] = [ema]
        for i in range(period, len(data)):
            ema = data[i] * k + ema * (1.0 - k)
            result.append(ema)
        return result

    def _macd(self, prices: list[float]) -> dict[str, float | None]:
        """计算 MACD(12,26,9)

        返回: {macd_line, signal, histogram}
        """
        need = self.config.macd_slow + self.config.macd_signal
        if len(prices) < need:
            return {"macd_line": None, "signal": None, "histogram": None}

        fast_ema = self._compute_ema(prices, self.config.macd_fast)
        slow_ema = self._compute_ema(prices, self.config.macd_slow)

        if not fast_ema or not slow_ema:
            return {"macd_line": None, "signal": None, "histogram": None}

        # MACD line = fast_ema - slow_ema (对齐到 slow_ema 的索引)
        offset = self.config.macd_slow - self.config.macd_fast
        macd_line_values = [
            fast_ema[i + offset] - slow_ema[i]
            for i in range(len(slow_ema))
        ]

        # Signal line = EMA(9) of MACD line
        signal_values = self._compute_ema(macd_line_values, self.config.macd_signal)

        if not macd_line_values or not signal_values:
            return {"macd_line": None, "signal": None, "histogram": None}

        macd_line = macd_line_values[-1]
        signal_line = signal_values[-1]
        histogram = macd_line - signal_line

        return {
            "macd_line": macd_line,
            "signal": signal_line,
            "histogram": histogram,
        }

    def _rsi(self, prices: list[float]) -> float | None:
        """计算 RSI(period) — Wilder 平滑版本"""
        period = self.config.rsi_period
        if len(prices) < period + 1:
            return None

        # 计算所有价格变化
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

        # 初始平均值: 简单平均前 period 个变化
        gains = [d if d > 0 else 0.0 for d in deltas[:period]]
        losses = [abs(d) if d < 0 else 0.0 for d in deltas[:period]]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        # Wilder 平滑: 对剩余数据点递推
        for d in deltas[period:]:
            if d > 0:
                avg_gain = (avg_gain * (period - 1) + d) / period
                avg_loss = (avg_loss * (period - 1)) / period
            else:
                avg_gain = (avg_gain * (period - 1)) / period
                avg_loss = (avg_loss * (period - 1) + abs(d)) / period

        if avg_loss == 0.0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    # ------------------------------------------------------------------
    # 主评估方法
    # ------------------------------------------------------------------

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        # 1. 收集现货价格
        if snapshot.spot is not None and snapshot.spot.price > 0:
            self._spot_prices.append(snapshot.spot.price)

        # 2. 收集 Token 价格用于 VWAP
        for book_side in [Side.UP, Side.DOWN]:
            book = snapshot.book_for(book_side)
            if book is not None and book.mid is not None and book.mid > 0:
                key = f"{snapshot.market.market_id}:{book_side.value}"
                self._vwap_stats.push(key, book.mid, 1.0)

        spot_prices = list(self._spot_prices)

        # 需要至少 macd_slow 个数据点才能计算 MACD
        if len(spot_prices) < self.config.macd_slow:
            return []

        # 3. 计算 MACD
        macd = self._macd(spot_prices)
        macd_line = macd.get("macd_line")
        signal = macd.get("signal")
        histogram = macd.get("histogram")
        if any(v is None for v in (macd_line, signal, histogram)):
            return []

        # 4. 计算 RSI
        rsi_val = self._rsi(spot_prices)
        if rsi_val is None:
            return []

        market_id = snapshot.market.market_id
        already_in = market_id in self._entered_markets
        signals: list[SignalCandidate] = []

        # 5. 判断 UP / DOWN 方向
        for direction_side in [Side.UP, Side.DOWN]:
            # --- 方向条件 ---
            if direction_side == Side.UP:
                # 看多条件: MACD 多头 + RSI 在 50-75 区间
                if not (
                    histogram > 0
                    and macd_line > signal
                    and self.config.rsi_up_min <= rsi_val <= self.config.rsi_upper
                ):
                    continue
            else:  # DOWN
                # 看空条件: MACD 空头 + RSI 在 25-50 区间
                if not (
                    histogram < 0
                    and macd_line < signal
                    and self.config.rsi_lower <= rsi_val <= self.config.rsi_down_max
                ):
                    continue

            # 6. Token 价格检查
            book = snapshot.book_for(direction_side)
            if book is None or book.mid is None:
                continue

            # Token 价格上限: 不能在价格太高时入场
            if book.mid > self.config.max_token_price:
                continue

            # 7. VWAP 确认
            vwap_key = f"{market_id}:{direction_side.value}"
            vwap_stats = self._vwap_stats.stats(vwap_key)
            current_vwap = vwap_stats.get("vwap")
            if current_vwap is None or current_vwap <= 0:
                continue

            if direction_side == Side.UP:
                # UP: 价格 > VWAP * (1 + deviation) — 价格在 VWAP 上方, 确认上涨
                if book.mid <= current_vwap * (1.0 + self.config.vwap_deviation):
                    continue
            else:
                # DOWN: 价格 < VWAP * (1 - deviation) — 价格在 VWAP 下方, 确认下跌
                if book.mid >= current_vwap * (1.0 - self.config.vwap_deviation):
                    continue

            # 8. 如果已入场该市场, 不再生成新信号
            if already_in:
                continue

            # 9. 生成信号
            self._entered_markets[market_id] = direction_side.value

            # 置信度: 结合 RSI 位置和 MACD 强度
            rsi_mid = abs(rsi_val - 50.0) / 50.0  # 0 在 50, 1 在 0 或 100
            macd_strength = abs(histogram) / (
                abs(macd_line) + 1e-10
            ) if abs(macd_line) > 1e-10 else 0.5
            macd_strength = min(1.0, macd_strength)

            confidence = 0.50 + 0.20 * rsi_mid + 0.10 * macd_strength
            confidence = max(0.50, min(0.95, confidence))

            signal = self._candidate(
                snapshot=snapshot,
                side=direction_side,
                confidence=confidence,
                max_entry_price=book.best_ask or (book.mid * 1.05),
                reason_codes=[
                    "BINARY_MOMENTUM",
                    f"MACD_{'BULL' if direction_side == Side.UP else 'BEAR'}",
                    f"RSI_{int(rsi_val)}",
                    "VWAP_CONFIRMED",
                ],
                metrics={
                    "macd_line": macd_line,
                    "macd_signal": signal,
                    "macd_histogram": histogram,
                    "rsi": rsi_val,
                    "vwap": current_vwap,
                    "token_mid": book.mid,
                    "direction": direction_side.value,
                    "spot_price": snapshot.spot.price if snapshot.spot else None,
                    "stop_loss_pct": self.config.stop_loss_pct,
                    "take_profit_pct": self.config.take_profit_pct,
                    "max_notional": self.config.max_notional,
                },
                order_intent=OrderIntent.TAKER_FAK,
            )
            if signal is not None:
                signals.append(signal)

        return signals
