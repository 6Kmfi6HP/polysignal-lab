"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.one_cent_buy_core, polysignal_lab.alpha.one_cent_buy_core.OneCentBuyAlphaCore, polysignal_lab.domain.enums, polysignal_lab.domain.enums.Side, polysignal_lab.domain.strategy_config, polysignal_lab.domain.strategy_config.OneCentBuyConfig, alpha_helpers, alpha_helpers.with_active_order
Output: test_one_cent_buy_uses_cached_orders_for_level_guard
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""


from __future__ import annotations

from polysignal_lab.alpha.one_cent_buy_core import OneCentBuyAlphaCore
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.strategy_config import OneCentBuyConfig
from alpha_helpers import with_active_order
from factories import sample_market_view


def test_one_cent_buy_uses_cached_orders_for_level_guard() -> None:
    core = OneCentBuyAlphaCore(
        OneCentBuyConfig(entry_prices=(0.01,), shares_per_level=10)
    )
    view = sample_market_view(up_ask=0.05, down_ask=0.01, seconds_to_close=60)

    decisions = core.evaluate(view)

    assert len(decisions) == 1
    assert decisions[0].side is Side.UP
    cached = with_active_order(
        view,
        core.name,
        side=Side.UP,
        price=0.01,
    )
    assert core.evaluate(cached) == []
    assert not hasattr(core, "_submitted_levels")
