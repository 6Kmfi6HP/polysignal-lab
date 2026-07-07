"""
Input: __future__, __future__.annotations, typing, typing.TypeAlias, fastapi, fastapi.FastAPI, polysignal_lab.storage.sqlite_store, polysignal_lab.storage.sqlite_store.SQLiteStore
Output: create_dashboard_app
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from typing import TypeAlias

from fastapi import FastAPI

from polysignal_lab.storage.sqlite_store import SQLiteStore

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

CALIBRATION_MIN_SAMPLE_SIZE = 30


def _bounded_limit(limit: int) -> int:
    return max(1, min(limit, 500))




def _fmt_money(value: JsonValue) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "0.00 USDC"
    return f"{amount:,.2f} USDC"


def _fmt_rate(value: JsonValue) -> str:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return "0.0%"
    return f"{rate * 100:.1f}%"


def _as_int(value: JsonValue) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: JsonValue) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _health_payload(store: SQLiteStore) -> dict[str, JsonValue]:
    counts = store.counts()
    recent_system_events = store.query_json(
        "system_events",
        where="ORDER BY created_at DESC, rowid DESC",
        limit=10,
    )
    snapshot = store.restore_latest_system_event("health_snapshot")
    if isinstance(snapshot, dict):
        return {
            "status": str(snapshot.get("status", "degraded")).lower(),
            "generated_at": snapshot.get("generated_at") or snapshot.get("created_at"),
            "components": snapshot.get("components", []),
            "counts": counts,
            "recent_system_events": recent_system_events,
        }
    return {
        "status": "ok",
        "generated_at": None,
        "components": [
            {
                "name": "sqlite_storage",
                "status": "ok",
                "last_success_at": None,
                "last_error_at": None,
                "last_error": None,
                "metrics": {"row_counts_available": True},
            }
        ],
        "counts": counts,
        "recent_system_events": recent_system_events,
    }


def _calibration_from_reports(reports: list[dict[str, JsonValue]]) -> dict[str, JsonValue]:
    merged: dict[str, JsonValue] = {}
    average_weighted_sum: dict[str, dict[str, float]] = {}
    average_sample_size: dict[str, dict[str, int]] = {}
    count_keys = ("sample_size", "wins", "losses")
    for report in reports:
        rows = report.get("calibration_breakdown", {})
        if not isinstance(rows, dict):
            continue
        for bucket, raw_row in rows.items():
            if not isinstance(raw_row, dict):
                merged[bucket] = raw_row
                continue
            row = raw_row
            entry = merged.get(bucket)
            if not isinstance(entry, dict):
                entry = {
                    key: value
                    for key, value in row.items()
                    if key not in count_keys and not key.startswith("average_")
                }
                merged[bucket] = entry
            sample_size = _as_int(row.get("sample_size"))
            for key in count_keys:
                entry[key] = _as_int(entry.get(key)) + _as_int(row.get(key))
            for key, value in row.items():
                if key.startswith("average_"):
                    weighted_sum = average_weighted_sum.setdefault(bucket, {})
                    weighted_count = average_sample_size.setdefault(bucket, {})
                    weighted_sum[key] = weighted_sum.get(key, 0.0) + (
                        _as_float(value) * sample_size
                    )
                    weighted_count[key] = weighted_count.get(key, 0) + sample_size
    for bucket, entry in merged.items():
        if isinstance(entry, dict):
            sample_size = _as_int(entry.get("sample_size"))
            entry["calibration_status"] = (
                "calibrated"
                if sample_size >= CALIBRATION_MIN_SAMPLE_SIZE
                else "insufficient_data"
            )
            for key, weighted_sum in average_weighted_sum.get(bucket, {}).items():
                divisor = average_sample_size.get(bucket, {}).get(key, 0)
                entry[key] = weighted_sum / divisor if divisor else 0.0
    return merged


def create_dashboard_app(store: SQLiteStore) -> FastAPI:
    app = FastAPI(title="PolySignal Lab Dashboard", version="1.0.0")

    def strategy_status_rows(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json(
            "strategy_status",
            where="ORDER BY created_at ASC",
            limit=_bounded_limit(limit),
        )


    @app.get("/health", response_model=None)
    def health() -> dict[str, JsonValue]:
        return _health_payload(store)

    @app.get("/api/overview", response_model=None)
    def overview() -> dict[str, JsonValue]:
        counts = store.counts()
        latest_report = store.restore_daily_reports(limit=1)
        report = latest_report[0] if latest_report else None
        return {
            "counts": counts,
            "latest_report": report,
            "calibration_breakdown": (
                report.get("calibration_breakdown", {}) if report else {}
            ),
            "strategy_status": strategy_status_rows(),
        }

    @app.get("/api/signals", response_model=None)
    def signals(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json(
            "signals",
            where="ORDER BY created_at DESC",
            limit=_bounded_limit(limit),
        )

    @app.get("/api/rejected-signals", response_model=None)
    def rejected_signals(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json(
            "rejected_signals",
            where="ORDER BY rejected_at DESC",
            limit=_bounded_limit(limit),
        )

    @app.get("/api/strategy-status", response_model=None)
    def strategy_status(limit: int = 100) -> list[dict[str, JsonValue]]:
        return strategy_status_rows(limit)

    @app.get("/api/paper-orders", response_model=None)
    def paper_orders(status: str | None = None, limit: int = 100) -> list[dict[str, JsonValue]]:
        if status:
            return store.query_json(
                "system_events",
                where="WHERE event_type=? AND json_extract(payload_json, '$.status')=? ORDER BY created_at DESC",
                params=("nautilus_order", status.upper()),
                limit=_bounded_limit(limit),
            )
        return store.query_json(
            "system_events",
            where="WHERE event_type=? ORDER BY created_at DESC",
            params=("nautilus_order",),
            limit=_bounded_limit(limit),
        )

    @app.get("/api/positions", response_model=None)
    def positions(status: str | None = None, limit: int = 100) -> list[dict[str, JsonValue]]:
        if status:
            return store.query_json(
                "system_events",
                where="WHERE event_type=? AND json_extract(payload_json, '$.status')=? ORDER BY created_at DESC",
                params=("nautilus_position", status.upper()),
                limit=_bounded_limit(limit),
            )
        return store.query_json(
            "system_events",
            where="WHERE event_type=? ORDER BY created_at DESC",
            params=("nautilus_position",),
            limit=_bounded_limit(limit),
        )

    @app.get("/api/trades", response_model=None)
    def trades(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json("paper_trade_results", limit=_bounded_limit(limit))

    @app.get("/api/leaderboard", response_model=None)
    def leaderboard(limit: int = 100) -> dict[str, JsonValue]:
        report_limit = _bounded_limit(limit)
        reports = store.restore_daily_reports(limit=report_limit)
        return {
            "leaderboard": store.restore_strategy_leaderboard(limit=report_limit),
            "calibration_breakdown": _calibration_from_reports(reports),
        }


    return app
