"""
Input: __future__, __future__.annotations, logging, collections.abc, collections.abc.Callable, dataclasses, dataclasses.dataclass, dataclasses.field, polysignal_lab.config, polysignal_lab.config.BinanceDataConfig
Output: GateDecision, GateRejection, SignalGate
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from dataclasses import dataclass, field
from threading import Lock

from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.signal_layer.deduper import SignalDeduper
from polysignal_lab.signal_layer.rate_limit import ChannelRateLimiter


@dataclass
class GateDecision:
    accepted: bool
    signal: SignalCandidate | None = None
    rejected: RejectedSignal | None = None


GateDetails = dict[str, str | float | int | None]
GateCheck = Callable[[SignalCandidate, MarketSnapshot], "GateRejection | None"]


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


class SignalGate:
    def __init__(
        self,
        signal_config: SignalConfig,
        poly_config: PolymarketDataConfig,
        binance_config: BinanceDataConfig,
        deduper: SignalDeduper | None = None,
        rate_limiter: ChannelRateLimiter | None = None,
    ) -> None:
        self.signal_config = signal_config
        self.poly_config = poly_config
        self.binance_config = binance_config
        self.deduper = deduper or SignalDeduper(signal_config.dedupe_ttl_sec)
        self.rate_limiter = rate_limiter or ChannelRateLimiter(signal_config.max_signals_per_hour, signal_config.max_signals_per_market)
        self._commit_lock = Lock()

    def evaluate(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateDecision:
        prevalidated = self.prevalidate(candidate, snapshot)
        if not prevalidated.accepted:
            return prevalidated
        return self.commit([candidate])[0]

    def commit(self, candidates: list[SignalCandidate]) -> list[GateDecision]:
        """Atomically reserve stateful gate capacity for an eligible candidate unit."""
        with self._commit_lock:
            stateful_candidates = [candidate for candidate in candidates if not candidate.reduce_only]
            duplicate = next(
                (
                    candidate
                    for candidate in stateful_candidates
                    if self.signal_config.dedupe_enabled
                    and self.deduper.contains(candidate)
                ),
                None,
            )
            if duplicate is not None:
                return self._commit_rejections(candidates, "DUPLICATE_SIGNAL", duplicate)
            if len({candidate.dedupe_key for candidate in stateful_candidates}) != len(stateful_candidates):
                return self._commit_rejections(candidates, "DUPLICATE_SIGNAL", stateful_candidates[0])
            entry_candidates = stateful_candidates
            if entry_candidates and not self.rate_limiter.can_allow(
                [candidate.market_id for candidate in entry_candidates]
            ):
                return self._commit_rejections(candidates, "CHANNEL_RATE_LIMIT", entry_candidates[0])
            for candidate in stateful_candidates:
                if self.signal_config.dedupe_enabled and self.deduper.is_duplicate(candidate):
                    return self._commit_rejections(candidates, "DUPLICATE_SIGNAL", candidate)
                if not self.rate_limiter.allow(candidate.market_id):
                    return self._commit_rejections(candidates, "CHANNEL_RATE_LIMIT", candidate)
        return [GateDecision(True, signal=candidate) for candidate in candidates]

    def _commit_rejections(
        self,
        candidates: list[SignalCandidate],
        reason_code: str,
        source: SignalCandidate,
    ) -> list[GateDecision]:
        return [
            GateDecision(True, signal=candidate)
            if candidate.reduce_only
            else GateDecision(
                False,
                rejected=RejectedSignal(
                    candidate=candidate,
                    gate_name="commit",
                    reason_code=reason_code,
                    details=self._rejection_details(
                        candidate,
                        GateRejection(reason_code, {"source_signal_id": source.signal_id}),
                    ),
                ),
            )
            for candidate in candidates
        ]

    def prevalidate(
        self, candidate: SignalCandidate, snapshot: MarketSnapshot
    ) -> GateDecision:
        """Check candidate eligibility without consuming dedupe or rate-limit state."""
        return self._evaluate_checks(
            candidate,
            snapshot,
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
        snapshot: MarketSnapshot,
        checks: list[GateCheck],
    ) -> GateDecision:
        log = logging.getLogger("polysignal_lab.gate")
        for check in checks:
            rejection = check(candidate, snapshot)
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
        snapshot: MarketSnapshot,
        *,
        source: str,
        missing_reason: str,
        stale_reason: str,
        data_source: Any | None,
        policy_staleness_ms: int | float | None,
        config_threshold: int,
    ) -> GateRejection | None:
        threshold_ms, policy_source = self._policy_threshold(
            candidate.freshness_policy,
            policy_staleness_ms,
            config_threshold,
        )
        if data_source is None:
            return GateRejection(
                missing_reason,
                self._freshness_details(
                    source=source,
                    lag_ms=None,
                    threshold_ms=threshold_ms,
                    policy_source=policy_source,
                ),
            )
        lag_ms = data_source.freshness_ms(snapshot.created_at)
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

    def _market_active(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        return None if snapshot.market.is_active else GateRejection("MARKET_NOT_ACTIVE")

    def _time_window(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if candidate.reduce_only:
            return None
        if candidate.order_intent == OrderIntent.PASSIVE_GTD and candidate.expiry_seconds is not None:
            return None
        if candidate.seconds_to_close is None or candidate.seconds_to_close <= 0:
            return GateRejection("OUTSIDE_ENTRY_WINDOW")
        return None

    def _book_freshness(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        return self._check_configured_freshness(
            candidate,
            snapshot,
            _BOOK_FRESHNESS,
            data_source=snapshot.book_for(candidate.side),
            policy_staleness_ms=candidate.freshness_policy.max_orderbook_staleness_ms if candidate.freshness_policy else None,  # noqa: E501
            config_threshold=self.poly_config.max_book_staleness_ms,
        )

    def _spot_freshness(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if candidate.reduce_only:
            return None
        return self._check_configured_freshness(
            candidate,
            snapshot,
            _SPOT_FRESHNESS,
            data_source=snapshot.spot,
            policy_staleness_ms=candidate.freshness_policy.max_spot_staleness_ms if candidate.freshness_policy else None,  # noqa: E501
            config_threshold=self.binance_config.max_price_staleness_ms,
        )

    def _check_configured_freshness(
        self,
        candidate: SignalCandidate,
        snapshot: MarketSnapshot,
        spec: _FreshnessCheckSpec,
        *,
        data_source: Any,
        policy_staleness_ms: int | None,
        config_threshold: int,
    ) -> GateRejection | None:
        return self._check_freshness(
            candidate,
            snapshot,
            source=spec.source,
            missing_reason=spec.missing_reason,
            stale_reason=spec.stale_reason,
            data_source=data_source,
            policy_staleness_ms=policy_staleness_ms,
            config_threshold=config_threshold,
        )

    def _spread(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if candidate.reduce_only or candidate.order_intent == OrderIntent.PASSIVE_GTD:
            return None
        book = snapshot.book_for(candidate.side)
        max_spread = candidate.metrics.get("max_spread", 0.12)
        if book and book.spread is not None and book.spread <= max_spread:
            return None
        return GateRejection("SPREAD_TOO_WIDE")

    def _max_entry(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if candidate.order_intent == OrderIntent.PASSIVE_GTD or candidate.reduce_only:
            return None
        ask = snapshot.ask_for(candidate.side)
        if ask is None or ask > candidate.max_entry_price:
            return GateRejection("ASK_ABOVE_MAX_ENTRY")
        return None

    def _gtd_expiry(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if candidate.order_intent != OrderIntent.PASSIVE_GTD:
            return None
        if candidate.expiry_seconds is None or candidate.expiry_seconds <= 0:
            return GateRejection("MISSING_GTD_EXPIRY")
        if candidate.expiry_seconds > 86400:
            return GateRejection("GTD_EXPIRY_EXCEEDS_24H")
        return None

    def _confidence(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if candidate.reduce_only:
            return None
        return (
            None
            if candidate.confidence >= self.signal_config.min_confidence_to_publish
            else GateRejection("CONFIDENCE_TOO_LOW")
        )

    def _dedupe(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if candidate.reduce_only:
            return None
        if self.signal_config.dedupe_enabled and self.deduper.is_duplicate(candidate):
            return GateRejection("DUPLICATE_SIGNAL")
        return None

    def _rate_limit(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateRejection | None:
        if candidate.reduce_only:
            return None
        if not self.rate_limiter.allow(candidate.market_id):
            return GateRejection("CHANNEL_RATE_LIMIT")
        return None
