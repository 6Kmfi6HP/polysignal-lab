from __future__ import annotations

from dataclasses import dataclass

from polysignal_lab.config import PaperTradingConfig, PolymarketDataConfig
from polysignal_lab.domain.enums import OrderStatus
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.paper.fill_model import BestAskTakerFillModel
from polysignal_lab.paper.wallet import PaperWallet


@dataclass
class SimulationResult:
    order: PaperOrder
    fill: PaperFill | None = None
    position: PaperPosition | None = None


class PaperSimulator:
    def __init__(self, config: PaperTradingConfig, data_config: PolymarketDataConfig, wallet: PaperWallet):
        self.config = config
        self.wallet = wallet
        self.fill_model = BestAskTakerFillModel(config.fill_model, data_config.max_book_staleness_ms)

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

    def process_signal(self, signal: SignalCandidate, orderbook: OrderBook) -> SimulationResult:
        order = self.build_paper_order(signal)
        rejection = self._paper_gate(order)
        if rejection:
            order.status = OrderStatus.REJECTED
            order.reject_reason = rejection
            return SimulationResult(order=order)
        decision = self.fill_model.fill(order, orderbook)
        if not decision.accepted or decision.fill is None:
            order.status = OrderStatus.REJECTED
            order.reject_reason = decision.reason_code
            if decision.available_depth_usdc is not None:
                order.metrics["available_depth_usdc"] = decision.available_depth_usdc
            return SimulationResult(order=order)
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
        return SimulationResult(order=order, fill=fill, position=position)

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
