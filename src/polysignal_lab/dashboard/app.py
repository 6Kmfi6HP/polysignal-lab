from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, TypeAlias

from fastapi import FastAPI

from polysignal_lab.dashboard.ports import (
    ReportingReadPort,
    RuntimeHealthPort,
    RuntimeHealthRead,
)
from polysignal_lab.domain.market import Market
from polysignal_lab.storage.event_projection import (
    normalize_report_order,
    normalize_report_position,
    report_token_id,
)

JsonValue: TypeAlias = Any

CALIBRATION_MIN_SAMPLE_SIZE = 30


def _bounded_limit(limit: int) -> int:
    return max(1, min(limit, 500))


def _bounded_offset(offset: int) -> int:
    return max(0, offset)


def _fmt_money(value: JsonValue) -> str:
    try:
        amount = float(str(value))
    except (TypeError, ValueError):
        return "0.00 USDC"
    return f"{amount:,.2f} USDC"


def _fmt_rate(value: JsonValue) -> str:
    try:
        rate = float(str(value))
    except (TypeError, ValueError):
        return "0.0%"
    return f"{rate * 100:.1f}%"


def _as_int(value: JsonValue) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _as_float(value: JsonValue) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _overall_health_status(components: list[dict[str, JsonValue]]) -> str:
    statuses = {
        str(component.get("status") or "unknown").lower() for component in components
    }
    if "down" in statuses:
        return "down"
    if "degraded" in statuses:
        return "degraded"
    if "unknown" in statuses:
        return "unknown"
    return "ok"


def _runtime_health(runtime_health: RuntimeHealthPort | None) -> RuntimeHealthRead:
    if runtime_health is None:
        return {
            "status": "unknown",
            "reason": "heartbeat_missing",
            "freshness_age_sec": None,
            "fatal_reason": None,
            "readiness_detail_by_key": {},
        }
    return runtime_health.read()


