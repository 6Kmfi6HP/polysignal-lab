# Project-side compatibility implementation of Polymarket helper symbols
# removed in nautilus_trader 2.0.0rc3 (upgrade migration, issue69 root fix).
#
# The 2.0 wheel deleted the pure-Python adapter package
# `nautilus_trader.adapters.polymarket.common` (symbol.py / gamma_markets.py).
# This module is a verbatim copy of the 1.x implementations used by the
# project, with import paths adapted to `nautilus_trader._libnautilus`.
#
# Note: only the pure-Python pieces the project actually consumes are kept
# (`build_markets_query` needs no HttpClient; the keyset-pagination helpers
# that did are unused project-side and were dropped).
#
# Never modify upstream / @refs; this module is project-owned.
# pyright: reportAttributeAccessIssue=false, reportInvalidTypeForm=false, reportUnknownVariableType=false, reportExplicitAny=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnusedParameter=false

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, cast

import pandas as pd

from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module

try:
    _lib_model = load_nautilus_module("nautilus_trader._libnautilus.model")
except ImportError:
    # Legacy 1.x layout fallback.
    _lib_model = load_nautilus_module("nautilus_trader.model.identifiers")

InstrumentId = cast(type, _lib_model.InstrumentId)
Symbol = cast(type, _lib_model.Symbol)
Price = cast(type, _lib_model.Price)
Quantity = cast(type, _lib_model.Quantity)
BinaryOption = cast(type, _lib_model.BinaryOption)
AssetClass = cast(type, _lib_model.AssetClass)

try:
    _lib_polymarket = load_nautilus_module("nautilus_trader._libnautilus.polymarket")
except ImportError:
    # Legacy 1.x layout fallback.
    _lib_polymarket = load_nautilus_module(
        "nautilus_trader.adapters.polymarket.common.constants"
    )

POLYMARKET_VENUE = _lib_polymarket.POLYMARKET_VENUE


def get_polymarket_instrument_id(condition_id: str, token_id: str | int) -> InstrumentId:
    return InstrumentId.from_str(f"{condition_id}-{token_id}.{POLYMARKET_VENUE}")


def get_polymarket_condition_id(instrument_id: InstrumentId) -> str:
    parts = instrument_id.symbol.value.split("-")
    if len(parts) != 2 or not parts[0]:
        raise ValueError(
            f"Invalid Polymarket instrument ID format: expected "
            f"'{{condition_id}}-{{token_id}}', was '{instrument_id.symbol.value}'",
        )
    return parts[0]


def get_polymarket_token_id(instrument_id: InstrumentId) -> str:
    parts = instrument_id.symbol.value.split("-")
    if len(parts) != 2 or not parts[1]:
        raise ValueError(
            f"Invalid Polymarket instrument ID format: expected "
            f"'{{condition_id}}-{{token_id}}', was '{instrument_id.symbol.value}'",
        )
    return parts[1]


# Match Nautilus Polymarket gamma_markets page cap.
_GAMMA_MARKETS_PAGE_LIMIT = 100


def build_markets_query(filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Build query params for Gamma Get Markets from a generic filter dict.

    Supported keys (passed through if present):
    - active, archived, closed, limit, order, ascending, id, slug,
      clob_token_ids, condition_ids,
      liquidity_num_min, liquidity_num_max,
      volume_num_min, volume_num_max,
      start_date_min, start_date_max,
      end_date_min, end_date_max,
      tag_id, related_tags

    Special handling:
    - is_active=True implies active=true, archived=false, closed=false
    - offset: applied locally by keyset iteration, never sent to the endpoint
    - after_cursor: added per page by the keyset pagination loop

    """
    params: dict[str, Any] = {}

    if not filters:
        return params

    if filters.get("is_active") is True:
        params["active"] = "true"
        params["archived"] = "false"
        params["closed"] = "false"

    passthrough_keys = (
        "active",
        "archived",
        "closed",
        "limit",
        "order",
        "ascending",
        "id",
        "slug",
        "clob_token_ids",
        "condition_ids",
        "liquidity_num_min",
        "liquidity_num_max",
        "volume_num_min",
        "volume_num_max",
        "start_date_min",
        "start_date_max",
        "end_date_min",
        "end_date_max",
        "tag_id",
        "related_tags",
    )

    for key in passthrough_keys:
        if key in filters and filters[key] is not None:
            params[key] = filters[key]

    return params


# --- instrument parsing (mirrors old common/parsing.py) ---

_PUSD = _lib_model.Currency.from_str("USDC")


def extract_fee_rates(market_info: dict[str, Any]) -> tuple[Decimal, Decimal]:
    """
    Extract effective maker and taker fee rates from Polymarket market info.

    Only takers pay fees; the maker rate is always zero. Without a feeSchedule
    both rates default to zero (no reliable source).
    """
    fee_schedule = market_info.get("feeSchedule")
    if fee_schedule is None:
        gamma_original = market_info.get("_gamma_original") or {}
        fee_schedule = gamma_original.get("feeSchedule")

    if fee_schedule is None:
        return Decimal(0), Decimal(0)

    rate = fee_schedule.get("rate")
    if rate is None:
        return Decimal(0), Decimal(0)

    taker_fee = Decimal(str(rate))
    return Decimal(0), taker_fee


def parse_polymarket_instrument(
    market_info: dict[str, Any],
    token_id: str,
    outcome: str,
    ts_init: int | None = None,
) -> BinaryOption:
    instrument_id = get_polymarket_instrument_id(
        str(market_info["condition_id"]), token_id
    )
    raw_symbol = Symbol(get_polymarket_token_id(instrument_id))
    description = market_info["question"]
    price_increment = Price.from_str(str(market_info["minimum_tick_size"]))
    # Trades are reported with 6-decimal collateral increments.
    size_increment = Quantity.from_str("0.000001")
    end_date_iso = market_info["end_date_iso"]

    if end_date_iso:
        expiration_ns = pd.Timestamp(end_date_iso).value
    else:
        expiration_ns = (pd.Timestamp.now(tz="UTC") + pd.DateOffset(years=10)).value

    maker_fee, taker_fee = extract_fee_rates(market_info)

    ts_init = ts_init if ts_init is not None else time.time_ns()

    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=raw_symbol,
        outcome=outcome,
        description=description,
        asset_class=AssetClass.ALTERNATIVE,
        currency=_PUSD,
        price_increment=price_increment,
        price_precision=price_increment.precision,
        size_increment=size_increment,
        size_precision=size_increment.precision,
        activation_ns=0,
        expiration_ns=expiration_ns,
        max_quantity=None,
        min_quantity=None,
        maker_fee=maker_fee,
        taker_fee=taker_fee,
        ts_event=ts_init,
        ts_init=ts_init,
        info=market_info,
    )
