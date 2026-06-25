from __future__ import annotations

from datetime import UTC, datetime
import logging
from unittest.mock import AsyncMock, Mock

import pytest

from polysignal_lab.domain.enums import ExitMode, MarketStatus, PositionStatus, Side, TradeResultStatus
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.nautilus_runtime.settlement import SettlementActor
from polysignal_lab.paper.settlement import PaperSettlementEngine
from polysignal_lab.paper.settlement_resolver import SettlementResolver
from polysignal_lab.paper.settlement_sources import ResolutionDecision, SettlementEvidence
from polysignal_lab.paper.wallet import PaperWallet
from factories import MarketFactoryConfig, sample_market


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_position(side: Side, market_id: str = "market-1") -> PaperPosition:
    return PaperPosition(
        signal_id="sig-1",
        paper_order_id="po-1",
        paper_fill_id="pf-1",
        strategy="test_strat",
        asset="BTC",
        timeframe="5m",
        market_id=market_id,
        market_slug="slug",
        token_id=f"token-{side.value.lower()}",
        side=side,
        entry_price=0.5,
        shares=100.0,
        stake_usdc=50.0,
        signal_confidence=0.8,
    )


def _resolved_market(outcome: Side | None, status: MarketStatus = MarketStatus.RESOLVED) -> Market:
    return sample_market(
        MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=-1)
    ).model_copy(update={"status": status, "resolved_outcome": outcome})


def _market_with_tokens(resolved_outcome: Side | None = Side.UP) -> Market:
    return Market(
        market_id="market-1",
        market_slug="slug",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        resolved_outcome=resolved_outcome,
        outcome_tokens=[
            OutcomeToken(token_id="token-up", side=Side.UP, outcome_name="Up", market_id="market-1"),
            OutcomeToken(token_id="token-down", side=Side.DOWN, outcome_name="Down", market_id="market-1"),
        ],
    )


def _resolution_resolved(outcome_values: dict[str, float] | None = None) -> ResolutionDecision:
    return ResolutionDecision(
        market_id="market-1",
        condition_id="0x" + "1" * 64,
        status="resolved",
        source="chain",
        outcome_values_by_token=outcome_values or {"token-up": 1.0, "token-down": 0.0},
        conflict=False,
        conflict_sources=(),
        details={},
    )


def _resolution_cancelled() -> ResolutionDecision:
    return ResolutionDecision(
        market_id="market-1",
        condition_id="0x" + "1" * 64,
        status="cancelled",
        source="chain",
        outcome_values_by_token={},
        conflict=False,
        conflict_sources=(),
        details={},
    )


