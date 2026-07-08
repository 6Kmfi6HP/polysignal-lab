"""
Input: __future__, __future__.annotations, collections, collections.defaultdict, collections.deque, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision, polysignal_lab.alpha.types.AlphaOrderEvent, polysignal_lab.alpha.types.MarketView, polysignal_lab.alpha.types.OrderIntentSpec
Output: _RollingPriceStats, BinaryMomentumAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from collections import defaultdict, deque

from polysignal_lab.alpha.types import AlphaDecision, AlphaOrderEvent, MarketView, OrderIntentSpec, SideBookView
from polysignal_lab.domain.enums import OrderIntent, Side


class _RollingPriceStats:
    """Pure copy of strategies.base.RollingPriceStats (kept pure: no import
    of the strategy layer, which pulls snapshot machinery)."""

    def __init__(self, window_size: int = 16) -> None:
        self.values: dict[str, deque[tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=window_size)
        )

    def push(self, key: str, price: float, size: float = 1.0) -> None:
        self.values[key].append((price, max(size, 1e-9)))

    def stats(self, key: str) -> dict[str, float | None]:
        vals = list(self.values[key])
        if not vals:
            return {"vwap": None, "momentum": None, "z_score": None, "count": 0}
        total_size = sum(size for _, size in vals)
        vwap = (
            sum(price * size for price, size in vals) / total_size
            if total_size
            else sum(p for p, _ in vals) / len(vals)
        )
        momentum = vals[-1][0] - vals[0][0] if len(vals) > 1 else 0.0
        prices = [p for p, _ in vals]
        stdev_val = (sum((p - (sum(prices) / len(prices))) ** 2 for p in prices) / len(prices)) ** 0.5
        mean_price = sum(prices) / len(prices)
        z = (prices[-1] - mean_price) / stdev_val if stdev_val > 0 else 0.0
        return {"vwap": vwap, "momentum": momentum, "z_score": z, "count": len(vals)}


class BinaryMomentumAlphaCore:
    name = "binary_momentum"

    def __init__(self, config) -> None:
        self.config = config
        maxlen = config.macd_slow + config.macd_signal + 20
        self._spot_prices: deque[float] = deque(maxlen=maxlen)
        self._vwap_stats = _RollingPriceStats(window_size=config.macd_slow * 2)
        self._entered_markets: set[str] = set()

    def reset(self) -> None:
        self._spot_prices.clear()
        self._vwap_stats = _RollingPriceStats(window_size=self.config.macd_slow * 2)
        self._entered_markets.clear()

    def on_order_accepted(self, event: AlphaOrderEvent) -> None:
        self._entered_markets.add(event.market_id)

    @staticmethod
    def _book_mid(book: SideBookView) -> float | None:
        if book.best_bid is not None and book.best_ask is not None:
            return (book.best_bid + book.best_ask) / 2.0
        return None

    @staticmethod
    def _compute_ema(data: list[float], period: int) -> list[float]:
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
        need = self.config.macd_slow + self.config.macd_signal
        if len(prices) < need:
            return {"macd_line": None, "signal": None, "histogram": None}

        fast_ema = self._compute_ema(prices, self.config.macd_fast)
        slow_ema = self._compute_ema(prices, self.config.macd_slow)
        if not fast_ema or not slow_ema:
            return {"macd_line": None, "signal": None, "histogram": None}

        offset = self.config.macd_slow - self.config.macd_fast
        macd_line_values = [
            fast_ema[i + offset] - slow_ema[i] for i in range(len(slow_ema))
        ]
        signal_values = self._compute_ema(macd_line_values, self.config.macd_signal)
        if not macd_line_values or not signal_values:
            return {"macd_line": None, "signal": None, "histogram": None}

        macd_line = macd_line_values[-1]
        signal_line = signal_values[-1]
        histogram = macd_line - signal_line
        return {"macd_line": macd_line, "signal": signal_line, "histogram": histogram}

    def _rsi(self, prices: list[float]) -> float | None:
        period = self.config.rsi_period
        if len(prices) < period + 1:
            return None
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0.0 for d in deltas[:period]]
        losses = [abs(d) if d < 0 else 0.0 for d in deltas[:period]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
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

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        cfg = self.config
        self._collect_data(view)

        spot_prices = list(self._spot_prices)
        if len(spot_prices) < cfg.macd_slow:
            return []

        macd = self._macd(spot_prices)
        macd_line = macd.get("macd_line")
        signal = macd.get("signal")
        histogram = macd.get("histogram")
        if any(v is None for v in (macd_line, signal, histogram)):
            return []

        rsi_val = self._rsi(spot_prices)
        if rsi_val is None:
            return []

        market_id = view.market_id
        already_in = market_id in self._entered_markets
        decisions: list[AlphaDecision] = []

        for direction_side in (Side.UP, Side.DOWN):
            decision = self._evaluate_direction(
                view, direction_side, macd_line, signal, histogram,
                rsi_val, already_in,
            )
            if decision is not None:
                decisions.append(decision)

        return decisions

    def _collect_data(self, view: MarketView) -> None:
        """Extract spot prices and token mids from the view."""
        if view.spot is not None and view.spot.price > 0:
            self._spot_prices.append(view.spot.price)
        for book_side in (Side.UP, Side.DOWN):
            book = view.book_for(book_side)
            if book.best_bid is not None and book.best_ask is not None:
                mid = (book.best_bid + book.best_ask) / 2.0
                if mid > 0:
                    key = f"{view.market_id}:{book_side.value}"
                    self._vwap_stats.push(key, mid, 1.0)

    def _evaluate_direction(
        self,
        view: MarketView,
        direction_side: Side,
        macd_line: float,
        signal: float,
        histogram: float,
        rsi_val: float,
        already_in: bool,
    ) -> AlphaDecision | None:
        """Check conditions for a single direction and return a decision if met."""
        cfg = self.config
        market_id = view.market_id

        # Direction-specific MACD/RSI check
        if direction_side == Side.UP:
            if not (
                histogram > 0
                and macd_line > signal
                and cfg.rsi_up_min <= rsi_val <= cfg.rsi_upper
            ):
                return None
        else:
            if not (
                histogram < 0
                and macd_line < signal
                and cfg.rsi_lower <= rsi_val <= cfg.rsi_down_max
            ):
                return None

        book = view.book_for(direction_side)
        mid = self._book_mid(book)
        if mid is None or mid > cfg.max_token_price:
            return None

        vwap_key = f"{market_id}:{direction_side.value}"
        vwap_stats = self._vwap_stats.stats(vwap_key)
        current_vwap = vwap_stats.get("vwap")
        if current_vwap is None or current_vwap <= 0:
            return None

        if direction_side == Side.UP:
            if mid <= current_vwap * (1.0 + cfg.vwap_deviation):
                return None
        else:
            if mid >= current_vwap * (1.0 - cfg.vwap_deviation):
                return None

        if already_in:
            return None

        rsi_mid = abs(rsi_val - 50.0) / 50.0
        macd_strength = (
            abs(histogram) / (abs(macd_line) + 1e-10)
            if abs(macd_line) > 1e-10
            else 0.5
        )
        macd_strength = min(1.0, macd_strength)
        confidence = 0.50 + 0.20 * rsi_mid + 0.10 * macd_strength
        confidence = max(0.50, min(0.95, confidence))

        return AlphaDecision(
            strategy=self.name,
            asset=view.asset,
            timeframe=view.timeframe,
            market_id=market_id,
            market_slug=view.market_slug,
            condition_id=view.condition_id,
            token_id=book.token_id,
            side=direction_side,
            confidence=confidence,
            entry_reference_price=book.best_ask if book.best_ask is not None else (mid * 1.05),
            max_entry_price=book.best_ask if book.best_ask is not None else (mid * 1.05),
            seconds_to_close=view.seconds_to_close,
            data_freshness_ms=view.freshness.max_ms,
            reason_codes=(
                "BINARY_MOMENTUM",
                f"MACD_{'BULL' if direction_side == Side.UP else 'BEAR'}",
                f"RSI_{int(rsi_val)}",
                "VWAP_CONFIRMED",
            ),
            metrics={
                "macd_line": macd_line,
                "macd_signal": signal,
                "macd_histogram": histogram,
                "rsi": rsi_val,
                "vwap": current_vwap,
                "token_mid": mid,
                "direction": direction_side.value,
                "spot_price": view.spot.price if view.spot else None,
                "stop_loss_pct": cfg.stop_loss_pct,
                "take_profit_pct": cfg.take_profit_pct,
                "max_notional": cfg.max_notional,
                "created_at_for_test": view.created_at,
            },
            order_intent=OrderIntentSpec(intent=OrderIntent.TAKER_FAK),
        )

    def evaluate_view_from_snapshot_for_test(
        self, snapshot: MarketSnapshot
    ) -> list[AlphaDecision]:
        from polysignal_lab.alpha.ptb_diff_core import market_view_from_snapshot
        view = market_view_from_snapshot(snapshot)
        return self.evaluate(view) if view is not None else []