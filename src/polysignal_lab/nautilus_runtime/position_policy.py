from __future__ import annotations

from datetime import datetime

from polysignal_lab.domain.enums import ExitMode, PositionStatus, TradeResultStatus
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.utils import utc_now


class PositionPolicyActor:
    """Evaluates open positions for exit conditions.

    Checks take-profit bid, stop-loss bid, and max hold time against
    a PaperPosition. Strategy-specific exit metrics (tp_sl_tp_prob,
    flip_stop_price, etc.) remain in alpha cores — this actor only
    enforces the global ExitModelConfig thresholds.
    """

    def __init__(self, config: ExitModelConfig, wallet: PaperWallet | None = None) -> None:
        self.config = config
        self.wallet = wallet

    def evaluate(
        self,
        position: PaperPosition,
        current_bid: float | None = None,
        now: datetime | None = None,
    ) -> PaperTradeResult | None:
        """Check a position for exit conditions.

        Returns a PaperTradeResult if an exit condition is met, or None.
        """
        if position.status != PositionStatus.OPEN:
            return None
        current = now or utc_now()

        if current_bid is None:
            return None

        exit_mode: ExitMode | None = None

        # Check strategy-specific metrics first (preserved in alpha cores)
        metrics = position.signal_metrics or {}
        tp_prob = metrics.get("tp_sl_tp_prob")
        stop_prob = metrics.get("tp_sl_stop_prob")
        flip_stop = metrics.get("flip_stop_price")
        has_signal_exit = any(
            isinstance(metrics.get(k), int | float)
            for k in ("tp_sl_tp_prob", "tp_sl_stop_prob", "flip_stop_price")
        )

        if isinstance(tp_prob, int | float) and current_bid >= float(tp_prob):
            exit_mode = ExitMode.TAKE_PROFIT
        elif isinstance(stop_prob, int | float) and current_bid <= float(stop_prob):
            exit_mode = ExitMode.STOP_LOSS
        elif isinstance(flip_stop, int | float) and current_bid <= float(flip_stop):
            exit_mode = ExitMode.STOP_LOSS
        elif not has_signal_exit and self.config.take_profit_enabled and current_bid >= self.config.take_profit_price:
            exit_mode = ExitMode.TAKE_PROFIT
        elif not has_signal_exit and self.config.stop_loss_enabled and current_bid <= self.config.stop_loss_price:
            exit_mode = ExitMode.STOP_LOSS
        elif self.config.max_hold_time_sec and (
            current - position.opened_at
        ).total_seconds() >= self.config.max_hold_time_sec:
            exit_mode = ExitMode.MAX_HOLD_TIME

        if exit_mode is None:
            return None

        settlement_value = position.shares * current_bid
        pnl = settlement_value - position.stake_usdc
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
            exit_mode=exit_mode,
            outcome_value=current_bid,
            settlement_value=settlement_value,
            pnl_usdc=pnl,
            roi=pnl / position.stake_usdc if position.stake_usdc else 0.0,
            result=(
                TradeResultStatus.WIN if pnl > 0
                else TradeResultStatus.LOSS if pnl < 0
                else TradeResultStatus.VOID
            ),
            opened_at=position.opened_at,
            closed_at=current,
            details={"exit_mode": exit_mode.value, "bid": current_bid},
        )
        position.status = PositionStatus.CLOSED
        position.closed_at = current
        if self.wallet is not None:
            self.wallet.close_position(
                position.paper_position_id, settlement_value, pnl
            )
        return result
