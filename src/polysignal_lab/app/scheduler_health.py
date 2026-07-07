"""
Input: __future__, __future__.annotations, sqlite3, typing, typing.TYPE_CHECKING, pydantic, pydantic.JsonValue, polysignal_lab.observability.health, polysignal_lab.observability.health.HealthSnapshot, polysignal_lab.utils
Output: note_storage_success, note_storage_failure, note_publish_result, sync_runtime_health, persist_health_snapshot
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from pydantic import JsonValue

from polysignal_lab.observability.health import HealthSnapshot
from polysignal_lab.utils import new_id, utc_iso, utc_now

if TYPE_CHECKING:
    from polysignal_lab.app.scheduler import PolySignalScheduler


def note_storage_success(scheduler: PolySignalScheduler, store_name: str) -> None:
    scheduler.health.mark_ok(f"{store_name}_storage", last_successful_write=utc_iso())


def note_storage_failure(
    scheduler: PolySignalScheduler, store_name: str, exc: BaseException
) -> None:
    scheduler.health.inc_metric(f"{store_name}_storage", "write_failures")
    scheduler.health.mark_down(f"{store_name}_storage", str(exc))


def note_publish_result(
    scheduler: PolySignalScheduler, publish: dict[str, str | None]
) -> None:
    status = str(publish.get("status") or "")
    if status == "SENT":
        scheduler.health.inc_metric("telegram", "sent")
        scheduler.health.mark_ok("telegram")
    elif status == "DRY_RUN":
        scheduler.health.inc_metric("telegram", "dry_run")
        scheduler.health.mark_ok("telegram", dry_run=True)
    else:
        scheduler.health.inc_metric("telegram", "failed")
        scheduler.health.mark_degraded(
            "telegram", publish.get("error") or "telegram publish failed"
        )


def sync_runtime_health(scheduler: PolySignalScheduler) -> HealthSnapshot:
    _sync_clob_ws(scheduler)
    _sync_clob_rest(scheduler)
    _sync_spot_feed(scheduler)
    _sync_book_staleness(scheduler)
    return scheduler.health.snapshot()


def persist_health_snapshot(scheduler: PolySignalScheduler) -> None:
    snapshot = sync_runtime_health(scheduler)
    payload = {
        "event_id": new_id("health_snapshot"),
        "event_type": "health_snapshot",
        "severity": "ERROR"
        if snapshot.status == "down"
        else "WARNING"
        if snapshot.status == "degraded"
        else "INFO",
        "created_at": snapshot.generated_at,
        **snapshot.as_dict(),
    }
    try:
        scheduler.sqlite.insert_system_event(payload)
        for event in scheduler.health.consume_transition_events():
            scheduler.sqlite.insert_system_event(event)
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler.logger.warning("Failed to persist health snapshot: %s", exc)


def _sync_clob_ws(scheduler: PolySignalScheduler) -> None:
    metrics = scheduler.ctx.books.metrics.snapshot()["counters"]
    stale_count = _stale_clob_token_count(scheduler)
    idle_without_active_tokens = (
        scheduler._market_refresh_completed and not scheduler._latest_market_token_ids
    )
    poly_ws = scheduler.poly_ws
    connected = bool(getattr(poly_ws, "connected", False))
    reconnect_count = int(getattr(poly_ws, "reconnect_count", 0))
    subscribed_token_count = int(getattr(poly_ws, "subscribed_token_count", 0))
    last_error = getattr(poly_ws, "last_error", None)
    component_metrics: dict[str, JsonValue] = {
        "connected": connected,
        "reconnect_count": reconnect_count,
        "subscribed_token_count": (
            0 if idle_without_active_tokens else subscribed_token_count
        ),
        "stale_token_count": stale_count,
        "invalid_event_count": int(metrics.get("ws_decode_errors", 0))
        + sum(
            int(value)
            for key, value in metrics.items()
            if key.startswith("ws_event_unknown_")
        ),
    }
    if not scheduler.settings.data.polymarket.use_market_ws:
        scheduler.health.mark_ok("clob_ws", enabled=False, **component_metrics)
    elif idle_without_active_tokens:
        scheduler.health.mark_ok("clob_ws", idle=True, **component_metrics)
    elif connected and stale_count == 0:
        scheduler.health.mark_ok("clob_ws", **component_metrics)
    else:
        scheduler.health.mark_degraded(
            "clob_ws",
            last_error or "clob websocket not fully healthy",
            **component_metrics,
        )


def _sync_clob_rest(scheduler: PolySignalScheduler) -> None:
    rest_metrics = getattr(scheduler.rest, "metrics", None)
    if rest_metrics is None:
        scheduler.health.mark_degraded(
            "clob_rest",
            "clob rest metrics unavailable",
            batch_success=0,
            batch_failure=0,
            fallback_count=0,
            latency_ms=None,
        )
        return
    metrics = rest_metrics.snapshot()
    counters = metrics["counters"]
    gauges = metrics["gauges"]
    payload: dict[str, JsonValue] = {
        "batch_success": int(counters.get("clob_rest_batch_success", 0)),
        "batch_failure": int(counters.get("clob_rest_batch_failure", 0)),
        "fallback_count": int(counters.get("clob_rest_fallback_count", 0)),
        "latency_ms": gauges.get("clob_rest_latency_ms"),
    }
    current = scheduler.health.components.get("clob_rest")
    previous_metrics = current.metrics if current is not None else {}
    previous_success = int(previous_metrics.get("batch_success") or 0)
    previous_failure = int(previous_metrics.get("batch_failure") or 0)
    new_success = payload["batch_success"] > previous_success
    new_failure = payload["batch_failure"] > previous_failure
    if current is not None and current.status == "down" and not new_success:
        scheduler.health.mark_down(
            "clob_rest", current.last_error or "clob rest down", **payload
        )
    elif new_failure and not new_success:
        scheduler.health.mark_degraded("clob_rest", "batch fallback used", **payload)
    elif payload["batch_failure"] and not payload["batch_success"]:
        scheduler.health.mark_degraded("clob_rest", "batch fallback used", **payload)
    else:
        scheduler.health.mark_ok("clob_rest", **payload)


def _sync_spot_feed(scheduler: PolySignalScheduler) -> None:
    now = utc_now()
    if scheduler.settings.data.polymarket.use_rtds_ws:
        name = "polymarket_rtds_ws"
        feed = scheduler.rtds_ws
        assets = tuple(scheduler.settings.data.polymarket.rtds_assets)
        source = "polymarket_rtds"
        enabled = True
    else:
        name = "binance_ws"
        feed = scheduler.binance_ws
        assets = tuple(scheduler.settings.data.binance.symbols)
        source = "binance"
        enabled = scheduler.settings.data.binance.enabled

    lags: dict[str, int | None] = {}
    missing_symbols = 0
    for asset in assets:
        spot = scheduler.ctx.spots.get(asset)
        if spot is None:
            missing_symbols += 1
            lags[f"{asset.lower()}_spot_lag_ms"] = None
        else:
            lags[f"{asset.lower()}_spot_lag_ms"] = spot.freshness_ms(now)
    worst_lag = max((lag for lag in lags.values() if lag is not None), default=None)
    metrics: dict[str, JsonValue] = {
        "connected": bool(getattr(feed, "connected", False)),
        "reconnect_count": int(getattr(feed, "reconnect_count", 0)),
        "missing_symbol_count": missing_symbols,
        "source": source,
        **lags,
    }
    message_count = getattr(feed, "message_count", None)
    ignored_message_count = getattr(feed, "ignored_message_count", None)
    if message_count is not None:
        metrics["message_count"] = int(message_count)
    if ignored_message_count is not None:
        metrics["ignored_message_count"] = int(ignored_message_count)

    if not enabled:
        scheduler.health.mark_ok(name, enabled=False, **metrics)
    elif worst_lag is None:
        scheduler.health.mark_down(
            name, getattr(feed, "last_error", None) or "no spot prices", **metrics
        )
    elif missing_symbols:
        scheduler.health.mark_degraded(name, "missing spot prices", **metrics)
    elif not metrics["connected"]:
        scheduler.health.mark_degraded(
            name,
            getattr(feed, "last_error", None) or f"{name} disconnected",
            **metrics,
        )
    elif worst_lag > scheduler.settings.data.binance.max_price_staleness_ms:
        scheduler.health.mark_degraded(name, "spot prices stale", **metrics)
    else:
        scheduler.health.mark_ok(name, **metrics)


def _sync_book_staleness(scheduler: PolySignalScheduler) -> None:
    stale_count = _stale_clob_token_count(scheduler)
    scheduler.health.set_metric("clob_ws", "stale_token_count", stale_count)


def _stale_clob_token_count(scheduler: PolySignalScheduler) -> int:
    if scheduler._market_refresh_completed and not scheduler._latest_market_token_ids:
        return 0
    if scheduler._market_ws_token_ids:
        active_token_ids = scheduler._market_ws_token_ids
    elif scheduler._market_refresh_completed:
        active_token_ids = scheduler._latest_market_token_ids
    else:
        active_token_ids = scheduler._latest_market_token_ids
    if active_token_ids or scheduler._market_refresh_completed:
        return sum(
            1
            for token_id in active_token_ids
            if (state := scheduler.ctx.books.states.get(token_id)) is None
            or not state.has_snapshot
        )
    return sum(
        1 for state in scheduler.ctx.books.states.values() if not state.has_snapshot
    )
