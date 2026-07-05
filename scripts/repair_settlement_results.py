#!/usr/bin/env python3
"""Offline repair for missed paper settlement persistence.

Stop the polysignal-lab / polysignal-nautilus container (or any process holding
the SQLite database) before running this script. Repairs are offline-only and
use read-only Gamma / Polygon RPC calls through the production settlement
resolver.

Example::

    python -m scripts.repair_settlement_results \\
        --config config/signal_bot.yaml \\
        --data-dir . \\
        --mode audit

    python -m scripts.repair_settlement_results \\
        --config config/signal_bot.yaml \\
        --data-dir . \\
        --mode backfill \\
        --apply \\
        --backup ./backups/pre-repair.sqlite
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.app.scheduler_reporting import _store_paper_result
from polysignal_lab.app.scheduler_state import persist_state
from polysignal_lab.config import load_settings
from polysignal_lab.domain.enums import MarketStatus, PositionStatus, TradeResultStatus
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.paper.settlement_sources import ResolutionDecision
from polysignal_lab.utils import new_id, utc_iso

WALLET_EPSILON = 1e-6
LOGGER = logging.getLogger("polysignal_lab.repair_settlement")


@dataclass(frozen=True, slots=True)
class RepairConfig:
    config_path: Path | None
    data_dir: Path
    mode: str
    dry_run: bool
    backup_path: Path | None
    since: date | None
    until: date | None
    market_id: str | None
    position_id: str | None
    publish_telegram: bool
    force_correct: bool


@dataclass
class AuditReport:
    run_id: str
    classes: dict[str, Any] = field(default_factory=dict)
    skipped_unknown: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "classes": self.classes,
            "skipped_unknown": self.skipped_unknown,
        }


def new_run_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"repair-{stamp}-{new_id('run')[-6:]}"


def _git_commit_hash() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = proc.stdout.strip()
    return commit or None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _position_in_range(position: PaperPosition, since: date | None, until: date | None) -> bool:
    opened = position.opened_at
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=ZoneInfo("UTC"))
    opened_date = opened.date()
    if since is not None and opened_date < since:
        return False
    if until is not None and opened_date > until:
        return False
    return True


def _existing_result_for_position(
    scheduler: PolySignalScheduler, paper_position_id: str
) -> dict[str, Any] | None:
    rows = scheduler.persistence.query_json("paper_trade_results", limit=100_000)
    for row in rows:
        if row.get("paper_position_id") == paper_position_id:
            return row
    return None


def _load_market(scheduler: PolySignalScheduler, market_id: str) -> Market | None:
    cached = scheduler.ctx.markets.get(market_id)
    if cached is not None:
        return cached
    rows = scheduler.persistence.query_json(
        "markets",
        where="WHERE market_id = ?",
        params=(market_id,),
        limit=1,
    )
    if not rows:
        return None
    market = Market.model_validate(rows[0])
    scheduler.ctx.markets.upsert_many([market])
    return market


def _settle_for_repair(
    scheduler: PolySignalScheduler,
    position: PaperPosition,
    market: Market,
    decision: ResolutionDecision,
) -> PaperTradeResult | None:
    if decision.status == "cancelled":
        return scheduler.settlement.settle(
            position,
            market.model_copy(update={"status": MarketStatus.CANCELLED}),
            details=decision.details,
        )
    if decision.status == "resolved":
        outcome_value = decision.outcome_value_for(position.token_id)
        if outcome_value is None:
            return None
        return scheduler.settlement.settle(
            position,
            market,
            outcome_value=outcome_value,
            details=decision.details,
        )
    return None


def _replay_wallet(scheduler: PolySignalScheduler) -> tuple[float, float, int]:
    starting = float(scheduler.settings.paper_trading.starting_balance_usdc)
    cash = starting
    fills = scheduler.persistence.query_json("paper_fills", limit=100_000)
    for fill in fills:
        cash -= float(fill.get("stake_usdc") or 0.0)
    results = scheduler.persistence.query_json("paper_trade_results", limit=100_000)
    realized_pnl = 0.0
    for row in results:
        cash += float(row.get("settlement_value") or 0.0)
        realized_pnl += float(row.get("pnl_usdc") or 0.0)
    open_positions = scheduler.persistence.restore_open_positions()
    open_count = len(open_positions)
    return round(cash, 10), round(realized_pnl, 10), open_count


def _wallet_drift(scheduler: PolySignalScheduler) -> dict[str, float]:
    replay_cash, replay_pnl, _ = _replay_wallet(scheduler)
    latest = scheduler.persistence.restore_latest_wallet_snapshot() or {}
    stored_cash = float(latest.get("cash_balance", replay_cash))
    stored_pnl = float(latest.get("realized_pnl", replay_pnl))
    return {
        "cash_delta": round(replay_cash - stored_cash, 10),
        "realized_pnl_delta": round(replay_pnl - stored_pnl, 10),
        "replay_cash": replay_cash,
        "replay_pnl": replay_pnl,
    }


def _is_c5_candidate(existing: dict[str, Any]) -> bool:
    details = existing.get("details") or {}
    if existing.get("result") == TradeResultStatus.UNKNOWN.value and not details.get("settlement_source"):
        return True
    return False


async def _resolve_position(
    scheduler: PolySignalScheduler,
    position: PaperPosition,
    market: Market,
) -> ResolutionDecision:
    return await scheduler.settlement_resolver.resolve_market(market)


def _planned_result_label(decision: ResolutionDecision, position: PaperPosition) -> str | None:
    if decision.status == "cancelled":
        return TradeResultStatus.VOID.value
    if decision.status != "resolved":
        return None
    outcome_value = decision.outcome_value_for(position.token_id)
    if outcome_value is None:
        return None
    if outcome_value == 1.0:
        return TradeResultStatus.WIN.value
    if outcome_value == 0.0:
        return TradeResultStatus.LOSS.value
    if 0.0 < outcome_value < 1.0:
        return TradeResultStatus.VOID.value
    return TradeResultStatus.UNKNOWN.value


async def audit(scheduler: PolySignalScheduler, config: RepairConfig) -> AuditReport:
    report = AuditReport(run_id=new_run_id())
    c1: list[dict[str, Any]] = []
    c2: list[dict[str, Any]] = []
    c5: list[dict[str, Any]] = []

    open_rows = scheduler.persistence.restore_open_positions()
    for row in open_rows:
        position = PaperPosition.model_validate(row)
        if config.position_id and position.paper_position_id != config.position_id:
            continue
        if config.market_id and position.market_id != config.market_id:
            continue
        if not _position_in_range(position, config.since, config.until):
            continue
        if _existing_result_for_position(scheduler, position.paper_position_id):
            if config.force_correct:
                existing = _existing_result_for_position(scheduler, position.paper_position_id)
                if existing and _is_c5_candidate(existing):
                    c5.append({"paper_position_id": position.paper_position_id, "market_id": position.market_id})
            continue
        market = _load_market(scheduler, position.market_id)
        if market is None:
            report.skipped_unknown.append(
                {
                    "paper_position_id": position.paper_position_id,
                    "reason": "MARKET_NOT_FOUND",
                }
            )
            continue
        decision = await _resolve_position(scheduler, position, market)
        if decision.status in {"resolved", "cancelled"}:
            c1.append(
                {
                    "paper_position_id": position.paper_position_id,
                    "market_id": position.market_id,
                    "planned_result": _planned_result_label(decision, position),
                }
            )
        elif decision.status == "unknown":
            report.skipped_unknown.append(
                {
                    "paper_position_id": position.paper_position_id,
                    "reason": str(decision.details.get("reason") or "NO_RESOLVED_EVIDENCE"),
                }
            )

    closed_rows = scheduler.persistence.query_json(
        "paper_positions",
        where="WHERE status = ?",
        params=(PositionStatus.CLOSED.value,),
        limit=100_000,
    )
    for row in closed_rows:
        position = PaperPosition.model_validate(row)
        if config.position_id and position.paper_position_id != config.position_id:
            continue
        if config.market_id and position.market_id != config.market_id:
            continue
        if _existing_result_for_position(scheduler, position.paper_position_id):
            existing = _existing_result_for_position(scheduler, position.paper_position_id)
            if existing and _is_c5_candidate(existing):
                c5.append({"paper_position_id": position.paper_position_id, "market_id": position.market_id})
            continue
        c2.append({"paper_position_id": position.paper_position_id, "market_id": position.market_id})

    drift = _wallet_drift(scheduler)
    report.classes = {
        "C1_missed_settlement": c1,
        "C2_closed_without_result": c2,
        "C3_wallet_drift": drift,
        "C5_manual_review": c5,
    }
    return report


def _backup_sqlite(scheduler: PolySignalScheduler, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(scheduler.sqlite.path, backup_path)


def _append_repair_audit(
    scheduler: PolySignalScheduler,
    *,
    run_id: str,
    backup_path: Path | None,
    counts: dict[str, int],
) -> None:
    event = {
        "event_id": new_id("evt", "settlement_repair_applied", run_id),
        "event_type": "settlement_repair_applied",
        "severity": "INFO",
        "created_at": utc_iso(),
        "run_id": run_id,
        "backup_path": str(backup_path) if backup_path else None,
        "git_commit": _git_commit_hash(),
        "counts": counts,
    }
    scheduler.persistence.insert_system_event(event)
    try:
        scheduler.persistence.append_log("system_events", event)
    except (OSError, TypeError, ValueError):
        LOGGER.warning("Failed to append settlement repair audit to JSONL")


async def backfill(scheduler: PolySignalScheduler, config: RepairConfig) -> dict[str, Any]:
    run_id = new_run_id()
    if not config.dry_run:
        if config.backup_path is None:
            raise ValueError("--backup is required when applying")
        _backup_sqlite(scheduler, config.backup_path)

    await scheduler._restore_wallet_state()
    applied = 0
    skipped = 0
    skipped_unknown: list[dict[str, str]] = []
    failures = 0
    affected_dates: set[date] = set()

    prior_send = scheduler.settings.telegram.send_paper_results
    if config.publish_telegram:
        scheduler.settings.telegram.send_paper_results = True

    try:
        for position_id, position in list(scheduler.wallet.open_positions.items()):
            if config.position_id and position.paper_position_id != config.position_id:
                continue
            if config.market_id and position.market_id != config.market_id:
                continue
            if not _position_in_range(position, config.since, config.until):
                continue
            if _existing_result_for_position(scheduler, position.paper_position_id) and not config.force_correct:
                skipped += 1
                continue

            market = _load_market(scheduler, position.market_id)
            if market is None:
                skipped_unknown.append(
                    {"paper_position_id": position.paper_position_id, "reason": "MARKET_NOT_FOUND"}
                )
                continue

            decision = await _resolve_position(scheduler, position, market)
            if decision.status == "unknown":
                skipped_unknown.append(
                    {
                        "paper_position_id": position.paper_position_id,
                        "reason": str(decision.details.get("reason") or "NO_RESOLVED_EVIDENCE"),
                    }
                )
                continue
            if decision.status not in {"resolved", "cancelled"}:
                continue

            cash_before = scheduler.wallet.cash_balance
            pnl_before = scheduler.wallet.realized_pnl
            status_before = position.status
            closed_at_before = position.closed_at
            was_open = position.paper_position_id in scheduler.wallet.open_positions

            result = _settle_for_repair(scheduler, position, market, decision)
            if result is None:
                skipped_unknown.append(
                    {"paper_position_id": position.paper_position_id, "reason": "NO_PAYOUT_FOR_TOKEN"}
                )
                if was_open:
                    scheduler.wallet.open_positions[position.paper_position_id] = position
                position.status = status_before
                position.closed_at = closed_at_before
                continue

            if config.dry_run:
                applied += 1
                LOGGER.info(
                    "Dry-run would settle %s -> %s",
                    position.paper_position_id,
                    result.result.value,
                )
                scheduler.wallet.cash_balance = cash_before
                scheduler.wallet.realized_pnl = pnl_before
                position.status = status_before
                position.closed_at = closed_at_before
                if was_open:
                    scheduler.wallet.open_positions[position.paper_position_id] = position
                continue

            try:
                await _store_paper_result(scheduler, result, position)
            except Exception as exc:
                failures += 1
                scheduler.wallet.cash_balance = cash_before
                scheduler.wallet.realized_pnl = pnl_before
                position.status = status_before
                position.closed_at = closed_at_before
                if was_open:
                    scheduler.wallet.open_positions[position.paper_position_id] = position
                LOGGER.error("Failed to persist repair for %s: %s", position.paper_position_id, exc)
                continue

            applied += 1
            closed_at = result.closed_at
            if closed_at.tzinfo is None:
                closed_at = closed_at.replace(tzinfo=ZoneInfo("UTC"))
            affected_dates.add(closed_at.date())
    finally:
        scheduler.settings.telegram.send_paper_results = prior_send

    if not config.dry_run and applied > 0:
        _append_repair_audit(
            scheduler,
            run_id=run_id,
            backup_path=config.backup_path,
            counts={"backfill_applied": applied, "backfill_failures": failures},
        )

    return {
        "run_id": run_id,
        "applied": applied,
        "skipped": skipped,
        "failures": failures,
        "skipped_unknown": skipped_unknown,
        "affected_report_dates": sorted(d.isoformat() for d in affected_dates),
    }


def reconcile_wallet(scheduler: PolySignalScheduler, config: RepairConfig) -> dict[str, Any]:
    drift = _wallet_drift(scheduler)
    needs_fix = (
        abs(drift["cash_delta"]) > WALLET_EPSILON
        or abs(drift["realized_pnl_delta"]) > WALLET_EPSILON
    )
    if not needs_fix:
        return {"applied": False, "drift": drift}

    if config.dry_run:
        return {"applied": False, "would_apply": True, "drift": drift}

    if config.backup_path is None:
        raise ValueError("--backup is required when applying")

    _backup_sqlite(scheduler, config.backup_path)
    replay_cash, replay_pnl, open_count = _replay_wallet(scheduler)
    scheduler.wallet.cash_balance = replay_cash
    scheduler.wallet.realized_pnl = replay_pnl
    for row in scheduler.persistence.restore_open_positions():
        position = PaperPosition.model_validate(row)
        scheduler.wallet.open_positions[position.paper_position_id] = position
    if open_count != scheduler.wallet.open_position_count:
        scheduler.wallet.open_positions = {
            position.paper_position_id: position
            for position in scheduler.wallet.open_positions.values()
        }
    persist_state(scheduler)
    return {"applied": True, "drift": drift}


async def regenerate_reports(scheduler: PolySignalScheduler, config: RepairConfig, dates: list[str]) -> dict[str, Any]:
    if not dates:
        return {"regenerated": []}
    today = datetime.now(ZoneInfo(scheduler.settings.app.timezone)).date().isoformat()
    regenerated: list[str] = []
    for report_date in dates:
        if report_date != today:
            LOGGER.warning(
                "Skipping daily report regeneration for %s (only today supported in v1)",
                report_date,
            )
            continue
        if config.dry_run:
            regenerated.append(report_date)
            continue
        existing = scheduler.persistence.query_json(
            "daily_reports",
            where="WHERE report_date = ?",
            params=(report_date,),
            limit=10,
        )
        for row in existing:
            report_id = row.get("report_id")
            if report_id:
                with scheduler.persistence.sqlite._lock, scheduler.persistence.sqlite._conn:
                    scheduler.persistence.sqlite._conn.execute(
                        "DELETE FROM daily_reports WHERE report_id = ?",
                        (report_id,),
                    )
        report = await scheduler.generate_daily_report()
        if report is not None:
            regenerated.append(report_date)
    return {"regenerated": regenerated}


async def build_scheduler(config: RepairConfig) -> PolySignalScheduler:
    settings = load_settings(config.config_path)
    scheduler = PolySignalScheduler(settings, base_dir=config.data_dir)
    from polysignal_lab.paper.wallet import PaperWallet
    from polysignal_lab.paper.exit_engine import PaperExitEngine
    from polysignal_lab.paper.settlement import PaperSettlementEngine

    scheduler.wallet = PaperWallet(scheduler.settings.paper_trading.starting_balance_usdc)
    scheduler.paper = None
    scheduler.exits = PaperExitEngine(scheduler.settings.paper_trading.exit_model, scheduler.wallet)
    scheduler.settlement = PaperSettlementEngine(scheduler.wallet)
    await scheduler._restore_wallet_state()
    return scheduler


def validate_config(config: RepairConfig) -> int | None:
    if not config.dry_run and config.backup_path is None:
        print("--backup is required when using --apply", file=sys.stderr)
        return 2
    if config.mode not in {"audit", "backfill", "wallet", "reports", "all"}:
        print(f"Unknown mode: {config.mode}", file=sys.stderr)
        return 2
    return None


async def run_repair_async(config: RepairConfig) -> int:
    error_code = validate_config(config)
    if error_code is not None:
        return error_code

    scheduler = await build_scheduler(config)
    exit_code = 0
    report_dates: list[str] = []

    if config.mode in {"audit", "all"}:
        audit_report = await audit(scheduler, config)
        print(json.dumps(audit_report.to_dict(), indent=2, default=str))

    if config.mode in {"backfill", "all"}:
        backfill_report = await backfill(scheduler, config)
        print(json.dumps(backfill_report, indent=2, default=str))
        report_dates = backfill_report.get("affected_report_dates", [])
        if backfill_report.get("failures", 0) > 0:
            exit_code = 1

    if config.mode in {"wallet", "all"}:
        wallet_report = reconcile_wallet(scheduler, config)
        print(json.dumps(wallet_report, indent=2, default=str))

    if config.mode in {"reports", "all"}:
        reports_report = await regenerate_reports(scheduler, config, report_dates)
        print(json.dumps(reports_report, indent=2, default=str))

    scheduler.persistence.close()
    return exit_code


def run_repair(config: RepairConfig) -> int:
    return asyncio.run(run_repair_async(config))


def _build_config_from_args(args: argparse.Namespace) -> RepairConfig:
    dry_run = not args.apply
    return RepairConfig(
        config_path=Path(args.config) if args.config else None,
        data_dir=Path(args.data_dir),
        mode=args.mode,
        dry_run=dry_run,
        backup_path=Path(args.backup) if args.backup else None,
        since=_parse_date(args.since),
        until=_parse_date(args.until),
        market_id=args.market_id,
        position_id=args.position_id,
        publish_telegram=args.publish_telegram,
        force_correct=args.force_correct,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="Path to signal_bot.yaml")
    parser.add_argument("--data-dir", default=".", help="Project base directory")
    parser.add_argument(
        "--mode",
        default="audit",
        choices=["audit", "backfill", "wallet", "reports", "all"],
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply mutations (default is dry-run)",
    )
    parser.add_argument("--backup", default=None, help="SQLite backup path (required with --apply)")
    parser.add_argument("--since", default=None, help="Filter OPEN positions opened on/after date (YYYY-MM-DD)")
    parser.add_argument("--until", default=None, help="Filter OPEN positions opened on/before date (YYYY-MM-DD)")
    parser.add_argument("--market-id", default=None, dest="market_id")
    parser.add_argument("--position-id", default=None, dest="position_id")
    parser.add_argument("--publish-telegram", action="store_true", dest="publish_telegram")
    parser.add_argument("--force-correct", action="store_true", dest="force_correct")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    return run_repair(_build_config_from_args(args))


if __name__ == "__main__":
    raise SystemExit(main())
