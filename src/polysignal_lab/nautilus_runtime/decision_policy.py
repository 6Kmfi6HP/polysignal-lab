from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import cast

from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.pretrade.gate import SignalGate


def decision_policy_from_settings(settings: object) -> DecisionPolicy:
    """Per-Strategy pretrade checks only — RiskEngine owns account/exposure risk."""
    signal = getattr(settings, "signal", SignalConfig())
    data = getattr(settings, "data", None)
    poly = (
        getattr(data, "polymarket", PolymarketDataConfig())
        if data is not None
        else PolymarketDataConfig()
    )
    binance = (
        getattr(data, "binance", BinanceDataConfig())
        if data is not None
        else BinanceDataConfig()
    )
    return DecisionPolicy(gate=SignalGate(signal, poly, binance))


def candidate_from_decision(
    decision: AlphaDecision, view: MarketView
) -> SignalCandidate:
    """Publish/projection DTO only — never used as order-routing SoT."""
    view_id = str(getattr(view, "view_id", "") or "")
    return SignalCandidate.build(
        signal_id=decision.signal_id(view_id),
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
        created_at=getattr(view, "created_at", None),
        snapshot_id=view_id,
        order_intent=decision.order_intent.intent if decision.order_intent else None,
        expiry_seconds=decision.order_intent.expiry_seconds
        if decision.order_intent
        else None,
        pair_id=decision.order_intent.pair_id if decision.order_intent else None,
        reduce_only=decision.reduce_only,
        hedge_leg=decision.hedge_leg,
    )


def publish_from_approved(approved: ApprovedDecision) -> SignalCandidate:
    """Telegram/SQLite projection from an approved trading intent."""
    return approved.publish


@dataclass(frozen=True, slots=True)
class ApprovedDecision:
    """Gate-approved AlphaDecision plus a publish-only projection.

    Trading/order path must use ``decision`` (and Nautilus OrderFactory).
    ``publish`` is SignalCandidate for notifications/storage only.
    """

    decision: AlphaDecision
    publish: SignalCandidate


@dataclass(frozen=True, slots=True)
class RejectedDecision:
    reason_code: str
    detail: Mapping[str, object]
    decision: AlphaDecision | None = None
    publish: SignalCandidate | None = None


@dataclass(frozen=True, slots=True)
class BatchArbitrationResult:
    """Gate-approved decisions and rejections after pair arbitration."""

    approvals: tuple[ApprovedDecision, ...] = ()
    rejections: tuple[tuple[AlphaDecision, RejectedDecision], ...] = ()


