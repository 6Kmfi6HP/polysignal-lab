#!/usr/bin/env python3
# noqa: SIZE_OK  — self-contained offline repair CLI; splitting is outside this security fix
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
import json
import logging
import sqlite3
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from polysignal_lab.app._settlement_check import _store_paper_result
from polysignal_lab.config import load_settings
from polysignal_lab.domain.enums import ExitMode, PositionStatus, Side, TradeResultStatus
from polysignal_lab.domain.market import Market
import anyio

from polysignal_lab.domain.paper_result import InvalidPaperTradeResultRow, PaperWalletSnapshot
from polysignal_lab.paper.settlement_sources import ResolutionDecision
from polysignal_lab.utils import new_id, utc_iso, utc_now

if TYPE_CHECKING:
    from polysignal_lab.nautilus_runtime.runtime_context_factory import NautilusRuntimeContext

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


@dataclass(slots=True)  # noqa: MUTABLE_OK  — audit report accumulates class buckets during one run
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


@dataclass(frozen=True, slots=True)
class MissingBackupError(RuntimeError):
    mode: str

    def __str__(self) -> str:
        return f"--backup is required when applying {self.mode}"


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


def _position_id(position: dict[str, Any]) -> str:
    return str(position.get("paper_position_id") or position.get("position_id") or "")


def _position_opened_at(position: dict[str, Any]) -> datetime | None:
    raw = position.get("opened_at") or position.get("ts") or position.get("created_at")
    if raw in (None, ""):
        return None
    if isinstance(raw, datetime):
        opened = raw
    else:
        try:
            opened = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=ZoneInfo("UTC"))
    return opened


def _position_side(position: dict[str, Any]) -> Side | None:
    raw = position.get("side")
    if raw in (None, ""):
        return None
    try:
        return Side(str(raw).upper())
    except ValueError:
        return None


def _position_in_range(position: dict[str, Any], since: date | None, until: date | None) -> bool:
    opened = _position_opened_at(position)
    if opened is None:
        return False
    opened_date = opened.date()
    if since is not None and opened_date < since:
        return False
    if until is not None and opened_date > until:
        return False
    return True


def _existing_results_for_position(
    scheduler: NautilusRuntimeContext, paper_position_id: str
) -> list[dict[str, Any]]:
    rows = scheduler.persistence.query_json("paper_trade_results", limit=100_000)
    return [row for row in rows if row.get("paper_position_id") == paper_position_id]


def _existing_result_for_position(
    scheduler: NautilusRuntimeContext, paper_position_id: str
) -> dict[str, Any] | None:
    rows = _existing_results_for_position(scheduler, paper_position_id)
    return rows[0] if rows else None


def _load_market(scheduler: NautilusRuntimeContext, market_id: str) -> Market | None:
    cached = scheduler.markets.get(market_id)
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
    scheduler.markets.upsert_many([market])
    return market


def _settle_for_repair(
    position: dict[str, Any],
    market: Market,
    decision: ResolutionDecision,
) -> dict[str, Any] | None:
    entry_price = _repair_float(position, "entry_price")
    shares = _repair_float(position, "shares")
    stake_usdc = _repair_float(position, "stake_usdc")
    if entry_price is None or shares is None or stake_usdc is None:
        return None
    opened_at = _position_opened_at(position)
    side = _position_side(position)
    if opened_at is None or side is None:
        return None
    token_id = str(position.get("token_id") or "")
    match decision.status:  # noqa: MATCH_OK  — external resolver status string, not a closed variant
        case "cancelled":
            outcome_value = entry_price
            settlement_value = stake_usdc
            pnl = 0.0
            roi = 0.0
            result_status = TradeResultStatus.VOID
        case "resolved":
            outcome_value = decision.outcome_value_for(token_id)
            if outcome_value is None:
                return None
            settlement_value = shares * float(outcome_value)
            pnl = settlement_value - stake_usdc
            roi = pnl / stake_usdc if stake_usdc else 0.0
            if outcome_value == 1.0:
                result_status = TradeResultStatus.WIN
            elif outcome_value == 0.0:
                result_status = TradeResultStatus.LOSS
            elif 0.0 < outcome_value < 1.0:
                result_status = TradeResultStatus.VOID
            else:
                result_status = TradeResultStatus.WIN if pnl > 0 else TradeResultStatus.LOSS
        case _:
            return None
    closed_at = utc_now()
    position["status"] = PositionStatus.CLOSED.value
    position["closed_at"] = closed_at.isoformat()
    position["is_closed"] = True
    return {
        "paper_trade_id": new_id("pt", _position_id(position), closed_at.isoformat()),
        "signal_id": str(position.get("signal_id") or ""),
        "paper_position_id": _position_id(position),
        "strategy": str(position.get("strategy") or ""),
        "asset": str(position.get("asset") or ""),
        "timeframe": str(position.get("timeframe") or ""),
        "market_id": market.market_id,
        "market_slug": market.market_slug,
        "side": side.value,
        "entry_price": entry_price,
        "shares": shares,
        "stake_usdc": stake_usdc,
        "exit_mode": ExitMode.RESOLUTION.value,
        "outcome_value": float(outcome_value),
        "settlement_value": settlement_value,
        "pnl_usdc": pnl,
        "roi": roi,
        "result": result_status.value,
        "opened_at": opened_at.isoformat(),
        "closed_at": closed_at.isoformat(),
        "details": {
            "resolved_outcome": market.resolved_outcome.value if market.resolved_outcome else None,
            "confidence": position.get("signal_confidence"),
            **decision.details,
        },
    }


