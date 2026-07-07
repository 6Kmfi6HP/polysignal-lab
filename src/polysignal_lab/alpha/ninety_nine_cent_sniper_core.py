"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision, polysignal_lab.alpha.types.AlphaOrderEvent, polysignal_lab.alpha.types.MarketView, polysignal_lab.alpha.types.OrderIntentSpec, polysignal_lab.alpha.types.SideBookView, polysignal_lab.domain.enums, polysignal_lab.domain.enums.OrderIntent
Output: NinetyNineCentSniperAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""






from __future__ import annotations

from polysignal_lab.alpha.types import AlphaDecision, AlphaOrderEvent, MarketView, OrderIntentSpec, SideBookView
from polysignal_lab.domain.enums import OrderIntent, Side


class NinetyNineCentSniperAlphaCore:
    """Snipe near-certain settlement outcomes in the final seconds."""

    name = "ninety_nine_cent_sniper"

    def __init__(self, config) -> None:
        self.config = config
        self._sniped_markets: set[tuple[str, str]] = set()

    def reset(self) -> None:
        self._sniped_markets.clear()

    def on_order_accepted(self, event: AlphaOrderEvent) -> None:
        self._sniped_markets.add((event.market_id, event.side.value))

    @staticmethod
    def _book_mid(book: SideBookView) -> float | None:
        if book.best_bid is not None and book.best_ask is not None:
            return (book.best_bid + book.best_ask) / 2.0
        return None

    def _external_probability(self, view: MarketView, side: Side) -> float | None:
        prob = view.metrics.get("external_probability")
        if prob is not None:
            return float(prob)
        return self._book_mid(view.book_for(side))

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        cfg = self.config
        seconds_to_close = view.seconds_to_close
        if seconds_to_close is None:
            return []

        if not (
            cfg.min_seconds_before_close
            <= seconds_to_close
            <= cfg.max_seconds_before_close
        ):
            return []

        market_id = view.market_id
        decisions: list[AlphaDecision] = []

        for side in (Side.UP, Side.DOWN):
            side_key = (market_id, side.value)
            if side_key in self._sniped_markets:
                continue

            book = view.book_for(side)
            if book.best_ask is None:
                continue

            if book.best_ask > cfg.max_entry_price:
                continue

            prob = self._external_probability(view, side)
            if prob is None or prob < cfg.min_external_probability:
                continue

            if book.best_bid is not None and book.best_bid <= cfg.stop_price:
                continue

            if cfg.require_effectively_settled:
                opposite_side = side.opposite
                opp_book = view.book_for(opposite_side)
                if opp_book.best_ask is None or opp_book.best_ask > 0.05:
                    continue

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
                    confidence=0.96,
                    entry_reference_price=book.best_ask,
                    max_entry_price=min(cfg.max_entry_price, book.best_ask * 1.01),
                    seconds_to_close=seconds_to_close,
                    data_freshness_ms=view.freshness.max_ms,
                    reason_codes=(
                        "NINETY_NINE_SNIPE",
                        "EFFECTIVELY_SETTLED",
                        "HIGH_PROBABILITY",
                        "FOK_EXECUTION",
                    ),
                    metrics={
                        "best_ask": book.best_ask,
                        "best_bid": book.best_bid,
                        "midpoint": self._book_mid(book),
                        "external_probability": prob,
                        "seconds_to_close": seconds_to_close,
                        "max_notional": cfg.max_notional_per_trade,
                        "stop_price": cfg.stop_price,
                        "require_effectively_settled": cfg.require_effectively_settled,
                        "opposite_ask": opp_book.best_ask if cfg.require_effectively_settled else None,
                        "created_at_for_test": view.created_at,
                    },
                    order_intent=OrderIntentSpec(intent=OrderIntent.TAKER_FOK),
                )
            )

        return decisions

    def evaluate_view_from_snapshot_for_test(
        self, snapshot: MarketSnapshot
    ) -> list[AlphaDecision]:
        from polysignal_lab.alpha.ptb_diff_core import market_view_from_snapshot
        view = market_view_from_snapshot(snapshot)
        return self.evaluate(view) if view is not None else []