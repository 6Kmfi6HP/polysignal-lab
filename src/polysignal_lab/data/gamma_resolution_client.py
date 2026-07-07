"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, httpx, polysignal_lab.domain.market, polysignal_lab.domain.market.Market, polysignal_lab.paper.settlement_sources, polysignal_lab.paper.settlement_sources.SettlementEvidence
Output: GammaResolutionClient
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from datetime import UTC, datetime

import httpx

from polysignal_lab.domain.market import Market
from polysignal_lab.paper.settlement_sources import SettlementEvidence, parse_gamma_resolution_payload


class GammaResolutionClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._http_client = httpx.AsyncClient(timeout=5.0)

    async def get_market(self, market: Market) -> SettlementEvidence:
        try:
            response = await self._http_client.get(f"{self.base_url}/markets/{market.market_id}")
            if response.status_code == 404:
                response = await self._http_client.get(f"{self.base_url}/markets", params={"condition_ids": market.condition_id, "closed": "true"})
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list) or not data:
                    raise RuntimeError("Gamma condition_ids query returned no markets")
                payload = data[0]
            else:
                response.raise_for_status()
                payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("Gamma response was not an object")
            return parse_gamma_resolution_payload(payload, market)
        except Exception as exc:
            return SettlementEvidence("gamma", "exact", market.market_id, market.market_slug, market.condition_id, {}, "error", datetime.now(UTC), error=str(exc)[:240])
