"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, types, types.SimpleNamespace, polysignal_lab.alpha.types, polysignal_lab.alpha.types.FreshnessView, polysignal_lab.alpha.types.MarketView
Output: test_evaluate_condition_does_not_run_custom_exit_scan, test_native_strategy_has_no_custom_exit_evaluation_api
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from polysignal_lab.alpha.types import FreshnessView, MarketView, SideBookView
from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy


def _native_strategy() -> PolySignalNativeStrategy:
    class Core:
        def evaluate(self, view):
            return []

    class Assembler:
        def build(self, condition_id):
            now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
            up = SideBookView(
                token_id="token-up",
                best_bid=0.91,
                best_ask=0.92,
                spread=0.01,
                freshness_ms=100,
            )
            down = SideBookView(
                token_id="token-down",
                best_bid=0.10,
                best_ask=0.11,
                spread=0.01,
                freshness_ms=100,
            )
            return MarketView(
                view_id="view-1",
                market_id="mkt-1",
                market_slug="slug",
                condition_id=condition_id,
                asset="BTC",
                timeframe="5m",
                start_ts=None,
                end_ts=None,
                created_at=now,
                seconds_to_close=300,
                up=up,
                down=down,
                spot=None,
                price_to_beat=None,
                up_trades=(),
                down_trades=(),
                metrics={},
                freshness=FreshnessView(100, 100, None, 100),
            )

    class Registry:
        def by_condition(self, condition_id):
            return None

    strategy = PolySignalNativeStrategy(
        core=Core(),
        assembler=Assembler(),
        condition_ids=("condition-1",),
        strategy_name="test",
        registry=Registry(),
        instrument_id_resolver=lambda value: value,
    )
    return strategy


def test_evaluate_condition_does_not_run_custom_exit_scan() -> None:
    strategy = _native_strategy()
    strategy.cache_reader = SimpleNamespace(
        read_positions=lambda: (_ for _ in ()).throw(
            AssertionError("custom exit engine must not scan Nautilus positions")
        )
    )

    strategy.evaluate_condition("condition-1")

    assert list(strategy.submitted_orders) == []


def test_native_strategy_has_no_custom_exit_evaluation_api() -> None:
    strategy = _native_strategy()

    assert not hasattr(strategy, "evaluate_exit_positions")
    assert not hasattr(strategy, "_submit_exit_position")
