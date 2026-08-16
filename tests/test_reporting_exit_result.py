from __future__ import annotations

from datetime import date

from factories import MarketFactoryConfig, sample_market
from polysignal_lab.app.daily_report.projection import report_result_from_projection
from polysignal_lab.domain.enums import ExitMode, MarketStatus, Side, TradeResultStatus
from polysignal_lab.reporting.exit_result import (
    FEE_MODEL_IGNORED_V1,
    fee_fields_v1,
    report_result_from_early_exit,
)


def test_fee_fields_v1_marker() -> None:
    fields = fee_fields_v1()
    assert fields["fee_model"] == FEE_MODEL_IGNORED_V1
    assert fields["entry_fee"] == 0.0


def test_resolution_result_writes_fee_model_ignored_v1() -> None:
    market = sample_market(
        MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=-1)
    ).model_copy(update={"status": MarketStatus.RESOLVED, "resolved_outcome": Side.UP})
    result = report_result_from_projection(
        {
            "position_id": "pos-fee",
            "signal_id": "sig-fee",
            "strategy": "ptb_diff",
            "asset": "BTC",
            "timeframe": "5m",
            "quantity": 25.0,
            "avg_entry_price": 0.40,
            "stake_usdc": 10.0,
            "token_id": market.token_for(Side.UP).token_id,
            "ts": date(2026, 6, 21).isoformat(),
        },
        market=market,
        outcome_value=1.0,
        details={"source": "test"},
    )
    assert result is not None
    assert result["fee_model"] == FEE_MODEL_IGNORED_V1
    assert result["entry_fee"] == 0.0
    assert result["details"]["fee_model"] == FEE_MODEL_IGNORED_V1
    assert result["pnl_usdc"] == 15.0


def test_early_exit_take_profit_builds_win_result() -> None:
    result = report_result_from_early_exit(
        {
            "exit_reason": "TAKE_PROFIT",
            "position_id": "position-1",
            "entry_price": 0.40,
            "position_quantity": 10.0,
            "stake_usdc": 4.0,
            "side": "UP",
            "asset": "BTC",
            "timeframe": "5m",
            "market_id": "mkt-1",
            "market_slug": "btc-updown-5m",
            "opened_at": "2026-07-06T12:00:00+00:00",
        },
        fill_price=0.91,
        fill_shares=10.0,
        strategy_name="ptb_diff",
        closed_at="2026-07-06T12:01:00+00:00",
    )
    assert result is not None
    assert result["exit_mode"] == ExitMode.TAKE_PROFIT.value
    assert result["result"] == TradeResultStatus.WIN.value
    assert result["strategy"] == "ptb_diff"
    assert result["fee_model"] == FEE_MODEL_IGNORED_V1
    assert result["entry_fee"] == 0.0
    assert result["settlement_value"] == 9.1
    assert abs(result["pnl_usdc"] - 5.1) < 1e-9
    assert result["report_position_id"] == "position-1"

    replay = report_result_from_early_exit(
        {
            "exit_reason": "TAKE_PROFIT",
            "position_id": "position-1",
            "entry_price": 0.40,
            "position_quantity": 10.0,
            "stake_usdc": 4.0,
            "side": "UP",
            "asset": "BTC",
            "timeframe": "5m",
            "market_id": "mkt-1",
            "market_slug": "btc-updown-5m",
        },
        fill_price=0.91,
        fill_shares=10.0,
        strategy_name="ptb_diff",
        closed_at="2026-07-06T12:02:00+00:00",
    )
    assert replay is not None
    assert replay["report_result_id"] == result["report_result_id"]


def test_early_exit_partial_fill_uses_actual_quantity_and_prorated_stake() -> None:
    result = report_result_from_early_exit(
        {
            "exit_reason": "TAKE_PROFIT",
            "position_id": "position-partial",
            "entry_price": 0.40,
            "position_quantity": 10.0,
            "stake_usdc": 4.0,
            "side": "UP",
            "asset": "BTC",
            "timeframe": "5m",
            "market_id": "mkt-1",
            "market_slug": "btc-updown-5m",
        },
        fill_price=0.90,
        fill_shares=2.5,
        strategy_name="ptb_diff",
    )

    assert result is not None
    assert result["shares"] == 2.5
    assert result["stake_usdc"] == 1.0
    assert result["settlement_value"] == 2.25
    assert result["pnl_usdc"] == 1.25


def test_early_exit_stop_loss_builds_loss_result() -> None:
    result = report_result_from_early_exit(
        {
            "exit_reason": "STOP_LOSS",
            "position_id": "position-2",
            "entry_price": 0.50,
            "position_quantity": 20.0,
            "side": "DOWN",
            "asset": "ETH",
            "timeframe": "15m",
            "market_id": "mkt-2",
            "market_slug": "eth-updown-15m",
            "opened_at": "2026-07-06T12:00:00+00:00",
        },
        fill_price=0.30,
        fill_shares=20.0,
        strategy_name="late_consensus",
        closed_at="2026-07-06T12:02:00+00:00",
    )
    assert result is not None
    assert result["exit_mode"] == ExitMode.STOP_LOSS.value
    assert result["result"] == TradeResultStatus.LOSS.value
    assert result["pnl_usdc"] < 0.0
    assert result["strategy"] == "late_consensus"


def test_early_exit_ignores_non_exit_fills() -> None:
    assert (
        report_result_from_early_exit(
            {"position_id": "p", "entry_price": 0.4, "position_quantity": 1.0},
            fill_price=0.5,
            fill_shares=1.0,
            strategy_name="ptb_diff",
        )
        is None
    )


BASE_EARLY_EXIT_METRICS: dict[str, object] = {
    "exit_reason": "TAKE_PROFIT",
    "position_id": "position-early-exit",
    "entry_price": 0.40,
    "position_quantity": 10.0,
    "stake_usdc": 4.0,
    "side": "UP",
    "asset": "BTC",
    "timeframe": "5m",
    "market_id": "mkt-1",
    "market_slug": "btc-updown-5m",
}


def test_early_exit_missing_or_zero_fill_price_returns_none() -> None:
    assert (
        report_result_from_early_exit(
            BASE_EARLY_EXIT_METRICS,
            fill_price=None,
            fill_shares=10.0,
            strategy_name="ptb_diff",
        )
        is None
    )
    assert (
        report_result_from_early_exit(
            BASE_EARLY_EXIT_METRICS,
            fill_price=0.0,
            fill_shares=10.0,
            strategy_name="ptb_diff",
        )
        is None
    )


def test_early_exit_missing_or_zero_fill_shares_returns_none() -> None:
    assert (
        report_result_from_early_exit(
            BASE_EARLY_EXIT_METRICS,
            fill_price=0.91,
            fill_shares=None,
            strategy_name="ptb_diff",
        )
        is None
    )
    assert (
        report_result_from_early_exit(
            BASE_EARLY_EXIT_METRICS,
            fill_price=0.91,
            fill_shares=0.0,
            strategy_name="ptb_diff",
        )
        is None
    )
