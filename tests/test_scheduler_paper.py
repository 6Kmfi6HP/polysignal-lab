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
    assert result["paper_order"].reject_reason == "PAPER_MISSING_ORDERBOOK"
    assert counts["signals"] == 1
    assert counts["paper_orders"] == 1
    assert counts["paper_fills"] == 0
    assert counts["paper_positions"] == 0
    assert order_rows[0]["reject_reason"] == "PAPER_MISSING_ORDERBOOK"
    assert order_rows[0]["metrics"]["fill_decision_reason"] == "PAPER_MISSING_ORDERBOOK"
    assert scheduler.logs.read_all("paper_orders")[0]["reject_reason"] == "PAPER_MISSING_ORDERBOOK"


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


async def test_process_signal_updates_paper_and_telegram_health(
    tmp_path: Path, snapshot, settings
) -> None:
    sig = await _signal(snapshot, settings)
    scheduler = _publishing_scheduler(tmp_path, settings)

    result = await scheduler.process_signal(sig)
    components = {component.name: component for component in scheduler.health.snapshot().components}

    assert result["published"] is True
    assert components["telegram"].status == "ok"
    assert components["telegram"].metrics["dry_run"] == 1
    assert components["paper_simulator"].metrics["rejects_PAPER_MISSING_ORDERBOOK"] == 1
    assert components["paper_simulator"].metrics["wallet_snapshot_count"] == 1


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
    assert result["paper_order"].reject_reason == "PAPER_STALE_ORDERBOOK"
    assert report is not None
    assert report.paper_orders == 1
    assert report.paper_fills == 0
    assert report.rejected_paper_orders == 1
    assert report.stale_paper_fills == 0
    assert scheduler.wallet.open_position_count == 0
    assert counts["paper_orders"] == 1
    assert counts["paper_fills"] == 0
    assert counts["paper_positions"] == 0
    assert order_rows[0]["metrics"]["fill_decision_reason"] == "PAPER_STALE_ORDERBOOK"


def test_scheduler_fill_notifier_dispatches_cancel_to_matching_strategy() -> None:
    from polysignal_lab.app.scheduler import _make_fill_notifier
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.paper_order import PaperOrder

    class Strategy:
        name = "test"

        def __init__(self) -> None:
            self.cancels = []

        def notify_cancel(self, market_id, side, reason):
            self.cancels.append((market_id, side, reason))

    strategy = Strategy()
    order = PaperOrder(
        signal_id="sig-1",
        asset="BTC",
        timeframe="5m",
        strategy="test",
        market_id="mkt-1",
        market_slug="s",
        token_id="t-up",
        side=Side.UP,
        limit_price=0.35,
        reference_price=0.35,
        stake_usdc=3.5,
        reject_reason="STALE_ORDERBOOK",
    )

    notifier = _make_fill_notifier([strategy])
    notifier(order, "cancelled", None)

    assert strategy.cancels == [("mkt-1", Side.UP, "STALE_ORDERBOOK")]

async def test_rejected_resting_order_is_persisted_logged_and_notified(
    tmp_path: Path, settings
) -> None:
    from polysignal_lab.app.scheduler_processing import tick_resting_orders
    from polysignal_lab.domain.enums import OrderIntent, Side
    from polysignal_lab.domain.signal import SignalCandidate

    scheduler = _paper_scheduler(tmp_path, settings)
    signal = SignalCandidate.build(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id="mkt-1",
        market_slug="s",
        condition_id="c",
        token_id="t-up",
        side=Side.UP,
        confidence=0.6,
        entry_reference_price=0.35,
        max_entry_price=0.35,
        seconds_to_close=300,
        data_freshness_ms=100,
        reason_codes=["T"],
        metrics={},
        order_intent=OrderIntent.PASSIVE_GTD,
        expiry_seconds=300,
    )
    scheduler.ctx.books.update(
        sample_book("t-up", BookFactoryConfig(ask=0.55, bid=0.30, size=100))
    )
    await scheduler.process_signal(signal)
    scheduler.ctx.books.update(
        sample_book("t-up", BookFactoryConfig(ask=0.55, bid=0.35, size=100)).model_copy(
            update={
                "received_at": utc_now()
                - timedelta(
                    milliseconds=settings.data.polymarket.max_book_staleness_ms + 1000
                )
            }
        )
    )
    notifications = []
    scheduler.paper.fill_notifier = (
        lambda order, event, fill: notifications.append((order, event, fill))
    )

    results = tick_resting_orders(scheduler)

    assert len(results) == 1
    assert results[0].order.status == "REJECTED"
    assert results[0].order.reject_reason == "PAPER_STALE_ORDERBOOK"
    order_rows = scheduler.sqlite.query_json("paper_orders")
    assert len(order_rows) == 1
    assert order_rows[0]["status"] == "REJECTED"
    assert order_rows[0]["reject_reason"] == "PAPER_STALE_ORDERBOOK"
    assert order_rows[0]["metrics"]["paper_original_reason"] == "STALE_ORDERBOOK"
    assert order_rows[0]["metrics"]["paper_normalized_reason"] == "PAPER_STALE_ORDERBOOK"
    assert "paper_terminal_at" in order_rows[0]["metrics"]
    paper_order_logs = scheduler.logs.read_all("paper_orders")
    assert paper_order_logs[-1]["status"] == "REJECTED"
    assert paper_order_logs[-1]["reject_reason"] == "PAPER_STALE_ORDERBOOK"
    assert paper_order_logs[-1]["metrics"]["paper_original_reason"] == "STALE_ORDERBOOK"
    assert paper_order_logs[-1]["metrics"]["paper_normalized_reason"] == "PAPER_STALE_ORDERBOOK"
    assert "paper_terminal_at" in paper_order_logs[-1]["metrics"]
    assert notifications == [(results[0].order, "cancelled", None)]


