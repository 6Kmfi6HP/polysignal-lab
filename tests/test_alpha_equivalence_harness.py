"""
Input: __future__, __future__.annotations, alpha_equivalence, alpha_equivalence.normalize_candidate, alpha_equivalence.normalize_decision, factories, factories.sample_snapshot, polysignal_lab.alpha.ptb_diff_core, polysignal_lab.alpha.ptb_diff_core.market_view_from_snapshot, polysignal_lab.alpha.types
Output: test_normalizers_compare_semantic_fields_only, test_sample_snapshot_assembles_valid_market_view, test_sample_snapshot_spot_price_override_assembles_market_view
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

# NOTE: bare imports (not `from tests.X import`) because the installed
# `py_order_utils` dependency ships a top-level `tests` package in site-packages
# that shadows our local `tests/` namespace. The repo's 80 existing test files
# follow this same bare-import convention (pytest puts `tests/` on sys.path via
# tests/conftest.py). See task-4-report.md.
from alpha_equivalence import normalize_candidate, normalize_decision
from factories import sample_snapshot
from polysignal_lab.alpha.ptb_diff_core import market_view_from_snapshot
from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate


def test_normalizers_compare_semantic_fields_only() -> None:
    candidate = SignalCandidate.build(
        strategy="skew_mean_reversion",
        asset="BTC",
        timeframe="5m",
        market_id="market-1",
        market_slug="slug-1",
        condition_id="condition-1",
        token_id="token-up",
        side=Side.UP,
        confidence=0.7,
        entry_reference_price=0.4,
        max_entry_price=0.45,
        seconds_to_close=60,
        data_freshness_ms=10,
        reason_codes=["SKEW_MEAN_REVERSION"],
        metrics={"spread": 0.2},
        snapshot_id="snapshot-host-generated",
    )
    decision = AlphaDecision(
        strategy="skew_mean_reversion",
        asset="BTC",
        timeframe="5m",
        market_id="market-1",
        market_slug="slug-1",
        condition_id="condition-1",
        token_id="token-up",
        side=Side.UP,
        confidence=0.7,
        entry_reference_price=0.4,
        max_entry_price=0.45,
        seconds_to_close=60,
        data_freshness_ms=10,
        reason_codes=("SKEW_MEAN_REVERSION",),
        metrics={"spread": 0.2},
    )

    assert normalize_candidate(candidate) == normalize_decision(decision)


def test_sample_snapshot_assembles_valid_market_view() -> None:
    # De-risks Task 5: a factory-built snapshot must yield a non-None MarketView
    # via the same assembler the alpha cores consume.
    view = market_view_from_snapshot(
        sample_snapshot(up_ask=0.82, down_ask=0.18, seconds_to_close=60)
    )
    assert view is not None


def test_sample_snapshot_spot_price_override_assembles_market_view() -> None:
    # Regression for review finding: passing spot_price previously raised
    # AttributeError because SpotFactoryConfig (a frozen dataclass) has no
    # model_copy. The override must now assemble a valid MarketView whose
    # spot price matches the requested value.
    view = market_view_from_snapshot(sample_snapshot(spot_price=100500.0))
    assert view is not None
    assert view.spot is not None
    assert view.spot.price == 100500.0
