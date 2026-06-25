"""Pure alpha core for the one-cent buy passive-limit strategy.

Decision logic moved verbatim from ``strategies/one_cent_buy.py``. The
``_submitted_levels`` guard is keyed by ``(market_id, price)`` and is ONLY
advanced by ``on_order_accepted``: candidate creation does not consume it, so
repeated ``evaluate`` calls keep emitting until an order is accepted for that
level.
"""

from __future__ import annotations

from polysignal_lab.alpha.types import AlphaDecision, AlphaOrderEvent, MarketView, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side


class OneCentBuyAlphaCore:
    """Extreme low-price passive limit ladder."""

    name = "one_cent_buy"

    def __init__(self, config) -> None:
        self.config = config
        # {(market_id, price)} — advanced only on order acceptance.
        self._submitted_levels: set[tuple[str, float]] = set()

    def reset(self) -> None:
        self._submitted_levels.clear()

    def on_order_accepted(self, event: AlphaOrderEvent) -> None:
        level_price = event.metrics.get("level_price")
        if level_price is not None:
            self._submitted_levels.add((event.market_id, float(level_price)))

    def _elapsed_seconds(self, view: MarketView) -> float | None:
        seconds_to_close = view.seconds_to_close
        if seconds_to_close is None:
            return None
        if view.start_ts is not None and view.end_ts is not None:
            duration = (view.end_ts - view.start_ts).total_seconds()
            return duration - seconds_to_close
        return None

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        cfg = self.config
        seconds_to_close = view.seconds_to_close
        if seconds_to_close is None:
            return []
        if seconds_to_close <= cfg.cancel_before_close_seconds:
            return []
        elapsed = self._elapsed_seconds(view)
        if elapsed is None:
            return []
        if elapsed < cfg.min_seconds_after_open or elapsed > cfg.max_seconds_after_open:
            return []

        market_id = view.market_id
        decisions: list[AlphaDecision] = []

        for side in (Side.UP, Side.DOWN):
            book = view.book_for(side)
            if book.best_ask is None:
                continue

            for price in cfg.entry_prices:
                level_key = (market_id, float(price))
                if level_key in self._submitted_levels:
                    continue
                # Passive: only place when our price is below the current ask.
                if book.best_ask <= price:
                    continue

                # ponytail: index lookup is O(n) but entry_prices is tiny (≤3).
                idx = list(cfg.entry_prices).index(price)
                confidence = 0.45 - 0.05 * idx

                metrics = {
                    "limit_price": price,
                    "entry_level_index": idx,
                    "shares_per_level": cfg.shares_per_level,
                    "take_profit_ladder": str(cfg.take_profit_ladder),
                    "elapsed_sec": elapsed,
                    "seconds_to_close": seconds_to_close,
                    "best_ask": book.best_ask,
                    "best_bid": book.best_bid,
                    "created_at_for_test": view.created_at,
                }

                decisions.append(
                    AlphaDecision(
                        strategy=self.name,
                        asset=view.asset,
                        timeframe=view.timeframe,
                        market_id=market_id,
                        market_slug=view.market_slug,
                        condition_id=view.condition_id,
                        token_id=book.token_id,
                        side=side,
                        confidence=confidence,
                        entry_reference_price=book.best_ask,
                        max_entry_price=price,
                        seconds_to_close=seconds_to_close,
                        data_freshness_ms=view.freshness.max_ms,
                        reason_codes=(
                            "ONE_CENT_BUY",
                            "PASSIVE_LIMIT",
                            f"LEVEL_{price:.2f}",
                        ),
                        metrics=metrics,
                        order_intent=OrderIntentSpec(
                            intent=OrderIntent.PASSIVE_GTD,
                            expiry_seconds=int(seconds_to_close - cfg.cancel_before_close_seconds),
                        ),
                    )
                )

        return decisions

    def evaluate_view_from_snapshot_for_test(
        self, snapshot: MarketSnapshot
    ) -> list[AlphaDecision]:
        from polysignal_lab.alpha.ptb_diff_core import market_view_from_snapshot
        view = market_view_from_snapshot(snapshot)
        return self.evaluate(view) if view is not None else []