"""
Input: __future__, __future__.annotations, logging, collections.abc, collections.abc.Callable, collections.abc.Mapping, dataclasses, dataclasses.dataclass, dataclasses.field, datetime
Output: GateDecision, GateRejection, _FreshnessCheckSpec, SignalGate
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""










from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from polysignal_lab.alpha.types import MarketView, SideBookView, SpotView
from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate


_UNKNOWN_LAG_MS = 10**12


@dataclass(frozen=True, slots=True)
class GateDecision:
    accepted: bool
    signal: SignalCandidate | None = None
    rejected: RejectedSignal | None = None


GateDetails = dict[str, str | float | int | None]
GateCheck = Callable[[SignalCandidate, MarketView], "GateRejection | None"]


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
    def __init__(
        self,
        signal_config: SignalConfig,
        poly_config: PolymarketDataConfig,
        binance_config: BinanceDataConfig,
    ) -> None:
        self.signal_config = signal_config
        self.poly_config = poly_config
        self.binance_config = binance_config

    def evaluate(self, candidate: SignalCandidate, view: MarketView) -> GateDecision:
        prevalidated = self.prevalidate(candidate, view)
        if not prevalidated.accepted:
            return prevalidated
        return self.commit([candidate])[0]

    def commit(self, candidates: list[SignalCandidate]) -> list[GateDecision]:
        """Accept prevalidated candidates; RiskEngine and Cache own stateful checks."""
        return [GateDecision(True, signal=candidate) for candidate in candidates]

    def prevalidate(
        self, candidate: SignalCandidate, view: MarketView
    ) -> GateDecision:
        """Check candidate eligibility without consuming dedupe or rate-limit state."""
        return self._evaluate_checks(
            candidate,
            view,
            [
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

    def _evaluate_checks(
        self,
        candidate: SignalCandidate,
        view: MarketView,
        checks: list[GateCheck],
    ) -> GateDecision:
        log = logging.getLogger("polysignal_lab.gate")
        for check in checks:
            rejection = check(candidate, view)
            if rejection:
                reason = rejection.reason_code
                log.info(
                    "GATE_REJECT %s %s market=%s side=%s reason=%s",
                    check.__name__,
                    reason,
                    candidate.market_id[:16],
                    candidate.side.value,
                    reason,
                )
                return GateDecision(
                    False,
                    rejected=RejectedSignal(
                        candidate=candidate,
                        gate_name=check.__name__,
                        reason_code=reason,
                        details=self._rejection_details(candidate, rejection),
                    ),
                )
        log.info(
            "GATE_ACCEPT %s market=%s side=%s confidence=%.3f",
            candidate.signal_id[:12],
            candidate.market_id[:16],
            candidate.side.value,
            candidate.confidence,
        )
        return GateDecision(True, signal=candidate)

    def _rejection_details(
        self, candidate: SignalCandidate, rejection: GateRejection
    ) -> dict[str, str | float | int | None]:
        details: dict[str, str | float | int | None] = {
            "reason_code": rejection.reason_code,
            "signal_id": candidate.signal_id,
            "strategy": candidate.strategy,
            "asset": candidate.asset,
            "timeframe": candidate.timeframe,
            "market_id": candidate.market_id,
            "side": candidate.side.value,
            "confidence": candidate.confidence,
            "entry_reference_price": candidate.entry_reference_price,
            "max_entry_price": candidate.max_entry_price,
            "seconds_to_close": candidate.seconds_to_close,
            "dedupe_key": candidate.dedupe_key,
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
        policy_value = (
            None if policy is None else policy.max_orderbook_staleness_ms
        )
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
        candidate: SignalCandidate,
        *,
        source: str,
        missing_reason: str,
        stale_reason: str,
        present: bool,
        lag_ms: int | None,
        policy_staleness_ms: int | float | None,
        config_threshold: int,
    ) -> GateRejection | None:
        threshold_ms, policy_source = self._policy_threshold(
            candidate.freshness_policy,
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

    def _market_active(self, candidate: SignalCandidate, view: MarketView) -> GateRejection | None:
        return None if _market_is_active(view) else GateRejection("MARKET_NOT_ACTIVE")

    def _time_window(self, candidate: SignalCandidate, view: MarketView) -> GateRejection | None:
        if candidate.reduce_only:
            return None
        if candidate.order_intent == OrderIntent.PASSIVE_GTD and candidate.expiry_seconds is not None:
            return None
        if candidate.seconds_to_close is None or candidate.seconds_to_close <= 0:
            return GateRejection("OUTSIDE_ENTRY_WINDOW")
        return None

    def _book_freshness(self, candidate: SignalCandidate, view: MarketView) -> GateRejection | None:
        book = view.book_for(candidate.side)
        present = _book_present(book)
        return self._check_configured_freshness(
            candidate,
            _BOOK_FRESHNESS,
            present=present,
            lag_ms=_book_lag_ms(book) if present else None,
            policy_staleness_ms=candidate.freshness_policy.max_orderbook_staleness_ms if candidate.freshness_policy else None,  # noqa: E501
            config_threshold=self.poly_config.max_book_staleness_ms,
        )

    def _spot_freshness(self, candidate: SignalCandidate, view: MarketView) -> GateRejection | None:
        if candidate.reduce_only:
            return None
        spot = view.spot
        present = spot is not None
        return self._check_configured_freshness(
            candidate,
            _SPOT_FRESHNESS,
            present=present,
            lag_ms=_spot_lag_ms(spot, view.created_at) if spot is not None else None,
            policy_staleness_ms=candidate.freshness_policy.max_spot_staleness_ms if candidate.freshness_policy else None,  # noqa: E501
            config_threshold=self.binance_config.max_price_staleness_ms,
        )

    def _check_configured_freshness(
        self,
        candidate: SignalCandidate,
        spec: _FreshnessCheckSpec,
        *,
        present: bool,
        lag_ms: int | None,
        policy_staleness_ms: int | None,
        config_threshold: int,
    ) -> GateRejection | None:
        return self._check_freshness(
            candidate,
            source=spec.source,
            missing_reason=spec.missing_reason,
            stale_reason=spec.stale_reason,
            present=present,
            lag_ms=lag_ms,
            policy_staleness_ms=policy_staleness_ms,
            config_threshold=config_threshold,
        )

    def _spread(self, candidate: SignalCandidate, view: MarketView) -> GateRejection | None:
        if candidate.reduce_only or candidate.order_intent == OrderIntent.PASSIVE_GTD:
            return None
        book = view.book_for(candidate.side)
        max_spread = candidate.metrics.get("max_spread", 0.12)
        if _book_present(book) and book.spread is not None and book.spread <= max_spread:
            return None
        return GateRejection("SPREAD_TOO_WIDE")

    def _max_entry(self, candidate: SignalCandidate, view: MarketView) -> GateRejection | None:
        if candidate.order_intent == OrderIntent.PASSIVE_GTD or candidate.reduce_only:
            return None
        ask = view.ask_for(candidate.side)
        if ask is None or ask > candidate.max_entry_price:
            return GateRejection("ASK_ABOVE_MAX_ENTRY")
        return None

    def _gtd_expiry(self, candidate: SignalCandidate, view: MarketView) -> GateRejection | None:
        if candidate.order_intent != OrderIntent.PASSIVE_GTD:
            return None
        if candidate.expiry_seconds is None or candidate.expiry_seconds <= 0:
            return GateRejection("MISSING_GTD_EXPIRY")
        if candidate.expiry_seconds > 86400:
            return GateRejection("GTD_EXPIRY_EXCEEDS_24H")
        return None

    def _confidence(self, candidate: SignalCandidate, view: MarketView) -> GateRejection | None:
        if candidate.reduce_only:
            return None
        return (
            None
            if candidate.confidence >= self.signal_config.min_confidence_to_publish
            else GateRejection("CONFIDENCE_TOO_LOW")
        )

