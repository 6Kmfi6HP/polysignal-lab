from __future__ import annotations

import logging
from dataclasses import dataclass

from polysignal_lab.config import PolymarketDataConfig, SignalConfig, BinanceDataConfig
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.signal_layer.deduper import SignalDeduper
from polysignal_lab.signal_layer.rate_limit import ChannelRateLimiter


@dataclass
class GateDecision:
    accepted: bool
    signal: SignalCandidate | None = None
    rejected: RejectedSignal | None = None


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

    def evaluate(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateDecision:
        checks = [
            self._market_active,
            self._time_window,
            self._book_freshness,
            self._spot_freshness,
            self._spread,
            self._max_entry,
            self._gtd_expiry,
            self._confidence,
            self._dedupe,
            self._rate_limit,
        ]
        log = logging.getLogger("polysignal_lab.gate")
        for check in checks:
            reason = check(candidate, snapshot)
            if reason:
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
                        details=self._rejection_details(candidate, reason),
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
        self, candidate: SignalCandidate, reason: str
    ) -> dict[str, str | float | int | None]:
        return {
            "reason_code": reason,
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

    def _market_active(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        return None if snapshot.market.is_active else "MARKET_NOT_ACTIVE"

    def _time_window(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        if candidate.order_intent == OrderIntent.PASSIVE_GTD and candidate.expiry_seconds is not None:
            return None
        if candidate.seconds_to_close is None or candidate.seconds_to_close <= 0:
            return "OUTSIDE_ENTRY_WINDOW"
        return None

    def _book_freshness(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        book = snapshot.book_for(candidate.side)
        if not book or not book.is_fresh(self.poly_config.max_book_staleness_ms, snapshot.created_at):
            return "STALE_ORDERBOOK"
        return None

    def _spot_freshness(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        if not snapshot.spot or not snapshot.spot.is_fresh(self.binance_config.max_price_staleness_ms, snapshot.created_at):
            return "STALE_SPOT_PRICE"
        return None

    def _spread(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        if candidate.order_intent == OrderIntent.PASSIVE_GTD:
            return None
        book = snapshot.book_for(candidate.side)
        max_spread = candidate.metrics.get("max_spread", 0.12)
        if book and book.spread is not None and book.spread <= max_spread:
            return None
        return "SPREAD_TOO_WIDE"

    def _max_entry(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        if candidate.order_intent == OrderIntent.PASSIVE_GTD:
            return None
        ask = snapshot.ask_for(candidate.side)
        if ask is None or ask > candidate.max_entry_price:
            return "ASK_ABOVE_MAX_ENTRY"
        return None

    def _gtd_expiry(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        if candidate.order_intent != OrderIntent.PASSIVE_GTD:
            return None
        if candidate.expiry_seconds is None or candidate.expiry_seconds <= 0:
            return "MISSING_GTD_EXPIRY"
        if candidate.expiry_seconds > 86400:
            return "GTD_EXPIRY_EXCEEDS_24H"
        return None

    def _confidence(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        return None if candidate.confidence >= self.signal_config.min_confidence_to_publish else "CONFIDENCE_TOO_LOW"

    def _dedupe(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        if self.signal_config.dedupe_enabled and self.deduper.is_duplicate(candidate):
            return "DUPLICATE_SIGNAL"
        return None

    def _rate_limit(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        if not self.rate_limiter.allow(candidate.market_id):
            return "CHANNEL_RATE_LIMIT"
        return None
