"""
Input: __future__, __future__.annotations, collections, collections.defaultdict, typing, typing.TYPE_CHECKING, typing.Any, typing.Mapping, polysignal_lab.alpha.state, polysignal_lab.alpha.state.json_safe_state
Output: TradeHistory, VWAPMomentumAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from polysignal_lab.alpha.helpers import enabled_for_view, evaluate_from_snapshot_for_test
from polysignal_lab.alpha.state import json_safe_state
from polysignal_lab.alpha.types import (
    AlphaDecision,
    AlphaFillEvent,
    AlphaOrderEvent,
    MarketView,
    OrderIntentSpec,
    SideBookView,
    TradeView,
)
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.trade import Trade

if TYPE_CHECKING:
    # ``from __future__ import annotations`` keeps this a string — no import of
    # ``domain.snapshot`` at module scope (alpha-core purity).
    from polysignal_lab.domain.snapshot import MarketSnapshot


class TradeHistory:
    """Time-windowed trade history per (market_id, side) key.

    Mirrors PolyBullLabs' deque of Trade objects used for VWAP,
    deviation, and momentum calculations.
    """

    def __init__(self) -> None:
        # key -> list[Trade] sorted oldest-first
        self._trades: dict[str, list[Trade]] = defaultdict(list)

    def push(self, key: str, price: float, size: float, timestamp: float) -> None:
        self._trades[key].append(Trade(price=price, size=size, timestamp=timestamp))

    def remove(self, key: str, price: float, size: float, timestamp: float) -> None:
        trades = self._trades.get(key)
        if not trades:
            return
        for idx in range(len(trades) - 1, -1, -1):
            trade = trades[idx]
            if (
                trade.price == price
                and trade.size == size
                and trade.timestamp == timestamp
            ):
                del trades[idx]
                if not trades:
                    self._trades.pop(key, None)
                return

    def _prune(self, key: str, window_sec: float, now: float) -> None:
        """Trim trades older than ``window_sec`` from storage.

        Momentum needs the band around ``now - window_sec`` while VWAP needs the
        recent window itself. We keep only data that could still affect either
        calculation, plus the newest trade so ``latest_price`` remains available.
        """
        trades = self._trades.get(key)
        if not trades:
            return
        cutoff = now - window_sec
        idx = 0
        while idx < len(trades) - 1 and trades[idx].timestamp < cutoff:
            idx += 1
        if idx > 0:
            self._trades[key] = trades[idx:]

    def trades_in_window(self, key: str, window_sec: float, now: float) -> list[Trade]:
        """Return trades within the window WITHOUT modifying storage."""
        trades = self._trades.get(key)
        if not trades:
            return []
        cutoff = now - window_sec
        return [t for t in trades if t.timestamp >= cutoff]

    def vwap(self, key: str, window_sec: float, now: float) -> float | None:
        trades = self.trades_in_window(key, window_sec, now)
        if not trades:
            return None
        total_vol = sum(t.size for t in trades)
        if total_vol <= 0:
            return None
        return sum(t.price * t.size for t in trades) / total_vol

    def momentum(self, key: str, window_sec: float, now: float) -> float | None:
        """Price change vs arithmetic mean price ~window_sec seconds ago.

        Uses a time-band approach matching PolyBullLabs:
        takes all trades in [now - window_sec - 1.5, now - window_sec + 1.5]
        (a 3-second band), computes the arithmetic mean of prices in that
        band, and returns the fractional change from that mean to the
        current price.

        Returns None if no trades are found in the band.
        """
        trades = self._trades.get(key)
        if not trades:
            return None

        band_start = now - window_sec - 1.5
        band_end = now - window_sec + 1.5

        band_prices = [t.price for t in trades if band_start <= t.timestamp <= band_end]

        if not band_prices:
            return None

        mean_price_ago = sum(band_prices) / len(band_prices)
        if mean_price_ago <= 0:
            return None

        current_price = self.latest_price(key)
        if current_price is None or current_price <= 0:
            return None

        return (current_price - mean_price_ago) / mean_price_ago

    def latest_price(self, key: str) -> float | None:
        trades = self._trades.get(key)
        if not trades:
            return None
        return trades[-1].price

    def clear_key(self, key: str) -> None:
        self._trades.pop(key, None)


@dataclass(frozen=True)
class _EvalContext:
    """Pre-validated evaluation context for VWAP evaluate()."""

    seconds_to_close: int
    elapsed_sec: float | None
    cfg: Any  # VWAPMomentumConfig — kept as Any to avoid import coupling


@dataclass(frozen=True)
class _HedgeDecisionContext:
    asset: str
    timeframe: str
    market_id: str
    market_slug: str
    condition_id: str
    token_id: str
    side: Side
    confidence: float
    seconds_to_close: int | None
    data_freshness_ms: int | None
    contracts: float


class VWAPMomentumAlphaCore:
    """PolyBullLabs VWAP / Deviation / Momentum signal strategy (pure core)."""

    name = "vwap_momentum"

    def __init__(self, config) -> None:
        self.config = config
        self.trades = TradeHistory()
        self._can_enter: dict[str, bool] = defaultdict(lambda: True)
        self._pending_signal_samples: dict[str, list[tuple[str, float, float, float]]] = {}
        # Transient holding area: evaluate stashes the just-pushed samples per
        # market here; the adapter binds them to the candidate's signal_id.
        self._pending_signal_samples_hold: dict[str, list[tuple[str, float, float, float]]] = {}
        self._last_trade_signatures: dict[str, tuple[float, float, str | None, float | None]] = {}
        self._seen_trade_signatures: dict[str, set[tuple[float, float, float]]] = defaultdict(set)
        self._pending_hedges: dict[str, tuple[Side, float]] = {}

    def reset_entry_guard(self, market_id: str) -> None:
        """Re-allow entry for a market (used by tests or manual reset)."""
        self._can_enter[market_id] = True

    # ------------------------------------------------------------------
    # StatefulAlphaCore callbacks
    # ------------------------------------------------------------------

    def on_order_accepted(self, event: AlphaOrderEvent) -> None:
        self._can_enter[event.market_id] = False
        # Drop the pending-sample binding; the samples REMAIN in history.
        self._pending_signal_samples.pop(event.order_id, None)
        if event.metrics.get("hedge_leg"):
            self._pending_hedges.pop(event.market_id, None)

    def on_order_rejected(self, event: AlphaOrderEvent) -> None:
        for key, price, size, timestamp in self._pending_signal_samples.pop(event.order_id, []):
            self.trades.remove(key, price, size, timestamp)

    def on_order_expired(self, event: AlphaOrderEvent) -> None:
        # A GTD hedge filling must not stage a reverse hedge — just clear it.
        self._pending_hedges.pop(event.market_id, None)

    def on_notify_fill(self, market_id: str, side: Side, shares: float) -> None:
        """Stage a pending hedge when an entry/hedge order fills.

        Mirrors legacy ``notify_fill``: records ``(side.opposite, shares)``
        without generating a decision.
        """
        if self.config.hedge_enabled and shares > 0:
            self._pending_hedges[market_id] = (side.opposite, shares)

    def on_order_filled(self, event: AlphaFillEvent) -> list[AlphaDecision]:
        """Taker fill → consume the staged pending hedge and emit a hedge decision.

        A GTD fill is handled by ``on_order_expired`` (clears the pending hedge,
        no reverse hedge); this method is only reached for taker fills.
        """
        if not self.config.hedge_enabled:
            return []
        pending = self._pending_hedges.pop(event.market_id, None)
        if pending is None:
            return []
        hedge_side, contracts = pending
        m = event.metrics
        opposite_token_id = m.get("opposite_token_id")
        condition_id = m.get("condition_id")
        if not isinstance(opposite_token_id, str) or not isinstance(condition_id, str):
            return []
        seconds_to_close = m.get("seconds_to_close")
        return [
            self._build_hedge_decision(
                _HedgeDecisionContext(
                    asset=str(m.get("asset", "")),
                    timeframe=str(m.get("timeframe", "")),
                    market_id=event.market_id,
                    market_slug=str(m.get("market_slug", "")),
                    condition_id=condition_id,
                    token_id=opposite_token_id,
                    side=hedge_side,
                    confidence=float(m.get("signal_confidence", 0.70)),
                    seconds_to_close=int(seconds_to_close)
                    if isinstance(seconds_to_close, (int, float))
                    else None,
                    data_freshness_ms=None,
                    contracts=contracts,
                )
            )
        ]

    def bind_signal(self, market_id: str, signal_id: str) -> None:
        """Bind the just-created candidate's signal_id to its pending samples.

        Called by the adapter after ``decision_to_signal`` so that
        ``on_order_rejected`` / ``on_order_accepted`` can key pending samples
        by ``signal_id`` (matching the legacy ``_pending_signal_samples`` key).
        """
        samples = self._pending_signal_samples_hold.pop(market_id, None)
        if samples is not None:
            self._pending_signal_samples[signal_id] = samples

    # ------------------------------------------------------------------
    # Evaluate — moved verbatim from the legacy strategy
    # ------------------------------------------------------------------

    def _market_key(self, market_id: str, side: Side) -> str:
        return f"{market_id}:{side.value}"

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        # Hedge short-circuit: emit the hedge candidate from the view.
        hedge = self._pending_hedge_decision(view)
        if hedge:
            return hedge

        # Phase 1: Validate entry conditions + calculate time context.
        ctx = self._validate_and_prepare(view)
        if ctx is None:
            return []

        # Phase 2: Ingest trade data from this snapshot into history.
        now_ts = view.created_at.timestamp()
        pushed_samples = self._ingest_trades(view, now_ts)

        up_key = self._market_key(view.market_id, Side.UP)
        down_key = self._market_key(view.market_id, Side.DOWN)

        up_price = self.trades.latest_price(up_key)
        down_price = self.trades.latest_price(down_key)
        if up_price is None or down_price is None:
            return []

        fav_side = Side.UP if up_price >= down_price else Side.DOWN
        fav_price = up_price if fav_side == Side.UP else down_price
        fav_key = self._market_key(view.market_id, fav_side)

        # Phase 3: Check all entry conditions.
        decision = self._check_entry(view, ctx, fav_side, fav_price, fav_key)
        if decision is None:
            return []

        # Stash the just-pushed samples so the adapter can bind them to the
        # candidate's signal_id (for on_order_rejected revert).
        self._pending_signal_samples_hold[view.market_id] = pushed_samples
        return [decision]

    def _validate_and_prepare(self, view: MarketView) -> _EvalContext | None:
        """Validate inputs and calculate time context.

        Returns None if any validation fails.
        """
        cfg = self.config
        if not enabled_for_view(cfg, view):
            return None

        seconds_to_close = view.seconds_to_close
        if seconds_to_close is None:
            return None

        # elapsed_sec = duration_sec - time_left = now - start_ts
        dt_duration: float | None = None
        if view.start_ts and view.end_ts:
            dt_duration = (view.end_ts - view.start_ts).total_seconds()
        elif view.end_ts:
            if view.timeframe == "5m":
                dt_duration = 300.0
            elif view.timeframe == "15m":
                dt_duration = 900.0

        elapsed_sec: float | None = None
        if dt_duration is not None and dt_duration > 0:
            elapsed_sec = dt_duration - seconds_to_close

        return _EvalContext(
            seconds_to_close=seconds_to_close,
            elapsed_sec=elapsed_sec,
            cfg=cfg,
        )

    def _ingest_trades(
        self, view: MarketView, now_ts: float
    ) -> list[tuple[str, float, float, float]]:
        pushed_samples: list[tuple[str, float, float, float]] = []
        for side in (Side.UP, Side.DOWN):
            book = view.book_for(side)
            key = self._market_key(view.market_id, side)
            trade_events = self._trade_events_for(view, side)
            if trade_events:
                pushed_samples.extend(self._ingest_trade_events(key, trade_events, now_ts))
                continue
            sample = self._ingest_book_trade(key, book, now_ts)
            if sample is not None:
                pushed_samples.append(sample)

        cfg = self.config
        history_window_sec = max(cfg.vwap_window_sec, cfg.momentum_window_sec + 1.5)
        for key in (self._market_key(view.market_id, Side.UP), self._market_key(view.market_id, Side.DOWN)):
            self._prune_trade_state(key, history_window_sec, now_ts)
        return pushed_samples

    @staticmethod
    def _trade_events_for(view: MarketView, side: Side) -> Sequence[TradeView]:
        return view.up_trades if side == Side.UP else view.down_trades

    def _ingest_trade_events(
        self,
        key: str,
        trade_events: Sequence[Any],
        now_ts: float,
    ) -> list[tuple[str, float, float, float]]:
        pushed_samples: list[tuple[str, float, float, float]] = []
        for raw_trade in trade_events:
            sample = self._trade_sample(raw_trade, now_ts)
            if sample is None:
                continue
            price, size, timestamp = sample
            if not self._push_unique_trade(key, price, size, timestamp):
                continue
            pushed_samples.append((key, price, size, timestamp))
        return pushed_samples

    @staticmethod
    def _trade_sample(raw_trade: Any, now_ts: float) -> tuple[float, float, float] | None:
        if isinstance(raw_trade, Trade):
            return raw_trade.price, raw_trade.size, raw_trade.timestamp
        if isinstance(raw_trade, TradeView):
            return (
                raw_trade.price,
                raw_trade.size,
                raw_trade.ts.timestamp() if raw_trade.ts else now_ts,
            )
        if isinstance(raw_trade, dict):
            trade = Trade.model_validate(raw_trade)
            return trade.price, trade.size, trade.timestamp
        return None

    def _push_unique_trade(
        self, key: str, price: float, size: float, timestamp: float
    ) -> bool:
        signature = (price, size, timestamp)
        if signature in self._seen_trade_signatures[key]:
            return False
        self._seen_trade_signatures[key].add(signature)
        self.trades.push(key, price, size, timestamp)
        return True

    def _ingest_book_trade(
        self,
        key: str,
        book: SideBookView,
        now_ts: float,
    ) -> tuple[str, float, float, float] | None:
        price = book.last_trade_price if book.last_trade_price is not None else book.best_ask
        if price is None or price <= 0:
            return None
        size = book.last_trade_size if book.last_trade_size and book.last_trade_size > 0 else 1.0
        signature = (
            price,
            size,
            book.last_trade_timestamp,
            book.received_at.timestamp() if book.received_at else None,
        )
        if self._last_trade_signatures.get(key) == signature:
            return None
        self._last_trade_signatures[key] = signature
        self.trades.push(key, price, size, now_ts)
        return key, price, size, now_ts

    def _check_entry(
        self,
        view: MarketView,
        ctx: _EvalContext,
        fav_side: Side,
        fav_price: float,
        fav_key: str,
    ) -> AlphaDecision | None:
        """Check all entry conditions and return a decision if all are met."""
        cfg = ctx.cfg

        # Condition 1: Price in range
        if not (cfg.min_price <= fav_price <= cfg.max_price):
            return None

        # Condition 2: Enough time elapsed
        if ctx.elapsed_sec is not None and ctx.elapsed_sec < cfg.min_elapsed_sec:
            return None

        # Condition 3: Not too close to end
        if ctx.seconds_to_close <= cfg.no_entry_before_end_sec:
            return None

        # VWAP & Deviation (fractional)
        now_ts = view.created_at.timestamp()
        vwap = self.trades.vwap(fav_key, cfg.vwap_window_sec, now_ts)
        if vwap is None or vwap <= 0:
            return None

        deviation_pct = (fav_price - vwap) / vwap

        # Condition 4: Deviation in range
        if not (cfg.min_deviation_pct < deviation_pct < cfg.max_deviation_pct):
            return None

        # Momentum (fractional) — time-band approach
        momentum = self.trades.momentum(fav_key, cfg.momentum_window_sec, now_ts)
        if momentum is None:
            return None

        # Condition 5: Positive momentum above noise threshold
        if momentum <= cfg.min_momentum:
            return None

        # One-shot entry guard (per-market) — READ ONLY here.
        if not self._can_enter[view.market_id]:
            return None

        entry_reference_price = view.ask_for(fav_side)
        if entry_reference_price is None:
            return None

        confidence = self._compute_confidence(deviation_pct, momentum)
        return self._build_decision(view, ctx, fav_side, fav_price, vwap, deviation_pct,
                                    momentum, confidence, entry_reference_price)

    @staticmethod
    def _build_decision(
        view: MarketView,
        ctx: _EvalContext,
        fav_side: Side,
        fav_price: float,
        vwap: float,
        deviation_pct: float,
        momentum: float,
        confidence: float,
        entry_reference_price: float,
    ) -> AlphaDecision:
        """Construct the final AlphaDecision from evaluated conditions."""
        opposite_book = view.book_for(fav_side.opposite)
        return AlphaDecision(
            strategy="vwap_momentum",
            asset=view.asset,
            timeframe=view.timeframe,
            market_id=view.market_id,
            market_slug=view.market_slug,
            condition_id=view.condition_id,
            token_id=view.book_for(fav_side).token_id,
            side=fav_side,
            confidence=confidence,
            entry_reference_price=entry_reference_price,
            max_entry_price=min(ctx.cfg.max_price, fav_price + 0.05),
            seconds_to_close=ctx.seconds_to_close,
            data_freshness_ms=view.freshness.max_ms,
            reason_codes=(
                "VWAP_DEVIATION_OK",
                "MOMENTUM_OK",
                "FAVORITE_SELECTED",
                "ENTRY_WINDOW_OK",
            ),
            metrics={
                "vwap": vwap,
                "deviation_pct": deviation_pct,
                "deviation_percent": deviation_pct * 100.0,
                "momentum_pct": momentum,
                "momentum": momentum,
                "favorite_side": fav_side.value,
                "fav_price": fav_price,
                "elapsed_sec": ctx.elapsed_sec,
                "seconds_to_close": ctx.seconds_to_close,
                "opposite_token_id": opposite_book.token_id,
                "condition_id": view.condition_id,
                "created_at_for_test": view.created_at,
            },
        )

    def _pending_hedge_decision(self, view: MarketView) -> list[AlphaDecision]:
        pending = self._pending_hedges.get(view.market_id)
        if pending is None:
            return []
        hedge_side, contracts = pending
        ask = view.ask_for(hedge_side)
        if ask is None:
            return []
        book = view.book_for(hedge_side)
        return [
            self._build_hedge_decision(
                _HedgeDecisionContext(
                    asset=view.asset,
                    timeframe=view.timeframe,
                    market_id=view.market_id,
                    market_slug=view.market_slug,
                    condition_id=view.condition_id,
                    token_id=book.token_id,
                    side=hedge_side,
                    confidence=0.70,
                    seconds_to_close=view.seconds_to_close,
                    data_freshness_ms=view.freshness.max_ms,
                    contracts=contracts,
                )
            )
        ]

    def _build_hedge_decision(self, ctx: _HedgeDecisionContext) -> AlphaDecision:
        return AlphaDecision(
            strategy=self.name,
            asset=ctx.asset,
            timeframe=ctx.timeframe,
            market_id=ctx.market_id,
            market_slug=ctx.market_slug,
            condition_id=ctx.condition_id,
            token_id=ctx.token_id,
            side=ctx.side,
            confidence=ctx.confidence,
            entry_reference_price=self.config.hedge_price,
            max_entry_price=self.config.hedge_price,
            seconds_to_close=ctx.seconds_to_close,
            data_freshness_ms=ctx.data_freshness_ms,
            reason_codes=("VWAP_GTD_HEDGE",),
            metrics={
                "contracts": ctx.contracts,
                "hedge_price": self.config.hedge_price,
                "hedge_source": "vwap_entry_fill",
            },
            order_intent=OrderIntentSpec(
                intent=OrderIntent.PASSIVE_GTD,
                expiry_seconds=self.config.hedge_expiry_seconds,
                pair_id=f"{ctx.market_id}:vwap",
            ),
            hedge_leg=True,
        )

    @staticmethod
    def _compute_confidence(deviation_pct: float, momentum: float) -> float:
        """Map deviation + momentum to a confidence score in [0, 1].

        Matches PolyBullLabs heuristic: stronger deviation and momentum
        produce higher confidence, capped at 0.95.
        """
        base = 0.50
        dev_contrib = max(0.0, min(0.25, abs(deviation_pct) * 2.0))
        mom_contrib = max(0.0, min(0.20, momentum * 3.0))
        return min(0.95, base + dev_contrib + mom_contrib)

    # ------------------------------------------------------------------
    # Test helper + state round-trip
    # ------------------------------------------------------------------

    def evaluate_view_from_snapshot_for_test(self, snapshot) -> list[AlphaDecision]:
        return evaluate_from_snapshot_for_test(self, snapshot)


    def _prune_trade_state(self, key: str, window_sec: float, now: float) -> None:
        self.trades._prune(key, window_sec, now)
        trades = self.trades._trades.get(key)
        if not trades:
            self._seen_trade_signatures.pop(key, None)
            return
        retained = {(trade.price, trade.size, trade.timestamp) for trade in trades}
        seen = self._seen_trade_signatures.get(key)
        if seen is None:
            return
        seen.intersection_update(retained)
        if not seen:
            self._seen_trade_signatures.pop(key, None)
    def save_state(self) -> Mapping[str, object]:
        return json_safe_state(
            {
                "trades": {
                    k: [
                        {"price": t.price, "size": t.size, "timestamp": t.timestamp}
                        for t in v
                    ]
                    for k, v in self.trades._trades.items()
                },
                "can_enter": dict(self._can_enter),
                "last_trade_signatures": self._last_trade_signatures,
                "seen_trade_signatures": self._seen_trade_signatures,
                "pending_hedges": self._pending_hedges,
            }
        )

    def load_state(self, payload: Mapping[str, object]) -> None:
        trades_raw = payload.get("trades", {}) or {}
        if not isinstance(trades_raw, Mapping):
            trades_raw = {}
        new_trades = TradeHistory()
        for k, lst in trades_raw.items():
            for t in lst:
                new_trades.push(
                    str(k), float(t["price"]), float(t["size"]), float(t["timestamp"])
                )
        self.trades = new_trades

        can_enter_raw = payload.get("can_enter", {}) or {}
        if not isinstance(can_enter_raw, Mapping):
            can_enter_raw = {}
        self._can_enter = defaultdict(
            lambda: True, {str(k): bool(v) for k, v in can_enter_raw.items()}
        )

        sigs_raw = payload.get("last_trade_signatures", {}) or {}
        if not isinstance(sigs_raw, Mapping):
            sigs_raw = {}
        self._last_trade_signatures = {str(k): tuple(v) for k, v in sigs_raw.items()}

        seen_raw = payload.get("seen_trade_signatures", {}) or {}
        if not isinstance(seen_raw, Mapping):
            seen_raw = {}
        self._seen_trade_signatures = defaultdict(
            set,
            {str(k): {tuple(sig) for sig in v} for k, v in seen_raw.items()},
        )

        hedges_raw = payload.get("pending_hedges", {}) or {}
        if not isinstance(hedges_raw, Mapping):
            hedges_raw = {}
        self._pending_hedges = {
            str(k): (Side(v[0]), float(v[1])) for k, v in hedges_raw.items()
        }
        # Transient pending-sample bookkeeping is not persisted.
        self._pending_signal_samples = {}
        self._pending_signal_samples_hold = {}
