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


def default_policies() -> list[TableRetentionPolicy]:
    return [
        TableRetentionPolicy("signals", "created_at", 14, True),
        TableRetentionPolicy("rejected_signals", "rejected_at", 14, True),
        TableRetentionPolicy("report_fills", "source_event_at", 30, True),
        TableRetentionPolicy("report_orders", "source_event_at", 30, True),
        TableRetentionPolicy("report_positions", "source_event_at", 30, True),
        TableRetentionPolicy("report_results", "closed_at", 30, True),
        TableRetentionPolicy("daily_reports", "created_at", 365, True),
        TableRetentionPolicy(
            "strategy_status",
            "created_at",
            7,
            False,
            keep_latest_only=True,
            latest_group_columns=("strategy", "asset", "timeframe"),
        ),
        TableRetentionPolicy("system_events", "created_at", 14, True),
        TableRetentionPolicy("health_snapshot", "created_at", 7, False),
        TableRetentionPolicy("nautilus_decision", "created_at", 14, False),
        TableRetentionPolicy("nautilus_fill", "created_at", 14, False),
        TableRetentionPolicy("report_publish_outbox", "created_at", 90, False),
    ]
