from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any

from polysignal_lab.config import FillModelConfig
from polysignal_lab.data.state import OrderBookRegistry
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.signal import SignalCandidate

PAPER_MISSING_ORDERBOOK = "PAPER_MISSING_ORDERBOOK"
PAPER_STALE_ORDERBOOK = "PAPER_STALE_ORDERBOOK"
PAPER_DEPTH_TOO_THIN = "PAPER_DEPTH_TOO_THIN"
PAPER_ENTRY_PRICE_MOVED = "PAPER_ENTRY_PRICE_MOVED"
PAPER_EDGE_VANISHED = "PAPER_EDGE_VANISHED"
PAPER_EXTREME_SLIPPAGE = "PAPER_EXTREME_SLIPPAGE"
PAPER_EXPOSURE_LIMIT_REACHED = "PAPER_EXPOSURE_LIMIT_REACHED"
PAPER_WALLET_INSUFFICIENT_CASH = "PAPER_WALLET_INSUFFICIENT_CASH"
PAPER_GTD_EXPIRED = "PAPER_GTD_EXPIRED"
PAPER_MALFORMED_ORDERBOOK = "PAPER_MALFORMED_ORDERBOOK"
PAPER_FILL_REJECTED = "PAPER_FILL_REJECTED"
PAPER_ACCEPTED = "PAPER_ACCEPTED"

_REASON_MAP: dict[str, str] = {
    "MISSING_ORDERBOOK": PAPER_MISSING_ORDERBOOK,
    "MISSING_BEST_ASK": PAPER_MISSING_ORDERBOOK,
    "NO_SNAPSHOT": PAPER_STALE_ORDERBOOK,
    "STALE_ORDERBOOK": PAPER_STALE_ORDERBOOK,
    "HASH_REGRESSION": PAPER_STALE_ORDERBOOK,
    "DELTA_BEFORE_SNAPSHOT": PAPER_STALE_ORDERBOOK,
    "RECONNECT_RESEED_FAILED": PAPER_STALE_ORDERBOOK,
    "TICK_SIZE_CHANGE_RESEED_REQUIRED": PAPER_STALE_ORDERBOOK,
    "BOOK_SEQUENCE_INVALID": PAPER_STALE_ORDERBOOK,
    "INSUFFICIENT_DEPTH": PAPER_DEPTH_TOO_THIN,
    "FOK_INSUFFICIENT_DEPTH": PAPER_DEPTH_TOO_THIN,
    "FAK_NO_LIQUIDITY": PAPER_DEPTH_TOO_THIN,
    "ASK_ABOVE_MAX_ENTRY": PAPER_ENTRY_PRICE_MOVED,
    "SLIPPAGE_EXCEEDS_MAX_ENTRY": PAPER_EXTREME_SLIPPAGE,
    "EXPOSURE_LIMIT_REACHED": PAPER_EXPOSURE_LIMIT_REACHED,
    "MAX_OPEN_POSITIONS_REACHED": PAPER_EXPOSURE_LIMIT_REACHED,
    "WALLET_INSUFFICIENT_CASH": PAPER_WALLET_INSUFFICIENT_CASH,
    "GTD_EXPIRED": PAPER_GTD_EXPIRED,
    "MALFORMED_ORDERBOOK": PAPER_MALFORMED_ORDERBOOK,
}


def normalize_paper_reject_reason(reason: str | None) -> str:
    if reason is None or reason == "":
        return PAPER_FILL_REJECTED
    if reason.startswith("PAPER_"):
        return reason
    return _REASON_MAP.get(reason, PAPER_FILL_REJECTED)


@dataclass(frozen=True, slots=True)
class PaperExecutionDecision:
    accepted: bool
    reason_code: str
    metrics: dict[str, bool | float | str | None]


