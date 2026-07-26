from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from polysignal_lab.alpha.types import AlphaDecision, MarketView, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side


@dataclass(frozen=True)
class _EvalContext:
    """Pre-validated context for LateConsensus evaluate()."""

    up_ask: float
    down_ask: float
    seconds: int
    market_id: str
    market_interval_sec: float
    now: datetime


class LateConsensusAlphaCore:
    """Meridian Late Entry V3 — exact 8-step entry flow (pure core)."""

    name = "late_consensus"

    def __init__(self, config) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Evaluate — moved verbatim from the legacy strategy
    # ------------------------------------------------------------------

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        ctx = self._validate_prepare(view)
        if ctx is None:
            return []

        decision = self._check_entry(view, ctx)
        return [decision] if decision is not None else []

    def _validate_prepare(self, view: MarketView) -> _EvalContext | None:
        """Validate inputs and prepare evaluation context.

        Returns None if any precondition fails.
        """
        cfg = self.config
        if not cfg.enabled:
            return None
        if view.asset.upper() not in [a.upper() for a in cfg.assets]:
            return None
        if view.timeframe not in cfg.timeframes:
            return None

        up_ask = view.ask_for(Side.UP)
        down_ask = view.ask_for(Side.DOWN)
        if up_ask is None or down_ask is None:
            return None

        market_id = view.market_id
        seconds = view.seconds_to_close
        if seconds is None or seconds <= 0:
            return None

        # Step 1: Time window check (market-interval-aware scaling).
        market_interval_sec = self._derive_market_interval(view)
        if market_interval_sec >= 900:
            effective_entry_window = cfg.entry_window_sec
        else:
            effective_entry_window = min(120, market_interval_sec - 10)
        if seconds > effective_entry_window:
            return None

        # Step 2: Entry frequency check.
        now = view.created_at
        last_entry = view.trading.latest_accepted_entry(self.name, market_id)
        if last_entry is not None and last_entry.ts_event is not None:
            elapsed = (now - last_entry.ts_event).total_seconds()
            if elapsed < cfg.entry_frequency_sec:
                return None

        return _EvalContext(
            up_ask=up_ask,
            down_ask=down_ask,
            seconds=seconds,
            market_id=market_id,
            market_interval_sec=market_interval_sec,
            now=now,
        )

    def _check_entry(self, view: MarketView, ctx: _EvalContext) -> AlphaDecision | None:
        """Evaluate entry conditions and return a decision if all are met."""
        cfg = self.config

        # Step 3: Spread = ask_sum <= max_ask_sum, > 0.
        ask_sum = ctx.up_ask + ctx.down_ask
        if ask_sum <= 0 or ask_sum > cfg.max_ask_sum:
            return None

        # Step 4: Confidence = |up_ask - down_ask| >= min_confidence_abs.
        confidence_value = abs(ctx.up_ask - ctx.down_ask)
        if confidence_value < cfg.min_confidence_abs:
            return None

        # Step 5: Identify favorite side.
        if ctx.up_ask > ctx.down_ask:
            favorite_side = Side.UP
            favorite_price = ctx.up_ask
        elif ctx.down_ask > ctx.up_ask:
            favorite_side = Side.DOWN
            favorite_price = ctx.down_ask
        else:
            return None  # tie — no clear favorite

        # Side-change guard: block rapid direction flips within the guard window.
        if self._side_change_blocked(view, favorite_side, ctx.market_id, ctx.now):
            return None

        # Step 6: Price ceiling — favorite_price <= max_entry_price.
        if favorite_price > cfg.max_entry_price:
            return None

        # Step 7: Dynamic position sizing (market-interval-aware).
        scale = ctx.market_interval_sec / 900.0
        high_threshold = int(180 * scale)
        mid_threshold = int(120 * scale)
        contracts = self._dynamic_position_size(
            ctx.seconds, high_threshold, mid_threshold
        )

        sequence = len(view.trading.accepted_entry_orders(self.name, ctx.market_id))
        effective_confidence = min(0.95, confidence_value + 0.35)

        return self._build_decision(
            view,
            ctx,
            favorite_side,
            favorite_price,
            ask_sum,
            confidence_value,
            contracts,
            sequence,
            effective_confidence,
        )

    def _build_decision(
        self,
        view: MarketView,
        ctx: _EvalContext,
        favorite_side: Side,
        favorite_price: float,
        ask_sum: float,
        confidence_value: float,
        contracts: float,
        sequence: int,
        effective_confidence: float,
    ) -> AlphaDecision:
        """Construct the final AlphaDecision."""
        cfg = self.config
        book = view.book_for(favorite_side)
        return AlphaDecision(
            strategy=self.name,
            asset=view.asset,
            timeframe=view.timeframe,
            market_id=ctx.market_id,
            market_slug=view.market_slug,
            condition_id=view.condition_id,
            token_id=book.token_id,
            side=favorite_side,
            confidence=effective_confidence,
            entry_reference_price=favorite_price,
            max_entry_price=cfg.max_entry_price,
            seconds_to_close=ctx.seconds,
            data_freshness_ms=view.freshness.max_ms,
            reason_codes=(
                "LATE_V3_WINDOW_OK",
                "LATE_V3_FREQ_OK",
                "LATE_V3_ASK_SUM_OK",
                "LATE_V3_CONFIDENCE_OK",
                "LATE_V3_PRICE_OK",
                "LATE_CONSENSUS_SIDE_CHANGE_OK",
            ),
            metrics={
                "confidence_raw": confidence_value,
                "confidence_abs": confidence_value,
                "ask_sum": round(ask_sum, 4),
                "up_ask": ctx.up_ask,
                "down_ask": ctx.down_ask,
                "favorite_side": favorite_side.value,
                "favorite_price": favorite_price,
                "seconds_to_close": ctx.seconds,
                "contracts": contracts,
                "max_investment_per_market": cfg.max_investment_per_market,
                "flip_stop_enabled": cfg.flip_stop_enabled,
                "flip_stop_price": cfg.flip_stop_price,
                "stop_loss_enabled": True,
                "stop_loss_config": cfg.stop_loss_per_coin,
                "entry_sequence": sequence,
                "created_at_for_test": view.created_at,
            },
            order_intent=OrderIntentSpec(
                intent=OrderIntent.TAKER_IOC,
                quantity=contracts,
            ),
        )

    # ------------------------------------------------------------------
    # Helpers (moved verbatim)
    # ------------------------------------------------------------------

    def _dynamic_position_size(
        self,
        seconds_remaining: int,
        high_threshold: int = 180,
        mid_threshold: int = 120,
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
        previous = view.trading.latest_accepted_entry(self.name, market_id)
        if previous is not None and previous.ts_event is not None:
            if (
                previous.side != side
                and (now - previous.ts_event).total_seconds()
                <= self.config.flip_guard_window_sec
            ):
                return True
        return False
