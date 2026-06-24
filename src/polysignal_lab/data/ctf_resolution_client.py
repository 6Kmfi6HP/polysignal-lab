from __future__ import annotations

from datetime import UTC, datetime
import re

import httpx

from polysignal_lab.paper.settlement_sources import SettlementEvidence

SELECTOR_DENOMINATOR = "0xdd34de67"
SELECTOR_NUMERATORS = "0x0504c814"
SELECTOR_SLOT_COUNT = "0xd42dc0c2"
_CONDITION_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


class CtfResolutionClient:
    def __init__(self, rpc_url: str, *, timeout_sec: float, contract: str) -> None:
        self.rpc_url = rpc_url
        self.contract = contract
        self._http_client = httpx.AsyncClient(timeout=timeout_sec)

    async def get_payouts(self, condition_id: str, token_ids: tuple[str, ...]) -> SettlementEvidence:
        observed_at = datetime.now(UTC)
        if not _CONDITION_RE.fullmatch(condition_id):
            return self._error(condition_id, observed_at, "invalid condition_id")
        if len(token_ids) != 2:
            return self._error(condition_id, observed_at, "expected exactly two token_ids")

        try:
            condition_word = condition_id[2:].lower()
            denominator = await self._eth_call(SELECTOR_DENOMINATOR + condition_word)
            if denominator == 0:
                return SettlementEvidence("chain", "authoritative", None, None, condition_id, {}, "unresolved", observed_at, raw={"denominator": 0})

            slot_count = await self._eth_call(SELECTOR_SLOT_COUNT + condition_word)
            if slot_count != 2:
                return self._error(condition_id, observed_at, f"unsupported outcome slot count {slot_count}")

            numerators = []
            for index in (0, 1):
                numerators.append(await self._eth_call(SELECTOR_NUMERATORS + condition_word + hex(index)[2:].zfill(64)))
            if denominator > 0 and all(value == 0 for value in numerators):
                return self._error(condition_id, observed_at, "resolved condition has all-zero numerators")

            return SettlementEvidence(
                "chain",
                "authoritative",
                None,
                None,
                condition_id,
                {token_ids[0]: numerators[0] / denominator, token_ids[1]: numerators[1] / denominator},
                "resolved",
                observed_at,
                raw={"denominator": denominator, "numerators": numerators},
            )
        except Exception as exc:
            return self._error(condition_id, observed_at, str(exc)[:240])

    async def _eth_call(self, data: str) -> int:
        response = await self._http_client.post(
            self.rpc_url,
            json={"jsonrpc": "2.0", "method": "eth_call", "params": [{"to": self.contract, "data": data}, "latest"], "id": 1},
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(payload["error"])
        return int(str(payload["result"]), 16)

    @staticmethod
    def _error(condition_id: str, observed_at: datetime, message: str) -> SettlementEvidence:
        return SettlementEvidence("chain", "authoritative", None, None, condition_id, {}, "error", observed_at, error=message[:240])
