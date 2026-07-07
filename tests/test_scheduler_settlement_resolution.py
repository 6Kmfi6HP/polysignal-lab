"""
Input: __future__, __future__.annotations, types, types.SimpleNamespace, unittest.mock, unittest.mock.AsyncMock, unittest.mock.Mock, pytest, polysignal_lab.app.scheduler_reporting, polysignal_lab.app.scheduler_reporting.check_settlements
Output: test_resolved_numeric_half_payout_closes_as_void_with_provenance, test_unknown_settlement_skips_open_projection, test_cancelled_decision_uses_refund_path, test_check_settlements_is_idempotent_per_position, test_chain_conflict_settlement_logs_system_event
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from polysignal_lab.app.scheduler_reporting import check_settlements
from polysignal_lab.domain.enums import MarketStatus, Side, TradeResultStatus
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.paper.settlement_sources import ResolutionDecision


def _market(status: MarketStatus = MarketStatus.ACTIVE) -> Market:
    return Market(
        market_id="market-1",
        market_slug="slug",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        status=status,
        outcome_tokens=[
            OutcomeToken(token_id="token-up", side=Side.UP, outcome_name="Up", market_id="market-1"),
            OutcomeToken(token_id="token-down", side=Side.DOWN, outcome_name="Down", market_id="market-1"),
        ],
    )


def _projection(
    *,
    token_id: str = "token-up",
    side: Side = Side.UP,
    quantity: float = 25.0,
    entry_price: float = 0.40,
) -> dict[str, object]:
    return {
        "paper_position_id": "pos-1",
        "position_id": "pos-1",
        "market_id": "market-1",
        "token_id": token_id,
        "side": side.value,
        "quantity": quantity,
        "avg_entry_price": entry_price,
        "signal_id": "sig-1",
        "strategy": "ptb_diff",
        "asset": "BTC",
        "timeframe": "5m",
        "is_closed": False,
    }


def _scheduler(market: Market, decision: ResolutionDecision) -> Mock:
    scheduler = Mock()
    scheduler.settlement_resolver = AsyncMock()
    scheduler.settlement_resolver.resolve_market.return_value = decision
    scheduler.ctx.markets.get.return_value = market
    scheduler.nautilus_cache_reader = SimpleNamespace(
        read_positions=lambda: [_projection()],
    )
    scheduler.persistence.insert_paper_trade_result.return_value = None
    scheduler.persistence.append_log.return_value = None
    scheduler.persistence.insert_system_event.return_value = None
    scheduler.persistence.query_json.return_value = []
    scheduler.settings.telegram.send_paper_results = False
    return scheduler


@pytest.mark.anyio
async def test_resolved_numeric_half_payout_closes_as_void_with_provenance() -> None:
    scheduler = _scheduler(
        _market(),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "resolved",
            "chain",
            {"token-up": 0.5, "token-down": 0.5},
            False,
            (),
            {"settlement_source": "chain", "condition_id": "0x" + "1" * 64},
        ),
    )

    results = await check_settlements(scheduler)

    assert len(results) == 1
    assert results[0].result == TradeResultStatus.VOID
    assert results[0].outcome_value == 0.5
    assert results[0].settlement_value == 12.5
    assert results[0].details["settlement_source"] == "chain"


@pytest.mark.anyio
async def test_unknown_settlement_skips_open_projection() -> None:
    decision = ResolutionDecision(
        "market-1",
        "0x" + "1" * 64,
        "unknown",
        "none",
        {},
        False,
        (),
        {"reason": "NO_RESOLVED_EVIDENCE"},
    )
    scheduler = _scheduler(_market(MarketStatus.ACTIVE), decision)

    results = await check_settlements(scheduler)

    assert results == []
    scheduler.persistence.insert_paper_trade_result.assert_not_called()


@pytest.mark.anyio
async def test_cancelled_decision_uses_refund_path() -> None:
    scheduler = _scheduler(
        _market(MarketStatus.CLOSED),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "cancelled",
            "gamma",
            {},
            False,
            (),
            {"settlement_source": "gamma"},
        ),
    )

    results = await check_settlements(scheduler)

    assert results[0].result == TradeResultStatus.VOID
    assert results[0].outcome_value == 0.40
    assert results[0].settlement_value == 10.0


@pytest.mark.anyio
async def test_check_settlements_is_idempotent_per_position() -> None:
    stored: list[dict[str, object]] = []

    def query_json(table: str, **kwargs: object) -> list[dict[str, object]]:
        if table == "paper_trade_results":
            return list(stored)
        return []

    def insert_paper_trade_result(result: object) -> None:
        stored.append(result.model_dump())  # type: ignore[union-attr]

    scheduler = _scheduler(
        _market(),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "resolved",
            "chain",
            {"token-up": 1.0, "token-down": 0.0},
            False,
            (),
            {"settlement_source": "chain"},
        ),
    )
    scheduler.persistence.query_json = query_json
    scheduler.persistence.insert_paper_trade_result = insert_paper_trade_result

    first = await check_settlements(scheduler)
    second = await check_settlements(scheduler)

    assert len(first) == 1
    assert second == []
    assert len(stored) == 1
    assert stored[0]["paper_position_id"] == "pos-1"


@pytest.mark.anyio
async def test_chain_conflict_settlement_logs_system_event() -> None:
    scheduler = _scheduler(
        _market(),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "resolved",
            "chain",
            {"token-up": 1.0, "token-down": 0.0},
            True,
            ("gamma",),
            {"settlement_source": "chain", "settlement_conflict": True},
        ),
    )

    results = await check_settlements(scheduler)

    assert results[0].result == TradeResultStatus.WIN
    scheduler.persistence.insert_system_event.assert_called_once()
