from __future__ import annotations

from dataclasses import dataclass

from polysignal_lab.config import PolymarketDataConfig, SignalConfig, BinanceDataConfig
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
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
    ):
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
            self._confidence,
            self._dedupe,
            self._rate_limit,
        ]
        import logging as _logging
        _log = _logging.getLogger("polysignal_lab.gate")
        for check in checks:
            reason = check(candidate, snapshot)
            if reason:
                _log.info("GATE_REJECT %s %s market=%s side=%s reason=%s",
                          check.__name__, reason,
                          candidate.market_id[:16], candidate.side.value if hasattr(candidate, 'side') else '?',
                          reason)
                return GateDecision(False, rejected=RejectedSignal(candidate=candidate, gate_name=check.__name__, reason_code=reason))
        _log.info("GATE_ACCEPT %s market=%s side=%s confidence=%.3f",
                  candidate.signal_id[:12], candidate.market_id[:16],
                  candidate.side.value if hasattr(candidate, 'side') else '?',
                  candidate.confidence)
        return GateDecision(True, signal=candidate)

    def _market_active(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        return None if snapshot.market.is_active else "MARKET_NOT_ACTIVE"

    def _time_window(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
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
        book = snapshot.book_for(candidate.side)
        max_spread = candidate.metrics.get("max_spread", 0.12)
        if book and book.spread is not None and book.spread <= max_spread:
            return None
        return "SPREAD_TOO_WIDE"

    def _max_entry(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        ask = snapshot.ask_for(candidate.side)
        if ask is None or ask > candidate.max_entry_price:
            return "ASK_ABOVE_MAX_ENTRY"
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
