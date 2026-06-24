from __future__ import annotations

from datetime import datetime

from polysignal_lab.config import ExitModelConfig
from polysignal_lab.domain.enums import ExitMode, PositionStatus, TradeResultStatus
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.utils import utc_now


class PaperExitEngine:
    def __init__(self, config: ExitModelConfig, wallet: PaperWallet):
        self.config = config
        self.wallet = wallet

    def evaluate(self, position: PaperPosition, orderbook: OrderBook, now: datetime | None = None) -> PaperTradeResult | None:
        current = now or utc_now()
        bid = orderbook.best_bid
        if bid is None:
            return None
        exit_mode: ExitMode | None = None
        if self.config.take_profit_enabled and bid >= self.config.take_profit_price:
            exit_mode = ExitMode.TAKE_PROFIT
        elif self.config.stop_loss_enabled and bid <= self.config.stop_loss_price:
            exit_mode = ExitMode.STOP_LOSS
        elif self.config.max_hold_time_sec and (current - position.opened_at).total_seconds() >= self.config.max_hold_time_sec:
            exit_mode = ExitMode.MAX_HOLD_TIME
        if exit_mode is None:
            return None
        settlement_value = position.shares * bid
        pnl = settlement_value - position.stake_usdc
        result = TradeResultStatus.WIN if pnl > 0 else TradeResultStatus.LOSS if pnl < 0 else TradeResultStatus.VOID
        position.status = PositionStatus.CLOSED
        position.closed_at = current
        trade = PaperTradeResult(
            signal_id=position.signal_id,
            paper_position_id=position.paper_position_id,
            strategy=position.strategy,
            asset=position.asset,
            timeframe=position.timeframe,
            market_id=position.market_id,
            market_slug=position.market_slug,
            side=position.side,
            entry_price=position.entry_price,
            shares=position.shares,
            stake_usdc=position.stake_usdc,
            exit_mode=exit_mode,
            outcome_value=bid,
            settlement_value=settlement_value,
            pnl_usdc=pnl,
            roi=pnl / position.stake_usdc if position.stake_usdc else 0.0,
            result=result,
            opened_at=position.opened_at,
            closed_at=current,
            details={
                "paper_exit_price": bid,
                "confidence": position.signal_confidence,
            },
        )
        self.wallet.close_position(position.paper_position_id, settlement_value, pnl)
        return trade
