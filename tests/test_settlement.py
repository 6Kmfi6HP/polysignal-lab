from __future__ import annotations

from datetime import date

from polysignal_lab.domain.enums import (
    ExitMode,
    MarketStatus,
    PositionStatus,
    Side,
    TradeResultStatus,
)
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.paper.report import PaperReportService
from polysignal_lab.paper.settlement import PaperSettlementEngine
from polysignal_lab.paper.wallet import PaperWallet
from factories import MarketFactoryConfig, sample_market


def _open_position(side: Side) -> PaperPosition:
    return PaperPosition(
        signal_id=f"sig-{side.value.lower()}",
        paper_order_id=f"order-{side.value.lower()}",
        paper_fill_id=f"fill-{side.value.lower()}",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m-test",
        market_slug="btc-updown-5m-test",
        token_id=f"token-{side.value.lower()}",
        side=side,
        entry_price=0.40,
        shares=25.0,
        stake_usdc=10.0,
    )


def _resolved_market(outcome: Side | None, status: MarketStatus = MarketStatus.RESOLVED) -> Market:
    return sample_market(
        MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=-1)
    ).model_copy(update={"status": status, "resolved_outcome": outcome})


def test_resolved_up_and_down_positions_settle_win_loss() -> None:
    wallet = PaperWallet(starting_balance=1000.0)
    up_position = _open_position(Side.UP)
    down_position = _open_position(Side.DOWN)
    wallet.apply_fill(up_position)
    wallet.apply_fill(down_position)

    engine = PaperSettlementEngine(wallet)
    up_result = engine.settle(up_position, _resolved_market(Side.UP))
    down_result = engine.settle(down_position, _resolved_market(Side.UP))

    assert up_result.result == TradeResultStatus.WIN
    assert up_result.outcome_value == 1.0
    assert up_result.settlement_value == 25.0
    assert down_result.result == TradeResultStatus.LOSS
    assert down_result.outcome_value == 0.0
    assert down_result.settlement_value == 0.0
    assert up_position.status == PositionStatus.CLOSED
    assert down_position.status == PositionStatus.CLOSED
    assert wallet.open_position_count == 0


def test_void_market_refunds_position_without_split_result_state() -> None:
    wallet = PaperWallet(starting_balance=1000.0)
    position = _open_position(Side.UP)
    wallet.apply_fill(position)

    result = PaperSettlementEngine(wallet).settle(
        position, _resolved_market(None, MarketStatus.CANCELLED)
    )

    assert result.result == TradeResultStatus.VOID
    assert result.outcome_value == position.entry_price
    assert result.settlement_value == position.stake_usdc
    assert position.status == PositionStatus.CLOSED
    assert "SPLIT" not in {state.value for state in TradeResultStatus}


def test_missing_resolved_outcome_stays_unknown_and_retriable() -> None:
    wallet = PaperWallet(starting_balance=1000.0)
    position = _open_position(Side.UP)
    wallet.apply_fill(position)

    result = PaperSettlementEngine(wallet).settle(position, _resolved_market(None))

    assert result.result == TradeResultStatus.UNKNOWN
    assert result.outcome_value == 0.0
    assert result.settlement_value == 0.0
    assert position.status == PositionStatus.OPEN
    assert position.closed_at is None
    assert wallet.open_position_count == 1
    assert wallet.cash_balance == 990.0


def test_unknown_outcome_does_not_inflate_win_rate() -> None:
    wallet = PaperWallet(starting_balance=1000.0)
    unknown_position = _open_position(Side.UP)
    wallet.apply_fill(unknown_position)
    unknown = PaperSettlementEngine(wallet).settle(
        unknown_position, _resolved_market(None)
    )
    win = PaperTradeResult(
        signal_id="sig-win",
        paper_position_id="pos-win",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="market-win",
        market_slug="market-win",
        side=Side.UP,
        entry_price=0.50,
        shares=20.0,
        stake_usdc=10.0,
        exit_mode=ExitMode.RESOLUTION,
        outcome_value=1.0,
        settlement_value=20.0,
        pnl_usdc=10.0,
        roi=1.0,
        result=TradeResultStatus.WIN,
        opened_at=date(2026, 6, 21),
    )

    report = PaperReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1010.0,
        total_signals=2,
        paper_orders=2,
        paper_fills=2,
        rejected_paper_orders=0,
        open_positions=1,
        results=[unknown, win],
    )

    assert unknown.result == TradeResultStatus.UNKNOWN
    assert unknown_position.status == PositionStatus.OPEN
    assert report.closed_positions == 1
    assert report.win_count == 1
    assert report.win_rate == 1.0
    assert report.total_pnl_usdc == 10.0
