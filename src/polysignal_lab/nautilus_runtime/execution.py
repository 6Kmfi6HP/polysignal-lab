from __future__ import annotations

from polysignal_lab.alpha.types import NautilusOrderSpec
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.nautilus_runtime.execution_types import PaperExecutionResult
from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision


# ── Paper Execution Client ─────────────────────────────────────────────────


from polysignal_lab.config import FillModelConfig  # noqa: E402
from polysignal_lab.data.state import OrderBookRegistry  # noqa: E402
from polysignal_lab.domain.enums import OrderStatus, Side  # noqa: E402
from polysignal_lab.domain.orderbook import OrderBook  # noqa: E402
from polysignal_lab.domain.paper_order import PaperOrder  # noqa: E402
from polysignal_lab.paper.order_intent_executor import (  # noqa: E402
    BestAskTakerExecutor,
    PassiveGtdExecutor,
)
from polysignal_lab.paper.wallet import PaperWallet  # noqa: E402
from polysignal_lab.utils import new_id, utc_now  # noqa: E402




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


def create_paper_execution_client(
    *,
    wallet: PaperWallet | None = None,
    registry: OrderBookRegistry | None = None,
    fill_config: FillModelConfig | None = None,
    order_book_data: dict[str, OrderBook] | None = None,
    max_book_staleness_ms: int = 10_000,
) -> PolySignalPaperExecutionClient:
    return PolySignalPaperExecutionClient(
        wallet=wallet,
        registry=registry,
        fill_config=fill_config,
        order_book_data=order_book_data,
        max_book_staleness_ms=max_book_staleness_ms,
    )


def _tag_float(tags: dict[str, str] | None, key: str) -> float | None:
    if not tags or key not in tags:
        return None
    try:
        return float(tags[key])
    except (TypeError, ValueError):
        return None
