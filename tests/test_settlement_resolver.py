"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, logging, unittest.mock, unittest.mock.AsyncMock, unittest.mock.Mock, pytest
Output: test_resolver_collects_chain_gamma_and_ws, test_resolver_turns_source_exception_into_retryable_decision
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import UTC, datetime
import logging
from unittest.mock import AsyncMock, Mock

import pytest

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.paper.settlement_resolver import SettlementResolver
from polysignal_lab.paper.settlement_sources import SettlementEvidence


def _market() -> Market:
    return Market(
        market_id="market-1",
        market_slug="slug",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="token-up", side=Side.UP, outcome_name="Up", market_id="market-1"),
            OutcomeToken(token_id="token-down", side=Side.DOWN, outcome_name="Down", market_id="market-1"),
        ],
    )


def _chain_result() -> SettlementEvidence:
    return SettlementEvidence("chain", "authoritative", "market-1", "slug", "0x" + "1" * 64, {"token-up": 1.0, "token-down": 0.0}, "resolved", datetime.now(UTC))


@pytest.mark.anyio
async def test_resolver_collects_chain_gamma_and_ws() -> None:
    chain = AsyncMock()
    gamma = AsyncMock()
    ws_cache = Mock()
    chain.get_payouts.return_value = _chain_result()
    gamma.get_market.return_value = SettlementEvidence("gamma", "exact", "market-1", "slug", "0x" + "1" * 64, {"token-up": 1.0, "token-down": 0.0}, "resolved", datetime.now(UTC))
    ws_cache.evidence_for.return_value = None

    decision = await SettlementResolver(chain, gamma, ws_cache, logger=logging.getLogger("test")).resolve_market(_market())

    assert decision.status == "resolved"
    assert decision.source == "chain"
    chain.get_payouts.assert_awaited_once_with("0x" + "1" * 64, ("token-up", "token-down"))
    gamma.get_market.assert_awaited_once()
    ws_cache.evidence_for.assert_called_once()


@pytest.mark.anyio
async def test_resolver_turns_source_exception_into_retryable_decision() -> None:
    chain = AsyncMock()
    gamma = AsyncMock()
    chain.get_payouts.side_effect = RuntimeError("rpc down")
    gamma.get_market.return_value = SettlementEvidence("gamma", "exact", "market-1", "slug", "0x" + "1" * 64, {}, "unresolved", datetime.now(UTC))

    decision = await SettlementResolver(chain, gamma, None, logger=logging.getLogger("test")).resolve_market(_market())

    assert decision.status == "unknown"
    assert decision.details["reason"] == "NO_RESOLVED_EVIDENCE"
