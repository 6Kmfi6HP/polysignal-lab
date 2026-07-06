from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from polysignal_lab.app.scheduler_reporting import check_settlements
from polysignal_lab.domain.enums import MarketStatus, PositionStatus, Side, TradeResultStatus
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.paper.settlement import PaperSettlementEngine
from polysignal_lab.paper.settlement_sources import ResolutionDecision


class _LedgerWallet:
    def __init__(self, starting_balance: float) -> None:
        self.starting_balance = starting_balance
        self.cash_balance = starting_balance
        self.realized_pnl = 0.0
        self.open_positions: dict[str, PaperPosition] = {}

    def apply_fill(self, position: PaperPosition) -> None:
        self.open_positions[position.paper_position_id] = position
        self.cash_balance -= position.stake_usdc

    @property
    def open_position_count(self) -> int:
        return len(self.open_positions)


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


def _position(token_id: str = "token-up", side: Side = Side.UP) -> PaperPosition:
    return PaperPosition(
        signal_id="sig-1",
        paper_order_id="order-1",
        paper_fill_id="fill-1",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="market-1",
        market_slug="slug",
        token_id=token_id,
        side=side,
        entry_price=0.40,
        shares=25.0,
        stake_usdc=10.0,
    )


def _scheduler(wallet: _LedgerWallet, market: Market, decision: ResolutionDecision) -> Mock:
    scheduler = Mock()
    scheduler.wallet = wallet
    scheduler.settlement = PaperSettlementEngine()
    scheduler.settlement_resolver = AsyncMock()
    scheduler.settlement_resolver.resolve_market.return_value = decision
    scheduler.ctx.markets.get.return_value = market
    scheduler.persistence.insert_paper_trade_result.return_value = None
    scheduler.persistence.upsert_paper_position.return_value = None
    scheduler.persistence.append_log.return_value = None
    scheduler.persistence.insert_system_event.return_value = None
    scheduler.settings.telegram.send_paper_results = False
    return scheduler


@pytest.mark.skip(reason="Task 5: wallet-based settlement removed; projection path pending")
@pytest.mark.anyio
async def test_resolved_numeric_half_payout_closes_as_void_with_provenance() -> None:
    wallet = _LedgerWallet(1000.0)
    position = _position()
    wallet.apply_fill(position)
    scheduler = _scheduler(
        wallet,
        _market(),
        ResolutionDecision("market-1", "0x" + "1" * 64, "resolved", "chain", {"token-up": 0.5, "token-down": 0.5}, False, (), {"settlement_source": "chain", "condition_id": "0x" + "1" * 64}),
    )

    results = await check_settlements(scheduler)

    assert len(results) == 1
    assert results[0].result == TradeResultStatus.VOID
    assert results[0].outcome_value == 0.5
    assert results[0].settlement_value == 12.5
    assert results[0].details["settlement_source"] == "chain"
    assert position.status == PositionStatus.CLOSED


@pytest.mark.skip(reason="Task 5: wallet-based settlement removed; projection path pending")
@pytest.mark.anyio
async def test_unknown_settlement_preserves_existing_active_exit_evaluation() -> None:
    wallet = _LedgerWallet(1000.0)
    position = _position()
    wallet.apply_fill(position)
    decision = ResolutionDecision("market-1", "0x" + "1" * 64, "unknown", "none", {}, False, (), {"reason": "NO_RESOLVED_EVIDENCE"})
    scheduler = _scheduler(wallet, _market(MarketStatus.ACTIVE), decision)
    scheduler.ctx.books.get.return_value = object()
    scheduler.exits.evaluate.return_value = None

    results = await check_settlements(scheduler)

    assert results == []
    scheduler.exits.evaluate.assert_called_once_with(position, scheduler.ctx.books.get.return_value)
    assert position.status == PositionStatus.OPEN


@pytest.mark.skip(reason="Task 5: wallet-based settlement removed; projection path pending")
@pytest.mark.anyio
async def test_cancelled_decision_uses_refund_path() -> None:
    wallet = _LedgerWallet(1000.0)
    position = _position()
    wallet.apply_fill(position)
    decision = ResolutionDecision("market-1", "0x" + "1" * 64, "cancelled", "gamma", {}, False, (), {"settlement_source": "gamma"})
    scheduler = _scheduler(wallet, _market(MarketStatus.CLOSED), decision)

    results = await check_settlements(scheduler)

    assert results[0].result == TradeResultStatus.VOID
    assert results[0].outcome_value == position.entry_price
    assert results[0].settlement_value == position.stake_usdc


@pytest.mark.skip(reason="Task 5: wallet-based settlement removed; projection path pending")
@pytest.mark.anyio
async def test_chain_conflict_settlement_logs_system_event() -> None:
    wallet = _LedgerWallet(1000.0)
    position = _position()
    wallet.apply_fill(position)
    decision = ResolutionDecision("market-1", "0x" + "1" * 64, "resolved", "chain", {"token-up": 1.0, "token-down": 0.0}, True, ("gamma",), {"settlement_source": "chain", "settlement_conflict": True})
    scheduler = _scheduler(wallet, _market(), decision)

    results = await check_settlements(scheduler)

    assert results[0].result == TradeResultStatus.WIN
    scheduler.persistence.insert_system_event.assert_called_once()
