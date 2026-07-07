"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.replace, datetime, datetime.datetime, datetime.timezone, types, types.SimpleNamespace, polysignal_lab.alpha.cross_market_core
Output: test_group_assembler_rejects_excessive_skew, test_group_assembler_accepts_acceptable_skew, test_cross_market_wrapper_evaluate_group_returns_decisions, test_cross_market_wrapper_submits_via_callback, test_cross_market_basket_tags_present, test_cross_market_leg_failure_marks_basket, test_cross_market_state_roundtrip, test_cross_market_wrapper_matches_legacy_alpha_output, test_cross_market_wrapper_fok_depth_counts_asks_through_max_entry, AllowAllPolicy
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

from polysignal_lab.alpha.cross_market_core import CrossMarketAlphaCore, RelationType
from polysignal_lab.alpha.types import (
    AlphaDecision,
    FreshnessView,
    MarketGroupView,
    MarketView,
    OrderIntentSpec,
    SideBookView,
)
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
from polysignal_lab.nautilus_runtime.group_views import MarketGroupViewAssembler
from polysignal_lab.nautilus_runtime.strategies.cross_market_bot import (
    CrossMarketNautilusStrategy,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _view(
    condition_id: str,
    asset: str = "BTC",
    timeframe: str = "5m",
    ask: float = 0.20,
    freshness_ms: int = 100,
) -> MarketView:
    now = datetime.now(timezone.utc)
    return MarketView(
        view_id=f"view-{condition_id}",
        market_id=f"market-{condition_id}",
        market_slug=f"{asset.lower()}-{condition_id}",
        condition_id=condition_id,
        asset=asset,
        timeframe=timeframe,
        start_ts=now,
        end_ts=now,
        created_at=now,
        seconds_to_close=120,
        up=SideBookView(
            token_id=f"{condition_id}-up",
            best_bid=None,
            best_ask=ask,
            spread=0.0,
            freshness_ms=freshness_ms,
            ask_levels=((ask, 100.0),),
        ),
        down=SideBookView(
            token_id=f"{condition_id}-down",
            best_bid=1.0 - ask,
            best_ask=1.0 - ask + 0.01,
            spread=0.01,
            freshness_ms=freshness_ms,
            ask_levels=((1.0 - ask + 0.01, 100.0),),
        ),
        spot=None,
        price_to_beat=100_000.0,
        up_trades=(),
        down_trades=(),
        metrics={},
        freshness=FreshnessView(
            up_book_ms=freshness_ms,
            down_book_ms=freshness_ms,
            spot_ms=None,
            max_ms=freshness_ms,
        ),
    )


_DEFAULT_CFG = SimpleNamespace(
    enabled=True,
    assets=["BTC", "ETH"],
    timeframes=["5m"],
    min_edge=0.01,
    max_leg_timeout_seconds=1.5,
    max_basket_notional=50.0,
    min_depth_shares=5,
    fee_rate=0.01,
)


def _core(relation_id: str = "btc-eth-rel") -> CrossMarketAlphaCore:
    core = CrossMarketAlphaCore(_DEFAULT_CFG)
    core.register_relation(
        relation_id,
        RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE,
        ["cond-btc", "cond-eth"],
        [Side.UP, Side.UP],
    )
    return core


def _group(
    relation_id: str = "btc-eth-rel",
    freshness_ms: int = 100,
) -> MarketGroupView:
    now = datetime.now(timezone.utc)
    return MarketGroupView(
        group_id="group-1",
        relation_id=relation_id,
        created_at=now,
        views_by_condition_id={
            "cond-btc": _view("cond-btc", "BTC", "5m", 0.20, freshness_ms),
            "cond-eth": _view("cond-eth", "ETH", "5m", 0.15, freshness_ms),
        },
        max_source_skew_ms=2000,
        metrics={},
    )


class AllowAllPolicy:
    """Policy that approves every decision without gate/arbiter checks."""

    def __init__(self):
        self.group_decisions: list[AlphaDecision] = []

    def decide(
        self, decision: AlphaDecision, view: MarketView
    ) -> ApprovedDecision:
        from polysignal_lab.domain.signal import SignalCandidate

        self.group_decisions.append(decision)
        return ApprovedDecision(
            signal=SignalCandidate.build(
                strategy=decision.strategy,
                asset=decision.asset,
                timeframe=decision.timeframe,
                market_id=decision.market_id,
                market_slug=decision.market_slug,
                condition_id=decision.condition_id,
                token_id=decision.token_id,
                side=decision.side,
                confidence=decision.confidence,
                entry_reference_price=decision.entry_reference_price,
                max_entry_price=decision.max_entry_price,
                seconds_to_close=decision.seconds_to_close,
                data_freshness_ms=decision.data_freshness_ms,
                reason_codes=list(decision.reason_codes),
                metrics=dict(decision.metrics),
            )
        )


def _strategy(
    core: CrossMarketAlphaCore | None = None,
    submitter: object = None,
) -> CrossMarketNautilusStrategy:
    return CrossMarketNautilusStrategy(
        core=core or _core(),
        assembler=None,
        condition_ids=["cond-btc", "cond-eth"],
        strategy_name="cross_market_bot",
        policy=AllowAllPolicy(),
        submitter=submitter,
    )


# ── MarketGroupViewAssembler tests ──────────────────────────────────────────


def test_group_assembler_rejects_excessive_skew() -> None:
    """Assembler must reject groups whose max freshness skew exceeds threshold."""
    assembler = MarketGroupViewAssembler(max_source_skew_ms=500)
    now = datetime.now(timezone.utc)
    group = assembler.assemble(
        relation_id="rel-1",
        views_by_condition_id={
            "a": _view("a", freshness_ms=100),
            "b": _view("b", freshness_ms=1000),
        },
        created_at=now,
        max_source_skew_ms=500,
    )
    assert group is None


def test_group_assembler_accepts_acceptable_skew() -> None:
    assembler = MarketGroupViewAssembler(max_source_skew_ms=2000)
    now = datetime.now(timezone.utc)
    group = assembler.assemble(
        relation_id="rel-1",
        views_by_condition_id={
            "a": _view("a", freshness_ms=100),
            "b": _view("b", freshness_ms=100),
        },
        created_at=now,
        max_source_skew_ms=2000,
    )
    assert group is not None
    assert isinstance(group, MarketGroupView)
    assert group.relation_id == "rel-1"


# ── CrossMarketNautilusStrategy tests ──────────────────────────────────────


def test_cross_market_wrapper_evaluate_group_returns_decisions() -> None:
    strategy = _strategy()
    specs = strategy.evaluate_group(_group())
    assert len(specs) >= 2
    # instrument_id is the token_id, derived from the view
    for spec in specs:
        assert spec.pair_id == "btc-eth-rel"


def test_cross_market_wrapper_submits_via_callback() -> None:
    submitted: list = []

    def fake_submitter(spec):
        submitted.append(spec)

    strategy = _strategy(submitter=fake_submitter)
    specs = strategy.evaluate_group(_group())
    assert len(specs) >= 2
    assert len(submitted) >= 2


def test_cross_market_basket_tags_present() -> None:
    strategy = _strategy()
    specs = strategy.evaluate_group(_group())
    for spec in specs:
        assert "pair_id" in spec.tags


def test_cross_market_leg_failure_marks_basket() -> None:
    core = _core()
    strategy = _strategy(core)
    strategy.on_leg_failure("btc-eth-rel", "cond-btc", Side.UP)
    basket = core._active_baskets.get("btc-eth-rel", {})
    assert basket.get("failed") is True


def test_cross_market_state_roundtrip() -> None:
    """Core state encodes basket state and decodes back."""
    from polysignal_lab.nautilus_bridge.state import encode_state, decode_state

    core = _core()
    core._active_baskets["btc-eth-rel"] = {
        "fills": {"cond-btc": {"side": "UP", "price": 0.20, "shares": 10}},
        "markets": {"cond-btc", "cond-eth"},
        "failed": False,
    }
    raw = encode_state("cross_market_bot", {"core": core.save_state()})
    decoded = decode_state("cross_market_bot", raw)
    assert decoded is not None
    assert "core" in decoded
    assert "_active_baskets" in decoded["core"]


def test_cross_market_wrapper_matches_legacy_alpha_output() -> None:
    """Nautilus wrapper must emit one spec per alpha decision for the same group."""
    core = _core()
    g = _group()
    legacy_decisions = core.evaluate_group(g)
    strategy = _strategy(core)
    specs = strategy.evaluate_group(g)
    assert len(specs) == len(legacy_decisions)
    # Each spec should carry the legacy decision's condition_id in tags
    for spec, decision in zip(specs, legacy_decisions):
        assert spec.pair_id == decision.metrics.get(
            "pair_id", decision.order_intent.pair_id if decision.order_intent else None
        )



def test_cross_market_wrapper_fok_depth_counts_asks_through_max_entry() -> None:
    base_view = _view("cond-btc", ask=0.50)
    view = replace(
        base_view,
        up=replace(
            base_view.up,
            ask_levels=((0.50, 10.0), (0.52, 10.0), (0.53, 100.0)),
        ),
    )
    group = replace(_group(), views_by_condition_id={"cond-btc": view})

    class FokCore:
        def evaluate_group(self, group):
            return [
                AlphaDecision(
                    strategy="cross_market_bot",
                    asset="BTC",
                    timeframe="5m",
                    market_id=view.market_id,
                    market_slug=view.market_slug,
                    condition_id=view.condition_id,
                    token_id=view.up.token_id,
                    side=Side.UP,
                    confidence=0.8,
                    entry_reference_price=0.50,
                    max_entry_price=0.52,
                    seconds_to_close=view.seconds_to_close,
                    data_freshness_ms=view.freshness.max_ms,
                    reason_codes=("TEST",),
                    metrics={},
                    order_intent=OrderIntentSpec(
                        intent=OrderIntent.TAKER_FOK,
                        pair_id="pair-1",
                    ),
                    hedge_leg=False,
                )
            ]

    class PreserveIntentPolicy:
        def decide(self, decision, view):
            from polysignal_lab.domain.signal import SignalCandidate

            intent = decision.order_intent
            return ApprovedDecision(
                signal=SignalCandidate.build(
                    strategy=decision.strategy,
                    asset=decision.asset,
                    timeframe=decision.timeframe,
                    market_id=decision.market_id,
                    market_slug=decision.market_slug,
                    condition_id=decision.condition_id,
                    token_id=decision.token_id,
                    side=decision.side,
                    confidence=decision.confidence,
                    entry_reference_price=decision.entry_reference_price,
                    max_entry_price=decision.max_entry_price,
                    seconds_to_close=decision.seconds_to_close,
                    data_freshness_ms=decision.data_freshness_ms,
                    reason_codes=list(decision.reason_codes),
                    metrics=dict(decision.metrics),
                    order_intent=intent.intent,
                    pair_id=intent.pair_id,
                )
            )

    strategy = CrossMarketNautilusStrategy(
        core=FokCore(),
        assembler=None,
        condition_ids=["cond-btc"],
        strategy_name="cross_market_bot",
        policy=PreserveIntentPolicy(),
        fixed_stake_usdc=10.0,
    )

    specs = strategy.evaluate_group(group)

    assert len(specs) == 1
    assert specs[0].intent == OrderIntent.TAKER_FOK
    assert specs[0].quantity == 20.0