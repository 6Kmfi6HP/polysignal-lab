"""Pure alpha core for the callback-heavy ``late_consensus`` strategy.

Decision logic (the 8-step Meridian Late Entry V3 flow) is moved verbatim from
``strategies/late_consensus.py``. The strategy's mutable callback state lives
on this core:

* ``_last_favorite``  — flip-guard memory (read by ``evaluate`` side-change guard).
* ``_last_entry_at``  — entry-frequency gate memory (read by ``evaluate``).
* ``_accepted_counts``— per-market accepted-signal counter; ``evaluate`` READS
  it to derive ``metrics["entry_sequence"]`` but does NOT increment it. Only
  ``on_order_accepted`` increments it (and writes the other two fields).

The dedupe-suffix (``:{sequence}``) is a CANDIDATE concern — ``AlphaDecision``
has no ``dedupe_key`` — so the adapter applies it from
``decision.metrics["entry_sequence"]`` after ``decision_to_signal``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Mapping

from polysignal_lab.alpha.state import json_safe_state, restore_utc_datetime
from polysignal_lab.alpha.types import AlphaDecision, AlphaOrderEvent, MarketView
from polysignal_lab.domain.enums import Side

if TYPE_CHECKING:
    # ``from __future__ import annotations`` keeps this as a string — no import
    # of ``domain.snapshot`` happens at module scope (alpha-core purity).
    from polysignal_lab.domain.snapshot import MarketSnapshot


class LateConsensusAlphaCore:
    """Meridian Late Entry V3 — exact 8-step entry flow (pure core)."""

    name = "late_consensus"

    def __init__(self, config) -> None:
        self.config = config
        self._last_favorite: dict[str, tuple[Side, datetime]] = {}
        self._last_entry_at: dict[str, datetime] = {}
        self._accepted_counts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # StatefulAlphaCore callbacks
    # ------------------------------------------------------------------

    def on_order_accepted(self, event: AlphaOrderEvent) -> None:
        """Advance ALL callback state: frequency gate, accepted counter, flip guard."""
        self._last_entry_at[event.market_id] = event.ts_event
        self._accepted_counts[event.market_id] = (
            self._accepted_counts.get(event.market_id, 0) + 1
        )
        if self.config.flip_guard_enabled:
            self._last_favorite[event.market_id] = (event.side, event.ts_event)

    # ------------------------------------------------------------------
    # Evaluate — moved verbatim from the legacy strategy
    # ------------------------------------------------------------------

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        cfg = self.config
        if not cfg.enabled:
            return []
        if view.asset.upper() not in [a.upper() for a in cfg.assets]:
            return []
        if view.timeframe not in cfg.timeframes:
            return []
        up_ask = view.ask_for(Side.UP)
        down_ask = view.ask_for(Side.DOWN)
        if up_ask is None or down_ask is None:
            return []

        market_id = view.market_id
        seconds = view.seconds_to_close
        # Step 1: Time window check (market-interval-aware scaling).
        if seconds is None or seconds <= 0:
            return []
        market_interval_sec = self._derive_market_interval(view)
        if market_interval_sec >= 900:
            effective_entry_window = cfg.entry_window_sec
        else:
            effective_entry_window = min(120, market_interval_sec - 10)
        if seconds > effective_entry_window:
            return []

        # Step 2: Entry frequency check (>= entry_frequency_sec since last entry).
        now = datetime.now(UTC)
        last_entry = self._last_entry_at.get(market_id)
        if last_entry is not None:
            elapsed = (now - last_entry).total_seconds()
            if elapsed < cfg.entry_frequency_sec:
                return []

        # Step 3: Spread = ask_sum <= max_ask_sum, > 0.
        ask_sum = up_ask + down_ask
        if ask_sum <= 0 or ask_sum > cfg.max_ask_sum:
            return []

        # Step 4: Confidence = |up_ask - down_ask| >= min_confidence_abs.
        confidence_value = abs(up_ask - down_ask)
        if confidence_value < cfg.min_confidence_abs:
            return []

        # Step 5: Identify favorite side.
        if up_ask > down_ask:
            favorite_side = Side.UP
            favorite_price = up_ask
        elif down_ask > up_ask:
            favorite_side = Side.DOWN
            favorite_price = down_ask
        else:
            return []  # tie — no clear favorite

        # Side-change guard: block rapid direction flips within the guard window.
        if self._side_change_blocked(view, favorite_side, market_id, now):
            return []

        # Step 6: Price ceiling — favorite_price <= max_entry_price.
        if favorite_price > cfg.max_entry_price:
            return []

        # Step 8: Dynamic position sizing (market-interval-aware).
        scale = market_interval_sec / 900.0
        high_threshold = int(180 * scale)
        mid_threshold = int(120 * scale)
        contracts = self._dynamic_position_size(
            seconds, high_threshold, mid_threshold
        )

        reason_codes = (
            "LATE_V3_WINDOW_OK",
            "LATE_V3_FREQ_OK",
            "LATE_V3_ASK_SUM_OK",
            "LATE_V3_CONFIDENCE_OK",
            "LATE_V3_PRICE_OK",
            "LATE_CONSENSUS_SIDE_CHANGE_OK",
        )

        effective_confidence = min(0.95, confidence_value + 0.35)

        # The sequence is READ-ONLY here: only on_order_accepted increments it.
        sequence = self._accepted_counts.get(market_id, 0)

        metrics: dict[str, Any] = {
            "confidence_raw": confidence_value,
            "confidence_abs": confidence_value,
            "ask_sum": round(ask_sum, 4),
            "up_ask": up_ask,
            "down_ask": down_ask,
            "favorite_side": favorite_side.value,
            "favorite_price": favorite_price,
            "seconds_to_close": seconds,
            "contracts": contracts,
            "max_investment_per_market": cfg.max_investment_per_market,
            "flip_stop_enabled": cfg.flip_stop_enabled,
            "flip_stop_price": cfg.flip_stop_price,
            "stop_loss_enabled": True,
            "stop_loss_config": cfg.stop_loss_per_coin,
            "entry_sequence": sequence,
            "created_at_for_test": view.created_at,
        }

        book = view.book_for(favorite_side)
        return [
            AlphaDecision(
                strategy=self.name,
                asset=view.asset,
                timeframe=view.timeframe,
                market_id=market_id,
                market_slug=view.market_slug,
                condition_id=view.condition_id,
                token_id=book.token_id,
                side=favorite_side,
                confidence=effective_confidence,
                entry_reference_price=favorite_price,
                max_entry_price=cfg.max_entry_price,
                seconds_to_close=seconds,
                data_freshness_ms=view.freshness.max_ms,
                reason_codes=reason_codes,
                metrics=metrics,
                order_intent=None,
            )
        ]

    # ------------------------------------------------------------------
    # Helpers (moved verbatim)
    # ------------------------------------------------------------------

    def _dynamic_position_size(
        self, seconds_remaining: int, high_threshold: int = 180, mid_threshold: int = 120
    ) -> int:
        if seconds_remaining > high_threshold:
            return self.config.sizing_above_180
        elif seconds_remaining > mid_threshold:
            return self.config.sizing_above_120
        else:
            return self.config.sizing_below_120

    @staticmethod
    def _derive_market_interval(view: MarketView) -> int:
        if view.timeframe == "15m":
            return 900
        if view.timeframe == "5m":
            return 300
        return 900

    def _side_change_blocked(
        self, view: MarketView, side: Side, market_id: str, now: datetime
    ) -> bool:
        if not self.config.flip_guard_enabled:
            return False
        previous = self._last_favorite.get(market_id)
        if previous:
            prev_side, prev_time = previous
            if prev_side != side and (now - prev_time).total_seconds() <= self.config.flip_guard_window_sec:
                return True
        return False

    # ------------------------------------------------------------------
    # Test helper + state round-trip
    # ------------------------------------------------------------------

    def evaluate_view_from_snapshot_for_test(
        self, snapshot: "MarketSnapshot"
    ) -> list[AlphaDecision]:
        from polysignal_lab.alpha.ptb_diff_core import market_view_from_snapshot

        view = market_view_from_snapshot(snapshot)
        return self.evaluate(view) if view is not None else []

    def save_state(self) -> Mapping[str, object]:
        return json_safe_state(
            {
                "last_favorite": self._last_favorite,
                "last_entry_at": self._last_entry_at,
                "accepted_counts": self._accepted_counts,
            }
        )

    def load_state(self, payload: Mapping[str, object]) -> None:
        fav_raw = payload.get("last_favorite", {}) or {}
        self._last_favorite = {
            str(k): (Side(v[0]), restore_utc_datetime(v[1]))
            for k, v in fav_raw.items()
        }
        entry_raw = payload.get("last_entry_at", {}) or {}
        self._last_entry_at = {str(k): restore_utc_datetime(v) for k, v in entry_raw.items()}
        counts_raw = payload.get("accepted_counts", {}) or {}
        self._accepted_counts = {str(k): int(v) for k, v in counts_raw.items()}
