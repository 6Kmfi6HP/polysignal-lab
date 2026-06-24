from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from pydantic import ValidationError

from polysignal_lab.app import scheduler_health

from polysignal_lab.domain.paper_position import PaperPosition

if TYPE_CHECKING:
    from polysignal_lab.app.scheduler import PolySignalScheduler


async def restore_wallet_state(scheduler: PolySignalScheduler) -> None:
    restored = 0

    try:
        for position_data in scheduler.sqlite.restore_open_positions():
            try:
                position = PaperPosition.model_validate(position_data)
                scheduler.wallet.open_positions[position.paper_position_id] = position
                restored += 1
            except ValidationError as exc:
                scheduler.logger.warning("Failed to restore position from SQLite: %s", exc)
        if restored > 0:
            scheduler.logger.info("Restored %d open positions from SQLite", restored)
    except (json.JSONDecodeError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler.logger.warning("SQLite restore failed: %s", exc)

    if restored == 0:
        positions_data = scheduler.state.read("open_positions", default=[])
        for position_data in positions_data:
            try:
                position = PaperPosition.model_validate(position_data)
                if position.paper_position_id not in scheduler.wallet.open_positions:
                    scheduler.wallet.open_positions[position.paper_position_id] = position
                    restored += 1
            except ValidationError as exc:
                scheduler.logger.warning("Failed to restore position from state JSON: %s", exc)

    try:
        wallet_data = scheduler.sqlite.restore_latest_wallet_snapshot()
    except (json.JSONDecodeError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler.logger.warning("SQLite wallet restore failed: %s", exc)
        wallet_data = None
    if wallet_data is None:
        wallet_data = scheduler.state.read("paper_wallet", default=None)
    if wallet_data:
        cash = wallet_data.get("cash_balance")
        if cash is not None:
            scheduler.wallet.cash_balance = float(cash)
        realized_pnl = wallet_data.get("realized_pnl")
        if realized_pnl is not None:
            scheduler.wallet.realized_pnl = float(realized_pnl)

    if restored > 0:
        scheduler.logger.info(
            "Restored wallet: %d open positions, cash=%.2f, realized_pnl=%.2f",
            restored,
            scheduler.wallet.cash_balance or 0,
            scheduler.wallet.realized_pnl or 0,
        )


def persist_state(scheduler: PolySignalScheduler) -> None:
    wallet_snapshot = scheduler.wallet.snapshot()
    try:
        scheduler.logs.append("paper_wallet_snapshots", wallet_snapshot)
        scheduler_health.note_storage_success(scheduler, "jsonl")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler.logger.warning("Failed to persist JSONL state: %s", exc)
        scheduler_health.note_storage_failure(scheduler, "jsonl", exc)

    try:
        scheduler.sqlite.insert_wallet_snapshot(wallet_snapshot)
        scheduler_health.note_storage_success(scheduler, "sqlite")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler.logger.warning("Failed to persist SQLite state: %s", exc)
        scheduler_health.note_storage_failure(scheduler, "sqlite", exc)

    try:
        scheduler.state.write("paper_wallet", wallet_snapshot)
        scheduler.state.write(
            "open_positions",
            [
                position.model_dump(mode="json")
                for position in scheduler.wallet.open_positions.values()
            ],
        )
        scheduler.state.write(
            "market_cache",
            [
                market.model_dump(mode="json")
                for market in scheduler.ctx.markets.markets.values()
            ],
        )
        scheduler.state.write("signal_dedupe", scheduler.gate.deduper.snapshot())
        scheduler_health.note_storage_success(scheduler, "state")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler.logger.warning("Failed to persist state files: %s", exc)
        scheduler_health.note_storage_failure(scheduler, "state", exc)
