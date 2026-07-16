"""
Input: __future__, sqlite3, datetime, typing, polysignal_lab.app.scheduler_health, polysignal_lab.domain.enums, polysignal_lab.domain.market, polysignal_lab.paper.exit_result, polysignal_lab.utils
Output: check_settlements, _paper_trade_result_from_projection
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""




from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, cast

from polysignal_lab.app import scheduler_health
from polysignal_lab.domain.enums import ExitMode, PositionStatus, Side, TradeResultStatus
from polysignal_lab.domain.market import Market
from polysignal_lab.paper.exit_result import fee_fields_v1
from polysignal_lab.utils import new_id, parse_dt, redact_text, utc_iso, utc_now


def _nautilus_positions(scheduler: object) -> list[dict[str, object]]:
    """Get open position projections from the Nautilus cache."""
    from polysignal_lab.nautilus_runtime.projections import project_position

    nautilus_cache = getattr(scheduler, "nautilus_cache", None)
    if nautilus_cache is None:
        return []
    positions_method = getattr(nautilus_cache, "positions_open", None)
    if not callable(positions_method):
        positions_method = getattr(nautilus_cache, "positions", None)
    if not callable(positions_method):
        return []
    try:
        raw = positions_method()
    except TypeError:
        legacy_positions = getattr(nautilus_cache, "positions", None)
        raw = legacy_positions() if callable(legacy_positions) else ()
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, bytearray)):
        return []
    catalog = getattr(scheduler, "market_catalog", None)
    projections: list[dict[str, object]] = []
    for position in raw:
        if position is None:
            continue
        projection = project_position(position)
        try:
            _enrich_position_identity(projection, catalog)
        except (RuntimeError, ValueError):
            continue
        projections.append(projection)
    return projections


def _enrich_position_identity(
    projection: dict[str, object],
    catalog: object | None,
) -> None:
    if catalog is None:
        return
    instrument_id = str(projection.get("instrument_id") or "")
    if not instrument_id:
        return
    condition_ids = getattr(catalog, "condition_ids", None)
    by_condition = getattr(catalog, "by_condition", None)
    instrument_id_for_token = getattr(catalog, "instrument_id_for_token", None)
    if not callable(condition_ids) or not callable(by_condition) or not callable(instrument_id_for_token):
        return
    for condition_id in condition_ids():
        pair = by_condition(condition_id)
        if pair is None:
            continue
        for token_meta in (pair.up, pair.down):
            if instrument_id_for_token(token_meta.token_id) != instrument_id:
                continue
            projection["token_id"] = token_meta.token_id
            projection["condition_id"] = pair.condition_id
            projection["market_id"] = pair.market_id
            projection["side"] = token_meta.side.value
            return


def _projection_float(source: dict[str, object] | None, key: str) -> float | None:
    if not isinstance(source, dict):
        return None
    value = source.get(key)
    if not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _load_market(scheduler: Any, market_id: str) -> Market | None:
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


async def check_settlements(scheduler: object) -> list[dict[str, Any]]:
    raw_positions = _nautilus_positions(scheduler)
    if not raw_positions:
        return []

    settled: list[dict[str, Any]] = []
    for projection in raw_positions:
        result = await _try_settle_projection(scheduler, projection)
        if result is not None:
            settled.append(result)
    return settled


async def _try_settle_projection(
    scheduler: Any, projection: dict[str, object]
) -> dict[str, Any] | None:
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
        if outcome_value is None:
            outcome_value = _projection_float(projection, "entry_price")
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
    settlement_details = dict(decision.details)
    settlement_details.setdefault("native_settlement_mode", "report_only")
    settlement_details.setdefault("native_position_mutation", "not_supported")
    settlement_details.setdefault("native_position_status", "open_projection")
    result = _paper_trade_result_from_projection(
        projection,
        market=market,
        outcome_value=outcome_value,
        details=settlement_details,
    )
    if result is None:
        return None
    await _store_projection_result(scheduler, result)
    if decision.conflict:
        await _log_settlement_conflict(scheduler, decision, result)
    return result


async def _log_settlement_conflict(
    scheduler: Any,
    decision: Any,
    result: Mapping[str, Any],
) -> None:
    """Log a settlement conflict event."""
    paper_trade_id = str(result.get("paper_trade_id") or "")
    event = {
        "event_id": new_id("evt", "settlement_conflict", paper_trade_id),
        "event_type": "settlement_conflict",
        "severity": "WARNING",
        "created_at": utc_iso(),
        "market_id": decision.market_id,
        "condition_id": decision.condition_id,
        "paper_trade_id": paper_trade_id,
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
    scheduler: Any, paper_position_id: str
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
) -> dict[str, Any] | None:
    quantity = _projection_float(projection, "shares")
    if quantity is None:
        quantity = _projection_float(projection, "quantity")
    entry_price = _projection_float(projection, "entry_price")
    if entry_price is None:
        entry_price = _projection_float(projection, "avg_entry_price")
    stake = _projection_float(projection, "stake_usdc")
    try:
        outcome = float(outcome_value)
    except (TypeError, ValueError):
        return None
    if (
        quantity is None
        or entry_price is None
        or stake is None
        or quantity <= 0.0
        or entry_price <= 0.0
        or stake <= 0.0
        or not math.isfinite(outcome)
    ):
        return None
    fee = fee_fields_v1()
    entry_fee = float(fee["entry_fee"])
    settlement_value = quantity * outcome
    pnl = settlement_value - stake - entry_fee
    token_id = str(projection.get("token_id") or projection.get("instrument_id") or "")
    side = _projection_side(projection, market, token_id)
    if side is None:
        return None
    if outcome_value == 1.0:
        result_status = TradeResultStatus.WIN
    elif outcome_value == 0.0:
        result_status = TradeResultStatus.LOSS
    elif 0.0 < outcome_value < 1.0:
        result_status = TradeResultStatus.VOID
    else:
        result_status = TradeResultStatus.WIN if pnl > 0 else TradeResultStatus.LOSS
    opened_at = None
    for key in ("opened_at", "ts", "created_at"):
        ts_raw = projection.get(key)
        if ts_raw:
            try:
                opened_at = parse_dt(cast(str | datetime | None, ts_raw))
            except ValueError:
                return None
            if opened_at is None:
                return None
            break
    if opened_at is None:
        return None
    closed_at = utc_now()
    result_details = dict(details)
    result_details.setdefault("fee_model", fee["fee_model"])
    result_details.setdefault("entry_fee", entry_fee)
    return {
        "schema_version": 1,
        "paper_trade_id": new_id("ptr"),
        "signal_id": str(projection.get("signal_id") or ""),
        "paper_position_id": str(
            projection.get("paper_position_id") or projection.get("position_id") or ""
        ),
        "strategy": str(projection.get("strategy") or market.asset),
        "asset": str(projection.get("asset") or market.asset),
        "timeframe": str(projection.get("timeframe") or market.timeframe),
        "market_id": market.market_id,
        "market_slug": market.market_slug,
        "side": side.value,
        "entry_price": entry_price,
        "shares": quantity,
        "stake_usdc": stake,
        "exit_mode": ExitMode.RESOLUTION.value,
        "outcome_value": float(outcome_value),
        "settlement_value": settlement_value,
        "pnl_usdc": pnl,
        "roi": pnl / stake if stake else 0.0,
        "result": result_status.value,
        "opened_at": opened_at.isoformat(),
        "closed_at": closed_at.isoformat(),
        "fee_model": fee["fee_model"],
        "entry_fee": entry_fee,
        "details": result_details,
    }


def _projection_side(projection: dict[str, object], market: Market, token_id: str) -> Side | None:
    raw_side = projection.get("side")
    if raw_side is not None:
        try:
            return Side(str(raw_side).upper())
        except ValueError:
            pass
    for token in market.outcome_tokens:
        if token.token_id == token_id:
            return token.side
    return None


async def _store_projection_result(
    scheduler: Any,
    result: Mapping[str, Any],
) -> None:
    scheduler.persistence.insert_paper_trade_result(result)
    scheduler.persistence.append_log("paper_trade_results", result)
    await _publish_paper_result_best_effort(scheduler, result)


async def _store_paper_result(
    scheduler: Any,
    result: Mapping[str, Any],
    position: dict[str, object],
) -> None:
    """Legacy wrapper — used by scripts/repair_settlement_results.py."""
    closed = dict(position)
    closed["status"] = PositionStatus.CLOSED.value
    closed["is_closed"] = True
    closed_at_raw = result.get("closed_at")
    if isinstance(closed_at_raw, datetime):
        closed_at_text = closed_at_raw.isoformat()
    else:
        closed_at_text = str(closed_at_raw)
    closed["closed_at"] = closed_at_text
    position_id = str(
        closed.get("paper_position_id") or closed.get("position_id") or ""
    )
    scheduler.persistence.insert_system_event(
        {
            "event_id": new_id("evt", "nautilus_position", position_id),
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": closed.get("closed_at") or utc_iso(),
            "ts": closed.get("closed_at") or utc_iso(),
            **closed,
        }
    )
    await _store_projection_result(scheduler, result)


async def _publish_paper_result_best_effort(
    scheduler: Any, result: Mapping[str, Any]
) -> None:
    if not scheduler.settings.telegram.send_paper_results:
        return
    publish_result = dict(result)
    try:
        publish = await scheduler.publish_service.publish_paper_result(publish_result)
        scheduler_health.note_publish_result(scheduler, publish.as_dict())
    except Exception as exc:
        scheduler.logger.warning(
            "Paper result publish failed after durable persistence for %s: %s",
            publish_result.get("paper_trade_id"),
            exc,
        )
        event = {
            "event_id": new_id(
                "evt",
                "paper_result_publish_failed",
                str(publish_result.get("paper_trade_id") or ""),
            ),
            "event_type": "paper_result_publish_failed",
            "severity": "WARNING",
            "created_at": utc_iso(),
            "paper_trade_id": publish_result.get("paper_trade_id"),
            "paper_position_id": publish_result.get("paper_position_id"),
            "signal_id": publish_result.get("signal_id"),
            "error_type": type(exc).__name__,
            "error": redact_text(str(exc)),
        }
        try:
            scheduler.persistence.insert_system_event(event)
            scheduler.persistence.append_log("system_events", event)
        except (OSError, sqlite3.Error, TypeError, ValueError):
            scheduler.logger.exception(
                "Failed to audit paper result publish failure for %s",
                publish_result.get("paper_trade_id"),
            )
