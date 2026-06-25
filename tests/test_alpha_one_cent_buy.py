from __future__ import annotations

from polysignal_lab.alpha.one_cent_buy_core import OneCentBuyAlphaCore
from polysignal_lab.alpha.types import AlphaOrderEvent
from polysignal_lab.domain.enums import Side
from polysignal_lab.strategies.config import OneCentBuyConfig
from polysignal_lab.strategies.one_cent_buy import OneCentBuyStrategy
from alpha_equivalence import assert_legacy_core_equivalent
from factories import sample_snapshot


def test_one_cent_buy_core_matches_legacy_candidate() -> None:
    config = OneCentBuyConfig(
        enabled=True,
        entry_prices=[0.01],
        min_seconds_after_open=0,
        max_seconds_after_open=300,
    )
    snapshot = sample_snapshot(up_ask=0.01, down_ask=0.02, seconds_to_close=240)

    assert_legacy_core_equivalent(OneCentBuyStrategy(config), OneCentBuyAlphaCore(config), snapshot)


def test_one_cent_buy_level_marks_only_after_order_acceptance() -> None:
    config = OneCentBuyConfig(
        enabled=True,
        entry_prices=[0.01],
        min_seconds_after_open=0,
        max_seconds_after_open=300,
    )
    snapshot = sample_snapshot(up_ask=0.01, down_ask=0.02, seconds_to_close=240)
    core = OneCentBuyAlphaCore(config)

    first = core.evaluate_view_from_snapshot_for_test(snapshot)
    second = core.evaluate_view_from_snapshot_for_test(snapshot)

    assert first
    assert second

    core.on_order_accepted(
        AlphaOrderEvent(
            strategy="one_cent_buy",
            market_id=first[0].market_id,
            condition_id=first[0].condition_id,
            token_id=first[0].token_id,
            side=Side.UP,
            order_id="order-1",
            client_order_id="client-1",
            reason=None,
            ts_event=first[0].metrics["created_at_for_test"],
            metrics={"level_price": 0.01},
        )
    )

    assert core.evaluate_view_from_snapshot_for_test(snapshot) == []