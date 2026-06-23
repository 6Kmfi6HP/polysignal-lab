from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from polysignal_lab.utils import utc_now
from factories import BookFactoryConfig, sample_book


async def _signal(snapshot, settings):
    return PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0]


def _paper_scheduler(tmp_path: Path, settings) -> PolySignalScheduler:
    settings.telegram.enabled = False
    settings.telegram.send_signals = False
    settings.telegram.send_paper_results = False
    settings.telegram.send_daily_report = False
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler._initialize_trading_components()
    return scheduler


def _publishing_scheduler(tmp_path: Path, settings) -> PolySignalScheduler:
    settings.telegram.enabled = True
    settings.telegram.dry_run = True
    settings.telegram.send_signals = True
    settings.telegram.send_paper_results = False
    settings.telegram.send_daily_report = False
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler._initialize_trading_components()
    return scheduler


async def test_missing_orderbook_persists_rejected_paper_order_without_fill(
    tmp_path: Path, snapshot, settings
) -> None:
    sig = await _signal(snapshot, settings)
    scheduler = _paper_scheduler(tmp_path, settings)

    result = await scheduler.process_signal(sig)

    counts = scheduler.sqlite.counts()
    order_rows = scheduler.sqlite.query_json("paper_orders")
    assert result["paper_order"] is not None
    assert result["paper_order"].status == "REJECTED"
    assert result["paper_order"].reject_reason == "MISSING_ORDERBOOK"
    assert counts["signals"] == 1
    assert counts["paper_orders"] == 1
    assert counts["paper_fills"] == 0
    assert counts["paper_positions"] == 0
    assert order_rows[0]["reject_reason"] == "MISSING_ORDERBOOK"
    assert order_rows[0]["metrics"]["fill_decision_reason"] == "MISSING_ORDERBOOK"
    assert scheduler.logs.read_all("paper_orders")[0]["reject_reason"] == "MISSING_ORDERBOOK"


async def test_process_signal_writes_prd_named_telegram_jsonl_stream(
    tmp_path: Path, snapshot, settings
) -> None:
    # Given: signal publishing is enabled in dry-run mode.
    sig = await _signal(snapshot, settings)
    scheduler = _publishing_scheduler(tmp_path, settings)

    # When: the real scheduler process_signal path publishes the signal.
    result = await scheduler.process_signal(sig)

    # Then: runtime JSONL writes use the PRD lifecycle stream name.
    publish_rows = scheduler.logs.read_all("telegram_publishes")
    assert result["published"] is True
    assert [(row["message_type"], row["status"]) for row in publish_rows] == [
        ("signal", "DRY_RUN")
    ]
    assert not (scheduler.logs.base_dir / "telegram_publish.jsonl").exists()


async def test_stale_paper_fill_count_is_zero(tmp_path: Path, snapshot, settings) -> None:
    sig = await _signal(snapshot, settings)
    scheduler = _paper_scheduler(tmp_path, settings)
    scheduler.ctx.books.update(
        sample_book(sig.token_id, BookFactoryConfig(ask=0.82, bid=0.79, size=500)).model_copy(
            update={
                "received_at": utc_now()
                - timedelta(milliseconds=settings.data.polymarket.max_book_staleness_ms + 1000)
            }
        )
    )

    result = await scheduler.process_signal(sig)
    report = await scheduler.generate_daily_report()

    counts = scheduler.sqlite.counts()
    order_rows = scheduler.sqlite.query_json("paper_orders")
    assert result["paper_order"] is not None
    assert result["paper_order"].status == "REJECTED"
    assert result["paper_order"].reject_reason == "STALE_ORDERBOOK"
    assert report is not None
    assert report.paper_orders == 1
    assert report.paper_fills == 0
    assert report.rejected_paper_orders == 1
    assert report.stale_paper_fills == 0
    assert scheduler.wallet.open_position_count == 0
    assert counts["paper_orders"] == 1
    assert counts["paper_fills"] == 0
    assert counts["paper_positions"] == 0
    assert order_rows[0]["metrics"]["fill_decision_reason"] == "STALE_ORDERBOOK"
