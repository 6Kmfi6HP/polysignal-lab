"""
Input: __future__, __future__.annotations, collections, collections.defaultdict, datetime, datetime.datetime, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate
Output: ConsensusEngine
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations


from polysignal_lab.domain.signal import SignalCandidate


class ConsensusEngine:
    def __init__(self, window_sec: int = 45, enabled: bool = True):
        self.window_sec = window_sec
        self.enabled = enabled
        self._buffer: list[SignalCandidate] = []

    def add(self, signal: SignalCandidate) -> SignalCandidate | None:
        if not self.enabled:
            return None
        reference_time = max(
            (candidate.created_at for candidate in self._buffer),
            default=signal.created_at,
        )
        reference_time = max(reference_time, signal.created_at)
        if (reference_time - signal.created_at).total_seconds() > self.window_sec:
            return None
        self._buffer = [
            candidate
            for candidate in self._buffer
            if 0 <= (reference_time - candidate.created_at).total_seconds() <= self.window_sec
        ]
        self._buffer.append(signal)
        same = [
            candidate
            for candidate in self._buffer
            if candidate.market_id == signal.market_id
            and candidate.side == signal.side
            and candidate.strategy != "consensus"
        ]
        different_strategies = sorted({candidate.strategy for candidate in same})
        if len(different_strategies) < 2:
            return None
        conflict = [
            candidate
            for candidate in self._buffer
            if candidate.market_id == signal.market_id
            and candidate.side != signal.side
            and candidate.strategy != "consensus"
        ]
        if conflict:
            return None
        confidence = min(0.99, sum(candidate.confidence for candidate in same) / len(same) + 0.08)
        base = max(same, key=lambda candidate: candidate.created_at)
        consensus_time = base.created_at
        merged_reasons = sorted(
            {reason for candidate in same for reason in candidate.reason_codes}
            | {"CONSENSUS_CONFIRMED"}
        )
        metrics = {
            "source_strategies": different_strategies,
            "source_signal_ids": [candidate.signal_id for candidate in same],
            "source_confidence_avg": sum(candidate.confidence for candidate in same) / len(same),
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
            created_at=consensus_time,
            snapshot_id=base.snapshot_id,
            source_signal_ids=[candidate.signal_id for candidate in same],
            reduce_only=base.reduce_only,
        )
