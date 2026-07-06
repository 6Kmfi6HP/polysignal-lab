from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from polysignal_lab.alpha.types import SideBookView
from polysignal_lab.nautilus_runtime.exit_policy import (
    ExitPolicyConfig,
    ExitReason,
    evaluate_exit_decision,
)


def _book(best_bid: float) -> SideBookView:
    return SideBookView(
        token_id="token-up",
        best_bid=best_bid,
        best_ask=best_bid + 0.01,
        spread=0.01,
        freshness_ms=100,
        min_order_size=1.0,
        tick_size=0.01,
        last_trade_price=best_bid,
        last_trade_size=10.0,
        last_trade_timestamp=None,
        received_at=datetime(2026, 7, 6, tzinfo=UTC),
        ask_levels=((best_bid + 0.01, 100.0),),
    )


def _position(opened_at: datetime, entry_price: float = 0.50) -> dict[str, object]:
    return {
        "position_id": "pos-1",
        "instrument_id": "token-up.POLYMARKET",
        "token_id": "token-up",
        "quantity": 20.0,
        "avg_entry_price": entry_price,
        "opened_at": opened_at.isoformat(),
        "is_closed": False,
    }


def _config() -> ExitPolicyConfig:
    return ExitPolicyConfig(
        mode="hold_to_resolution_with_optional_tp_sl",
        take_profit_enabled=True,
        stop_loss_enabled=True,
        take_profit_price=0.90,
        stop_loss_price=0.35,
        max_hold_time_sec=900,
    )


def test_take_profit_exit_uses_nautilus_projection_without_wallet() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)

    decision = evaluate_exit_decision(_position(now), _book(0.91), now, _config())

    assert decision is not None
    assert decision.reason is ExitReason.TAKE_PROFIT
    assert decision.instrument_id == "token-up.POLYMARKET"
    assert decision.quantity == 20.0
    assert decision.limit_price == 0.91


def test_stop_loss_exit_uses_nautilus_projection_without_wallet() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)

    decision = evaluate_exit_decision(_position(now), _book(0.34), now, _config())

    assert decision is not None
    assert decision.reason is ExitReason.STOP_LOSS
    assert decision.limit_price == 0.34


def test_max_hold_exit_uses_best_bid_after_hold_time() -> None:
    now = datetime(2026, 7, 6, 12, 20, tzinfo=UTC)
    opened_at = now - timedelta(seconds=901)

    decision = evaluate_exit_decision(_position(opened_at), _book(0.51), now, _config())

    assert decision is not None
    assert decision.reason is ExitReason.MAX_HOLD_TIME
    assert decision.limit_price == 0.51


def test_no_exit_when_thresholds_not_met() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)

    assert evaluate_exit_decision(_position(now), _book(0.53), now, _config()) is None
