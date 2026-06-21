from __future__ import annotations

from dataclasses import dataclass, field

from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperWalletSnapshot


@dataclass
class PaperWallet:
    starting_balance: float = 1000.0
    wallet_id: str = "default"
    currency: str = "USDC"
    cash_balance: float | None = None
    realized_pnl: float = 0.0
    reserved_balance: float = 0.0
    open_positions: dict[str, PaperPosition] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cash_balance is None:
            self.cash_balance = float(self.starting_balance)

    @property
    def open_position_count(self) -> int:
        return len(self.open_positions)

    @property
    def equity(self) -> float:
        return float(self.cash_balance or 0.0) + sum(p.stake_usdc for p in self.open_positions.values())

    def can_afford(self, stake_usdc: float) -> bool:
        return (self.cash_balance or 0.0) >= stake_usdc

    def apply_fill(self, position: PaperPosition) -> None:
        if not self.can_afford(position.stake_usdc):
            raise ValueError("WALLET_INSUFFICIENT_CASH")
        self.cash_balance = round((self.cash_balance or 0.0) - position.stake_usdc, 10)
        self.open_positions[position.paper_position_id] = position

    def close_position(self, position_id: str, settlement_value: float, pnl_usdc: float) -> None:
        self.open_positions.pop(position_id, None)
        self.cash_balance = round((self.cash_balance or 0.0) + settlement_value, 10)
        self.realized_pnl = round(self.realized_pnl + pnl_usdc, 10)

    def exposure_by_market(self, market_id: str) -> float:
        return sum(p.stake_usdc for p in self.open_positions.values() if p.market_id == market_id)

    def exposure_by_strategy(self, strategy: str) -> float:
        return sum(p.stake_usdc for p in self.open_positions.values() if p.strategy == strategy)

    def snapshot(self) -> PaperWalletSnapshot:
        return PaperWalletSnapshot(
            wallet_id=self.wallet_id,
            currency=self.currency,
            starting_balance=self.starting_balance,
            cash_balance=float(self.cash_balance or 0.0),
            reserved_balance=self.reserved_balance,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=0.0,
            equity=self.equity,
            open_position_count=self.open_position_count,
        )
