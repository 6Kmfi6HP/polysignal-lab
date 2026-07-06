from __future__ import annotations

from pathlib import Path

from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy


async def _signal(snapshot, settings):
    return PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0]


def _signal_scheduler(tmp_path: Path, settings) -> PolySignalScheduler:
    settings.telegram.enabled = False
    settings.telegram.send_signals = False
    settings.telegram.send_paper_results = False
    settings.telegram.send_daily_report = False
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler._initialize_trading_components()
    return scheduler


async def test_process_signal_stores_signal_without_local_paper_execution(
    tmp_path: Path, snapshot, settings
) -> None:
    sig = await _signal(snapshot, settings)
    scheduler = _signal_scheduler(tmp_path, settings)

    result = await scheduler.process_signal(sig)

    counts = scheduler.sqlite.counts()
    assert result == {
        "signal_id": sig.signal_id,
        "stored": True,
        "published": False,
        "publish_status": None,
    }
    assert counts["signals"] == 1
    assert counts["paper_orders"] == 0
    assert counts["paper_fills"] == 0
    assert counts["paper_positions"] == 0
    assert not hasattr(scheduler, "wallet")
    assert not hasattr(scheduler, "paper")


async def test_process_signal_writes_prd_named_telegram_jsonl_stream(
    tmp_path: Path, snapshot, settings
) -> None:
    sig = await _signal(snapshot, settings)
    settings.telegram.enabled = True
    settings.telegram.dry_run = True
    settings.telegram.send_signals = True
    settings.telegram.send_paper_results = False
    settings.telegram.send_daily_report = False
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler._initialize_trading_components()

    result = await scheduler.process_signal(sig)

    publish_rows = scheduler.logs.read_all("telegram_publishes")
    assert result["published"] is True
    assert [(row["message_type"], row["status"]) for row in publish_rows] == [
        ("signal", "DRY_RUN")
    ]
    assert not (scheduler.logs.base_dir / "telegram_publish.jsonl").exists()
