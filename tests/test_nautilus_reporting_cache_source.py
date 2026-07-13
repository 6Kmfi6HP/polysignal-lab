"""
Input: __future__, __future__.annotations, types, types.SimpleNamespace, polysignal_lab.app.scheduler_reporting, polysignal_lab.app.scheduler_reporting._report_equity_inputs
Output: test_report_equity_inputs_prefers_nautilus_cache_over_shadow_wallet, test_report_equity_inputs_keeps_portfolio_equity_equal_to_starting_equity, test_report_equity_inputs_keeps_zero_portfolio_equity, test_report_equity_inputs_uses_nautilus_account_balance_when_portfolio_equity_missing, test_report_equity_inputs_uses_pusd_account_balance_when_portfolio_equity_missing, test_generate_daily_report_uses_configured_pusd_equity, test_generate_daily_report_uses_canonical_order_state_and_marks_telemetry_loss, test_generate_daily_report_retries_pending_outbox_without_duplicate_report, test_generate_daily_report_revises_after_late_settlement, test_generate_daily_report_retries_prior_day_pending_publish, test_report_equity_inputs_uses_account_balance_for_non_numeric_portfolio_equity, test_report_equity_inputs_requires_nautilus_cache, test_report_equity_inputs_requires_reporting_cache_protocol, test_report_equity_inputs_ignores_shadow_wallet_without_cache
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""






from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from polysignal_lab.app.scheduler_reporting import (
    _report_equity_inputs,
    generate_daily_report,
)
from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.app.services.publish_service import PublishService
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.paper.report import PaperReportService
from polysignal_lab.publish.telegram_publisher import PublishResult
from polysignal_lab.signal_layer.formatter import MessageFormatter
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore
from factories import sample_paper_trade_result


def _settings(
    starting_balance: float = 1_000.0,
    *,
    sandbox_base_currency: str = "USDC",
) -> SimpleNamespace:
    return SimpleNamespace(
        paper_trading=SimpleNamespace(starting_balance_usdc=starting_balance),
        runtime=SimpleNamespace(
            nautilus=SimpleNamespace(sandbox_base_currency=sandbox_base_currency),
        ),
        data=SimpleNamespace(polymarket=SimpleNamespace(max_book_staleness_ms=60_000)),
        telegram=SimpleNamespace(
            send_daily_report=False,
            publish_timeout_sec=5.0,
        ),
        app=SimpleNamespace(timezone="UTC"),
    )


def test_report_equity_inputs_prefers_nautilus_cache_over_shadow_wallet() -> None:
    ts = datetime.now(UTC)
    cache = SimpleNamespace(
        account=lambda: SimpleNamespace(
            id="A-1",
            balances=[SimpleNamespace(currency="USDC", total=2_222.0)],
        ),
        positions=lambda: [
            SimpleNamespace(
                id="P-1", instrument_id="I", signed_qty=10, avg_px_open=0.5,
                realized_pnl=0.0, is_closed=False, ts_event=ts,
            ),
            SimpleNamespace(
                id="P-2", instrument_id="I", signed_qty=10, avg_px_open=0.5,
                realized_pnl=0.0, is_closed=True, ts_event=ts,
            ),
            SimpleNamespace(
                id="P-3", instrument_id="I", signed_qty=10, avg_px_open=0.5,
                realized_pnl=0.0, is_closed=False, ts_event=ts,
            ),
        ],
    )
    portfolio = SimpleNamespace(id="PF-1", equity=1_234.5)
    scheduler = SimpleNamespace(
        settings=_settings(),
        nautilus_cache=cache,
        nautilus_portfolio=portfolio,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_234.5, 2)


def test_report_equity_inputs_keeps_portfolio_equity_equal_to_starting_equity() -> None:
    cache = SimpleNamespace(
        account=lambda: SimpleNamespace(
            id="A-1",
            balances=[SimpleNamespace(currency="USDC", total=987.65)],
        ),
        positions=lambda: [],
    )
    portfolio = SimpleNamespace(id="PF-1", equity=1_000.0)
    scheduler = SimpleNamespace(
        settings=_settings(),
        nautilus_cache=cache,
        nautilus_portfolio=portfolio,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_000.0, 0)


def test_report_equity_inputs_keeps_zero_portfolio_equity() -> None:
    cache = SimpleNamespace(
        account=lambda: SimpleNamespace(
            id="A-1",
            balances=[SimpleNamespace(currency="USDC", total=987.65)],
        ),
        positions=lambda: [],
    )
    portfolio = SimpleNamespace(id="PF-1", equity=0.0)
    scheduler = SimpleNamespace(
        settings=_settings(),
        nautilus_cache=cache,
        nautilus_portfolio=portfolio,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 0.0, 0)


def test_report_equity_inputs_uses_nautilus_account_balance_when_portfolio_equity_missing() -> None:
    ts = datetime.now(UTC)
    cache = SimpleNamespace(
        account=lambda: SimpleNamespace(
            id="A-1",
            balances=[
                SimpleNamespace(currency="BTC", total=99.0),
                SimpleNamespace(currency="USDC", total=987.65),
            ],
        ),
        positions=lambda: [
            SimpleNamespace(
                id="P-1", instrument_id="I", signed_qty=10, avg_px_open=0.5,
                realized_pnl=0.0, is_closed=False, ts_event=ts,
            ),
        ],
    )
    scheduler = SimpleNamespace(
        settings=_settings(),
        nautilus_cache=cache,
        # No nautilus_portfolio — falls through to account balance
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 987.65, 1)


def test_report_equity_inputs_uses_pusd_account_balance_when_portfolio_equity_missing() -> None:
    cache = SimpleNamespace(
        account=lambda: SimpleNamespace(
            id="A-1",
            balances=lambda: {
                "PUSD": SimpleNamespace(currency="PUSD", total=111.0),
                "pUSD": SimpleNamespace(currency="pUSD", total=987.65),
            },
        ),
        positions=lambda: [],
    )
    portfolio = SimpleNamespace(id="PF-1", equity=lambda **_kwargs: {})
    scheduler = SimpleNamespace(
        settings=_settings(sandbox_base_currency="pUSD"),
        nautilus_cache=cache,
        nautilus_portfolio=portfolio,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 987.65, 0)


def test_generate_daily_report_uses_configured_pusd_equity() -> None:
    reports: list[object] = []
    persistence = SimpleNamespace(
        query_json=lambda *_args, **_kwargs: [],
        claim_daily_report=lambda report, *, enqueue_publish: (
            reports.append(report) or (report, True)
        ),
        append_log=lambda *_args: None,
    )
    cache = SimpleNamespace(
        account=lambda: SimpleNamespace(
            id="A-1",
            balances=[SimpleNamespace(currency="pUSD", total=987.65)],
        ),
        positions=lambda: [],
        orders=lambda: [],
        fills=lambda: [],
    )
    scheduler = SimpleNamespace(
        settings=_settings(sandbox_base_currency="pUSD"),
        persistence=persistence,
        nautilus_cache=cache,
        health=SimpleNamespace(mark_ok=lambda *_args, **_kwargs: None),
        logger=SimpleNamespace(
            error=lambda *_args: None,
            info=lambda *_args: None,
        ),
        publish_service=None,
    )

    report = asyncio.run(generate_daily_report(scheduler))

    assert report is not None
    assert report.ending_equity == 987.65
    assert report.equity_currency == "pUSD"
    assert reports == [report]


def test_generate_daily_report_uses_canonical_order_state_and_marks_telemetry_loss(
    tmp_path,
) -> None:
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    persistence = PersistenceService(
        JSONLStore(tmp_path / "logs"),
        store,
        StateStore(tmp_path / "state"),
    )
    now = datetime.now(UTC)
    for event_id, status, offset in (
        ("order-resting", "ACCEPTED", -1),
        ("order-filled", "FILLED", 0),
    ):
        event_at = (now + timedelta(seconds=offset)).isoformat()
        store.insert_system_event(
            {
                "event_id": event_id,
                "event_type": "nautilus_order",
                "severity": "info",
                "created_at": event_at,
                "paper_order_id": "order-current",
                "status": status,
                "ts": event_at,
            }
        )
    store.insert_system_event(
        {
            "event_id": "order-invalid",
            "event_type": "nautilus_order",
            "severity": "warning",
            "created_at": now.isoformat(),
            "paper_order_id": "order-invalid",
            "ts": now.isoformat(),
        }
    )
    health = HealthRegistry()
    health.mark_degraded(
        "observability_actor",
        "telemetry queue full",
        telemetry_queue_drops=101,
        telemetry_last_drop_at=now.isoformat(),
    )
    scheduler = SimpleNamespace(
        settings=_settings(),
        persistence=persistence,
        nautilus_cache=SimpleNamespace(
            account=lambda: SimpleNamespace(
                id="A-1",
                balances=[SimpleNamespace(currency="USDC", total=1_000.0)],
            ),
            positions=lambda: [],
            orders=lambda: [],
            fills=lambda: [
                SimpleNamespace(
                    trade_id="fill-native",
                    client_order_id="order-current",
                    instrument_id="token.UP",
                    last_qty=20.0,
                    last_px=0.5,
                    liquidity_side="TAKER",
                    tags=(),
                    metrics={},
                    ts_event=now,
                )
            ],
        ),
        health=health,
        logger=SimpleNamespace(
            error=lambda *_args: None,
            info=lambda *_args: None,
        ),
        publish_service=None,
    )

    report = asyncio.run(generate_daily_report(scheduler))

    assert report is not None
    assert report.paper_orders == 1
    assert report.paper_fills == 1
    assert report.telemetry_status == "incomplete"
    assert report.telemetry_incomplete_reasons == [
        "paper_order_projection_invalid:1",
        "telemetry_queue_drops",
    ]


def test_generate_daily_report_retries_pending_outbox_without_duplicate_report(
    tmp_path,
) -> None:
    db_path = tmp_path / "reports.sqlite3"
    store = SQLiteStore(db_path)
    logs = JSONLStore(tmp_path / "logs")
    persistence = PersistenceService(logs, store, StateStore(tmp_path / "state"))
    formatter_report_ids: list[str] = []
    publish_statuses = ["FAILED", "SENT"]
    successful_messages: list[str] = []

    class Formatter:
        def daily_report_message(self, report) -> str:
            report_id = (
                str(report["report_id"])
                if isinstance(report, dict)
                else report.report_id
            )
            formatter_report_ids.append(report_id)
            return f"daily report {report_id}"

    class Publisher:
        async def send(
            self,
            message: str,
            message_type: str,
            signal_id: str | None,
        ) -> PublishResult:
            outbox = store.restore_report_publish_outbox()
            assert store.counts()["daily_reports"] == 1
            assert outbox[0]["status"] == "DELIVERING"
            status = publish_statuses.pop(0)
            if status == "SENT":
                successful_messages.append(message)
            return PublishResult(
                publish_id=f"pub-{2 - len(publish_statuses)}",
                message_type=message_type,
                signal_id=signal_id,
                status=status,
                error="temporary" if status == "FAILED" else None,
                sent_at="2026-07-13T12:00:00Z" if status == "SENT" else None,
            )

    settings = _settings(sandbox_base_currency="pUSD")
    settings.telegram.send_daily_report = True
    cache = SimpleNamespace(
        account=lambda: SimpleNamespace(
            id="A-1",
            balances=[SimpleNamespace(currency="pUSD", total=987.65)],
        ),
        positions=lambda: [],
        orders=lambda: [],
        fills=lambda: [],
    )
    scheduler = SimpleNamespace(
        settings=settings,
        persistence=persistence,
        nautilus_cache=cache,
        health=HealthRegistry(),
        logger=SimpleNamespace(
            error=lambda *_args: None,
            info=lambda *_args: None,
        ),
        publish_service=PublishService(Formatter(), Publisher(), persistence),
    )

    first = asyncio.run(generate_daily_report(scheduler))
    pending = store.restore_report_publish_outbox()

    persistence.close()
    store = SQLiteStore(db_path)
    persistence = PersistenceService(logs, store, StateStore(tmp_path / "state"))
    scheduler.persistence = persistence
    scheduler.publish_service = PublishService(Formatter(), Publisher(), persistence)

    second = asyncio.run(generate_daily_report(scheduler))
    delivered = store.restore_report_publish_outbox()

    assert first is not None
    assert second is not None
    assert second.report_id == first.report_id
    assert store.counts()["daily_reports"] == 1
    assert store.counts()["report_publish_outbox"] == 1
    assert len(logs.read_all("daily_reports")) == 1
    assert pending[0]["status"] == "PENDING"
    assert pending[0]["attempt_count"] == 1
    assert pending[0]["last_error"] == "temporary"
    assert delivered[0]["status"] == "SENT"
    assert delivered[0]["attempt_count"] == 2
    assert formatter_report_ids == [first.report_id, first.report_id]
    assert successful_messages == [f"daily report {first.report_id}"]


def test_generate_daily_report_revises_after_late_settlement(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    logs = JSONLStore(tmp_path / "logs")
    persistence = PersistenceService(
        logs,
        store,
        StateStore(tmp_path / "state"),
    )
    settings = _settings()
    settings.telegram.send_daily_report = True
    deliveries: list[tuple[str, str]] = []

    class Publisher:
        async def send(
            self,
            message: str,
            message_type: str,
            signal_id: str | None,
        ) -> PublishResult:
            deliveries.append((message_type, message))
            status = "FAILED" if len(deliveries) == 1 else "SENT"
            return PublishResult(
                publish_id=f"pub-report-{len(deliveries)}",
                message_type=message_type,
                signal_id=signal_id,
                status=status,
                error="temporary" if status == "FAILED" else None,
                sent_at=datetime.now(UTC).isoformat() if status == "SENT" else None,
            )

    scheduler = SimpleNamespace(
        settings=settings,
        persistence=persistence,
        nautilus_cache=SimpleNamespace(
            account=lambda: SimpleNamespace(
                id="A-1",
                balances=[SimpleNamespace(currency="USDC", total=1_000.0)],
            ),
            positions=lambda: [],
            orders=lambda: [],
            fills=lambda: [],
        ),
        health=HealthRegistry(),
        logger=SimpleNamespace(
            error=lambda *_args: None,
            info=lambda *_args: None,
        ),
        publish_service=PublishService(
            MessageFormatter(),
            Publisher(),
            persistence,
        ),
    )

    initial = asyncio.run(generate_daily_report(scheduler))
    persistence.insert_paper_trade_result(
        sample_paper_trade_result(
            paper_trade_id="pt-late-settlement",
            paper_position_id="pos-late-settlement",
            closed_at=datetime.now(UTC).isoformat(),
        )
    )
    revised = asyncio.run(generate_daily_report(scheduler))
    duplicate = asyncio.run(generate_daily_report(scheduler))

    reports = store.restore_daily_reports()
    outbox = sorted(
        store.restore_report_publish_outbox(),
        key=lambda row: int(row["revision"]),
    )

    assert initial is not None
    assert revised is not None
    assert duplicate is not None
    assert initial.revision == 1
    assert revised.revision == 2
    assert duplicate.report_id == revised.report_id
    assert revised.closed_positions == 1
    assert len(reports) == 2
    assert int(reports[0]["revision"]) == 2
    assert {int(row["revision"]) for row in reports} == {1, 2}
    assert [row["idempotency_key"] for row in outbox] == [
        f"daily_report:{initial.report_date.isoformat()}:r1",
        f"daily_report:{initial.report_date.isoformat()}:r2",
    ]
    assert [row["status"] for row in outbox] == ["SUPERSEDED", "SENT"]
    assert [message_type for message_type, _ in deliveries] == [
        "daily_report",
        "daily_report_correction",
    ]
    assert "Correction" in deliveries[1][1]
    assert "Revision 2" in deliveries[1][1]
    assert len(logs.read_all("daily_reports")) == 2


def test_generate_daily_report_retries_prior_day_pending_publish(tmp_path) -> None:
    db_path = tmp_path / "reports.sqlite3"
    store = SQLiteStore(db_path)
    prior_report = PaperReportService().build_daily_report(
        report_date=datetime.now(UTC).date() - timedelta(days=1),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=0,
        paper_orders=0,
        paper_fills=0,
        rejected_paper_orders=0,
        open_positions=0,
        results=[],
    )
    store.claim_daily_report(prior_report, enqueue_publish=True)
    store.close()

    store = SQLiteStore(db_path)
    logs = JSONLStore(tmp_path / "logs")
    persistence = PersistenceService(logs, store, StateStore(tmp_path / "state"))
    settings = _settings()
    settings.telegram.send_daily_report = True
    published_report_ids: list[str] = []

    class Formatter:
        def daily_report_message(self, report) -> str:
            report_id = str(report["report_id"])
            published_report_ids.append(report_id)
            return f"daily report {report_id}"

    class Publisher:
        async def send(
            self,
            message: str,
            message_type: str,
            signal_id: str | None,
        ) -> PublishResult:
            settings.telegram.send_daily_report = False
            return PublishResult(
                publish_id="pub-prior-day",
                message_type=message_type,
                signal_id=signal_id,
                status="SENT",
                sent_at="2026-07-14T00:00:00Z",
            )

    scheduler = SimpleNamespace(
        settings=settings,
        persistence=persistence,
        nautilus_cache=SimpleNamespace(
            account=lambda: None,
            positions=lambda: [],
            orders=lambda: [],
            fills=lambda: [],
        ),
        health=HealthRegistry(),
        logger=SimpleNamespace(
            error=lambda *_args: None,
            info=lambda *_args: None,
        ),
        publish_service=PublishService(Formatter(), Publisher(), persistence),
    )

    current_report = asyncio.run(generate_daily_report(scheduler))
    outbox = store.restore_report_publish_outbox()

    assert current_report is not None
    assert current_report.report_date != prior_report.report_date
    assert store.counts()["daily_reports"] == 2
    assert store.counts()["report_publish_outbox"] == 1
    assert outbox[0]["status"] == "SENT"
    assert published_report_ids == [prior_report.report_id]


def test_report_equity_inputs_uses_account_balance_for_non_numeric_portfolio_equity() -> None:
    cache = SimpleNamespace(
        account=lambda: SimpleNamespace(
            id="A-1",
            balances=[SimpleNamespace(currency="usdc", total=987.65)],
        ),
        positions=lambda: [],
    )
    scheduler = SimpleNamespace(
        settings=_settings(),
        nautilus_cache=cache,
        nautilus_portfolio=SimpleNamespace(id="PF-1", equity="unavailable"),
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 987.65, 0)


def test_report_equity_inputs_requires_nautilus_cache() -> None:
    scheduler = SimpleNamespace(
        settings=_settings(),
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_000.0, 0)


def test_report_equity_inputs_requires_reporting_cache_protocol() -> None:
    invalid_caches = (
        SimpleNamespace(),
        SimpleNamespace(account=123, positions=lambda: []),
        SimpleNamespace(account=lambda: None, positions=[]),
    )

    for cache in invalid_caches:
        scheduler = SimpleNamespace(
            settings=_settings(),
            nautilus_cache=cache,
        )

        assert _report_equity_inputs(scheduler) == (1_000.0, 1_000.0, 0)


def test_report_equity_inputs_ignores_shadow_wallet_without_cache() -> None:
    scheduler = SimpleNamespace(
        settings=_settings(),
        wallet=SimpleNamespace(starting_balance=1_000.0, equity=1_025.0, open_position_count=3),
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_000.0, 0)
