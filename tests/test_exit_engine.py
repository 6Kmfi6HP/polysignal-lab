from __future__ import annotations

from datetime import timedelta

from polysignal_lab.config import ExitModelConfig
from polysignal_lab.domain.enums import ExitMode, PositionStatus, Side, TradeResultStatus
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.paper.exit_engine import PaperExitEngine
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.utils import utc_now
from factories import BookFactoryConfig, sample_book


def _position(signal_id: str, opened_seconds_ago: int = 30) -> PaperPosition:
    return PaperPosition(
        signal_id=signal_id,
        paper_order_id=f"order-{signal_id}",
        paper_fill_id=f"fill-{signal_id}",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m-test",
        market_slug="btc-updown-5m-test",
        token_id="btc-5m-test-UP",
        side=Side.UP,
        entry_price=0.50,
        shares=20.0,
        stake_usdc=10.0,
        opened_at=utc_now() - timedelta(seconds=opened_seconds_ago),
    )


def _engine_with_position(position: PaperPosition) -> tuple[PaperExitEngine, PaperWallet]:
    wallet = PaperWallet(starting_balance=1000.0)
    wallet.apply_fill(position)
    config = ExitModelConfig(
        take_profit_enabled=True,
        stop_loss_enabled=True,
        take_profit_price=0.90,
        stop_loss_price=0.35,
        max_hold_time_sec=60,
    )
    return PaperExitEngine(config, wallet), wallet


def test_take_profit_stop_loss_and_max_hold_exits() -> None:
    # Given: three open paper positions and current orderbooks with best bids.
    tp_position = _position("sig-tp")
    sl_position = _position("sig-sl")
    hold_position = _position("sig-hold", opened_seconds_ago=120)
    tp_engine, tp_wallet = _engine_with_position(tp_position)
    sl_engine, sl_wallet = _engine_with_position(sl_position)
    hold_engine, hold_wallet = _engine_with_position(hold_position)

    # When: the paper exit engine evaluates TP, SL, and max-hold conditions.
    take_profit = tp_engine.evaluate(
        tp_position, sample_book(tp_position.token_id, BookFactoryConfig(ask=0.94, bid=0.91))
    )
    stop_loss = sl_engine.evaluate(
        sl_position, sample_book(sl_position.token_id, BookFactoryConfig(ask=0.36, bid=0.34))
    )
    max_hold = hold_engine.evaluate(
        hold_position,
        sample_book(hold_position.token_id, BookFactoryConfig(ask=0.55, bid=0.52)),
    )

    # Then: each position is closed with a PRD result state and no open paper exposure.
    assert take_profit is not None
    assert take_profit.exit_mode == ExitMode.TAKE_PROFIT
    assert take_profit.result == TradeResultStatus.WIN
    assert take_profit.details["paper_exit_price"] == 0.91
    assert tp_position.status == PositionStatus.CLOSED
    assert tp_wallet.open_position_count == 0
    assert tp_wallet.cash_balance == 1008.2

    assert stop_loss is not None
    assert stop_loss.exit_mode == ExitMode.STOP_LOSS
    assert stop_loss.result == TradeResultStatus.LOSS
    assert stop_loss.details["paper_exit_price"] == 0.34
    assert sl_position.status == PositionStatus.CLOSED
    assert sl_wallet.open_position_count == 0
    assert sl_wallet.cash_balance == 996.8

    assert max_hold is not None
    assert max_hold.exit_mode == ExitMode.MAX_HOLD_TIME
    assert max_hold.result == TradeResultStatus.WIN
    assert max_hold.details["paper_exit_price"] == 0.52
    assert hold_position.status == PositionStatus.CLOSED
    assert hold_wallet.open_position_count == 0
    assert hold_wallet.cash_balance == 1000.4