async def test_cancelled_resting_gtd_expiry_is_persisted_with_normalized_reason(
    tmp_path: Path, settings
) -> None:
    from polysignal_lab.app.scheduler_processing import tick_resting_orders
    from polysignal_lab.domain.enums import OrderIntent, Side
    from polysignal_lab.domain.signal import SignalCandidate

    scheduler = _paper_scheduler(tmp_path, settings)
    signal = SignalCandidate.build(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id="mkt-1",
        market_slug="s",
        condition_id="c",
        token_id="t-up",
        side=Side.UP,
        confidence=0.6,
        entry_reference_price=0.35,
        max_entry_price=0.35,
        seconds_to_close=300,
        data_freshness_ms=100,
        reason_codes=["T"],
        metrics={},
        order_intent=OrderIntent.PASSIVE_GTD,
        expiry_seconds=1,
    ).model_copy(update={"created_at": utc_now() - timedelta(seconds=10)})
    scheduler.ctx.books.update(
        sample_book("t-up", BookFactoryConfig(ask=0.55, bid=0.30, size=100))
    )
    await scheduler.process_signal(signal)
    wallet_snapshots_before = len(scheduler.logs.read_all("paper_wallet_snapshots"))
    notifications = []
    scheduler.paper.fill_notifier = (
        lambda order, event, fill: notifications.append((order, event, fill))
    )

    results = tick_resting_orders(scheduler)

    assert len(results) == 1
    assert results[0].status == "CANCELLED"
    assert results[0].order.status == "CANCELLED"
    assert results[0].reject_reason == "PAPER_GTD_EXPIRED"
    assert results[0].order.reject_reason == "PAPER_GTD_EXPIRED"
    order_rows = scheduler.sqlite.query_json("paper_orders")
    assert len(order_rows) == 1
    assert order_rows[0]["status"] == "CANCELLED"
    assert order_rows[0]["reject_reason"] == "PAPER_GTD_EXPIRED"
    assert order_rows[0]["metrics"]["paper_original_reason"] == "GTD_EXPIRED"
    assert order_rows[0]["metrics"]["paper_normalized_reason"] == "PAPER_GTD_EXPIRED"
    assert "paper_terminal_at" in order_rows[0]["metrics"]
    paper_order_logs = scheduler.logs.read_all("paper_orders")
    assert paper_order_logs[-1]["status"] == "CANCELLED"
    assert paper_order_logs[-1]["reject_reason"] == "PAPER_GTD_EXPIRED"
    assert paper_order_logs[-1]["metrics"]["paper_original_reason"] == "GTD_EXPIRED"
    assert paper_order_logs[-1]["metrics"]["paper_normalized_reason"] == "PAPER_GTD_EXPIRED"
    assert "paper_terminal_at" in paper_order_logs[-1]["metrics"]
    assert len(scheduler.logs.read_all("paper_wallet_snapshots")) == wallet_snapshots_before + 1
    assert notifications == [(results[0].order, "cancelled", None)]


async def test_cancelled_resting_no_cash_is_persisted_with_normalized_reason(
    tmp_path: Path, settings
) -> None:
    from polysignal_lab.app.scheduler_processing import tick_resting_orders
    from polysignal_lab.domain.enums import OrderIntent, Side
    from polysignal_lab.domain.signal import SignalCandidate

    scheduler = _paper_scheduler(tmp_path, settings)
    signal = SignalCandidate.build(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id="mkt-1",
        market_slug="s",
        condition_id="c",
        token_id="t-up",
        side=Side.UP,
        confidence=0.6,
        entry_reference_price=0.35,
        max_entry_price=0.35,
        seconds_to_close=300,
        data_freshness_ms=100,
        reason_codes=["T"],
        metrics={},
        order_intent=OrderIntent.PASSIVE_GTD,
        expiry_seconds=300,
    )
    scheduler.ctx.books.update(
        sample_book("t-up", BookFactoryConfig(ask=0.55, bid=0.30, size=100))
    )
    await scheduler.process_signal(signal)
    scheduler.wallet.cash_balance = 0.0
    scheduler.ctx.books.update(
        sample_book("t-up", BookFactoryConfig(ask=0.55, bid=0.35, size=100))
    )
    wallet_snapshots_before = len(scheduler.logs.read_all("paper_wallet_snapshots"))
    notifications = []
    scheduler.paper.fill_notifier = (
        lambda order, event, fill: notifications.append((order, event, fill))
    )

    results = tick_resting_orders(scheduler)

    assert len(results) == 1
    assert results[0].status == "CANCELLED"
    assert results[0].order.status == "CANCELLED"
    assert results[0].reject_reason == "PAPER_WALLET_INSUFFICIENT_CASH"
    assert results[0].order.reject_reason == "PAPER_WALLET_INSUFFICIENT_CASH"
    order_rows = scheduler.sqlite.query_json("paper_orders")
    assert len(order_rows) == 1
    assert order_rows[0]["status"] == "CANCELLED"
    assert order_rows[0]["reject_reason"] == "PAPER_WALLET_INSUFFICIENT_CASH"
    assert order_rows[0]["metrics"]["paper_original_reason"] == "WALLET_INSUFFICIENT_CASH"
    assert (
        order_rows[0]["metrics"]["paper_normalized_reason"]
        == "PAPER_WALLET_INSUFFICIENT_CASH"
    )
    assert "paper_terminal_at" in order_rows[0]["metrics"]
    assert (
        len(scheduler.logs.read_all("paper_wallet_snapshots"))
        == wallet_snapshots_before + 1
    )
    assert notifications == [(results[0].order, "cancelled", None)]