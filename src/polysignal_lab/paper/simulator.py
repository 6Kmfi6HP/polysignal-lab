from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from polysignal_lab.config import PaperTradingConfig, PolymarketDataConfig
from polysignal_lab.domain.enums import OrderIntent, OrderStatus
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.paper.fill_model import BestAskTakerFillModel, FillDecision
from polysignal_lab.paper.order_intent_executor import (
    BestAskTakerExecutor,
    IntentDispatchResult,
    MultiLegCoordinator,
    PassiveGtdExecutor,
)
from polysignal_lab.paper.wallet import PaperWallet


@dataclass
class SimulationResult:
    order: PaperOrder
    fill: PaperFill | None = None
    position: PaperPosition | None = None
    status: OrderStatus | None = None
    extra_fills: list[PaperFill] = field(default_factory=list)
    extra_positions: list[PaperPosition] = field(default_factory=list)


class PaperSimulator:
    def __init__(self, config: PaperTradingConfig, data_config: PolymarketDataConfig, wallet: PaperWallet):
        self.config = config
        self.wallet = wallet
        self.fill_model = BestAskTakerFillModel(config.fill_model, data_config.max_book_staleness_ms)
        self.taker = BestAskTakerExecutor(config.fill_model, data_config.max_book_staleness_ms)
        self.passive = PassiveGtdExecutor()
        self.pair_coordinator = MultiLegCoordinator()
        self.fill_notifier: Callable[[PaperOrder, str, PaperFill | None], None] | None = None

    def build_paper_order(self, signal: SignalCandidate) -> PaperOrder:
        return PaperOrder(
            signal_id=signal.signal_id,
            asset=signal.asset,
            timeframe=signal.timeframe,
            strategy=signal.strategy,
            market_id=signal.market_id,
            market_slug=signal.market_slug,
            token_id=signal.token_id,
            side=signal.side,
            limit_price=signal.max_entry_price,
            reference_price=signal.entry_reference_price,
            stake_usdc=self.config.fixed_stake_usdc,
        )

    def process_signal(self, signal: SignalCandidate, orderbook: OrderBook | None) -> SimulationResult:
        order = self.build_paper_order(signal)
        if signal.order_intent is not None:
            order.order_intent = signal.order_intent.value
        rejection = self._paper_gate(order)
        if rejection:
            self._reject_order(order, rejection)
            return SimulationResult(order=order, status=OrderStatus.REJECTED)
        if orderbook is None:
            self._reject_order(order, "MISSING_ORDERBOOK")
            return SimulationResult(order=order, status=OrderStatus.REJECTED)

        intent = signal.order_intent

        if intent == OrderIntent.PASSIVE_GTD:
            result = self.passive.enqueue(order, signal)
            return self._to_result(result)

        if intent in (OrderIntent.TAKER_FAK, OrderIntent.TAKER_FOK):
            if signal.pair_id:
                self.pair_coordinator.register(signal)
            # Only use atomic FOK pair coordination when both legs are TAKER_FOK
            # and the first leg was already recorded as pending. Otherwise execute
            # independently — the pair_id is for strategy tracking, not simulator atomicity.
            if (
                intent == OrderIntent.TAKER_FOK
                and not signal.hedge_leg
                and signal.pair_id
                and not self.pair_coordinator._pending_fok
            ):
                # First FOK leg of a potential pair — record and wait for hedge
                self.pair_coordinator.record_pending(signal, order, orderbook)
                return SimulationResult(order=order, status=OrderStatus.PENDING)
            elif (
                signal.hedge_leg
                and intent == OrderIntent.TAKER_FOK
                and signal.pair_id
                and self.pair_coordinator._pending_fok
            ):
                # Hedge leg arrived — try to execute the FOK pair atomically
                result = self.pair_coordinator.try_execute_fok_pair(
                    signal, order, orderbook, self.taker
                )
                if result is None:
                    self._reject_order(order, "FOK_PAIR_FAILED")
                    return SimulationResult(order=order, status=OrderStatus.REJECTED)
                self._apply_fills_to_wallet(result)
                return self._to_result(result)
            # Standalone execution: FAK legs, FOK legs without pending pair, hedge legs
            result = self.taker.execute(order, orderbook, intent)
            self._apply_fills_to_wallet(result)
            return self._to_result(result)

        # Default: existing best-ask taker
        decision = self.fill_model.fill(order, orderbook)
        order.metrics.update(self._decision_metrics(decision, orderbook, order))
        if not decision.accepted or decision.fill is None:
            self._reject_order(order, decision.reason_code or "FILL_REJECTED")
            return SimulationResult(order=order, status=OrderStatus.REJECTED)
        fill = decision.fill
        position = PaperPosition(
            signal_id=signal.signal_id,
            paper_order_id=order.paper_order_id,
            paper_fill_id=fill.paper_fill_id,
            strategy=signal.strategy,
            asset=signal.asset,
            timeframe=signal.timeframe,
            market_id=signal.market_id,
            market_slug=signal.market_slug,
            token_id=signal.token_id,
            side=signal.side,
            entry_price=fill.fill_price,
            shares=fill.shares,
            stake_usdc=fill.stake_usdc,
        )
        self.wallet.apply_fill(position)
        order.status = OrderStatus.FILLED
        return SimulationResult(order=order, fill=fill, position=position, status=OrderStatus.FILLED)

    def _to_result(self, intent_result: IntentDispatchResult) -> SimulationResult:
        first_fill = intent_result.fills[0] if intent_result.fills else None
        first_position = intent_result.positions[0] if intent_result.positions else None
        extra_fills = intent_result.fills[1:] if len(intent_result.fills) > 1 else []
        extra_positions = intent_result.positions[1:] if len(intent_result.positions) > 1 else []
        result = SimulationResult(
            order=intent_result.order,
            fill=first_fill,
            position=first_position,
            status=intent_result.status,
            extra_fills=extra_fills,
            extra_positions=extra_positions,
        )
        if intent_result.status == OrderStatus.REJECTED and intent_result.reject_reason:
            result.order.reject_reason = intent_result.reject_reason
        return result

    def _apply_fills_to_wallet(self, intent_result: IntentDispatchResult) -> None:
        for position in intent_result.positions:
            if self.wallet.can_afford(position.stake_usdc):
                self.wallet.apply_fill(position)

    def _decision_metrics(
        self,
        decision: FillDecision,
        orderbook: OrderBook,
        order: PaperOrder,
    ) -> dict[str, bool | float | str | None]:
        fill = decision.fill
        reason = decision.reason_code or ("FILLED" if decision.accepted else "FILL_REJECTED")
        metrics: dict[str, bool | float | str | None] = {
            "fill_decision_accepted": decision.accepted,
            "fill_decision_reason": reason,
            "orderbook_token_id": orderbook.token_id,
            "orderbook_fresh": orderbook.is_fresh(self.fill_model.max_book_staleness_ms, order.created_at),
            "orderbook_staleness_ms": float(orderbook.freshness_ms(order.created_at)),
            "raw_best_ask": orderbook.best_ask,
            "available_depth_usdc": decision.available_depth_usdc,
        }
        if fill is not None:
            metrics["fill_price"] = fill.fill_price
            metrics["fill_ratio"] = fill.fill_ratio
            metrics["shares"] = fill.shares
        return metrics

    def _reject_order(self, order: PaperOrder, reason: str) -> None:
        order.status = OrderStatus.REJECTED
        order.reject_reason = reason
        order.metrics.setdefault("fill_decision_accepted", False)
        order.metrics["fill_decision_reason"] = reason

    def _paper_gate(self, order: PaperOrder) -> str | None:
        if not self.wallet.can_afford(order.stake_usdc):
            return "WALLET_INSUFFICIENT_CASH"
        if self.wallet.open_position_count >= self.config.max_open_positions:
            return "MAX_OPEN_POSITIONS_REACHED"
        if self.wallet.exposure_by_market(order.market_id) + order.stake_usdc > self.config.max_market_exposure_usdc:
            return "EXPOSURE_LIMIT_REACHED"
        if self.wallet.exposure_by_strategy(order.strategy) + order.stake_usdc > self.config.max_strategy_exposure_usdc:
            return "EXPOSURE_LIMIT_REACHED"
        return None
