from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from polysignal_lab.alpha.types import AlphaDecision, NautilusOrderSpec
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision


def order_spec_from_decision(
    decision: ApprovedDecision | AlphaDecision | SignalCandidate,
    fixed_stake_usdc: float,
    best_ask: float | None = None,
    available_shares: float | None = None,
) -> NautilusOrderSpec:
    source = _decision_source(decision)
    max_price = _positive_float(source.max_entry_price, "max_entry_price")
    intent = _intent(source) or OrderIntent.TAKER_IOC
    expiry_seconds = _expiry_seconds(source)
    pair_id = _pair_id(source)
    metrics = dict(getattr(source, "metrics", {}) or {})
    if available_shares is None:
        available_shares = _metric_float(
            metrics, "available_ask_shares", "ask_available_shares", "depth_shares"
        )

    explicit_intent = _intent(source)
    if explicit_intent is None:
        if best_ask is None:
            price = max_price
        else:
            price = _positive_float(best_ask, "best_ask")
            if price > max_price:
                raise ValueError(f"best ask {price} exceeds max entry price {max_price}")
    elif intent in {
        OrderIntent.TAKER_FAK,
        OrderIntent.TAKER_FOK,
        OrderIntent.TAKER_IOC,
    }:
        if best_ask is None:
            raise ValueError(f"{intent.value} requires best ask depth")
        price = _positive_float(best_ask, "best_ask")
        if price > max_price:
            raise ValueError(f"best ask {price} exceeds max entry price {max_price}")
    else:
        price = max_price

    contracts = _metric_float(metrics, "contracts")
    quantity = (
        _positive_float(contracts, "contracts")
        if contracts is not None
        else _positive_float(fixed_stake_usdc, "fixed_stake_usdc") / price
    )
    if intent == OrderIntent.TAKER_FOK:
        if available_shares is None or available_shares < quantity:
            raise ValueError("insufficient depth for full fill")
    elif available_shares is not None and available_shares <= 0:
        raise ValueError("insufficient depth for taker order")

    tags: dict[str, str] = {
        "strategy": str(source.strategy),
        "asset": str(source.asset),
        "timeframe": str(source.timeframe),
        "market_id": str(source.market_id),
        "market_slug": str(source.market_slug),
        "condition_id": str(source.condition_id),
        "confidence": str(source.confidence),
        "entry_reference_price": str(source.entry_reference_price),
        "max_entry_price": str(source.max_entry_price),
        "order_intent": intent.value,
    }
    signal_id = getattr(source, "signal_id", None)
    if signal_id is not None:
        tags["signal_id"] = str(signal_id)
    seconds_to_close = getattr(source, "seconds_to_close", None)
    if seconds_to_close is not None:
        tags["seconds_to_close"] = str(seconds_to_close)
    data_freshness_ms = getattr(source, "data_freshness_ms", None)
    if data_freshness_ms is not None:
        tags["data_freshness_ms"] = str(data_freshness_ms)
    reason_codes = getattr(source, "reason_codes", None)
    if reason_codes:
        tags["reason_codes"] = "|".join(str(code) for code in reason_codes)
    if bool(getattr(source, "hedge_leg", False)):
        tags["hedge_leg"] = "true"
    if intent == OrderIntent.PASSIVE_GTD:
        tags["time_in_force"] = "GTD"
        if expiry_seconds is not None:
            tags["expire_seconds"] = str(expiry_seconds)
    elif intent == OrderIntent.TAKER_FOK:
        tags["time_in_force"] = "FOK"
    else:
        tags["time_in_force"] = "IOC"
        tags["fill_policy"] = "FAK" if intent == OrderIntent.TAKER_FAK else "IOC"
        if _intent(source) is None:
            tags["paper_safe_default"] = "true"

    return NautilusOrderSpec(
        instrument_id=str(source.token_id),
        side=source.side,
        price=price,
        quantity=quantity,
        intent=intent,
        expiry_seconds=expiry_seconds,
        pair_id=pair_id,
        reduce_only=False,
        hedge_leg=bool(getattr(source, "hedge_leg", False)),
        tags=tags,
    )


def _decision_source(
    decision: ApprovedDecision | AlphaDecision | SignalCandidate,
) -> AlphaDecision | SignalCandidate:
    if isinstance(decision, ApprovedDecision):
        return decision.signal
    return decision


def _intent(source: AlphaDecision | SignalCandidate) -> OrderIntent | None:
    raw = getattr(source, "order_intent", None)
    if raw is None:
        return None
    if isinstance(raw, OrderIntent):
        return raw
    value = getattr(raw, "intent", raw)
    return value if isinstance(value, OrderIntent) else OrderIntent(value)


def _expiry_seconds(source: AlphaDecision | SignalCandidate) -> int | None:
    raw = getattr(source, "order_intent", None)
    value = getattr(raw, "expiry_seconds", None)
    if value is None and (raw is None or isinstance(raw, OrderIntent)):
        value = getattr(source, "expiry_seconds", None)
    return int(value) if value is not None else None


def _pair_id(source: AlphaDecision | SignalCandidate) -> str | None:
    raw = getattr(source, "order_intent", None)
    value = getattr(raw, "pair_id", None)
    if value is None and (raw is None or isinstance(raw, OrderIntent)):
        value = getattr(source, "pair_id", None)
    return str(value) if value is not None else None


