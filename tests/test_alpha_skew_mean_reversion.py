"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.skew_mean_reversion_core, polysignal_lab.alpha.skew_mean_reversion_core.SkewMeanReversionAlphaCore, polysignal_lab.strategies.config, polysignal_lab.strategies.config.SkewMeanReversionConfig, polysignal_lab.strategies.skew_mean_reversion, polysignal_lab.strategies.skew_mean_reversion.SkewMeanReversionStrategy, alpha_equivalence, alpha_equivalence.assert_legacy_core_equivalent
Output: test_skew_mean_reversion_core_matches_legacy_candidate
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from polysignal_lab.alpha.skew_mean_reversion_core import SkewMeanReversionAlphaCore
from polysignal_lab.strategies.config import SkewMeanReversionConfig
from polysignal_lab.strategies.skew_mean_reversion import SkewMeanReversionStrategy
from alpha_equivalence import assert_legacy_core_equivalent
from factories import sample_snapshot


def test_skew_mean_reversion_core_matches_legacy_candidate() -> None:
    config = SkewMeanReversionConfig(enabled=True)
    # Default fixture: up_ask=0.82, down_ask=0.18 → big skew, cheap DOWN side.
    snapshot = sample_snapshot()

    assert_legacy_core_equivalent(
        SkewMeanReversionStrategy(config), SkewMeanReversionAlphaCore(config), snapshot
    )