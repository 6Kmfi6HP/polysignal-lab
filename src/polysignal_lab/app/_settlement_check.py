"""
Input: __future__, __future__.annotations, sqlite3, datetime, datetime.datetime, typing, typing.cast, polysignal_lab.app, polysignal_lab.app.scheduler_health, polysignal_lab.domain.enums
Output: check_settlements
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import cast

from polysignal_lab.app import scheduler_health
from polysignal_lab.domain.enums import ExitMode, Side, TradeResultStatus
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.utils import new_id, parse_dt, redact_text, utc_iso, utc_now


def _nautilus_positions(scheduler: object) -> list[dict[str, object]]:
    """Get projected position dicts from the Nautilus cache."""
    from polysignal_lab.nautilus_runtime.projections import project_position

    nautilus_cache = getattr(scheduler, "nautilus_cache", None)
    if nautilus_cache is None:
        return []
    positions_method = getattr(nautilus_cache, "positions", None)
    if not callable(positions_method):
        return []
    raw = positions_method()
    if not isinstance(raw, (list, tuple)):
        return []
    return [project_position(p) for p in raw if p is not None]


def _projection_float(source: dict[str, object] | None, key: str) -> float | None:
    if not isinstance(source, dict):
        return None
    value = source.get(key)
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_market(scheduler: object, market_id: str) -> Market | None:
    markets = getattr(scheduler, "markets", None)
    if markets is not None:
        cached = markets.get(market_id)
        if cached is not None:
            return cached
    rows = scheduler.persistence.query_json(
        "markets",
        where="WHERE market_id = ?",
        params=(market_id,),
    )
    if not rows:
        return None
    try:
        market = Market.model_validate(rows[0])
    except (TypeError, ValueError):
        return None
    if markets is not None and hasattr(markets, "upsert_many"):
        markets.upsert_many([market])
    return market


async def check_settlements(scheduler: object) -> list[PaperTradeResult]:
    raw_positions = _nautilus_positions(scheduler)
    if not raw_positions:
        return []

    settled: list[PaperTradeResult] = []
    for projection in raw_positions:
        result = await _try_settle_projection(scheduler, projection)
        if result is not None:
            settled.append(result)
    return settled


async def _try_settle_projection(
    scheduler: object, projection: dict[str, object]
) -> PaperTradeResult | None:
    """Try to settle a single position projection.

    Returns the settlement result, or None if the projection should
    not be settled (e.g., already closed, no market found, unready).
    """
    if not isinstance(projection, dict):
        return None
    if bool(projection.get("is_closed")):
        return None
    market_id = str(projection.get("market_id") or "")
    token_id = str(projection.get("token_id") or projection.get("instrument_id") or "")
    if not market_id or not token_id:
        return None
    market = _load_market(scheduler, market_id)
    if market is None:
        return None
    settlement_resolver = getattr(scheduler, "settlement_resolver", None)
    if settlement_resolver is None:
        return None
    decision = await settlement_resolver.resolve_market(market)
    outcome_value: float | None
    if decision.status == "resolved":
        outcome_value = decision.outcome_value_for(token_id)
    elif decision.status == "cancelled":
        outcome_value = _projection_float(projection, "avg_entry_price")
    else:
        return None
    if outcome_value is None:
        return None
    paper_position_id = str(
        projection.get("paper_position_id") or projection.get("position_id") or ""
    )
    if not paper_position_id:
        return None
    if _existing_result_for_position(scheduler, paper_position_id):
        return None
    result = _paper_trade_result_from_projection(
        projection,
        market=market,
        outcome_value=outcome_value,
        details=decision.details,
    )
    await _store_projection_result(scheduler, result)
    if decision.conflict:
        await _log_settlement_conflict(scheduler, decision, result)
    return result


async def _log_settlement_conflict(
    scheduler: object,
    decision: object,
    result: PaperTradeResult,
) -> None:
    """Log a settlement conflict event."""
    event = {
        "event_id": new_id("evt", "settlement_conflict", result.paper_trade_id),
        "event_type": "settlement_conflict",
        "severity": "WARNING",
        "created_at": utc_iso(),
        "market_id": decision.market_id,
        "condition_id": decision.condition_id,
        "paper_trade_id": result.paper_trade_id,
        "conflict_sources": list(decision.conflict_sources),
    }
    try:
        scheduler.persistence.insert_system_event(event)
        scheduler.persistence.append_log("system_events", event)
    except (OSError, sqlite3.Error, TypeError, ValueError):
        scheduler.logger.warning(
            "Failed to audit settlement conflict for %s",
            decision.market_id,
        )


def _existing_result_for_position(
    scheduler: object, paper_position_id: str
) -> dict[str, object] | None:
    rows = scheduler.persistence.query_json("paper_trade_results", limit=100_000)
    for row in rows:
        if row.get("paper_position_id") == paper_position_id:
            return row
    return None


def _paper_trade_result_from_projection(
    projection: dict[str, object],
    *,
    market: Market,
    outcome_value: float,
    details: dict[str, object],
) -> PaperTradeResult:
    quantity = _projection_float(projection, "quantity") or 0.0
    entry_price = _projection_float(projection, "avg_entry_price") or 0.0
    stake = quantity * entry_price
    settlement_value = quantity * float(outcome_value)
    pnl = settlement_value - stake
    token_id = str(projection.get("token_id") or projection.get("instrument_id") or "")
    side = _projection_side(projection, market, token_id)
    if outcome_value == 1.0:
        result_status = TradeResultStatus.WIN
    elif outcome_value == 0.0:
        result_status = TradeResultStatus.LOSS
    elif 0.0 < outcome_value < 1.0:
        result_status = TradeResultStatus.VOID
    else:
        result_status = TradeResultStatus.WIN if pnl > 0 else TradeResultStatus.LOSS
    ts_raw = projection.get("ts")
    opened_at = parse_dt(cast(str | datetime | None, ts_raw)) if ts_raw else None
    return PaperTradeResult(
        paper_trade_id=new_id("ptr"),
        signal_id=str(projection.get("signal_id") or ""),
        paper_position_id=str(
            projection.get("paper_position_id") or projection.get("position_id") or ""
        ),
        strategy=str(projection.get("strategy") or market.asset),
        asset=str(projection.get("asset") or market.asset),
        timeframe=str(projection.get("timeframe") or market.timeframe),
        market_id=market.market_id,
        market_slug=market.market_slug,
        side=side,
        entry_price=entry_price,
        shares=quantity,
        stake_usdc=stake,
        exit_mode=ExitMode.RESOLUTION,
        outcome_value=float(outcome_value),
        settlement_value=settlement_value,
        pnl_usdc=pnl,
        roi=pnl / stake if stake else 0.0,
        result=result_status,
        opened_at=opened_at or utc_now(),
        closed_at=utc_now(),
        details=details,
    )


def _projection_side(projection: dict[str, object], market: Market, token_id: str) -> Side:
    raw_side = projection.get("side")
    if raw_side is not None:
        try:
            return Side(str(raw_side).upper())
        except ValueError:
            pass
    for token in market.outcome_tokens:
        if token.token_id == token_id:
            return token.side
    return Side.UP


async def _store_projection_result(
    scheduler: object,
    result: PaperTradeResult,
) -> None:
    scheduler.persistence.insert_paper_trade_result(result)
    scheduler.persistence.append_log("paper_trade_results", result)
    await _publish_paper_result_best_effort(scheduler, result)


async def _store_paper_result(
    scheduler: object,
    result: PaperTradeResult,
    position: PaperPosition,
) -> None:
    """Legacy wrapper — used by scripts/repair_settlement_results.py."""
    scheduler.persistence.upsert_paper_position(position)
    await _store_projection_result(scheduler, result)


async def _publish_paper_result_best_effort(
    scheduler: object, result: PaperTradeResult
) -> None:
    if not scheduler.settings.telegram.send_paper_results:
        return
    try:
        publish = await scheduler.publish_service.publish_paper_result(result)
        scheduler_health.note_publish_result(scheduler, publish.as_dict())
    except Exception as exc:
        scheduler.logger.warning(
            "Paper result publish failed after durable persistence for %s: %s",
            result.paper_trade_id,
            exc,
        )
        event = {
            "event_id": new_id("evt", "paper_result_publish_failed", result.paper_trade_id),
            "event_type": "paper_result_publish_failed",
            "severity": "WARNING",
            "created_at": utc_iso(),
            "paper_trade_id": result.paper_trade_id,
            "paper_position_id": result.paper_position_id,
            "signal_id": result.signal_id,
            "error_type": type(exc).__name__,
            "error": redact_text(str(exc)),
        }
        try:
            scheduler.persistence.insert_system_event(event)
            scheduler.persistence.append_log("system_events", event)
        except (OSError, sqlite3.Error, TypeError, ValueError):
            scheduler.logger.exception(
                "Failed to audit paper result publish failure for %s",
                result.paper_trade_id,
            )
