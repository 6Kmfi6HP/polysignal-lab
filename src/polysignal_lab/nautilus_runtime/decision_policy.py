"""Decision policy actor for Nautilus alpha decisions.

The actor stays Nautilus-free: it converts ``AlphaDecision`` objects into the
existing signal-layer types and runs the same gate/consensus policy used by the
current runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from polysignal_lab.alpha.types import AlphaDecision, MarketView, SideBookView, SpotView
from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.signal_layer.arbiter import SignalArbiter
from polysignal_lab.signal_layer.consensus import ConsensusEngine
from polysignal_lab.signal_layer.gate import SignalGate

_UNKNOWN_LAG_MS = 10**12


@dataclass(frozen=True, slots=True)
class ApprovedDecision:
    signal: SignalCandidate
    consensus: SignalCandidate | None = None


@dataclass(frozen=True, slots=True)
class RejectedDecision:
    reason_code: str
    detail: Mapping[str, Any]
    candidate: SignalCandidate | None = None


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

    def freshness_ms(self, _now: object = None) -> int:
        return self.spot.freshness_ms if self.spot.freshness_ms is not None else _UNKNOWN_LAG_MS


@dataclass(frozen=True, slots=True)
class _GateSnapshotAdapter:
    view: MarketView

    @property
    def created_at(self) -> object:
        return self.view.created_at

    @property
    def market(self) -> _MarketAdapter:
        raw = self.view.metrics.get("market_is_active", self.view.metrics.get("is_active", True))
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


class DecisionPolicyActor:
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
        self.gate = gate or SignalGate(signal_config, PolymarketDataConfig(), BinanceDataConfig())
        self.arbiter = arbiter or SignalArbiter()
        self.consensus = consensus or ConsensusEngine(
            window_sec=signal_config.consensus_window_sec,
            enabled=signal_config.consensus_enabled,
        )
        self.disabled_strategies = set(disabled_strategies)
        self.strategy_dependencies = {
            name: tuple(deps) for name, deps in (dependencies or {}).items()
        }
        self.strategy_freshness_policies = dict(strategy_freshness_policies or {})

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
        dependencies = payload.get("strategy_dependencies", {}) or {}
        self.disabled_strategies = {str(name) for name in disabled}
        self.strategy_dependencies = {
            str(name): tuple(str(dep) for dep in deps)
            for name, deps in dict(dependencies).items()
        }

    def evaluate(
        self, decision: AlphaDecision, view: MarketView
    ) -> ApprovedDecision | RejectedDecision:
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

        gate_decision = self.gate.evaluate(candidate, _GateSnapshotAdapter(view))
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

    def _candidate_from_decision(
        self, decision: AlphaDecision, view: MarketView
    ) -> SignalCandidate:
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
            freshness_policy=self.strategy_freshness_policies.get(decision.strategy),
            snapshot_id=view.view_id,
            order_intent=decision.order_intent.intent if decision.order_intent else None,
            expiry_seconds=decision.order_intent.expiry_seconds if decision.order_intent else None,
            pair_id=decision.order_intent.pair_id if decision.order_intent else None,
            hedge_leg=decision.hedge_leg,
        )
