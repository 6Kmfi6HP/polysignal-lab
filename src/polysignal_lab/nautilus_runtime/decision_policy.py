"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Iterable, collections.abc.Mapping, dataclasses, dataclasses.dataclass, typing, typing.cast, polysignal_lab.alpha.types
Output: ApprovedDecision, RejectedDecision, candidate_from_decision, _MarketAdapter, _BookAdapter, _SpotAdapter, _GateSnapshotAdapter, DecisionPolicy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from polysignal_lab.alpha.types import AlphaDecision, MarketView, SideBookView, SpotView
from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.signal_layer.arbiter import SignalArbiter
from polysignal_lab.signal_layer.consensus import ConsensusEngine
from polysignal_lab.signal_layer.gate import SignalGate

def _string_tuple_mapping(raw: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw, Mapping):
        return {}
    raw_mapping = cast(Mapping[object, object], raw)
    coerced: dict[str, tuple[str, ...]] = {}
    for name, deps in raw_mapping.items():
        if isinstance(deps, str):
            coerced[str(name)] = (deps,)
            continue
        if isinstance(deps, Iterable):
            coerced[str(name)] = tuple(str(dep) for dep in deps)
    return coerced

_UNKNOWN_LAG_MS = 10**12


def candidate_from_decision(decision: AlphaDecision, view: MarketView) -> SignalCandidate:
    return SignalCandidate.build(
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
        created_at=view.created_at,
        snapshot_id=view.view_id,
        order_intent=decision.order_intent.intent if decision.order_intent else None,
        expiry_seconds=decision.order_intent.expiry_seconds if decision.order_intent else None,
        pair_id=decision.order_intent.pair_id if decision.order_intent else None,
        reduce_only=decision.order_intent.reduce_only if decision.order_intent else False,
        hedge_leg=decision.hedge_leg,
    )


@dataclass(frozen=True, slots=True)
class ApprovedDecision:
    signal: SignalCandidate
    consensus: SignalCandidate | None = None


@dataclass(frozen=True, slots=True)
class RejectedDecision:
    reason_code: str
    detail: Mapping[str, object]
    candidate: SignalCandidate | None = None


class BatchArbitrationResult(list[AlphaDecision]):
    def __init__(
        self,
        survivors: Iterable[AlphaDecision] = (),
        rejections: Iterable[tuple[AlphaDecision, RejectedDecision]] = (),
    ) -> None:
        super().__init__(survivors)
        self.rejections = tuple(rejections)


_BatchEntry = tuple[AlphaDecision, MarketView, SignalCandidate]
_PreparedBatchEntry = tuple[
    AlphaDecision, MarketView, SignalCandidate | None, RejectedDecision | None
]


@dataclass(frozen=True, slots=True)
class _MarketAdapter:
    is_active: bool


@dataclass(frozen=True, slots=True)
class _BookAdapter:
    book: SideBookView

    @property
    def spread(self) -> float | None:
        return self.book.spread

    def freshness_ms(self, _now: object = None) -> int:
        return self.book.freshness_ms if self.book.freshness_ms is not None else _UNKNOWN_LAG_MS


@dataclass(frozen=True, slots=True)
class _SpotAdapter:
    spot: SpotView

    def freshness_ms(self, now: object = None) -> int:
        if isinstance(now, datetime):
            dynamic = self.spot.freshness_ms_at(now)
            if dynamic is not None:
                return dynamic
        return self.spot.freshness_ms if self.spot.freshness_ms is not None else _UNKNOWN_LAG_MS


@dataclass(frozen=True, slots=True)
class _GateSnapshotAdapter:
    """Minimal MarketSnapshot-shaped view over MarketView for SignalGate.evaluate."""

    view: MarketView

    @property
    def created_at(self) -> object:
        return self.view.created_at

    @property
    def market(self) -> _MarketAdapter:
        metrics = cast(Mapping[str, object], self.view.metrics)
        raw = metrics.get("market_is_active", metrics.get("is_active", True))
        return _MarketAdapter(is_active=bool(raw))

    @property
    def spot(self) -> _SpotAdapter | None:
        return _SpotAdapter(self.view.spot) if self.view.spot is not None else None

    def book_for(self, side: Side) -> _BookAdapter | None:
        book = self.view.book_for(side)
        if (
            book.best_bid is None
            and book.best_ask is None
            and book.spread is None
            and book.freshness_ms is None
        ):
            return None
        return _BookAdapter(book)

    def ask_for(self, side: Side) -> float | None:
        return self.view.ask_for(side)


