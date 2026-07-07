"""
Input: __future__, __future__.annotations, datetime, datetime.date, polysignal_lab.app.services.persistence_service, polysignal_lab.app.services.persistence_service.PersistenceService, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.config.TelegramConfig, polysignal_lab.config.load_settings
Output: test_telegram_interactive_config_defaults_fail_closed, test_telegram_interactive_yaml_overrides_model_defaults, test_persistence_service_restores_daily_reports_and_latest_event
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from datetime import date

from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.config import Settings, TelegramConfig, load_settings
from polysignal_lab.domain.paper_result import DailyReport
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore
from polysignal_lab.utils import new_id, utc_iso


def test_telegram_interactive_config_defaults_fail_closed() -> None:
    config = TelegramConfig()

    assert config.interactive_enabled is False
    assert config.interactive_dry_run is False
    assert config.interactive_allowed_chat_ids == ()
    assert config.interactive_poll_interval_sec == 0.0
    assert config.interactive_poll_timeout_sec == 30
    assert config.interactive_drop_pending_updates_on_start is True


def test_telegram_interactive_yaml_overrides_model_defaults() -> None:
    settings = load_settings("config/signal_bot.yaml")

    assert isinstance(settings, Settings)
    assert settings.telegram.interactive_enabled is True
    assert settings.telegram.interactive_dry_run is False
    assert settings.telegram.interactive_allowed_chat_ids == (461927973,)
    assert settings.telegram.interactive_poll_interval_sec == 0.0
    assert settings.telegram.interactive_poll_timeout_sec == 30
    assert settings.telegram.interactive_drop_pending_updates_on_start is True


def test_persistence_service_restores_daily_reports_and_latest_event(tmp_path) -> None:
    sqlite = SQLiteStore(tmp_path / "db.sqlite3")
    service = PersistenceService(
        JSONLStore(tmp_path / "logs"), sqlite, StateStore(tmp_path / "state")
    )
    report = DailyReport(
        report_date=date(2026, 6, 24),
        starting_equity=1000.0,
        ending_equity=1005.0,
        paper_pnl=5.0,
        paper_roi=0.005,
        total_signals=2,
        paper_orders=2,
        paper_fills=1,
        rejected_paper_orders=1,
        open_positions=1,
        closed_positions=1,
        win_count=1,
        loss_count=0,
        void_count=0,
        win_rate=1.0,
        total_pnl_usdc=5.0,
        average_roi=0.005,
        max_drawdown=0.0,
        profit_factor=None,
    )
    event = {
        "event_id": new_id("health_snapshot"),
        "event_type": "health_snapshot",
        "severity": "INFO",
        "created_at": utc_iso(),
        "status": "ok",
        "components": [],
    }

    service.insert_daily_report(report)
    service.insert_system_event(event)

    assert service.restore_daily_reports(limit=1)[0]["report_id"] == report.report_id
    assert service.restore_latest_system_event("health_snapshot") == event
