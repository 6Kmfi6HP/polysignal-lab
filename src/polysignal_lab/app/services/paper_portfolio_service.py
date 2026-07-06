from __future__ import annotations

import logging
from typing import Any


class PaperPortfolioService:
    name = "paper_portfolio_removed"

    def __init__(
        self,
        *,
        settings: Any,
        scheduler: Any = None,
        logger: logging.Logger | None = None,
        **_removed_dependencies: Any,
    ) -> None:
        self.settings = settings
        self.scheduler = scheduler
        self.logger = logger or logging.getLogger("polysignal_lab.scheduler.paper_portfolio_removed")

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def health(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": "removed",
            "metrics": {
                "open_positions": 0,
                "equity_source": "nautilus_cache_portfolio",
            },
        }

    def process_signal(self, _signal: Any, _result: dict[str, Any]) -> None:
        raise RuntimeError("Local paper execution was removed; submit orders through Nautilus strategy callbacks")

    def tick_resting_orders(self) -> list[Any]:
        return []

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