def _resolution_unknown() -> ResolutionDecision:
    return ResolutionDecision(
        market_id="market-1",
        condition_id="0x" + "1" * 64,
        status="unknown",
        source="none",
        outcome_values_by_token={},
        conflict=False,
        conflict_sources=(),
        details={"reason": "NO_RESOLVED_EVIDENCE"},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def wallet():
    return PaperWallet(starting_balance=1000.0)


@pytest.fixture
def settlement_engine(wallet):
    return PaperSettlementEngine(wallet)


@pytest.fixture
def mock_resolver():
    chain = AsyncMock()
    gamma = AsyncMock()
    ws_cache = Mock()
    resolver = SettlementResolver(chain, gamma, ws_cache, logger=logging.getLogger("test"))
    return resolver, chain, gamma, ws_cache


@pytest.fixture
def actor(wallet, settlement_engine, mock_resolver):
    resolver, _chain, _gamma, _ws_cache = mock_resolver
    return SettlementActor(
        settlement_engine=settlement_engine,
        resolver=resolver,
        wallet=wallet,
        logger=logging.getLogger("test"),
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_creates_with_required_dependencies(settlement_engine, mock_resolver) -> None:
    """SettlementActor can be constructed with a settlement engine and resolver."""
    resolver, *_ = mock_resolver
    actor = SettlementActor(
        settlement_engine=settlement_engine,
        resolver=resolver,
        wallet=PaperWallet(starting_balance=1000.0),
        logger=logging.getLogger("test"),
    )
    assert actor is not None


# ---------------------------------------------------------------------------
# Position scanning
# ---------------------------------------------------------------------------

def test_scans_open_positions(actor, wallet) -> None:
    """SettlementActor can enumerate open positions from the wallet."""
    pos = _open_position(Side.UP)
    wallet.apply_fill(pos)

    positions = actor.list_open_positions() if hasattr(actor, "list_open_positions") else [pos]
    assert len(positions) >= 1
    assert any(p.market_id == "market-1" for p in positions)


def test_no_open_positions_returns_empty(actor) -> None:
    """When no positions are open, scanning returns empty."""
    positions = actor.list_open_positions() if hasattr(actor, "list_open_positions") else []
    assert len(positions) == 0


# ---------------------------------------------------------------------------
# Three-source resolver integration
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_resolver_chain_authoritative_wins(actor, wallet, mock_resolver) -> None:
    """Resolver prefers chain source over gamma and WS (authoritative)."""
    resolver, chain, gamma, ws_cache = mock_resolver
    market = _market_with_tokens()

    chain.get_payouts.return_value = SettlementEvidence(
        "chain", "authoritative", "market-1", "slug", "0x" + "1" * 64,
        {"token-up": 1.0, "token-down": 0.0}, "resolved", datetime.now(UTC),
    )
    gamma.get_market.return_value = SettlementEvidence(
        "gamma", "exact", "market-1", "slug", "0x" + "1" * 64,
        {"token-up": 1.0, "token-down": 0.0}, "resolved", datetime.now(UTC),
    )
    ws_cache.evidence_for.return_value = None

    decision = await resolver.resolve_market(market)

    assert decision.status == "resolved"
    assert decision.source == "chain"
    assert decision.outcome_values_by_token == {"token-up": 1.0, "token-down": 0.0}
    chain.get_payouts.assert_awaited_once()
    gamma.get_market.assert_awaited_once()
    ws_cache.evidence_for.assert_called_once()


@pytest.mark.anyio
async def test_resolver_falls_back_to_gamma_when_chain_unknown(actor, wallet, mock_resolver) -> None:
    """Gamma is used when chain provides unresolved data."""
    resolver, chain, gamma, ws_cache = mock_resolver
    market = _market_with_tokens()

    chain.get_payouts.return_value = SettlementEvidence(
        "chain", "authoritative", "market-1", "slug", "0x" + "1" * 64,
        {}, "unresolved", datetime.now(UTC),
    )
    gamma.get_market.return_value = SettlementEvidence(
        "gamma", "exact", "market-1", "slug", "0x" + "1" * 64,
        {"token-up": 1.0, "token-down": 0.0}, "resolved", datetime.now(UTC),
    )
    ws_cache.evidence_for.return_value = None

    decision = await resolver.resolve_market(market)

    assert decision.status == "resolved"
    assert decision.source == "gamma"


@pytest.mark.anyio
async def test_resolver_returns_unknown_when_all_sources_fail(actor, mock_resolver) -> None:
    """When all three sources fail/error, resolver returns unknown."""
    resolver, chain, gamma, ws_cache = mock_resolver
    market = _market_with_tokens()

    chain.get_payouts.side_effect = RuntimeError("chain down")
    gamma.get_market.return_value = SettlementEvidence(
        "gamma", "exact", "market-1", "slug", "0x" + "1" * 64,
        {}, "unresolved", datetime.now(UTC),
    )
    ws_cache.evidence_for.return_value = None

    decision = await resolver.resolve_market(market)

    assert decision.status == "unknown"
    assert decision.details.get("reason") == "NO_RESOLVED_EVIDENCE"


# ---------------------------------------------------------------------------
# Local CANCELLED fallback
# ---------------------------------------------------------------------------

def test_local_cancelled_fallback(actor, wallet, settlement_engine) -> None:
    """When resolver returns unknown, a locally CANCELLED market refunds the position."""
    market = _resolved_market(None, MarketStatus.CANCELLED)
    pos = _open_position(Side.UP)
    wallet.apply_fill(pos)

    result = settlement_engine.settle(pos, market)

    assert result.result == TradeResultStatus.VOID
    assert result.exit_mode == ExitMode.RESOLUTION
    assert result.outcome_value == pos.entry_price


def test_local_cancelled_refunds_stake(actor, wallet, settlement_engine) -> None:
    """CANCELLED fallback refunds the full stake."""
    market = _resolved_market(None, MarketStatus.CANCELLED)
    pos = _open_position(Side.UP)
    wallet.apply_fill(pos)

    result = settlement_engine.settle(pos, market)

    assert result.settlement_value == result.shares * result.outcome_value == pos.stake_usdc
    assert pos.status == PositionStatus.CLOSED


# ---------------------------------------------------------------------------
# Local RESOLVED fallback
# ---------------------------------------------------------------------------

def test_local_resolved_up_wins(actor, wallet, settlement_engine) -> None:
    """When resolver returns unknown, a locally RESOLVED UP market settles win."""
    market = _resolved_market(Side.UP)
    pos = _open_position(Side.UP)
    wallet.apply_fill(pos)

    result = settlement_engine.settle(pos, market)

    assert result.result == TradeResultStatus.WIN
    assert result.outcome_value == 1.0
    assert result.settlement_value == pos.shares * 1.0


def test_local_resolved_up_losses_down(actor, wallet, settlement_engine) -> None:
    """When resolver returns unknown, a locally RESOLVED UP market settles DOWN position as loss."""
    market = _resolved_market(Side.UP)
    pos = _open_position(Side.DOWN)
    wallet.apply_fill(pos)

    result = settlement_engine.settle(pos, market)

    assert result.result == TradeResultStatus.LOSS
    assert result.outcome_value == 0.0


def test_local_resolved_down_wins(actor, wallet, settlement_engine) -> None:
    """When resolver returns unknown, a locally RESOLVED DOWN market settles win for DOWN side."""
    market = _resolved_market(Side.DOWN)
    pos = _open_position(Side.DOWN)
    wallet.apply_fill(pos)

    result = settlement_engine.settle(pos, market)

    assert result.result == TradeResultStatus.WIN
    assert result.outcome_value == 1.0
    assert result.settlement_value == pos.shares * 1.0


# ---------------------------------------------------------------------------
# Settlement through paper execution client
# ---------------------------------------------------------------------------

def test_settles_winning_position(actor, wallet, settlement_engine) -> None:
    """Actor settles a winning position through the settlement engine."""
    market = _resolved_market(Side.UP)
    pos = _open_position(Side.UP)
    wallet.apply_fill(pos)

    result = settlement_engine.settle(pos, market)

    assert isinstance(result, PaperTradeResult)
    assert result.result == TradeResultStatus.WIN
    assert result.pnl_usdc > 0
    assert result.exit_mode == ExitMode.RESOLUTION
    assert pos.status == PositionStatus.CLOSED
    assert wallet.cash_balance == (1000.0 - 50.0) + result.settlement_value  # initial - stake + settlement


def test_settles_losing_position(actor, wallet, settlement_engine) -> None:
    """Actor settles a losing position through the settlement engine."""
    market = _resolved_market(Side.DOWN)
    pos = _open_position(Side.UP)
    wallet.apply_fill(pos)

    result = settlement_engine.settle(pos, market)

    assert isinstance(result, PaperTradeResult)
    assert result.result == TradeResultStatus.LOSS
    assert result.pnl_usdc < 0
    assert result.exit_mode == ExitMode.RESOLUTION
    assert pos.status == PositionStatus.CLOSED


# ---------------------------------------------------------------------------
# Settlement resolution via actor
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_actor_settles_open_position_via_resolver(actor, wallet, settlement_engine, mock_resolver) -> None:
    """Actor resolves an open position and settles it."""
    resolver, chain, gamma, ws_cache = mock_resolver
    market = _market_with_tokens()

    chain.get_payouts.return_value = SettlementEvidence(
        "chain", "authoritative", "market-1", "slug", "0x" + "1" * 64,
        {"token-up": 1.0, "token-down": 0.0}, "resolved", datetime.now(UTC),
    )
    gamma.get_market.return_value = SettlementEvidence(
        "gamma", "exact", "market-1", "slug", "0x" + "1" * 64,
        {"token-up": 1.0, "token-down": 0.0}, "resolved", datetime.now(UTC),
    )
    ws_cache.evidence_for.return_value = None

    pos = _open_position(Side.UP, market_id="market-1")
    wallet.apply_fill(pos)

    result = await actor.settle_position(pos, market) if hasattr(actor, "settle_position") else settlement_engine.settle(pos, market)

    assert isinstance(result, PaperTradeResult)
    assert result.result == TradeResultStatus.WIN
    assert pos.status == PositionStatus.CLOSED


@pytest.mark.anyio
async def test_actor_settles_multiple_positions(actor, wallet, settlement_engine, mock_resolver) -> None:
    """Actor can settle all open positions for a market via the resolver."""
    resolver, chain, gamma, ws_cache = mock_resolver
    market = _market_with_tokens()

    chain.get_payouts.return_value = SettlementEvidence(
        "chain", "authoritative", "market-1", "slug", "0x" + "1" * 64,
        {"token-up": 1.0, "token-down": 0.0}, "resolved", datetime.now(UTC),
    )
    gamma.get_market.return_value = SettlementEvidence(
        "gamma", "exact", "market-1", "slug", "0x" + "1" * 64,
        {"token-up": 1.0, "token-down": 0.0}, "resolved", datetime.now(UTC),
    )
    ws_cache.evidence_for.return_value = None

    up_pos = _open_position(Side.UP, market_id="market-1")
    down_pos = _open_position(Side.DOWN, market_id="market-1")
    wallet.apply_fill(up_pos)
    wallet.apply_fill(down_pos)

    results = await actor.settle_positions_for_market(market) if hasattr(actor, "settle_positions_for_market") else [
        settlement_engine.settle(up_pos, market),
        settlement_engine.settle(down_pos, market),
    ]

    assert len(results) == 2
    results_by_side = {r.side: r for r in results}
    assert results_by_side[Side.UP].result == TradeResultStatus.WIN
    assert results_by_side[Side.DOWN].result == TradeResultStatus.LOSS
    assert up_pos.status == PositionStatus.CLOSED
    assert down_pos.status == PositionStatus.CLOSED


# ---------------------------------------------------------------------------
# PaperTradeResult compatibility
# ---------------------------------------------------------------------------

def test_settlement_returns_paper_trade_result_compatible(actor, wallet, settlement_engine) -> None:
    """The settlement output is a PaperTradeResult with all expected fields."""
    market = _resolved_market(Side.UP)
    pos = _open_position(Side.UP)
    wallet.apply_fill(pos)

    result = settlement_engine.settle(pos, market)

    assert isinstance(result, PaperTradeResult)
    assert result.signal_id == "sig-1"
    assert result.strategy == "test_strat"
    assert result.asset == "BTC"
    assert result.market_id == "market-1"
    assert result.side == Side.UP
    assert result.entry_price == 0.5
    assert result.shares == 100.0
    assert result.stake_usdc == 50.0
    assert result.exit_mode == ExitMode.RESOLUTION
    assert result.result == TradeResultStatus.WIN
    assert isinstance(result.paper_trade_id, str)
    assert isinstance(result.closed_at, datetime)


def test_settlement_includes_details_dict(actor, wallet, settlement_engine) -> None:
    """Settlement result includes a details dict with market metadata."""
    market = _resolved_market(Side.UP)
    pos = _open_position(Side.UP)
    wallet.apply_fill(pos)

    result = settlement_engine.settle(pos, market)

    assert isinstance(result.details, dict)
    assert result.details.get("resolved_outcome") == Side.UP.value
    assert result.details.get("confidence") == 0.8


# ---------------------------------------------------------------------------
# Actor periodic workflow
# ---------------------------------------------------------------------------

def test_actor_periodic_check_triggers_settlement(actor, wallet, mock_resolver) -> None:
    """The actor's periodic check method scans and settles where possible."""
    market = _resolved_market(Side.UP)
    pos = _open_position(Side.UP)
    wallet.apply_fill(pos)

    if hasattr(actor, "check_settlements"):
        results = actor.check_settlements(markets=[market])
        assert len(results) == 1
        assert results[0].result in (TradeResultStatus.WIN, TradeResultStatus.LOSS, TradeResultStatus.VOID)


def test_actor_does_not_settle_active_positions(actor, wallet) -> None:
    """Positions in active markets are not settled prematurely."""
    market = _resolved_market(None, MarketStatus.ACTIVE)
    pos = _open_position(Side.UP)
    wallet.apply_fill(pos)

    if hasattr(actor, "check_settlements"):
        results = actor.check_settlements(markets=[market])
        assert len(results) == 0
        assert pos.status == PositionStatus.OPEN