def _repair_float(position: dict[str, Any], key: str) -> float | None:
    value = position.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _replay_wallet(scheduler: NautilusRuntimeContext) -> tuple[float, float, int]:
    starting = float(scheduler.settings.paper_trading.starting_balance_usdc)
    cash = starting
    fills = scheduler.persistence.query_json(
        "system_events",
        where="WHERE event_type=?",
        params=("nautilus_fill",),
        limit=100_000,
    )
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


def _wallet_drift(scheduler: NautilusRuntimeContext) -> dict[str, float]:
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
    scheduler: NautilusRuntimeContext,
    position: dict[str, Any],
    market: Market,
) -> ResolutionDecision:
    return await scheduler.settlement_resolver.resolve_market(market)


def _planned_result_label(decision: ResolutionDecision, position: dict[str, Any]) -> str | None:
    if decision.status == "cancelled":
        return TradeResultStatus.VOID.value
    if decision.status != "resolved":
        return None
    outcome_value = decision.outcome_value_for(str(position.get("token_id") or ""))
    if outcome_value is None:
        return None
    if outcome_value == 1.0:
        return TradeResultStatus.WIN.value
    if outcome_value == 0.0:
        return TradeResultStatus.LOSS.value
    if 0.0 < outcome_value < 1.0:
        return TradeResultStatus.VOID.value
    return TradeResultStatus.UNKNOWN.value


async def audit(scheduler: NautilusRuntimeContext, config: RepairConfig) -> AuditReport:
    report = AuditReport(run_id=new_run_id())
    c1: list[dict[str, Any]] = []
    c2: list[dict[str, Any]] = []
    c5: list[dict[str, Any]] = []

    open_rows = scheduler.persistence.restore_open_positions()
    for row in open_rows:
        position = dict(row)
        position_id = _position_id(position)
        if config.position_id and position_id != config.position_id:
            continue
        if config.market_id and position.get("market_id") != config.market_id:
            continue
        if not _position_in_range(position, config.since, config.until):
            continue
        if _existing_result_for_position(scheduler, position_id):
            if config.force_correct:
                existing = _existing_result_for_position(scheduler, position_id)
                if existing and _is_c5_candidate(existing):
                    c5.append({"paper_position_id": position_id, "market_id": position.get("market_id")})
            continue
        market = _load_market(scheduler, str(position.get("market_id") or ""))
        if market is None:
            report.skipped_unknown.append(
                {
                    "paper_position_id": position_id,
                    "reason": "MARKET_NOT_FOUND",
                }
            )
            continue
        decision = await _resolve_position(scheduler, position, market)
        if decision.status in {"resolved", "cancelled"}:
            c1.append(
                {
                    "paper_position_id": position_id,
                    "market_id": position.get("market_id"),
                    "planned_result": _planned_result_label(decision, position),
                }
            )
        elif decision.status == "unknown":
            report.skipped_unknown.append(
                {
                    "paper_position_id": position_id,
                    "reason": str(decision.details.get("reason") or "NO_RESOLVED_EVIDENCE"),
                }
            )

    closed_rows = scheduler.persistence.restore_closed_positions()
    for row in closed_rows:
        position = dict(row)
        position_id = _position_id(position)
        if config.position_id and position_id != config.position_id:
            continue
        if config.market_id and position.get("market_id") != config.market_id:
            continue
        if _existing_result_for_position(scheduler, position_id):
            existing = _existing_result_for_position(scheduler, position_id)
            if existing and _is_c5_candidate(existing):
                c5.append({"paper_position_id": position_id, "market_id": position.get("market_id")})
            continue
        c2.append({"paper_position_id": position_id, "market_id": position.get("market_id")})

    drift = _wallet_drift(scheduler)
    report.classes = {
        "C1_missed_settlement": c1,
        "C2_closed_without_result": c2,
        "C3_wallet_drift": drift,
        "C5_manual_review": c5,
    }
    return report


