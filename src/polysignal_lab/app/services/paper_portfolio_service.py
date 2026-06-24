from __future__ import annotations

import logging
from typing import Any


class PaperPortfolioService:
    name = "paper_portfolio"

    def __init__(
        self,
        *,
        settings: Any,
        wallet: Any = None,
        paper: Any = None,
        exits: Any = None,
        settlement: Any = None,
        markets: Any = None,
        books: Any = None,
        persistence: Any = None,
        scheduler: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings
        self.wallet = wallet
        self.paper = paper
        self.exits = exits
        self.settlement = settlement
        self.markets = markets
        self.books = books
        self.persistence = persistence
        self.scheduler = scheduler
        self.logger = logger or logging.getLogger("polysignal_lab.scheduler.paper_portfolio")

    def configure(
        self,
        *,
        wallet: Any,
        paper: Any,
        exits: Any,
        settlement: Any,
        markets: Any,
        books: Any,
        persistence: Any,
    ) -> None:
        self.wallet = wallet
        self.paper = paper
        self.exits = exits
        self.settlement = settlement
        self.markets = markets
        self.books = books
        self.persistence = persistence

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def health(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": "ok",
            "metrics": {
                "open_positions": getattr(self.wallet, "open_position_count", 0),
                "equity": getattr(self.wallet, "equity", None),
            },
        }

    def process_signal(self, signal: Any, result: dict[str, Any]) -> None:
        if self.scheduler is None:
            raise RuntimeError("PaperPortfolioService requires scheduler compatibility adapter")
        from polysignal_lab.app.scheduler_processing import _store_simulation_result

        book = self.books.get(signal.token_id) if self.books is not None else None
        if self.settings.paper_trading.enabled:
            if book is None:
                self.logger.warning(
                    "No order book for token %s (signal %s)",
                    signal.token_id,
                    signal.signal_id,
                )
            sim = self.paper.process_signal(signal, book)
            _store_simulation_result(self.scheduler, sim, result)

    def tick_resting_orders(self) -> list[Any]:
        if self.scheduler is None:
            return []
        from polysignal_lab.app.scheduler_processing import tick_resting_orders

        return tick_resting_orders(self.scheduler)

    async def check_settlements(self) -> list[Any]:
        if self.scheduler is None:
            return []
        from polysignal_lab.app.scheduler_reporting import check_settlements

        return await check_settlements(self.scheduler)

    async def generate_daily_report(self) -> Any:
        if self.scheduler is None:
            return None
        from polysignal_lab.app.scheduler_reporting import generate_daily_report

        return await generate_daily_report(self.scheduler)
