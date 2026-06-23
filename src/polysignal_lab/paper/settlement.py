from __future__ import annotations

from polysignal_lab.domain.enums import ExitMode, MarketStatus, PositionStatus, Side, TradeResultStatus
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.utils import utc_now


class PaperSettlementEngine:
    def __init__(self, wallet: PaperWallet):
        self.wallet = wallet

    def settle(self, position: PaperPosition, market: Market, outcome_value: float | None = None) -> PaperTradeResult:
        if outcome_value is None:
            if market.status == MarketStatus.CANCELLED:
                status = TradeResultStatus.VOID
                outcome_value = position.entry_price
            elif market.resolved_outcome is None:
                status = TradeResultStatus.UNKNOWN
                outcome_value = 0.0
            elif market.resolved_outcome == position.side:
                status = TradeResultStatus.WIN
                outcome_value = 1.0
            else:
                status = TradeResultStatus.LOSS
                outcome_value = 0.0
        else:
            if outcome_value == 1.0:
                status = TradeResultStatus.WIN
            elif outcome_value == 0.0:
                status = TradeResultStatus.LOSS
            elif 0.0 < outcome_value < 1.0:
                status = TradeResultStatus.VOID
            else:
                status = TradeResultStatus.VOID
        settlement_value = position.shares * outcome_value
        pnl = settlement_value - position.stake_usdc
        closed_at = utc_now()
        result = PaperTradeResult(
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
            exit_mode=ExitMode.RESOLUTION,
            outcome_value=outcome_value,
            settlement_value=settlement_value,
            pnl_usdc=pnl,
            roi=pnl / position.stake_usdc if position.stake_usdc else 0.0,
            result=status,
            opened_at=position.opened_at,
            closed_at=closed_at,
            details={"resolved_outcome": market.resolved_outcome.value if market.resolved_outcome else None},
        )
        if status != TradeResultStatus.UNKNOWN:
            position.status = PositionStatus.CLOSED
            position.closed_at = closed_at
            self.wallet.close_position(position.paper_position_id, settlement_value, pnl)
        return result
