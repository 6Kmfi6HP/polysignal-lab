"""
Input: __future__, __future__.annotations, sqlite3, polysignal_lab.observability.health, polysignal_lab.observability.health.HealthSnapshot, polysignal_lab.utils, polysignal_lab.utils.new_id, polysignal_lab.utils.utc_iso, polysignal_lab.utils.utc_now
Output: note_storage_success, note_storage_failure, note_publish_result, sync_runtime_health, persist_health_snapshot
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import sqlite3

from polysignal_lab.observability.health import HealthSnapshot
from polysignal_lab.utils import new_id, utc_iso, utc_now


def note_storage_success(scheduler: object, store_name: str) -> None:
    scheduler.health.mark_ok(f"{store_name}_storage", last_successful_write=utc_iso())


def note_storage_failure(
    scheduler: object, store_name: str, exc: BaseException
) -> None:
    scheduler.health.inc_metric(f"{store_name}_storage", "write_failures")
    scheduler.health.mark_down(f"{store_name}_storage", str(exc))


def note_publish_result(
    scheduler: object, publish: dict[str, str | None]
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


def sync_runtime_health(scheduler: object) -> HealthSnapshot:
    return scheduler.health.snapshot()


def persist_health_snapshot(scheduler: object) -> None:
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


