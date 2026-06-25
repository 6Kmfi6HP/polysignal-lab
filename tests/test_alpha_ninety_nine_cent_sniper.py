from __future__ import annotations

from polysignal_lab.alpha.ninety_nine_cent_sniper_core import NinetyNineCentSniperAlphaCore
from polysignal_lab.alpha.types import AlphaOrderEvent
from polysignal_lab.strategies.config import NinetyNineCentSniperConfig
from polysignal_lab.strategies.ninety_nine_cent_sniper import NinetyNineCentSniperStrategy
from polysignal_lab.domain.enums import Side
from alpha_equivalence import assert_legacy_core_equivalent
from factories import sample_snapshot


def _sniper_snapshot() -> "object":
    return sample_snapshot(
        up_ask=0.98,
        down_ask=0.02,
        seconds_to_close=60,
    ).model_copy(update={"metrics": {"external_probability": 0.996}})


def test_ninety_nine_cent_sniper_core_matches_legacy_candidate() -> None:
    config = NinetyNineCentSniperConfig()
    snapshot = _sniper_snapshot()

    assert_legacy_core_equivalent(
        NinetyNineCentSniperStrategy(config), NinetyNineCentSniperAlphaCore(config), snapshot
    )


def test_ninety_nine_cent_sniper_side_marks_only_after_order_acceptance() -> None:
    config = NinetyNineCentSniperConfig()
    snapshot = _sniper_snapshot()
    core = NinetyNineCentSniperAlphaCore(config)

    first = core.evaluate_view_from_snapshot_for_test(snapshot)
    second = core.evaluate_view_from_snapshot_for_test(snapshot)

    assert first
    assert second

    core.on_order_accepted(
        AlphaOrderEvent(
            strategy="ninety_nine_cent_sniper",
            market_id=first[0].market_id,
            condition_id=first[0].condition_id,
            token_id=first[0].token_id,
            side=first[0].side,
            order_id="order-1",
            client_order_id="client-1",
            reason=None,
            ts_event=first[0].metrics["created_at_for_test"],
            metrics={},
        )
    )

    assert core.evaluate_view_from_snapshot_for_test(snapshot) == []