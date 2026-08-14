from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace

import pytest

from factories import MarketFactoryConfig, sample_market
from polysignal_lab.app.daily_report.projection import report_result_from_projection
from polysignal_lab.app.daily_report.storage import delete_report_result_rows
from polysignal_lab.domain.missing_values import (
    MissingIdentifierError,
    bind_missing_value_counter,
)
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.nautilus_runtime.projections import project_fill_event
from polysignal_lab.reporting.exit_result import report_result_from_early_exit
from polysignal_lab.storage.projection_migration import _migrate_orders


@pytest.fixture(autouse=True)
def _reset_missing_value_counter_after_test() -> Iterator[None]:
    bind_missing_value_counter(None)
    yield
    bind_missing_value_counter(None)


def _collapsed_count(registry: HealthRegistry, field: str) -> int:
    components = {
        component.name: component for component in registry.snapshot().components
    }
    return int(components["missing_values"].metrics.get(f"collapsed_{field}", 0))


def test_delete_report_result_rows_skips_and_counts_missing_identifier() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)
    deleted: list[tuple[str, str | None]] = []
    scheduler = SimpleNamespace(
        persistence=SimpleNamespace(
            delete_report_result_rows=lambda report_result_id, publish_id: deleted.append(
                (report_result_id, publish_id)
            )
        )
    )

    delete_report_result_rows(scheduler, {"report_result_id": ""}, None)
    assert deleted == []
    assert _collapsed_count(registry, "report_result_id") == 1

    delete_report_result_rows(scheduler, {"report_result_id": "rr-1"}, None)
    assert deleted == [("rr-1", None)]
    assert _collapsed_count(registry, "report_result_id") == 1


def test_report_result_projection_skips_and_counts_missing_token_id() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)
    market = sample_market(
        MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=-1)
    )

    result = report_result_from_projection(
        {
            "position_id": "pos-1",
            "signal_id": "sig-1",
            "strategy": "ptb_diff",
            "asset": "BTC",
            "timeframe": "5m",
            "quantity": 25.0,
            "avg_entry_price": 0.40,
            "stake_usdc": 10.0,
            "ts": date(2026, 6, 21).isoformat(),
        },
        market=market,
        outcome_value=1.0,
        details={},
    )
    assert result is None
    assert _collapsed_count(registry, "token_id") == 1


def test_early_exit_skips_and_counts_missing_position_id() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    assert (
        report_result_from_early_exit(
            {"exit_reason": "TAKE_PROFIT"},
            fill_price=0.91,
            fill_shares=10.0,
            strategy_name="ptb_diff",
        )
        is None
    )
    assert _collapsed_count(registry, "position_id") == 1


def test_early_exit_skips_and_counts_missing_market_id() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    assert (
        report_result_from_early_exit(
            {
                "exit_reason": "TAKE_PROFIT",
                "position_id": "position-1",
                "entry_price": 0.40,
                "position_quantity": 10.0,
                "stake_usdc": 4.0,
                "side": "UP",
                "asset": "BTC",
                "timeframe": "5m",
                "market_slug": "btc-updown-5m",
            },
            fill_price=0.91,
            fill_shares=10.0,
            strategy_name="ptb_diff",
        )
        is None
    )
    assert _collapsed_count(registry, "market_id") == 1


def test_project_fill_event_missing_signal_id_raises_on_main_path() -> None:
    with pytest.raises(MissingIdentifierError):
        project_fill_event(SimpleNamespace(last_qty=1.0, last_px=0.5))


def test_project_fill_event_signal_id_from_tags_wins_over_metrics() -> None:
    row = project_fill_event(
        SimpleNamespace(
            last_qty=1.0,
            last_px=0.5,
            tags={"signal_id": "sig-from-tags"},
        )
    )
    assert row["signal_id"] == "sig-from-tags"


def test_projection_migration_skips_dirty_order_row() -> None:
    import json
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE paper_order_states("
        "paper_order_id TEXT PRIMARY KEY,status TEXT NOT NULL,"
        "created_event_at TEXT NOT NULL,source_event_at TEXT NOT NULL,"
        "source_event_id TEXT NOT NULL,payload_json TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO paper_order_states VALUES(NULL,'FILLED','t','t','e','{}')"
    )
    conn.execute(
        "INSERT INTO paper_order_states VALUES('pg-1','FILLED','t','t','e','{}')"
    )
    conn.execute(
        "CREATE TABLE report_orders("
        "report_order_id TEXT PRIMARY KEY,status TEXT NOT NULL,"
        "created_event_at TEXT NOT NULL,source_event_at TEXT NOT NULL,"
        "source_event_id TEXT NOT NULL,payload_json TEXT NOT NULL)"
    )

    _migrate_orders(conn, json_dumps=json.dumps)

    rows = conn.execute("SELECT report_order_id FROM report_orders").fetchall()
    assert [row["report_order_id"] for row in rows] == ["pg-1"]