class DecisionPolicy:
    """Stateless strategy pretrade gate; RiskEngine + Cache own account risk."""

    def __init__(
        self,
        *,
        gate: SignalGate | None = None,
        disabled_strategies: Iterable[str] = (),
        strategy_freshness_policies: Mapping[str, FreshnessPolicy] | None = None,
    ) -> None:
        signal_config = SignalConfig()
        self.gate: SignalGate = gate or SignalGate(
            signal_config, PolymarketDataConfig(), BinanceDataConfig()
        )
        self.disabled_strategies: set[str] = set(disabled_strategies)
        self.strategy_freshness_policies: dict[str, FreshnessPolicy] = dict(
            strategy_freshness_policies or {}
        )

    def orderbook_readiness_threshold_ms(self) -> float:
        return float(self.gate.poly_config.max_book_readiness_staleness_ms)

    def orderbook_trade_threshold_ms(self, strategy: str) -> float:
        return self.gate.orderbook_freshness_threshold_ms(
            self.strategy_freshness_policies.get(strategy)
        )

    def set_strategy_enabled(self, name: str, enabled: bool) -> None:
        if enabled:
            self.disabled_strategies.discard(name)
        else:
            self.disabled_strategies.add(name)

    def save_state(self) -> dict[str, object]:
        return {"disabled_strategies": sorted(self.disabled_strategies)}

    def load_state(self, payload: Mapping[str, object]) -> None:
        disabled = payload.get("disabled_strategies", ()) or ()
        if isinstance(disabled, Iterable) and not isinstance(disabled, (str, bytes)):
            self.disabled_strategies |= {
                str(name) for name in cast(Iterable[object], disabled)
            }

    def decide(
        self, decision: AlphaDecision, view: MarketView
    ) -> ApprovedDecision | RejectedDecision:
        return self.evaluate(decision, view)

    def evaluate(
        self, decision: AlphaDecision, view: MarketView
    ) -> ApprovedDecision | RejectedDecision:
        if decision.strategy in self.disabled_strategies:
            return RejectedDecision(
                reason_code="manual_disabled",
                detail={},
                decision=decision,
            )
        gate_decision = self.gate.evaluate(
            decision,
            view,
            freshness_policy=self.strategy_freshness_policies.get(decision.strategy),
        )
        if gate_decision.accepted:
            publish = gate_decision.publish or candidate_from_decision(decision, view)
            return ApprovedDecision(decision=decision, publish=publish)
        if gate_decision.rejected is not None:
            rejected = gate_decision.rejected
            return RejectedDecision(
                reason_code=rejected.reason_code,
                detail=dict(rejected.details),
                decision=decision,
                publish=rejected.candidate,
            )
        return RejectedDecision(
            reason_code="GATE_REJECTED",
            detail={},
            decision=decision,
            publish=candidate_from_decision(decision, view),
        )

    def batch_arbitrate(
        self,
        decisions: list[tuple[AlphaDecision, MarketView]],
    ) -> BatchArbitrationResult:
        """Return gate-approved decisions and rejections after pair arbitration."""
        unpaired, rejections = self._partition_batch(decisions)
        committed, gate_rejections = self._gate_batch(unpaired)
        rejections.extend(gate_rejections)
        return BatchArbitrationResult(
            approvals=tuple(
                ApprovedDecision(decision=decision, publish=publish)
                for decision, _, publish in committed
            ),
            rejections=tuple(rejections),
        )

    def _partition_batch(
        self,
        decisions: list[tuple[AlphaDecision, MarketView]],
    ) -> tuple[
        list[tuple[AlphaDecision, MarketView]],
        list[tuple[AlphaDecision, RejectedDecision]],
    ]:
        rejections: list[tuple[AlphaDecision, RejectedDecision]] = []
        unpaired: list[tuple[AlphaDecision, MarketView]] = []
        pairs: dict[str, list[tuple[AlphaDecision, MarketView]]] = {}
        for decision, view in decisions:
            if decision.strategy in self.disabled_strategies:
                rejections.append(
                    (
                        decision,
                        RejectedDecision(
                            reason_code="manual_disabled",
                            detail={},
                            decision=decision,
                        ),
                    )
                )
                continue
            pair_id = decision.pair_id
            if pair_id:
                pairs.setdefault(pair_id, []).append((decision, view))
            else:
                unpaired.append((decision, view))
        for members in pairs.values():
            self._resolve_pair_group(members, unpaired=unpaired, rejections=rejections)
        return unpaired, rejections

    def _resolve_pair_group(
        self,
        members: list[tuple[AlphaDecision, MarketView]],
        *,
        unpaired: list[tuple[AlphaDecision, MarketView]],
        rejections: list[tuple[AlphaDecision, RejectedDecision]],
    ) -> None:
        sides = {decision.side for decision, _ in members}
        malformed = len(members) > 2 or (
            len(members) == 2 and sides != {Side.UP, Side.DOWN}
        )
        if not malformed and len(members) == 2:
            unpaired.extend(members)
            return
        reason = "MALFORMED_PAIR" if malformed else "INCOMPLETE_PAIR"
        for decision, view in members:
            rejections.append(
                (
                    decision,
                    RejectedDecision(
                        reason_code=reason,
                        detail={},
                        decision=decision,
                        publish=candidate_from_decision(decision, view),
                    ),
                )
            )

    def _gate_batch(
        self,
        unpaired: list[tuple[AlphaDecision, MarketView]],
    ) -> tuple[
        list[tuple[AlphaDecision, MarketView, SignalCandidate]],
        list[tuple[AlphaDecision, RejectedDecision]],
    ]:
        committed: list[tuple[AlphaDecision, MarketView, SignalCandidate]] = []
        rejections: list[tuple[AlphaDecision, RejectedDecision]] = []
        for decision, view in unpaired:
            gate_decision = self.gate.evaluate(
                decision,
                view,
                freshness_policy=self.strategy_freshness_policies.get(
                    decision.strategy
                ),
            )
            if gate_decision.accepted:
                publish = gate_decision.publish or candidate_from_decision(
                    decision, view
                )
                committed.append((decision, view, publish))
                continue
            if gate_decision.rejected is not None:
                rejected = gate_decision.rejected
                rejections.append(
                    (
                        decision,
                        RejectedDecision(
                            reason_code=rejected.reason_code,
                            detail=dict(rejected.details),
                            decision=decision,
                            publish=rejected.candidate,
                        ),
                    )
                )
            else:
                rejections.append(
                    (
                        decision,
                        RejectedDecision(
                            reason_code="GATE_REJECTED",
                            detail={},
                            decision=decision,
                            publish=candidate_from_decision(decision, view),
                        ),
                    )
                )
        return committed, rejections
