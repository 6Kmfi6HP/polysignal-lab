"""
Input: __future__, __future__.annotations, collections, collections.defaultdict, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate
Output: SignalArbiter
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from collections import defaultdict

from polysignal_lab.domain.signal import SignalCandidate


class SignalArbiter:
    def __init__(self, conflict_policy: str = "suppress_ambiguous") -> None:
        self.conflict_policy = conflict_policy

    def arbitrate(
        self,
        candidates: list[SignalCandidate],
        strategy_priorities: dict[str, int],
        strategy_config_indexes: dict[str, int],
        market_config_indexes: dict[str, int],
    ) -> list[SignalCandidate]:
        indexed = list(enumerate(candidates))
        if self.conflict_policy == "suppress_ambiguous":
            sides_by_market: dict[str, set[str]] = defaultdict(set)
            for _, candidate in indexed:
                sides_by_market[candidate.market_id].add(candidate.side.value)
            indexed = [
                item
                for item in indexed
                if len(sides_by_market[item[1].market_id]) <= 1
            ]

        return [
            candidate
            for _, candidate in sorted(
                indexed,
                key=lambda item: (
                    strategy_priorities.get(item[1].strategy, 100),
                    strategy_config_indexes.get(item[1].strategy, 10_000),
                    market_config_indexes.get(item[1].market_id, 10_000),
                    item[0],
                ),
            )
        ]
