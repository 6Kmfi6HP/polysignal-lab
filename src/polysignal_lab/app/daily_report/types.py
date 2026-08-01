from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from polysignal_lab.domain.reporting_result import DailyReport
from polysignal_lab.storage.sqlite_store import DailyReportPublishAuthorization


class _ReportPersistence(Protocol):
    def query_json(
        self,
        table: str,
        limit: int = 100,
        where: str = "",
        params: Iterable[Any] = (),
    ) -> list[dict[str, Any]]: ...

    def claim_daily_report(
        self,
        report: DailyReport,
        *,
        enqueue_publish: bool,
    ) -> tuple[DailyReport, bool]: ...

    def pending_daily_report_publishes(
        self,
        *,
        before_date: str,
        limit: int = 100,
    ) -> list[DailyReport]: ...

    def claim_daily_report_publish(
        self,
        report_id: str,
        *,
        lease_sec: float,
    ) -> dict[str, Any] | None: ...

    def authorize_daily_report_publish(
        self,
        intent_id: str,
        attempt_count: int,
        *,
        lease_sec: float,
    ) -> DailyReportPublishAuthorization: ...

    def complete_daily_report_publish(
        self,
        intent_id: str,
        attempt_count: int,
        publish: dict[str, Any],
    ) -> dict[str, Any] | None: ...

    def append_log(self, stream: str, payload: Any) -> None: ...


class _ReportLogger(Protocol):
    def error(self, msg: str, *args: Any) -> None: ...

    def info(self, msg: str, *args: Any) -> None: ...


# NOTE: every attribute on the narrow Protocols below is a read-only
# ``@property``.  Data members (even never-reassigned ones) are invariant
# for pyright Protocol conformance, which forces wide concrete Settings to
# be narrowed before they can be treated as a scheduler.  Read-only
# properties are covariant, so the wide ``Settings``/``PersistenceService``
# already satisfy the contract structurally without a wrapper.


class _TradingSettings(Protocol):
    @property
    def starting_balance_usdc(self) -> float: ...


class _PolymarketSettings(Protocol):
    @property
    def max_book_staleness_ms(self) -> float: ...


class _DataSettings(Protocol):
    @property
    def polymarket(self) -> _PolymarketSettings: ...


class _TelegramSettings(Protocol):
    @property
    def send_daily_report(self) -> bool: ...

    @property
    def publish_timeout_sec(self) -> float: ...


class _AppSettings(Protocol):
    @property
    def timezone(self) -> str: ...


class _ReportSettings(Protocol):
    @property
    def trading(self) -> _TradingSettings: ...

    @property
    def data(self) -> _DataSettings: ...

    @property
    def telegram(self) -> _TelegramSettings: ...

    @property
    def app(self) -> _AppSettings: ...


class _DailyReportPublisher(Protocol):
    async def deliver_daily_report(
        self,
        report: Any,
        *,
        idempotency_key: str | None = None,
    ) -> Any: ...


class _ReportScheduler(Protocol):
    @property
    def persistence(self) -> _ReportPersistence: ...

    @property
    def settings(self) -> _ReportSettings: ...

    @property
    def logger(self) -> _ReportLogger: ...

    @property
    def publish_service(self) -> _DailyReportPublisher: ...


@dataclass(frozen=True, slots=True)
class DailyReportInputs:
    today: date
    today_iso: str
    today_signals_raw: list[dict[str, Any]]
    today_orders_raw: list[dict[str, Any]]
    today_fills_raw: list[dict[str, Any]]
    today_reject_orders_raw: list[dict[str, Any]]
    trade_results: list[dict[str, Any]]
    telemetry_incomplete_reasons: tuple[str, ...] = ()
