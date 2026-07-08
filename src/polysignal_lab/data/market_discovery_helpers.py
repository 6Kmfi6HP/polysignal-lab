"""
Input: __future__, __future__.annotations, json, re, collections.abc, datetime, datetime.timedelta, typing, pydantic
Output: gamma_events_from_json, json_list, timeframe_seconds, gamma_events_query_params, paginate_gamma_events, build_current_slot_slugs, flatten_gamma_markets, match_crypto_updown, infer_outcome_tokens, is_allowed_active_market, is_allowed_window
Pos: Application code — testable helpers for MarketDiscovery

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Final

from pydantic import JsonValue

from polysignal_lab.config import MarketConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken

JsonObject = dict[str, JsonValue]
GAMMA_PAGE_LIMIT: Final = 200


def gamma_events_from_json(payload: JsonValue) -> list[JsonObject]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("events", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def json_list(raw: JsonValue | None) -> list[JsonValue]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def timeframe_seconds(timeframe: str) -> int | None:
    match = re.fullmatch(r"([1-9]\d*)m", timeframe)
    if match is None:
        return None
    return int(match.group(1)) * 60


def gamma_events_query_params(market_config: MarketConfig, offset: int) -> dict[str, str]:
    return {
        "active": str(market_config.active_only).lower(),
        "closed": str(market_config.closed).lower(),
        "order": "startDate",
        "ascending": "false",
        "limit": str(GAMMA_PAGE_LIMIT),
        "offset": str(offset),
    }


def paginate_gamma_events(
    fetch_page: Callable[[int], list[JsonObject]],
) -> list[JsonObject]:
    events: list[JsonObject] = []
    offset = 0
    while True:
        page = fetch_page(offset)
        events.extend(page)
        if len(page) < GAMMA_PAGE_LIMIT:
            return events
        offset += GAMMA_PAGE_LIMIT


async def paginate_gamma_events_async(
    fetch_page: Callable[[int], Awaitable[list[JsonObject]]],
) -> list[JsonObject]:
    events: list[JsonObject] = []
    offset = 0
    while True:
        page = await fetch_page(offset)
        events.extend(page)
        if len(page) < GAMMA_PAGE_LIMIT:
            return events
        offset += GAMMA_PAGE_LIMIT


def build_current_slot_slugs(
    assets: list[str],
    timeframes: list[str],
    *,
    now_ts: int,
    include_next_periods: int = 0,
    stale_grace_sec: int = 0,
) -> list[str]:
    next_periods = max(int(include_next_periods), 0)
    grace_sec = max(int(stale_grace_sec), 0)
    slugs: list[str] = []
    for asset in assets:
        asset_slug = str(asset).strip().lower()
        if not asset_slug:
            continue
        for timeframe in timeframes:
            timeframe_slug = str(timeframe).strip().lower()
            seconds = timeframe_seconds(timeframe_slug)
            if seconds is None:
                continue
            current_slot_base = now_ts // seconds * seconds
            bases: list[int] = []
            if grace_sec > 0 and now_ts - current_slot_base < grace_sec:
                bases.append(current_slot_base - seconds)
            bases.extend(
                current_slot_base + offset * seconds
                for offset in range(next_periods + 1)
            )
            for slot_base in bases:
                slugs.append(f"{asset_slug}-updown-{timeframe_slug}-{slot_base}")
    return slugs


def flatten_gamma_markets(payloads: list[JsonObject]) -> list[JsonObject]:
    out: list[JsonObject] = []
    for event in payloads:
        event_markets = event.get("markets")
        if isinstance(event_markets, list) and event_markets:
            for market in event_markets:
                if isinstance(market, dict):
                    merged = {**event, **market}
                    merged.setdefault("eventSlug", event.get("slug"))
                    out.append(merged)
        else:
            out.append(event)
    return out


def match_crypto_updown(
    payload: JsonObject,
    *,
    assets: list[str],
    timeframes: list[str],
) -> tuple[str, str] | None:
    slug = str(payload.get("slug") or payload.get("eventSlug") or "")
    match = re.match(r"^([a-z0-9]+)-updown-([0-9]+m)-\d+$", slug.lower())
    if match is None:
        return None
    asset = match.group(1).upper()
    timeframe = match.group(2)
    if asset in {configured.upper() for configured in assets} and timeframe in timeframes:
        return asset, timeframe
    return None


def infer_outcome_tokens(payload: JsonObject, market_id: str) -> list[OutcomeToken]:
    token_ids = json_list(payload.get("clobTokenIds") or payload.get("clob_token_ids") or payload.get("tokenIds"))
    if len(token_ids) < 2:
        return []
    return [
        OutcomeToken(token_id=str(token_ids[0]), side=Side.UP, outcome_name="Up", market_id=market_id),
        OutcomeToken(token_id=str(token_ids[1]), side=Side.DOWN, outcome_name="Down", market_id=market_id),
    ]


def is_allowed_active_market(
    payload: JsonObject,
    *,
    active_only: bool,
    closed: bool,
) -> bool:
    is_closed = bool(payload.get("closed") or payload.get("archived") or payload.get("resolved"))
    active = bool(payload.get("active", not is_closed))
    if active_only and not active:
        return False
    return is_closed == closed


def is_allowed_window(
    market: Market,
    *,
    active_only: bool,
    closed: bool,
    include_next_periods: int = 0,
    stale_grace_sec: int = 0,
    now: datetime,
) -> bool:
    if not (active_only and not closed):
        return True
    if market.start_ts is None or market.end_ts is None:
        return True
    grace_window = timedelta(seconds=max(int(stale_grace_sec), 0))
    future_seconds = max(int(include_next_periods), 0) * (
        timeframe_seconds(market.timeframe) or 0
    )
    future_window = timedelta(seconds=future_seconds)
    return market.start_ts <= now + future_window and market.end_ts >= now - grace_window
