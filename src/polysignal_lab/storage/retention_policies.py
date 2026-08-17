from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableRetentionPolicy:
    """Per-table retention rule for SQLite."""

    table: str
    time_column: str
    hot_days: int
    archive: bool
    keep_latest_only: bool = False
    latest_group_columns: tuple[str, ...] = ()
    latest_order_column: str = "created_at"
    preserve_statuses: tuple[str, ...] = ()


def default_policies() -> list[TableRetentionPolicy]:
    """激进保留策略：热数据仅保留 7 天（2026-08-17 生产库 26.6GB/850 万行清理后定档）。

    大表统一 7 天以控制 SQLite 体积；daily_reports / report_publish_outbox 属业务
    交付记录，行数极小，保留更长。
    """
    return [
        TableRetentionPolicy("signals", "created_at", 7, True),
        TableRetentionPolicy("rejected_signals", "rejected_at", 7, True),
        TableRetentionPolicy("report_fills", "source_event_at", 7, True),
        TableRetentionPolicy(
            "report_orders",
            "source_event_at",
            7,
            True,
            preserve_statuses=(
                "PARTIAL",
                "PARTIALLY_FILLED",
                "ACCEPTED",
                "RESTING",
                "SUBMITTED",
            ),
        ),
        TableRetentionPolicy(
            "report_positions",
            "source_event_at",
            7,
            True,
            preserve_statuses=("OPEN",),
        ),
        TableRetentionPolicy("report_results", "closed_at", 7, True),
        TableRetentionPolicy("daily_reports", "created_at", 365, True),
        TableRetentionPolicy("telegram_publishes", "sent_at", 7, True),
        TableRetentionPolicy(
            "strategy_status",
            "created_at",
            7,
            False,
            keep_latest_only=True,
            latest_group_columns=("strategy", "asset", "timeframe"),
        ),
        TableRetentionPolicy("system_events", "created_at", 7, True),
        TableRetentionPolicy("health_snapshot", "created_at", 7, False),
        TableRetentionPolicy("nautilus_decision", "created_at", 7, False),
        TableRetentionPolicy("nautilus_fill", "created_at", 7, False),
        TableRetentionPolicy("report_publish_outbox", "created_at", 90, False),
    ]
