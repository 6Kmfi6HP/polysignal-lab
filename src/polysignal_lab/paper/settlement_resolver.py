from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
from typing import Protocol

from polysignal_lab.domain.market import Market
from polysignal_lab.paper.settlement_sources import ResolutionDecision, SettlementEvidence, WsResolutionCache, choose_decision


class ChainResolutionSource(Protocol):
    async def get_payouts(self, condition_id: str, token_ids: tuple[str, ...]) -> SettlementEvidence: ...


class GammaResolutionSource(Protocol):
    async def get_market(self, market: Market) -> SettlementEvidence: ...


class SettlementResolver:
    def __init__(self, chain: ChainResolutionSource | None, gamma: GammaResolutionSource | None, ws_cache: WsResolutionCache | None, *, logger: logging.Logger) -> None:
        self.chain = chain
        self.gamma = gamma
        self.ws_cache = ws_cache
        self.logger = logger

    async def resolve_market(self, market: Market) -> ResolutionDecision:
        token_ids = tuple(token.token_id for token in market.outcome_tokens)
        pending: list[tuple[str, object]] = []
        if self.chain is not None:
            pending.append(("chain", self.chain.get_payouts(market.condition_id, token_ids)))
        if self.gamma is not None:
            pending.append(("gamma", self.gamma.get_market(market)))

        evidence: list[SettlementEvidence] = []
        if pending:
            results = await asyncio.gather(*(task for _, task in pending), return_exceptions=True)
            for (source, _), result in zip(pending, results, strict=True):
                if isinstance(result, Exception):
                    self.logger.warning("settlement %s source failed for %s: %s", source, market.market_id, result)
                    evidence.append(SettlementEvidence(source, "authoritative" if source == "chain" else "exact", market.market_id, market.market_slug, market.condition_id, {}, "error", datetime.now(UTC), error=str(result)[:240]))
                else:
                    evidence.append(result)

        if self.ws_cache is not None:
            ws_evidence = self.ws_cache.evidence_for(market)
            if ws_evidence is not None:
                evidence.append(ws_evidence)

        return choose_decision(evidence, market)
