from __future__ import annotations

from dataclasses import dataclass, field

from polysignal_lab.domain.enums import OrderStatus
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult


@dataclass(slots=True)
class PaperExecutionResult:
    order: PaperOrder | None = None
    fills: list[PaperFill] = field(default_factory=list)
    positions: list[PaperPosition] = field(default_factory=list)
    status: OrderStatus = OrderStatus.PENDING
    trade_results: list[PaperTradeResult] = field(default_factory=list)
    reason: str | None = None
