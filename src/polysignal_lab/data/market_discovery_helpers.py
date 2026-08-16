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
from polysignal_lab.domain.missing_values import count_collapse

JsonObject = dict[str, JsonValue]
# Match Nautilus Polymarket gamma_markets page cap. Requesting >100 makes the
# "len(page) < limit" stop condition trip after page one under silent server caps.
GAMMA_PAGE_LIMIT: Final = 100


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


def gamma_events_query_params(
    market_config: MarketConfig, offset: int
) -> dict[str, str]:
    """Build /events query params for crypto-updown discovery.

    /events is project-owned business transport (official gamma_markets only
    covers /markets). Pagination limit still follows the official 100-item cap.
    """
    return {
        "active": str(market_config.active_only).lower(),
        "closed": str(market_config.closed).lower(),
        "order": "startDate",
        "ascending": "false",
        "limit": str(GAMMA_PAGE_LIMIT),
        "offset": str(offset),
    }


def gamma_markets_slug_query_params(slug: str) -> dict[str, str]:
    """Build /markets?slug=... params via official Nautilus gamma helper."""
    from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module

    gamma_markets = load_nautilus_module(
        "nautilus_trader.adapters.polymarket.common.gamma_markets"
    )
    build_markets_query = gamma_markets.build_markets_query

    raw = build_markets_query({"slug": slug})
    return {str(key): str(value) for key, value in raw.items()}


def paginate_gamma_events(
    fetch_page: Callable[[int], list[JsonObject]],
    *,
    max_pages: int | None = None,
) -> list[JsonObject]:
    events: list[JsonObject] = []
    offset = 0
    pages = 0
    while True:
        page = fetch_page(offset)
        events.extend(page)
        pages += 1
        if len(page) < GAMMA_PAGE_LIMIT or (
            max_pages is not None and pages >= max(max_pages, 1)
        ):
            return events
        offset += GAMMA_PAGE_LIMIT


async def paginate_gamma_events_async(
    fetch_page: Callable[[int], Awaitable[list[JsonObject]]],
    *,
    max_pages: int | None = None,
) -> list[JsonObject]:
    events: list[JsonObject] = []
    offset = 0
    pages = 0
    while True:
        page = await fetch_page(offset)
        events.extend(page)
        pages += 1
        if len(page) < GAMMA_PAGE_LIMIT or (
            max_pages is not None and pages >= max(max_pages, 1)
        ):
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


def parse_gamma_markets(
    payloads: list[JsonObject],
    market_config: MarketConfig,
    *,
    now: datetime,
    include_next_periods: int = 0,
    stale_grace_sec: int = 0,
) -> list[Market]:
    markets: list[Market] = []
    seen: set[str] = set()
    for payload in flatten_gamma_markets(payloads):
        match = match_crypto_updown(
            payload,
            assets=market_config.assets,
            timeframes=market_config.timeframes,
        )
        if match is None or not is_allowed_active_market(
            payload,
            active_only=market_config.active_only,
            closed=market_config.closed,
        ):
            continue
        asset, timeframe = match
        try:
            market = Market.from_gamma(payload, asset=asset, timeframe=timeframe)
        except (KeyError, TypeError, ValueError):
            continue
        if len(market.outcome_tokens) < 2:
            market.outcome_tokens = infer_outcome_tokens(payload, market.market_id)
        if not is_allowed_window(
            market,
            active_only=market_config.active_only,
            closed=market_config.closed,
            include_next_periods=include_next_periods,
            stale_grace_sec=stale_grace_sec,
            now=now,
        ):
            continue
        key = market.condition_id or market.market_id or market.market_slug
        if len(market.outcome_tokens) >= 2 and key not in seen:
            seen.add(key)
            markets.append(market)
    return markets


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
    if (
        asset in {configured.upper() for configured in assets}
        and timeframe in timeframes
    ):
        return asset, timeframe
    return None


def infer_outcome_tokens(payload: JsonObject, market_id: str) -> list[OutcomeToken]:
    token_ids = json_list(
        payload.get("clobTokenIds")
        or payload.get("clob_token_ids")
        or payload.get("tokenIds")
    )
    if len(token_ids) < 2:
        return []
    return [
        OutcomeToken(
            token_id=str(token_ids[0]),
            side=Side.UP,
            outcome_name="Up",
            market_id=market_id,
        ),
        OutcomeToken(
            token_id=str(token_ids[1]),
            side=Side.DOWN,
            outcome_name="Down",
            market_id=market_id,
        ),
    ]


def is_allowed_active_market(
    payload: JsonObject,
    *,
    active_only: bool,
    closed: bool,
) -> bool:
    is_closed = bool(
        payload.get("closed") or payload.get("archived") or payload.get("resolved")
    )
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
    period_seconds = timeframe_seconds(market.timeframe)
    if period_seconds is None:
        count_collapse("timeframe_seconds")
        period_seconds = 0
    future_seconds = max(int(include_next_periods), 0) * period_seconds
    future_window = timedelta(seconds=future_seconds)
    return (
        market.start_ts <= now + future_window and market.end_ts >= now - grace_window
    )
