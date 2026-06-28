from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from polysignal_lab.domain.enums import MarketStatus, PositionStatus
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.paper.settlement import PaperSettlementEngine
from polysignal_lab.paper.settlement_resolver import SettlementResolver
from polysignal_lab.paper.settlement_sources import ResolutionDecision
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.utils import utc_now


class SettlementActor:
    """Settlement actor that resolves open positions through the three-source resolver.

    Integrates with the existing SettlementResolver (chain > Gamma > WS)
    and PaperSettlementEngine, preserving local CANCELLED / RESOLVED fallback.
    """

    def __init__(
        self,
        settlement_engine: PaperSettlementEngine,
        resolver: SettlementResolver | None = None,
        wallet: PaperWallet | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settlement_engine = settlement_engine
        self.resolver = resolver
        self.wallet = wallet or PaperWallet(starting_balance=10_000.0)
        self.logger = logger or logging.getLogger(__name__)

    def list_open_positions(self) -> list[PaperPosition]:
        """List all currently open positions from the wallet."""
        if self.wallet is None:
            return []
        return [p for p in self.wallet.open_positions.values() if p.status == PositionStatus.OPEN]

    async def resolve_market(
        self, market: Market
    ) -> ResolutionDecision | None:
        """Resolve a market through the three-source resolver."""
        if self.resolver is None:
            return None
        return await self.resolver.resolve_market(market)

    def settle_with_local_fallback(
        self,
        position: PaperPosition,
        market: Market,
    ) -> PaperTradeResult:
        """Settle a position with the settlement engine using local data."""
        return self.settlement_engine.settle(position, market)

    async def settle_position(
        self,
        position: PaperPosition,
        market: Market,
    ) -> PaperTradeResult | None:
        """Resolve a position: try remote resolver first, fall back to local."""
        decision = None
        if self.resolver is not None:
            decision = await self.resolver.resolve_market(market)

        if decision is not None and decision.status in ("resolved", "cancelled"):
            outcome_value = None
            for token in market.outcome_tokens:
                ov = decision.outcome_value_for(token.token_id)
                if ov is not None:
                    outcome_value = ov
                    break
            result = self.settlement_engine.settle(
                position, market, outcome_value=outcome_value,
                details={"resolved_by": decision.source},
            )
        else:
            # Local fallback: use Market model's own status/outcome
            result = self.settlement_engine.settle(position, market)

        return result

    async def periodic_check(
        self, markets: dict[str, Market] | None = None
    ) -> list[PaperTradeResult]:
        """Scan all open positions and settle any resolvable ones.

        Called periodically from the scheduler loop.
        """
        results: list[PaperTradeResult] = []
        positions = self.list_open_positions()
        if not positions:
            return results

        for position in positions:
            market = (markets or {}).get(position.market_id)
            if market is None:
                continue
            if market.status in (MarketStatus.ACTIVE, MarketStatus.UNKNOWN):
                continue

            result = await self.settle_position(position, market)
            if result is not None:
                results.append(result)

        return results