def _health_component(
    *,
    name: str,
    status: str,
    freshness_age_sec: int | None,
    reason: str | None,
    last_error: str | None,
    metrics: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return {
        "name": name,
        "status": status,
        "freshness_age_sec": freshness_age_sec,
        "reason": reason,
        "last_success_at": None,
        "last_error_at": None,
        "last_error": last_error,
        "metrics": metrics,
    }


def _health_payload(
    reporting: ReportingReadPort,
    runtime_health: RuntimeHealthPort | None,
) -> dict[str, JsonValue]:
    storage = reporting.storage_health()
    runtime = _runtime_health(runtime_health)
    snapshot = storage["latest_health_snapshot"]
    reported_components = (
        snapshot.get("components", []) if isinstance(snapshot, dict) else []
    )
    components = [
        component
        for component in reported_components
        if isinstance(component, dict)
        and component.get("name") not in {"runtime", "sqlite", "sqlite_storage"}
    ]
    components.extend(
        [
            _health_component(
                name="sqlite_storage",
                status=storage["status"],
                freshness_age_sec=storage["freshness_age_sec"],
                reason=storage["reason"],
                last_error=storage["reason"],
                metrics={
                    "row_counts_available": storage["status"] == "ok",
                    "freshness_age_sec": storage["freshness_age_sec"],
                    "reason": storage["reason"],
                },
            ),
            _health_component(
                name="runtime",
                status=runtime["status"],
                freshness_age_sec=runtime["freshness_age_sec"],
                reason=runtime["reason"],
                last_error=runtime["fatal_reason"] or runtime["reason"],
                metrics={
                    "freshness_age_sec": runtime["freshness_age_sec"],
                    "reason": runtime["reason"],
                    "fatal_reason": runtime["fatal_reason"],
                    "readiness_detail_by_key": runtime.get(
                        "readiness_detail_by_key",
                        {},
                    ),
                },
            ),
        ]
    )
    return {
        "status": _overall_health_status(components),
        "generated_at": datetime.now(UTC).isoformat(),
        "components": components,
        "counts": storage["counts"],
        "recent_system_events": storage["recent_system_events"],
    }


def _calibration_from_reports(
    reports: list[dict[str, JsonValue]],
) -> dict[str, JsonValue]:
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


def _market_lookup(
    reporting: ReportingReadPort,
) -> tuple[dict[str, Market], dict[str, Market]]:
    by_id: dict[str, Market] = {}
    by_token: dict[str, Market] = {}
    for row in reporting.market_rows(10_000):
        try:
            market = Market.model_validate(row)
        except (TypeError, ValueError):
            continue
        _ = by_id.setdefault(market.market_id, market)
        for token in market.outcome_tokens:
            _ = by_token.setdefault(token.token_id, market)
    return by_id, by_token


def _market_for_row(
    row: dict[str, JsonValue],
    *,
    by_id: dict[str, Market],
    by_token: dict[str, Market],
) -> Market | None:
    market_id = str(row.get("market_id") or "")
    if market_id:
        market = by_id.get(market_id)
        if market is not None:
            return market
    token_id = report_token_id(row)
    if token_id:
        return by_token.get(token_id)
    return None


def _finite_nonnegative(value: JsonValue) -> bool:
    if value in (None, ""):
        return False
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return False
    return math.isfinite(parsed) and parsed >= 0.0


def _valid_timestamp(value: JsonValue) -> bool:
    if isinstance(value, datetime):
        return True
    if not isinstance(value, str):
        return False
    try:
        _ = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _valid_order_payload(payload: dict[str, JsonValue]) -> bool:
    return bool(payload.get("report_order_id")) and bool(payload.get("status"))


def _valid_position_payload(payload: dict[str, JsonValue]) -> bool:
    if not bool(payload.get("report_position_id")):
        return False
    if payload.get("side") not in {"UP", "DOWN"}:
        return False
    if payload.get("status") not in {"OPEN", "CLOSED"}:
        return False
    opened_at = payload.get("opened_at")
    if opened_at in (None, ""):
        return False
    if not _valid_timestamp(opened_at):
        return False
    for key in ("entry_price", "shares", "stake_usdc"):
        value = payload.get(key)
        if value in (None, ""):
            return False
        if not _finite_nonnegative(value):
            return False
    return True


def create_dashboard_app(
    reporting: ReportingReadPort,
    runtime_health: RuntimeHealthPort | None = None,
) -> FastAPI:
    app = FastAPI(title="PolySignal Lab Dashboard", version="1.0.0")

    def strategy_status_rows(limit: int = 100) -> list[dict[str, JsonValue]]:
        return reporting.strategy_status_rows(_bounded_limit(limit))

    @app.get("/health", response_model=None)
    async def health() -> dict[str, JsonValue]:
        return _health_payload(reporting, runtime_health)

    @app.get("/api/overview", response_model=None)
    async def overview() -> dict[str, JsonValue]:
        counts = reporting.counts()
        latest_report = reporting.daily_reports(1)
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
    async def signals(limit: int = 100) -> list[dict[str, JsonValue]]:
        return reporting.signal_rows(_bounded_limit(limit))

    @app.get("/api/rejected-signals", response_model=None)
    async def rejected_signals(limit: int = 100) -> list[dict[str, JsonValue]]:
        return reporting.rejected_signal_rows(_bounded_limit(limit))

    @app.get("/api/strategy-status", response_model=None)
    async def strategy_status(limit: int = 100) -> list[dict[str, JsonValue]]:
        return strategy_status_rows(limit)

    @app.get("/api/report-orders", response_model=None)
    async def order_count(
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, JsonValue]:
        limit = _bounded_limit(limit)
        rows = reporting.report_order_rows(
            status,
            limit,
            _bounded_offset(offset),
        )
        by_id, by_token = _market_lookup(reporting)
        payloads = [
            normalize_report_order(
                row,
                market=_market_for_row(row, by_id=by_id, by_token=by_token),
            )
            for row in rows
        ]
        return {
            "items": [
                payload for payload in payloads if _valid_order_payload(payload)
            ],
            "total": reporting.report_order_count(status),
        }

    @app.get("/api/positions", response_model=None)
    async def positions(
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, JsonValue]:
        limit = _bounded_limit(limit)
        rows = reporting.report_position_rows(
            status,
            limit,
            _bounded_offset(offset),
        )
        by_id, by_token = _market_lookup(reporting)
        payloads = [
            normalize_report_position(
                row,
                market=_market_for_row(row, by_id=by_id, by_token=by_token),
            )
            for row in rows
        ]
        return {
            "items": [
                payload for payload in payloads if _valid_position_payload(payload)
            ],
            "total": reporting.report_position_count(status),
        }

    @app.get("/api/trades", response_model=None)
    async def trades(limit: int = 100, offset: int = 0) -> dict[str, JsonValue]:
        return {
            "items": reporting.report_result_rows(
                _bounded_limit(limit),
                _bounded_offset(offset),
            ),
            "total": reporting.report_result_count(),
        }

    @app.get("/api/report-summary", response_model=None)
    async def report_summary() -> dict[str, JsonValue]:
        return reporting.report_summary()

    @app.get("/api/leaderboard", response_model=None)
    async def leaderboard(limit: int = 100) -> dict[str, JsonValue]:
        report_limit = _bounded_limit(limit)
        reports = reporting.daily_reports(report_limit)
        return {
            "leaderboard": reporting.strategy_leaderboard(report_limit),
            "calibration_breakdown": _calibration_from_reports(reports),
        }

    return app
