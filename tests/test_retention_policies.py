from polysignal_lab.config import RetentionConfig, Settings
from polysignal_lab.storage.retention_policies import default_policies


def test_retention_config_defaults_are_available_on_settings() -> None:
    retention = Settings().retention

    assert retention == RetentionConfig()
    assert retention.sqlite_soft_limit_bytes == 900_000_000
    assert retention.jsonl_max_file_bytes == 100_000_000
    assert retention.crash_log_max_days == 30


def test_default_policies_match_sqlite_schema_and_retention_windows() -> None:
    policies = {policy.table: policy for policy in default_policies()}

    assert set(policies) == {
        "signals",
        "rejected_signals",
        "report_fills",
        "report_orders",
        "report_positions",
        "report_results",
        "daily_reports",
        "strategy_status",
        "system_events",
        "health_snapshot",
        "nautilus_decision",
        "nautilus_fill",
        "report_publish_outbox",
    }
    assert (policies["signals"].time_column, policies["signals"].hot_days) == (
        "created_at",
        14,
    )
    assert policies["rejected_signals"].time_column == "rejected_at"
    assert policies["report_results"].time_column == "closed_at"
    assert policies["daily_reports"].hot_days == 365
    assert policies["report_publish_outbox"].hot_days == 90
    assert policies["strategy_status"].keep_latest_only is True
    assert policies["strategy_status"].latest_group_columns == (
        "strategy",
        "asset",
        "timeframe",
    )
    assert policies["health_snapshot"].archive is False