def _positive_float(value: float, name: str) -> float:
    number = float(value)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _metric_float(metrics: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = metrics.get(name)
        if value is not None:
            return float(value)
    return None


# ── Paper Execution Client ─────────────────────────────────────────────────


from polysignal_lab.config import FillModelConfig  # noqa: E402
from polysignal_lab.data.state import OrderBookRegistry  # noqa: E402
from polysignal_lab.domain.enums import OrderStatus, Side  # noqa: E402
from polysignal_lab.domain.orderbook import OrderBook  # noqa: E402
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder  # noqa: E402
from polysignal_lab.domain.paper_position import PaperPosition  # noqa: E402
from polysignal_lab.paper.order_intent_executor import (  # noqa: E402
    BestAskTakerExecutor,
    PassiveGtdExecutor,
)
from polysignal_lab.paper.wallet import PaperWallet  # noqa: E402
from polysignal_lab.utils import new_id, utc_now  # noqa: E402


@dataclass
class PaperExecutionResult:
    order: PaperOrder | None = None
    fills: list[PaperFill] = field(default_factory=list)
    positions: list[PaperPosition] = field(default_factory=list)
    status: OrderStatus = OrderStatus.PENDING
    reason: str | None = None


class PolySignalPaperExecutionClient:
    """Paper-only execution client for the Nautilus runtime.

    Submits orders against local OrderBook data — no network I/O, no credentials.
    Drives fills through existing PaperFillModel/OrderIntentExecutor infrastructure.
    """

    def __init__(
        self,
        wallet: PaperWallet | None = None,
        registry: OrderBookRegistry | None = None,
        fill_config: FillModelConfig | None = None,
        order_book_data: dict[str, OrderBook] | None = None,
        max_book_staleness_ms: int = 10_000,
    ) -> None:
        self.wallet = wallet or PaperWallet(starting_balance=10_000.0)
        self.registry = registry
        self._fill_config = fill_config or FillModelConfig()
        self._taker_executor = BestAskTakerExecutor(
            self._fill_config, max_book_staleness_ms=max_book_staleness_ms,
            registry=registry,
        )
        self._book_for_token: dict[str, OrderBook] = dict(order_book_data) if order_book_data else {}

    # -- book data injection (from Nautilus data) --

    def update_book(self, token_id: str, book: OrderBook) -> None:
        self._book_for_token[token_id] = book

    def book_for(self, token_id: str) -> OrderBook | None:
        return self._book_for_token.get(token_id)

    # -- Nautilus-style order submission --

    def submit_spec(self, spec: NautilusOrderSpec) -> PaperExecutionResult:
        """Submit a NautilusOrderSpec directly (convenience wrapper)."""
        return self.execute_order(
            instrument_id=spec.instrument_id,
            side=spec.side,
            price=spec.price,
            quantity=spec.quantity,
            intent=spec.intent,
            expiry_seconds=spec.expiry_seconds,
            pair_id=spec.pair_id,
            reduce_only=spec.reduce_only,
            hedge_leg=spec.hedge_leg,
            tags=dict(spec.tags) if spec.tags else None,
            strategy_name=spec.tags.get("strategy", "") if spec.tags else "",
            token_id=spec.instrument_id,
        )

    def execute_order(
        self,
        instrument_id: str,
        side: Side,
        price: float,
        quantity: float,
        intent: OrderIntent,
        expiry_seconds: int | None = None,
        pair_id: str | None = None,
        reduce_only: bool = False,
        hedge_leg: bool = False,
        tags: dict[str, str] | None = None,
        strategy_name: str = "",
        token_id: str = "",
        condition_id: str = "",
        market_id: str = "",
    ) -> PaperExecutionResult:
        """Execute a paper order with the given parameters."""
        book = self._book_for_token.get(token_id)
        order_id = new_id("paper")
        now = utc_now()
        limit_price = price
        max_entry_price = _tag_float(tags, "max_entry_price")
        if max_entry_price is not None and intent in {
            OrderIntent.TAKER_FAK,
            OrderIntent.TAKER_FOK,
            OrderIntent.TAKER_IOC,
        }:
            limit_price = max_entry_price

        order = PaperOrder(
            paper_order_id=order_id,
            signal_id=tags.get("signal_id", "") if tags else "",
            token_id=token_id,
            side=side,
            limit_price=limit_price,
            stake_usdc=quantity * price,
            shares=quantity,
            asset=tags.get("asset", ""),
            timeframe=tags.get("timeframe", ""),
            strategy=strategy_name,
            market_id=market_id or tags.get("market_id", ""),
            market_slug=tags.get("market_slug", ""),
            reference_price=price,
            created_at=now,
            order_intent=intent,
            pair_id=pair_id,
            reduce_only=reduce_only,
            hedge_leg=hedge_leg,
            signal_confidence=_tag_float(tags, "confidence"),
            metrics={**(tags or {}), "strategy": strategy_name},
        )

        if book is None:
            return PaperExecutionResult(
                order=order,
                status=OrderStatus.REJECTED,
                reason="MISSING_ORDERBOOK",
            )

        result = self._taker_executor.execute(order, book, intent=intent)
        for position in result.positions:
            if self.wallet.can_afford(position.stake_usdc):
                self.wallet.apply_fill(position)
        return PaperExecutionResult(
            order=result.order,
            fills=result.fills,
            positions=result.positions,
            status=result.status,
            reason=result.reject_reason,
        )


def _tag_float(tags: dict[str, str] | None, key: str) -> float | None:
    if not tags or key not in tags:
        return None
    try:
        return float(tags[key])
    except (TypeError, ValueError):
        return None
