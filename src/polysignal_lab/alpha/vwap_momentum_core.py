"""
Input: __future__, __future__.annotations, collections, collections.defaultdict, typing, typing.TYPE_CHECKING, typing.Any, typing.Mapping, polysignal_lab.alpha.state, polysignal_lab.alpha.state.json_safe_state
Output: VWAPMomentumAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from polysignal_lab.alpha.helpers import enabled_for_view
from polysignal_lab.alpha.state import json_safe_state
from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketView,
    OrderIntentSpec,
    SideBookView,
    TradeView,
)
from polysignal_lab.alpha.vwap_state import encode_vwap_state, restore_vwap_state_fields
from polysignal_lab.alpha.vwap_trade_history import TradeHistory
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.trade import Trade


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
        self._last_trade_signatures: dict[str, tuple[float, float, str | None, float | None]] = {}
        self._seen_trade_signatures: dict[str, set[tuple[float, float, float]]] = defaultdict(set)

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
        self._ingest_trades(view, now_ts)

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
        if view.trading.has_market_activity(self.name, view.market_id):
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
        position = view.trading.unhedged_leg(self.name, view.market_id)
        if position is None or view.trading.has_hedge_order(self.name, view.market_id):
            return []
        hedge_side = position.side.opposite
        contracts = position.quantity
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



    def _prune_trade_state(self, key: str, window_sec: float, now: float) -> None:
        self.trades.prune(key, window_sec, now)
        trades = self.trades.trades_for_key(key)
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
            encode_vwap_state(
                {
                    "trades": {
                        key: [
                            {"price": trade.price, "size": trade.size, "timestamp": trade.timestamp}
                            for trade in trades
                        ]
                        for key, trades in self.trades.all_trades().items()
                    },
                    "last_trade_signatures": self._last_trade_signatures,
                    "seen_trade_signatures": self._seen_trade_signatures,
                }
            )
        )

    def load_state(self, payload: Mapping[str, object]) -> None:
        (
            self.trades,
            self._last_trade_signatures,
            self._seen_trade_signatures,
        ) = restore_vwap_state_fields(payload)
