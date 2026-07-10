"""
Input: __future__, __future__.annotations, collections, collections.defaultdict, datetime, datetime.datetime, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate, polysignal_lab.utils, polysignal_lab.utils.utc_now
Output: ConsensusEngine
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations


from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.utils import utc_now


class ConsensusEngine:
    def __init__(self, window_sec: int = 45, enabled: bool = True):
        self.window_sec = window_sec
        self.enabled = enabled
        self._buffer: list[SignalCandidate] = []

    def add(self, signal: SignalCandidate) -> SignalCandidate | None:
        if not self.enabled:
            return None
        now = utc_now()
        self._buffer = [s for s in self._buffer if (now - s.created_at).total_seconds() <= self.window_sec]
        self._buffer.append(signal)
        same = [s for s in self._buffer if s.market_id == signal.market_id and s.side == signal.side and s.strategy != "consensus"]
        different_strategies = sorted({s.strategy for s in same})
        if len(different_strategies) < 2:
            return None
        conflict = [s for s in self._buffer if s.market_id == signal.market_id and s.side != signal.side and s.strategy != "consensus"]
        if conflict:
            return None
        confidence = min(0.99, sum(s.confidence for s in same) / len(same) + 0.08)
        base = same[-1]
        merged_reasons = sorted({reason for s in same for reason in s.reason_codes} | {"CONSENSUS_CONFIRMED"})
        metrics = {
            "source_strategies": different_strategies,
            "source_signal_ids": [s.signal_id for s in same],
            "source_confidence_avg": sum(s.confidence for s in same) / len(same),
        }
        return SignalCandidate.build(
            strategy="consensus",
            asset=base.asset,
            timeframe=base.timeframe,
            market_id=base.market_id,
            market_slug=base.market_slug,
            condition_id=base.condition_id,
            token_id=base.token_id,
            side=base.side,
            confidence=confidence,
            entry_reference_price=base.entry_reference_price,
            max_entry_price=base.max_entry_price,
            seconds_to_close=base.seconds_to_close,
            data_freshness_ms=base.data_freshness_ms,
            reason_codes=merged_reasons,
            metrics=metrics,
            snapshot_id=base.snapshot_id,
            source_signal_ids=[s.signal_id for s in same],
        )
