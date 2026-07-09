"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, datetime, datetime.date, typing, typing.Any, typing.Protocol, polysignal_lab.domain.paper_result
Output: DailyReportInputs, _ReportScheduler, _ReportPersistence, _ReportLogger
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from polysignal_lab.domain.paper_result import DailyReport


class _ReportPersistence(Protocol):
    def query_json(
        self,
        table: str,
        limit: int = 100,
        where: str = "",
        params: tuple[Any, ...] = (),
    ) -> list[dict[str, Any]]: ...

    def insert_daily_report(self, report: DailyReport) -> None: ...

    def append_log(self, table: str, payload: Any) -> None: ...


class _ReportLogger(Protocol):
    def error(self, msg: str, *args: Any) -> None: ...

    def info(self, msg: str, *args: Any) -> None: ...


class _PaperTradingSettings(Protocol):
    starting_balance_usdc: float


class _PolymarketSettings(Protocol):
    max_book_staleness_ms: float


class _DataSettings(Protocol):
    polymarket: _PolymarketSettings


class _TelegramSettings(Protocol):
    send_daily_report: bool


class _AppSettings(Protocol):
    timezone: str


class _ReportSettings(Protocol):
    paper_trading: _PaperTradingSettings
    data: _DataSettings
    telegram: _TelegramSettings
    app: _AppSettings


class _PublishResult(Protocol):
    def as_dict(self) -> dict[str, str | None]: ...


class _DailyReportPublisher(Protocol):
    async def publish_daily_report(self, report: DailyReport) -> _PublishResult: ...


class _ReportScheduler(Protocol):
    persistence: _ReportPersistence
    settings: _ReportSettings
    logger: _ReportLogger
    publish_service: _DailyReportPublisher


@dataclass(frozen=True, slots=True)
class DailyReportInputs:
    today: date
    today_iso: str
    today_signals_raw: list[dict[str, Any]]
    today_orders_raw: list[dict[str, Any]]
    today_fills_raw: list[dict[str, Any]]
    today_reject_orders_raw: list[dict[str, Any]]
    trade_results: list[dict[str, Any]]