class DecisionPolicy:
    """Decision gate, arbitration, and consensus for signal evaluation.

    Runs before Nautilus order submission; Nautilus RiskEngine still owns
    account, exposure, and execution-side risk checks.

    Owns the active SignalGate/SignalArbiter/ConsensusEngine instances.
    These are the single source of truth — no parallel instances exist elsewhere.
    """

    def __init__(
        self,
        *,
        gate: SignalGate | None = None,
        arbiter: SignalArbiter | None = None,
        consensus: ConsensusEngine | None = None,
        disabled_strategies: Iterable[str] = (),
        dependencies: Mapping[str, Iterable[str]] | None = None,
        strategy_freshness_policies: Mapping[str, FreshnessPolicy] | None = None,
    ) -> None:
        signal_config = SignalConfig()
        # Gate/consensus/arbiter default-constructed here; callers may pass
        # instances via parameters for testing or custom wiring.
        self.gate: SignalGate = gate or SignalGate(signal_config, PolymarketDataConfig(), BinanceDataConfig())
        self.arbiter: SignalArbiter = arbiter or SignalArbiter()
        self.consensus: ConsensusEngine = consensus or ConsensusEngine(
            window_sec=signal_config.consensus_window_sec,
            enabled=signal_config.consensus_enabled,
        )
        self.disabled_strategies: set[str] = set(disabled_strategies)
        self.strategy_dependencies: dict[str, tuple[str, ...]] = {
            name: tuple(deps) for name, deps in (dependencies or {}).items()
        }
        self.strategy_freshness_policies: dict[str, FreshnessPolicy] = dict(strategy_freshness_policies or {})
        self._batch_approved: dict[
            int, tuple[AlphaDecision, MarketView, SignalCandidate]
        ] = {}

    def set_strategy_enabled(self, name: str, enabled: bool) -> None:
        if enabled:
            self.disabled_strategies.discard(name)
        else:
            self.disabled_strategies.add(name)

    def save_state(self) -> dict[str, object]:
        return {
            "disabled_strategies": sorted(self.disabled_strategies),
            "strategy_dependencies": {
                name: list(deps)
                for name, deps in sorted(self.strategy_dependencies.items())
            },
        }

    def load_state(self, payload: Mapping[str, object]) -> None:
        disabled = payload.get("disabled_strategies", ()) or ()
        dependencies = _string_tuple_mapping(payload.get("strategy_dependencies", {}))
        saved_disabled = (
            {str(name) for name in cast(Iterable[object], disabled)}
            if isinstance(disabled, Iterable) and not isinstance(disabled, (str, bytes))
            else set()
        )
        self.disabled_strategies = self.disabled_strategies | saved_disabled
        if dependencies:
            self.strategy_dependencies = {**self.strategy_dependencies, **dependencies}

    def decide(
        self, decision: AlphaDecision, view: MarketView
    ) -> ApprovedDecision | RejectedDecision:
        return self.evaluate(decision, view)

    def evaluate(
        self, decision: AlphaDecision, view: MarketView
    ) -> ApprovedDecision | RejectedDecision:
        handoff = self._batch_approved.get(id(decision))
        if handoff is not None and handoff[0] is decision and handoff[1] is view:
            _ = self._batch_approved.pop(id(decision))
            signal = handoff[2]
            return ApprovedDecision(signal=signal, consensus=self.consensus.add(signal))
        skip_reason = self._skip_reason_for(decision.strategy)
        if skip_reason is not None:
            return RejectedDecision(reason_code=skip_reason, detail={})

        candidate = self._candidate_from_decision(decision, view)
        if not self._arbiter_keeps(candidate):
            return RejectedDecision(
                reason_code="ARBITRATION_SUPPRESSED",
                detail={
                    "strategy": candidate.strategy,
                    "conflict_policy": getattr(self.arbiter, "conflict_policy", None),
                },
                candidate=candidate,
            )

        gate_decision = self.gate.evaluate(
            candidate,
            cast(MarketSnapshot, cast(object, _GateSnapshotAdapter(view))),
        )
        if gate_decision.accepted:
            signal = gate_decision.signal or candidate
            return ApprovedDecision(signal=signal, consensus=self.consensus.add(signal))
        if gate_decision.rejected is not None:
            rejected = gate_decision.rejected
            return RejectedDecision(
                reason_code=rejected.reason_code,
                detail=dict(rejected.details),
                candidate=rejected.candidate,
            )
        return RejectedDecision(reason_code="GATE_REJECTED", detail={}, candidate=candidate)

    def _skip_reason_for(self, name: str) -> str | None:
        if name in self.disabled_strategies:
            return "manual_disabled"
        for dependency in self.strategy_dependencies.get(name, ()):
            if dependency in self.disabled_strategies:
                return f"dependency_disabled:{dependency}"
        return None

    def _arbiter_keeps(self, candidate: SignalCandidate) -> bool:
        kept = self.arbiter.arbitrate(
            [candidate],
            strategy_priorities={candidate.strategy: 0},
            strategy_config_indexes={candidate.strategy: 0},
            market_config_indexes={candidate.market_id: 0},
        )
        return any(id(item) == id(candidate) for item in kept)

    def batch_arbitrate(
        self,
        decisions: list[tuple[AlphaDecision, MarketView]],
    ) -> BatchArbitrationResult:
        """Commit only complete, prevalidated batch survivors in stable order."""
        self._batch_approved.clear()
        prepared, pairs, rejections = self._prepare_batch(decisions)
        paired, pair_rejections = self._eligible_pair_entries(pairs)
        rejections.extend(pair_rejections)
        unpaired = self._eligible_unpaired(prepared)
        kept_ids = self._arbitrated_candidate_ids(unpaired)
        rejections.extend(self._suppressed_rejections(unpaired, kept_ids))
        committed, gate_rejections = self._commit_eligible(paired, unpaired, kept_ids)
        rejections.extend(gate_rejections)
        committed.sort(key=self._candidate_sort_key)
        self._batch_approved = {
            id(decision): (decision, view, candidate)
            for decision, view, candidate in committed
        }
        committed_ids = {id(decision) for decision, _, _ in committed}
        survivors = [decision for decision, _ in decisions if id(decision) in committed_ids]
        return BatchArbitrationResult(survivors, rejections)

    def _prepare_batch(
        self, decisions: list[tuple[AlphaDecision, MarketView]]
    ) -> tuple[
        list[_PreparedBatchEntry],
        dict[str, list[_PreparedBatchEntry]],
        list[tuple[AlphaDecision, RejectedDecision]],
    ]:
        prepared: list[_PreparedBatchEntry] = []
        pairs: dict[str, list[_PreparedBatchEntry]] = {}
        rejections: list[tuple[AlphaDecision, RejectedDecision]] = []
        for decision, view in decisions:
            result = self._batch_candidate(decision, view)
            candidate = result if isinstance(result, SignalCandidate) else None
            rejection = result if isinstance(result, RejectedDecision) else None
            entry = (decision, view, candidate, rejection)
            prepared.append(entry)
            pair_id = decision.order_intent.pair_id if decision.order_intent else None
            if pair_id:
                pairs.setdefault(pair_id, []).append(entry)
            elif rejection is not None:
                rejections.append((decision, rejection))
        return prepared, pairs, rejections

    @staticmethod
    def _eligible_pair_entries(
        pairs: dict[str, list[_PreparedBatchEntry]],
    ) -> tuple[list[_BatchEntry], list[tuple[AlphaDecision, RejectedDecision]]]:
        eligible: list[_BatchEntry] = []
        rejections: list[tuple[AlphaDecision, RejectedDecision]] = []
        for members in pairs.values():
            candidates = [candidate for _, _, candidate, _ in members if candidate is not None]
            malformed = len(members) > 2 or (
                len(candidates) == 2
                and {candidate.side for candidate in candidates} != {Side.UP, Side.DOWN}
            )
            if not malformed and len(candidates) == 2:
                eligible.extend(
                    (decision, view, candidate)
                    for decision, view, candidate, _ in members
                    if candidate is not None
                )
                continue
            reason_code = "MALFORMED_PAIR" if malformed else "INCOMPLETE_PAIR"
            rejections.extend(
                (
                    decision,
                    rejection
                    or RejectedDecision(reason_code=reason_code, detail={}, candidate=candidate),
                )
                for decision, _, candidate, rejection in members
            )
        return eligible, rejections

    @staticmethod
    def _eligible_unpaired(prepared: list[_PreparedBatchEntry]) -> list[_BatchEntry]:
        return sorted(
            (
                (decision, view, candidate)
                for decision, view, candidate, rejection in prepared
                if candidate is not None
                and rejection is None
                and not (decision.order_intent and decision.order_intent.pair_id)
            ),
            key=DecisionPolicy._candidate_sort_key,
        )

    def _arbitrated_candidate_ids(self, unpaired: list[_BatchEntry]) -> set[int]:
        candidates = [candidate for _, _, candidate in unpaired]
        return {
            id(candidate)
            for candidate in self.arbiter.arbitrate(
                candidates,
                strategy_priorities={candidate.strategy: 0 for candidate in candidates},
                strategy_config_indexes={candidate.strategy: 0 for candidate in candidates},
                market_config_indexes={candidate.market_id: 0 for candidate in candidates},
            )
        }

    def _suppressed_rejections(
        self, unpaired: list[_BatchEntry], kept_ids: set[int]
    ) -> list[tuple[AlphaDecision, RejectedDecision]]:
        return [
            (
                decision,
                RejectedDecision(
                    reason_code="ARBITRATION_SUPPRESSED",
                    detail={
                        "strategy": candidate.strategy,
                        "conflict_policy": getattr(self.arbiter, "conflict_policy", None),
                    },
                    candidate=candidate,
                ),
            )
            for decision, _, candidate in unpaired
            if id(candidate) not in kept_ids
        ]

    def _commit_eligible(
        self,
        paired: list[_BatchEntry],
        unpaired: list[_BatchEntry],
        kept_ids: set[int],
    ) -> tuple[list[_BatchEntry], list[tuple[AlphaDecision, RejectedDecision]]]:
        committed: list[_BatchEntry] = []
        rejections: list[tuple[AlphaDecision, RejectedDecision]] = []
        for group in self._commit_groups(paired, unpaired, kept_ids):
            gate_results = self.gate.commit([candidate for _, _, candidate in group])
            if all(result.accepted for result in gate_results):
                committed.extend(group)
                continue
            rejections.extend(
                (decision, self._rejected_gate_decision(result, candidate))
                for (decision, _, candidate), result in zip(group, gate_results, strict=True)
            )
        return committed, rejections

    @staticmethod
    def _candidate_sort_key(
        item: tuple[AlphaDecision, MarketView, SignalCandidate]
    ) -> tuple[str, str, str, str]:
        candidate = item[2]
        return (
            candidate.strategy,
            candidate.market_id,
            candidate.token_id,
            candidate.side.value,
        )

    @staticmethod
    def _commit_groups(
        paired: list[tuple[AlphaDecision, MarketView, SignalCandidate]],
        unpaired: list[tuple[AlphaDecision, MarketView, SignalCandidate]],
        kept_ids: set[int],
    ) -> list[list[tuple[AlphaDecision, MarketView, SignalCandidate]]]:
        pairs_by_id: dict[str, list[tuple[AlphaDecision, MarketView, SignalCandidate]]] = {}
        for entry in paired:
            pair_id = entry[2].pair_id
            if pair_id is not None:
                pairs_by_id.setdefault(pair_id, []).append(entry)
        pair_groups = [
            sorted(group, key=DecisionPolicy._candidate_sort_key)
            for _, group in sorted(pairs_by_id.items())
        ]
        return pair_groups + [
            [entry] for entry in unpaired if id(entry[2]) in kept_ids
        ]

    @staticmethod
    def _rejected_gate_decision(
        gate_decision: object, candidate: SignalCandidate
    ) -> RejectedDecision:
        rejected = getattr(gate_decision, "rejected", None)
        if rejected is None:
            return RejectedDecision(reason_code="GATE_REJECTED", detail={}, candidate=candidate)
        return RejectedDecision(
            reason_code=rejected.reason_code,
            detail=dict(rejected.details),
            candidate=rejected.candidate,
        )

    def _batch_candidate(
        self, decision: AlphaDecision, view: MarketView
    ) -> SignalCandidate | RejectedDecision:
        skip_reason = self._skip_reason_for(decision.strategy)
        if skip_reason is not None:
            return RejectedDecision(reason_code=skip_reason, detail={})
        candidate = self._candidate_from_decision(decision, view)
        gate_decision = self.gate.prevalidate(
            candidate,
            cast(MarketSnapshot, cast(object, _GateSnapshotAdapter(view))),
        )
        if gate_decision.accepted:
            return gate_decision.signal or candidate
        if gate_decision.rejected is not None:
            rejected = gate_decision.rejected
            return RejectedDecision(
                reason_code=rejected.reason_code,
                detail=dict(rejected.details),
                candidate=rejected.candidate,
            )
        return RejectedDecision(reason_code="GATE_REJECTED", detail={}, candidate=candidate)

    def _candidate_from_decision(
        self, decision: AlphaDecision, view: MarketView
    ) -> SignalCandidate:
        candidate = candidate_from_decision(decision, view)
        policy = self.strategy_freshness_policies.get(decision.strategy)
        if policy is None:
            return candidate
        return candidate.model_copy(update={"freshness_policy": policy})