def _backup_sqlite(scheduler: NautilusRuntimeContext, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(scheduler.sqlite.path, backup_path)


def _append_repair_audit(
    scheduler: NautilusRuntimeContext,
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


async def backfill(scheduler: NautilusRuntimeContext, config: RepairConfig) -> dict[str, Any]:
    run_id = new_run_id()
    if not config.dry_run:
        if config.backup_path is None:
            raise MissingBackupError(mode="backfill")
        _backup_sqlite(scheduler, config.backup_path)

    applied = 0
    skipped = 0
    skipped_unknown: list[dict[str, str]] = []
    failures = 0
    affected_dates: set[date] = set()

    prior_send = scheduler.settings.telegram.send_paper_results
    if config.publish_telegram:
        scheduler.settings.telegram.send_paper_results = True

    try:
        open_rows = scheduler.persistence.restore_open_positions()
        for row in open_rows:
            position = dict(row)
            position_id = _position_id(position)
            if config.position_id and position_id != config.position_id:
                continue
            if config.market_id and position.get("market_id") != config.market_id:
                continue
            if not _position_in_range(position, config.since, config.until):
                continue
            if _existing_result_for_position(scheduler, position_id) and not config.force_correct:
                skipped += 1
                continue

            market = _load_market(scheduler, str(position.get("market_id") or ""))
            if market is None:
                skipped_unknown.append(
                    {"paper_position_id": position_id, "reason": "MARKET_NOT_FOUND"}
                )
                continue

            decision = await _resolve_position(scheduler, position, market)
            if decision.status == "unknown":
                skipped_unknown.append(
                    {
                        "paper_position_id": position_id,
                        "reason": str(decision.details.get("reason") or "NO_RESOLVED_EVIDENCE"),
                    }
                )
                continue
            if decision.status not in {"resolved", "cancelled"}:
                continue

            work_position = position if not config.dry_run else dict(position)
            result = _settle_for_repair(work_position, market, decision)
            if result is None:
                skipped_unknown.append(
                    {"paper_position_id": position_id, "reason": "NO_PAYOUT_FOR_TOKEN"}
                )
                continue

            if config.force_correct and not config.dry_run:
                for stale in _existing_results_for_position(scheduler, position_id):
                    paper_trade_id = stale.get("paper_trade_id")
                    if isinstance(paper_trade_id, str):
                        publish_id = stale.get("publish_id")
                        scheduler.persistence.delete_paper_result_rows(
                            paper_trade_id,
                            publish_id if isinstance(publish_id, str) else None,
                        )

            if config.dry_run:
                applied += 1
                LOGGER.info(
                    "Dry-run would settle %s -> %s",
                    position_id,
                    result["result"],
                )
                continue

            try:
                await _store_paper_result(scheduler, result, work_position)
            except (InvalidPaperTradeResultRow, KeyError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
                failures += 1
                LOGGER.error("Failed to persist repair for %s: %s", position_id, exc)
                continue

            applied += 1
            closed_at_raw = result["closed_at"]
            if isinstance(closed_at_raw, datetime):
                closed_at = closed_at_raw
            else:
                closed_at = datetime.fromisoformat(str(closed_at_raw).replace("Z", "+00:00"))
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


def reconcile_wallet(scheduler: NautilusRuntimeContext, config: RepairConfig) -> dict[str, Any]:
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
        raise MissingBackupError(mode="wallet repair")

    _backup_sqlite(scheduler, config.backup_path)
    replay_cash, replay_pnl, open_count = _replay_wallet(scheduler)
    starting = float(scheduler.settings.paper_trading.starting_balance_usdc)
    open_rows = scheduler.persistence.restore_open_positions()
    open_stake = sum(float(row.get("stake_usdc") or 0.0) for row in open_rows)
    snapshot = PaperWalletSnapshot(
        starting_balance=starting,
        cash_balance=replay_cash,
        realized_pnl=replay_pnl,
        equity=replay_cash + open_stake,
        open_position_count=open_count,
        created_at=utc_now(),
    )
    scheduler.persistence.sqlite.insert_wallet_snapshot(snapshot)
    return {"applied": True, "drift": drift}


async def regenerate_reports(scheduler: NautilusRuntimeContext, config: RepairConfig, dates: list[str]) -> dict[str, Any]:
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


async def build_runtime(config: RepairConfig) -> NautilusRuntimeContext:
    from polysignal_lab.nautilus_runtime.runtime_context_factory import (
        build_nautilus_runtime_context,
    )

    settings = load_settings(config.config_path)
    return build_nautilus_runtime_context(settings, base_dir=config.data_dir)


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

    runtime = await build_runtime(config)
    exit_code = 0
    report_dates: list[str] = []

    if config.mode in {"audit", "all"}:
        audit_report = await audit(runtime, config)
        print(json.dumps(audit_report.to_dict(), indent=2, default=str))

    if config.mode in {"backfill", "all"}:
        backfill_report = await backfill(runtime, config)
        print(json.dumps(backfill_report, indent=2, default=str))
        report_dates = backfill_report.get("affected_report_dates", [])
        if backfill_report.get("failures", 0) > 0:
            exit_code = 1

    if config.mode in {"wallet", "all"}:
        wallet_report = reconcile_wallet(runtime, config)
        print(json.dumps(wallet_report, indent=2, default=str))

    if config.mode in {"reports", "all"}:
        reports_report = await regenerate_reports(runtime, config, report_dates)
        print(json.dumps(reports_report, indent=2, default=str))

    runtime.persistence.close()
    return exit_code


def run_repair(config: RepairConfig) -> int:
    return anyio.run(run_repair_async, config)


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
