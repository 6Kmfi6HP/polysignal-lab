"""
Input: __future__, __future__.annotations
Output: build_strategies, build_strategy
Pos: Application code — RETIRED

Legacy strategy factory that instantiated BaseStrategy subclasses.
All strategies now use AlphaCore via Nautilus-native routing.

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from polysignal_lab.config import StrategyConfig


def build_strategies(config: StrategyConfig) -> list[object]:
    raise RuntimeError(
        "build_strategies is retired. Strategies are now built via Nautilus-native routing."
    )


def build_strategy(config: object) -> object:
    raise RuntimeError(
        "build_strategy is retired. Strategies are now built via Nautilus-native routing."
    )
