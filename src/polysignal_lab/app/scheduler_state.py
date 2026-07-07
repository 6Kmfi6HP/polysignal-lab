"""
Input: __future__, __future__.annotations, sqlite3, typing, typing.TYPE_CHECKING, polysignal_lab.app, polysignal_lab.app.scheduler_health
Output: persist_state
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from polysignal_lab.app import scheduler_health

if TYPE_CHECKING:
    from polysignal_lab.app.scheduler import PolySignalScheduler


def persist_state(scheduler: PolySignalScheduler) -> None:
    market_cache = [
        market.model_dump(mode="json")
        for market in scheduler.ctx.markets.markets.values()
    ]
    signal_dedupe = scheduler.gate.deduper.snapshot()

    try:
        scheduler.persistence.write_state("market_cache", market_cache)
        scheduler.persistence.write_state("signal_dedupe", signal_dedupe)
        scheduler_health.note_storage_success(scheduler, "state")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler.logger.warning("Failed to persist state files: %s", exc)
        scheduler_health.note_storage_failure(scheduler, "state", exc)
