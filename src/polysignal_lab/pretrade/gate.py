from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from polysignal_lab.alpha.types import AlphaDecision, MarketView, SideBookView, SpotView
from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate

_UNKNOWN_LAG_MS = 10**12


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Pretrade check result. ``publish`` is optional projection for storage only."""

    accepted: bool
    decision: AlphaDecision | None = None
    publish: SignalCandidate | None = None
    rejected: RejectedSignal | None = None


GateDetails = dict[str, str | float | int | None]
GateCheck = Callable[[AlphaDecision, MarketView], "GateRejection | None"]


@dataclass(frozen=True, slots=True)
class GateRejection:
    reason_code: str
    details: GateDetails = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _FreshnessCheckSpec:
    source: str
    missing_reason: str
    stale_reason: str


_BOOK_FRESHNESS = _FreshnessCheckSpec(
    source="orderbook",
    missing_reason="MISSING_ORDERBOOK",
    stale_reason="STALE_ORDERBOOK",
)
_SPOT_FRESHNESS = _FreshnessCheckSpec(
    source="spot_price",
    missing_reason="MISSING_SPOT_PRICE",
    stale_reason="STALE_SPOT_PRICE",
)


def _book_present(book: SideBookView) -> bool:
    return not (
        book.best_bid is None
        and book.best_ask is None
        and book.spread is None
        and book.freshness_ms is None
    )


def _book_lag_ms(book: SideBookView) -> int:
    return book.freshness_ms if book.freshness_ms is not None else _UNKNOWN_LAG_MS


def _spot_lag_ms(spot: SpotView, now: datetime) -> int:
    dynamic = spot.freshness_ms_at(now)
    if dynamic is not None:
        return dynamic
    return spot.freshness_ms if spot.freshness_ms is not None else _UNKNOWN_LAG_MS


def _market_is_active(view: MarketView) -> bool:
    metrics = view.metrics if isinstance(view.metrics, Mapping) else {}
    raw = metrics.get("market_is_active", metrics.get("is_active", True))
    return bool(raw)


class SignalGate:
    """Stateless strategy pretrade checks on AlphaDecision.

    Account/exposure/rate limits belong to Nautilus RiskEngine + Cache.
    """

    def __init__(
        self,
        signal_config: SignalConfig,
        poly_config: PolymarketDataConfig,
        binance_config: BinanceDataConfig,
    ) -> None:
        self.signal_config = signal_config
        self.poly_config = poly_config
        self.binance_config = binance_config

    def evaluate(
        self,
        decision: AlphaDecision,
        view: MarketView,
        *,
        freshness_policy: FreshnessPolicy | None = None,
    ) -> GateDecision:
        prevalidated = self.prevalidate(
            decision, view, freshness_policy=freshness_policy
        )
        if not prevalidated.accepted:
            return prevalidated
        publish = self._publish_projection(decision, view)
        return GateDecision(True, decision=decision, publish=publish)

    def commit(
        self,
        decisions: list[AlphaDecision],
        view: MarketView,
        *,
        freshness_policy: FreshnessPolicy | None = None,
    ) -> list[GateDecision]:
        """Evaluate each AlphaDecision; RiskEngine owns stateful rate limits."""
        return [
            self.evaluate(decision, view, freshness_policy=freshness_policy)
            for decision in decisions
        ]

    def prevalidate(
        self,
        decision: AlphaDecision,
        view: MarketView,
        *,
        freshness_policy: FreshnessPolicy | None = None,
    ) -> GateDecision:
        """Check eligibility without RiskEngine/Cache stateful checks."""
        previous = getattr(self, "_freshness_policy", None)
        self._freshness_policy = freshness_policy
        try:
            return self._evaluate_checks(
                decision,
                view,
                [
                    self._identity,
                    self._market_active,
                    self._time_window,
                    self._book_freshness,
                    self._spot_freshness,
                    self._spread,
                    self._max_entry,
                    self._gtd_expiry,
                    self._confidence,
                ],
            )
        finally:
            self._freshness_policy = previous

    def _evaluate_checks(
        self,
        decision: AlphaDecision,
        view: MarketView,
        checks: list[GateCheck],
    ) -> GateDecision:
        log = logging.getLogger("polysignal_lab.gate")
        for check in checks:
            rejection = check(decision, view)
            if rejection:
                reason = rejection.reason_code
                log.info(
                    "GATE_REJECT %s %s market=%s side=%s reason=%s",
                    check.__name__,
                    reason,
                    decision.market_id[:16],
                    decision.side.value,
                    reason,
                )
                publish = self._publish_projection(decision, view)
                return GateDecision(
                    False,
                    decision=decision,
                    publish=publish,
                    rejected=RejectedSignal(
                        candidate=publish,
                        gate_name=check.__name__,
                        reason_code=reason,
                        details=self._rejection_details(decision, rejection, publish),
                    ),
                )
        log.info(
            "GATE_ACCEPT market=%s side=%s confidence=%.3f strategy=%s",
            decision.market_id[:16],
            decision.side.value,
            decision.confidence,
            decision.strategy,
        )
        return GateDecision(True, decision=decision)

    def _publish_projection(
        self, decision: AlphaDecision, view: MarketView
    ) -> SignalCandidate:
        # Local import avoids gate → decision_policy cycle.
        from polysignal_lab.nautilus_runtime.decision_policy import (
            candidate_from_decision,
        )

        return candidate_from_decision(decision, view)

    def _rejection_details(
        self,
        decision: AlphaDecision,
        rejection: GateRejection,
        publish: SignalCandidate,
    ) -> dict[str, str | float | int | None]:
        details: dict[str, str | float | int | None] = {
            "reason_code": rejection.reason_code,
            "signal_id": publish.signal_id,
            "strategy": decision.strategy,
            "asset": decision.asset,
            "timeframe": decision.timeframe,
            "market_id": decision.market_id,
            "side": decision.side.value,
            "confidence": decision.confidence,
            "entry_reference_price": decision.entry_reference_price,
            "max_entry_price": decision.max_entry_price,
            "seconds_to_close": decision.seconds_to_close,
            "dedupe_key": decision.dedupe_key(),
        }
        details.update(rejection.details)
        return details

    def _policy_threshold(
        self,
        policy: FreshnessPolicy | None,
        policy_value: int | float | None,
        global_value: int,
    ) -> tuple[int | float, str]:
        if policy is None or policy_value is None:
            return global_value, "global"
        return min(global_value, policy_value), "strategy_and_global"

    def orderbook_freshness_threshold_ms(
        self,
        policy: FreshnessPolicy | None,
    ) -> float:
        policy_value = None if policy is None else policy.max_orderbook_staleness_ms
        threshold_ms, _ = self._policy_threshold(
            policy,
            policy_value,
            self.poly_config.max_book_staleness_ms,
        )
        return float(threshold_ms)

    @staticmethod
    def _freshness_details(
        *,
        source: str,
        lag_ms: int | None,
        threshold_ms: int | float,
        policy_source: str,
    ) -> GateDetails:
        return {
            "source": source,
            "lag_ms": lag_ms,
            "threshold_ms": threshold_ms,
            "policy_source": policy_source,
        }

    def _check_freshness(
        self,
        decision: AlphaDecision,
        *,
        source: str,
        missing_reason: str,
        stale_reason: str,
        present: bool,
        lag_ms: int | None,
        policy_staleness_ms: int | float | None,
        config_threshold: int,
        freshness_policy: FreshnessPolicy | None = None,
    ) -> GateRejection | None:
        threshold_ms, policy_source = self._policy_threshold(
            freshness_policy,
            policy_staleness_ms,
            config_threshold,
        )
        if not present:
            return GateRejection(
                missing_reason,
                self._freshness_details(
                    source=source,
                    lag_ms=None,
                    threshold_ms=threshold_ms,
                    policy_source=policy_source,
                ),
            )
        assert lag_ms is not None
        if lag_ms > threshold_ms:
            return GateRejection(
                stale_reason,
                self._freshness_details(
                    source=source,
                    lag_ms=lag_ms,
                    threshold_ms=threshold_ms,
                    policy_source=policy_source,
                ),
            )
        return None

    @staticmethod
    def _identity(decision: AlphaDecision, view: MarketView) -> GateRejection | None:
        if decision.market_id != view.market_id:
            return GateRejection("MARKET_ID_MISMATCH")
        if decision.condition_id != view.condition_id:
            return GateRejection("CONDITION_ID_MISMATCH")
        if decision.token_id != view.book_for(decision.side).token_id:
            return GateRejection("TOKEN_SIDE_MISMATCH")
        return None

    def _market_active(
        self, decision: AlphaDecision, view: MarketView
    ) -> GateRejection | None:
        _ = decision
        return None if _market_is_active(view) else GateRejection("MARKET_NOT_ACTIVE")

    def _time_window(
        self, decision: AlphaDecision, view: MarketView
    ) -> GateRejection | None:
        _ = view
        if decision.reduce_only:
            return None
        if (
            decision.explicit_intent == OrderIntent.PASSIVE_GTD
            and decision.expiry_seconds is not None
        ):
            return None
        if decision.seconds_to_close is None or decision.seconds_to_close <= 0:
            return GateRejection("OUTSIDE_ENTRY_WINDOW")
        return None

    def _book_freshness(
        self, decision: AlphaDecision, view: MarketView
    ) -> GateRejection | None:
        book = view.book_for(decision.side)
        present = _book_present(book)
        policy = getattr(self, "_freshness_policy", None)
        return self._check_freshness(
            decision,
            source=_BOOK_FRESHNESS.source,
            missing_reason=_BOOK_FRESHNESS.missing_reason,
            stale_reason=_BOOK_FRESHNESS.stale_reason,
            present=present,
            lag_ms=_book_lag_ms(book) if present else None,
            policy_staleness_ms=(
                None if policy is None else policy.max_orderbook_staleness_ms
            ),
            config_threshold=self.poly_config.max_book_staleness_ms,
            freshness_policy=policy,
        )

    def _spot_freshness(
        self, decision: AlphaDecision, view: MarketView
    ) -> GateRejection | None:
        if decision.reduce_only:
            return None
        spot = view.spot
        present = spot is not None
        policy = getattr(self, "_freshness_policy", None)
        return self._check_freshness(
            decision,
            source=_SPOT_FRESHNESS.source,
            missing_reason=_SPOT_FRESHNESS.missing_reason,
            stale_reason=_SPOT_FRESHNESS.stale_reason,
            present=present,
            lag_ms=_spot_lag_ms(spot, view.created_at) if spot is not None else None,
            policy_staleness_ms=(
                None if policy is None else policy.max_spot_staleness_ms
            ),
            config_threshold=self.binance_config.max_price_staleness_ms,
            freshness_policy=policy,
        )

    def _spread(
        self, decision: AlphaDecision, view: MarketView
    ) -> GateRejection | None:
        if decision.reduce_only or decision.explicit_intent == OrderIntent.PASSIVE_GTD:
            return None
        book = view.book_for(decision.side)
        max_spread = decision.metrics.get("max_spread", 0.12)
        if (
            _book_present(book)
            and book.spread is not None
            and book.spread <= max_spread
        ):
            return None
        return GateRejection("SPREAD_TOO_WIDE")

    def _max_entry(
        self, decision: AlphaDecision, view: MarketView
    ) -> GateRejection | None:
        if decision.explicit_intent == OrderIntent.PASSIVE_GTD or decision.reduce_only:
            return None
        ask = view.ask_for(decision.side)
        if ask is None or ask > decision.max_entry_price:
            return GateRejection("ASK_ABOVE_MAX_ENTRY")
        return None

    def _gtd_expiry(
        self, decision: AlphaDecision, view: MarketView
    ) -> GateRejection | None:
        _ = view
        if decision.explicit_intent != OrderIntent.PASSIVE_GTD:
            return None
        if decision.expiry_seconds is None or decision.expiry_seconds <= 0:
            return GateRejection("MISSING_GTD_EXPIRY")
        if decision.expiry_seconds > 86400:
            return GateRejection("GTD_EXPIRY_EXCEEDS_24H")
        return None

    def _confidence(
        self, decision: AlphaDecision, view: MarketView
    ) -> GateRejection | None:
        _ = view
        if decision.reduce_only:
            return None
        return (
            None
            if decision.confidence >= self.signal_config.min_confidence_to_publish
            else GateRejection("CONFIDENCE_TOO_LOW")
        )