class PaperExecutionPreflight:
    def __init__(
        self,
        fill_model: FillModelConfig,
        max_book_staleness_ms: int,
        fixed_stake_usdc: float,
        registry: OrderBookRegistry | None = None,
    ) -> None:
        self.fill_model = fill_model
        self.max_book_staleness_ms = max_book_staleness_ms
        self.fixed_stake_usdc = fixed_stake_usdc
        self.registry = registry

    def evaluate(
        self,
        signal: SignalCandidate,
        orderbook: OrderBook | None,
        now: datetime,
        intent: OrderIntent | None = None,
    ) -> PaperExecutionDecision:
        metrics = self._base_metrics(signal, orderbook, now, intent)
        if orderbook is None:
            return self._reject("MISSING_ORDERBOOK", metrics)
        malformed = self._malformed_book_reason(signal, orderbook)
        if malformed is not None:
            return self._reject(malformed, metrics)
        stale_reason = self._stale_reason(signal.token_id, orderbook, now)
        metrics["paper_orderbook_fresh"] = stale_reason is None
        metrics["paper_orderbook_staleness_ms"] = float(orderbook.freshness_ms(now))
        metrics["paper_execution_best_ask"] = orderbook.best_ask
        metrics["paper_execution_best_bid"] = orderbook.best_bid
        metrics["paper_available_depth_usdc"] = orderbook.depth_until(signal.max_entry_price)
        if stale_reason is not None:
            return self._reject(stale_reason, metrics)
        if intent == OrderIntent.PASSIVE_GTD:
            metrics["paper_depth_revalidated"] = False
            metrics["paper_edge_revalidated"] = False
            return PaperExecutionDecision(True, PAPER_ACCEPTED, metrics)
        if orderbook.best_ask is None:
            return self._reject("MISSING_BEST_ASK", metrics)
        if orderbook.best_ask > signal.max_entry_price:
            return self._reject("ASK_ABOVE_MAX_ENTRY", metrics)
        slippage_price = orderbook.best_ask + orderbook.best_ask * self.fill_model.slippage_bps / 10000
        metrics["paper_slippage_bps"] = self.fill_model.slippage_bps
        metrics["paper_slippage_price"] = slippage_price
        if intent not in (OrderIntent.TAKER_FAK, OrderIntent.TAKER_FOK) and slippage_price > signal.max_entry_price:
            return self._reject("SLIPPAGE_EXCEEDS_MAX_ENTRY", metrics)
        if intent == OrderIntent.TAKER_FOK:
            metrics["paper_depth_revalidated"] = True
            if float(metrics["paper_available_depth_usdc"] or 0.0) < self.fixed_stake_usdc:
                return self._reject("FOK_INSUFFICIENT_DEPTH", metrics)
        elif intent == OrderIntent.TAKER_FAK:
            metrics["paper_depth_revalidated"] = True
            fak_fill_price = self._fak_fill_price(signal, orderbook)
            if fak_fill_price is None:
                return self._reject("FAK_NO_LIQUIDITY", metrics)
            slippage_price = fak_fill_price + fak_fill_price * self.fill_model.slippage_bps / 10000
            metrics["paper_slippage_price"] = slippage_price
            if slippage_price > signal.max_entry_price:
                return self._reject("SLIPPAGE_EXCEEDS_MAX_ENTRY", metrics)
        elif self.fill_model.require_depth_check:
            metrics["paper_depth_revalidated"] = True
            available = float(metrics["paper_available_depth_usdc"] or 0.0)
            fill_ratio = min(1.0, available / self.fixed_stake_usdc) if self.fixed_stake_usdc else 0.0
            metrics["paper_depth_fill_ratio"] = fill_ratio
            if fill_ratio < self.fill_model.min_fill_ratio and self.fill_model.reject_if_partial:
                return self._reject("INSUFFICIENT_DEPTH", metrics)
        else:
            metrics["paper_depth_revalidated"] = False
        edge_reason = self._edge_reason(signal, orderbook.best_ask, metrics)
        if edge_reason is not None:
            return self._reject(edge_reason, metrics)
        return PaperExecutionDecision(True, PAPER_ACCEPTED, metrics)

    def _base_metrics(
        self,
        signal: SignalCandidate,
        orderbook: OrderBook | None,
        now: datetime,
        intent: OrderIntent | None,
    ) -> dict[str, bool | float | str | None]:
        return {
            "paper_preflight_checked": True,
            "paper_execution_checked_at": now.isoformat(),
            "paper_order_intent": intent.value if intent is not None else None,
            "paper_original_reason": None,
            "paper_normalized_reason": None,
            "paper_orderbook_token_id": orderbook.token_id if orderbook is not None else None,
            "paper_signal_token_id": signal.token_id,
            "paper_limit_price": signal.max_entry_price,
            "paper_stake_usdc": self.fixed_stake_usdc,
        }

    def _reject(
        self,
        reason: str,
        metrics: dict[str, bool | float | str | None],
    ) -> PaperExecutionDecision:
        normalized = normalize_paper_reject_reason(reason)
        metrics["paper_original_reason"] = reason
        metrics["paper_normalized_reason"] = normalized
        return PaperExecutionDecision(False, normalized, metrics)

    def _malformed_book_reason(self, signal: SignalCandidate, orderbook: OrderBook) -> str | None:
        if orderbook.token_id != signal.token_id:
            return "MALFORMED_ORDERBOOK"
        if any(
            not isfinite(level.price) or not isfinite(level.size) or level.price <= 0 or level.size <= 0
            for level in [*orderbook.asks, *orderbook.bids]
        ):
            return "MALFORMED_ORDERBOOK"
        return None

    def _stale_reason(self, token_id: str, orderbook: OrderBook, now: datetime) -> str | None:
        if self.registry is not None:
            if self.registry.is_fill_eligible(token_id, self.max_book_staleness_ms, now):
                return None
            state = self.registry.get_state(token_id)
            return state.stale_reason if state and state.stale_reason else "NO_SNAPSHOT"
        if not orderbook.is_fresh(self.max_book_staleness_ms, now):
            return "STALE_ORDERBOOK"
        return None

    def _fak_fill_price(self, signal: SignalCandidate, orderbook: OrderBook) -> float | None:
        remaining = self.fixed_stake_usdc
        filled_usdc = 0.0
        shares = 0.0
        for level in sorted(orderbook.asks, key=lambda ask: ask.price):
            if level.price > signal.max_entry_price:
                break
            take = min(remaining, level.price * level.size)
            filled_usdc += take
            shares += take / level.price
            remaining -= take
            if remaining <= 0:
                break
        if filled_usdc <= 0 or shares <= 0:
            return None
        return filled_usdc / shares

    def _edge_reason(
        self,
        signal: SignalCandidate,
        execution_ask: float,
        metrics: dict[str, bool | float | str | None],
    ) -> str | None:
        signal_metrics: dict[str, Any] = signal.metrics
        metrics["paper_edge_revalidated"] = False
        min_probability_edge = _finite_float(signal_metrics.get("min_probability_edge"))
        directional_probability = _finite_float(signal_metrics.get("directional_probability"))
        if min_probability_edge is not None and min_probability_edge > 0 and directional_probability is not None:
            current_edge = directional_probability - execution_ask
            metrics["paper_execution_probability_edge"] = current_edge
            metrics["paper_required_probability_edge"] = min_probability_edge
            metrics["paper_edge_revalidated"] = True
            if current_edge < min_probability_edge:
                return PAPER_EDGE_VANISHED
            return None
        min_token_price = _finite_float(signal_metrics.get("min_token_price"))
        if min_token_price is not None and min_token_price > 0:
            metrics["paper_execution_min_token_price"] = min_token_price
            metrics["paper_edge_revalidated"] = True
            if execution_ask < min_token_price:
                return PAPER_EDGE_VANISHED
            return None
        stored_probability_edge = _finite_float(signal_metrics.get("probability_edge"))
        entry_prob = _finite_float(signal_metrics.get("entry_prob"))
        if (
            stored_probability_edge is not None
            and stored_probability_edge > 0
            and entry_prob is not None
            and directional_probability is not None
        ):
            current_edge = directional_probability - execution_ask
            metrics["paper_execution_probability_edge"] = current_edge
            metrics["paper_required_probability_edge"] = stored_probability_edge
            metrics["paper_entry_probability"] = entry_prob
            metrics["paper_edge_revalidated"] = True
            if current_edge < stored_probability_edge:
                return PAPER_EDGE_VANISHED
            return None
        return None


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None
