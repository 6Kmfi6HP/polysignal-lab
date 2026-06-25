from __future__ import annotations

from polysignal_lab.alpha.mid_price_sizing_core import MidPriceSizingAlphaCore
from polysignal_lab.alpha.types import AlphaFillEvent, AlphaOrderEvent
from polysignal_lab.domain.enums import Side
from polysignal_lab.strategies.mid_price_sizing import MidPriceSizingConfig, MidPriceSizingStrategy
from polysignal_lab.utils import utc_now
from alpha_equivalence import assert_legacy_core_equivalent
from factories import sample_snapshot


def _fill(market_id: str, condition_id: str, token_id: str, side: Side, price: float) -> AlphaFillEvent:
    return AlphaFillEvent(
        strategy="mid_price_sizing",
        market_id=market_id,
        condition_id=condition_id,
        token_id=token_id,
        side=side,
        order_id=f"mid_price_sizing:{market_id}:{side.value}",
        client_order_id=None,
        reason=None,
        ts_event=utc_now(),
        metrics={},
        fill_price=price,
        shares=5.0,
        liquidity_side=None,
    )


def test_mid_price_sizing_core_matches_legacy_candidate() -> None:
    config = MidPriceSizingConfig()
    snapshot = sample_snapshot(up_ask=0.46, down_ask=0.44)
    assert_legacy_core_equivalent(MidPriceSizingStrategy(config), MidPriceSizingAlphaCore(config), snapshot)


def test_layer_count_changes_only_on_order_filled() -> None:
    config = MidPriceSizingConfig()
    core = MidPriceSizingAlphaCore(config)
    snapshot = sample_snapshot(up_ask=0.46, down_ask=0.44)
    key = core._pos_key(snapshot.market.market_id, Side.UP)

    assert core.evaluate_view_from_snapshot_for_test(snapshot)
    assert core.evaluate_view_from_snapshot_for_test(snapshot)
    assert core._layer_count.get(key, 0) == 0
    assert core._entry_prices.get(key, []) == []

    core.on_order_accepted(
        AlphaOrderEvent(
            strategy="mid_price_sizing",
            market_id=snapshot.market.market_id,
            condition_id=snapshot.market.condition_id,
            token_id=snapshot.market.token_for(Side.UP).token_id,
            side=Side.UP,
            order_id="accepted-only",
            client_order_id=None,
            reason=None,
            ts_event=utc_now(),
            metrics={},
        )
    )
    assert core._layer_count.get(key, 0) == 0

    core.on_order_filled(
        _fill(snapshot.market.market_id, snapshot.market.condition_id, snapshot.market.token_for(Side.UP).token_id, Side.UP, 0.46)
    )

    assert core._layer_count[key] == 1
    assert core._entry_prices[key] == [0.46]
