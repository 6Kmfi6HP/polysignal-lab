from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from polysignal_lab.config import FillModelConfig
from polysignal_lab.data.state import OrderBookRegistry
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder


@dataclass
class FillDecision:
    accepted: bool
    fill: PaperFill | None = None
    reason_code: str | None = None
    available_depth_usdc: float | None = None


class BestAskTakerFillModel:
    def __init__(
        self,
        config: FillModelConfig,
        max_book_staleness_ms: int,
        registry: OrderBookRegistry | None = None,
    ):
        self.config = config
        self.max_book_staleness_ms = max_book_staleness_ms
        self.registry = registry

    def fill(self, order: PaperOrder, orderbook: OrderBook) -> FillDecision:
        if orderbook.token_id != order.token_id:
            return FillDecision(False, reason_code="MALFORMED_ORDERBOOK")
        if self.registry is not None:
            if not self.registry.is_fill_eligible(
                order.token_id, self.max_book_staleness_ms, order.created_at
            ):
                state = self.registry.get_state(order.token_id)
                reason = state.stale_reason if state else "NO_SNAPSHOT"
                return FillDecision(False, reason_code=reason or "STALE_ORDERBOOK")
        elif not orderbook.is_fresh(self.max_book_staleness_ms, order.created_at):
            return FillDecision(False, reason_code="STALE_ORDERBOOK")
        raw = orderbook.best_ask
        if not orderbook.asks or raw is None:
            return FillDecision(False, reason_code="MISSING_BEST_ASK")
        if not isfinite(raw) or not isfinite(order.limit_price):
            return FillDecision(False, reason_code="MALFORMED_ORDERBOOK")
        if any(
            not isfinite(level.price)
            or not isfinite(level.size)
            or level.price <= 0
            or level.size <= 0
            for level in orderbook.asks
        ):
            return FillDecision(False, reason_code="MALFORMED_ORDERBOOK")
        if raw > order.limit_price:
            return FillDecision(False, reason_code="ASK_ABOVE_MAX_ENTRY")
        fill_price = raw + raw * self.config.slippage_bps / 10000
        if not isfinite(fill_price):
            return FillDecision(False, reason_code="MALFORMED_ORDERBOOK")
        if fill_price > order.limit_price:
            return FillDecision(False, reason_code="SLIPPAGE_EXCEEDS_MAX_ENTRY")
        target_contracts = order.metrics.get("contracts")
        shares = float(target_contracts) if isinstance(target_contracts, int | float) and target_contracts > 0 else None
        stake_usdc = shares * fill_price if shares is not None else order.stake_usdc
        available = None
        if self.config.require_depth_check:
            available = orderbook.depth_until(order.limit_price)
            ratio = min(1.0, available / stake_usdc) if stake_usdc else 0.0
            if ratio < self.config.min_fill_ratio and self.config.reject_if_partial:
                return FillDecision(False, reason_code="INSUFFICIENT_DEPTH", available_depth_usdc=available)
        shares = shares if shares is not None else stake_usdc / fill_price
        fill = PaperFill(
            paper_order_id=order.paper_order_id,
            signal_id=order.signal_id,
            token_id=order.token_id,
            side=order.side,
            raw_best_ask=raw,
            slippage_bps=self.config.slippage_bps,
            fill_price=fill_price,
            stake_usdc=stake_usdc,
            shares=shares,
            depth_checked=self.config.require_depth_check,
            available_depth_usdc=available,
            fill_ratio=1.0,
        )
        return FillDecision(True, fill=fill, available_depth_usdc=available)
