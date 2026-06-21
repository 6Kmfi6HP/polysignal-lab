from __future__ import annotations

from dataclasses import dataclass

from polysignal_lab.config import FillModelConfig
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder


@dataclass
class FillDecision:
    accepted: bool
    fill: PaperFill | None = None
    reason_code: str | None = None
    available_depth_usdc: float | None = None


class BestAskTakerFillModel:
    def __init__(self, config: FillModelConfig, max_book_staleness_ms: int):
        self.config = config
        self.max_book_staleness_ms = max_book_staleness_ms

    def fill(self, order: PaperOrder, orderbook: OrderBook) -> FillDecision:
        if not orderbook.is_fresh(self.max_book_staleness_ms, order.created_at):
            return FillDecision(False, reason_code="STALE_ORDERBOOK")
        if orderbook.best_ask is None:
            return FillDecision(False, reason_code="STALE_ORDERBOOK")
        raw = orderbook.best_ask
        if raw > order.limit_price:
            return FillDecision(False, reason_code="ASK_ABOVE_MAX_ENTRY")
        fill_price = raw + raw * self.config.slippage_bps / 10000
        if fill_price > order.limit_price:
            return FillDecision(False, reason_code="SLIPPAGE_EXCEEDS_MAX_ENTRY")
        available = None
        if self.config.require_depth_check:
            available = orderbook.depth_until(order.limit_price)
            ratio = min(1.0, available / order.stake_usdc) if order.stake_usdc else 0.0
            if ratio < self.config.min_fill_ratio and self.config.reject_if_partial:
                return FillDecision(False, reason_code="INSUFFICIENT_DEPTH", available_depth_usdc=available)
        shares = order.stake_usdc / fill_price
        fill = PaperFill(
            paper_order_id=order.paper_order_id,
            signal_id=order.signal_id,
            token_id=order.token_id,
            side=order.side,
            raw_best_ask=raw,
            slippage_bps=self.config.slippage_bps,
            fill_price=fill_price,
            stake_usdc=order.stake_usdc,
            shares=shares,
            depth_checked=self.config.require_depth_check,
            available_depth_usdc=available,
            fill_ratio=1.0,
        )
        return FillDecision(True, fill=fill, available_depth_usdc=available)
