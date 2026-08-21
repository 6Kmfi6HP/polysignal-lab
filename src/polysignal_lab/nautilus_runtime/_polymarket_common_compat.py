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
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Final, cast

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


def get_polymarket_instrument_id(
    condition_id: str, token_id: str | int
) -> InstrumentId:
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


# --- price precision (issue69: one authoritative tick -> precision mapping) ---
#
# Polymarket reports the same price grid under several spellings: Gamma
# `orderPriceMinTickSize` (JSON number), legacy `minimum_tick_size`/`tickSize`
# (string) and the free-form decimal strings carried by book messages
# ("0.42", "0.420", "0.4").  Nautilus prices are fixed-precision: a Price built
# from a book string inherits the STRING's decimal places, so "0.42" becomes a
# precision-2 Price.  When such a Price reaches an order book whose instrument
# has price_precision=3 the native boundary rejects it with the live issue69
# failure `Invalid delta order price precision 2, expected 3`.
#
# The authoritative price grid is the market minimum tick size, not the number
# of decimals in any one book message.  Everything below funnels raw tick and
# price values through Decimal (never binary float) so project-side objects
# always land on the instrument's own grid.

_WEI_PRECISION: Final = 18  # Nautilus Price/Quantity hard cap (WEI_PRECISION).

_MINIMUM_TICK_SIZE_KEYS: Final = (
    "minimum_tick_size",
    "minimumTickSize",
    "tick_size",
    "tickSize",
)
_GAMMA_MINIMUM_TICK_SIZE_KEYS: Final = (
    "orderPriceMinTickSize",
    "orderPriceMinTick",
    "minimumTickSize",
    "minimum_tick_size",
    "tickSize",
    "tick_size",
)


def extract_minimum_tick_size(market_info: Mapping[str, Any] | None) -> Any:
    """Return the best-known minimum tick value from a Gamma payload.

    Consults the top-level metadata keys first, then the embedded
    ``_gamma_original`` payload (the official Gamma field
    ``orderPriceMinTickSize`` is numeric). Returns None when every source is
    absent/empty so callers can apply their own documented default.
    """
    if not isinstance(market_info, Mapping):
        return None
    mappings: list[Mapping[str, Any]] = [market_info]
    original = market_info.get("_gamma_original")
    if isinstance(original, Mapping):
        mappings.append(cast(Mapping[str, Any], original))
    for mapping in mappings:
        for key in _MINIMUM_TICK_SIZE_KEYS:
            value = mapping.get(key)
            if value is not None and value != "":
                return value
    for mapping in mappings:
        for key in _GAMMA_MINIMUM_TICK_SIZE_KEYS:
            if key in _MINIMUM_TICK_SIZE_KEYS:
                continue
            value = mapping.get(key)
            if value is not None and value != "":
                return value
    return None


def canonical_minimum_tick_size(value: Any) -> Decimal:
    """Validate a minimum tick size and return its trailing-zero-free Decimal.

    Accepted forms: "0.01", "0.001", "1", "1e-3", 0.001 (float), 1 (int).
    Rejects: None, "", NaN/inf, zero, negatives and bools. Input never
    round-trips through binary float, so "0.0010" canonicalizes to 0.001 and
    1.0 to 1 (Nautilus Price would otherwise keep precision 4 or 1).
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(
            f"Polymarket minimum tick size must be a positive decimal, was {value!r}"
        )
    text = value.strip() if isinstance(value, str) else str(value)
    if not text:
        raise ValueError(
            "Polymarket minimum tick size must be a positive decimal, was empty"
        )
    try:
        tick = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(
            f"Polymarket minimum tick size {value!r} is not a decimal number"
        ) from exc
    if not tick.is_finite() or tick <= 0:
        raise ValueError(
            f"Polymarket minimum tick size must be a positive decimal, was {value!r}"
        )
    return tick.normalize()


def price_precision_from_minimum_tick_size(value: Any) -> int:
    """Exact price precision implied by a tick size.

    0.01 -> 2, 0.001 -> 3, 1 -> 0, "0.0010" -> 3 (trailing zeros stripped),
    "1e-3" -> 3. Precisely the canonical Decimal exponent, capped at the
    Nautilus WEI_PRECISION=18.
    """
    tick = canonical_minimum_tick_size(value)
    exponent = tick.as_tuple().exponent
    if not isinstance(exponent, int):
        # Only reachable for non-finite Decimals (already rejected above).
        raise ValueError(
            f"Polymarket minimum tick size {value!r} is not a decimal number"
        )
    precision = max(0, -exponent)
    if precision > _WEI_PRECISION:
        raise ValueError(
            f"Polymarket minimum tick size {value!r} requires precision "
            f"{precision}, exceeding Nautilus limit {_WEI_PRECISION}"
        )
    return precision


def price_increment_from_minimum_tick_size(value: Any) -> Price:
    """Official Price increment (canonical precision) for a tick size."""
    tick = canonical_minimum_tick_size(value)
    return Price.from_decimal(tick)


def _coerce_precision(precision: Any, *, what: str) -> int:
    if isinstance(precision, bool) or not isinstance(precision, int):
        raise ValueError(f"{what} precision must be an int, was {precision!r}")
    if not 0 <= precision <= _WEI_PRECISION:
        raise ValueError(
            f"{what} precision must be in 0..{_WEI_PRECISION}, was {precision}"
        )
    return precision


def make_price_at_precision(value: Any, price_precision: Any) -> Price:
    """Quantize a raw Polymarket price value onto an exact Nautilus price grid.

    String/float/Decimal input is converted via Decimal (no binary float
    error): 0.42 -> 0.420 at precision 3, 0.421 unchanged. Values with more
    decimals than ``price_precision`` are quantized with the official Nautilus
    rule (``Price.from_decimal_dp``, ROUND_HALF_EVEN); venue book prices are
    tick-aligned, so that only fires on malformed input.
    """
    precision = _coerce_precision(price_precision, what="price")
    if value is None:
        raise ValueError("Polymarket price value is required")
    text = value.strip() if isinstance(value, str) else str(value)
    if not text:
        raise ValueError("Polymarket price value is empty")
    try:
        decimal = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Polymarket price {value!r} is not a decimal number") from exc
    if not decimal.is_finite():
        raise ValueError(f"Polymarket price must be finite, was {value!r}")
    return Price.from_decimal_dp(decimal, precision)


def make_quantity_at_precision(value: Any, size_precision: Any) -> Quantity:
    """Quantize a raw Polymarket size value onto the instrument size grid."""
    precision = _coerce_precision(size_precision, what="size")
    if value is None:
        raise ValueError("Polymarket size value is required")
    text = value.strip() if isinstance(value, str) else str(value)
    if not text:
        raise ValueError("Polymarket size value is empty")
    try:
        decimal = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Polymarket size {value!r} is not a decimal number") from exc
    if not decimal.is_finite() or decimal < 0:
        raise ValueError(
            f"Polymarket size must be a finite non-negative decimal, was {value!r}"
        )
    return Quantity.from_decimal_dp(decimal, precision)


# --- instrument parsing (mirrors old common/parsing.py) ---

_PUSD = _lib_model.Currency.from_str("USDC")


def _expiration_ns(end_date_iso: Any) -> int:
    """Expiration ns from the market end date (10-year default when absent)."""
    if end_date_iso:
        return int(pd.Timestamp(end_date_iso).value)
    return int((pd.Timestamp.now(tz="UTC") + pd.DateOffset(years=10)).value)


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
    # Price grid authority: the market minimum tick size (official Gamma
    # `orderPriceMinTickSize` or legacy spellings) — never a book string's
    # decimal places ("0.42" would yield 2 vs the instrument's 3, issue69).
    raw_tick_size = extract_minimum_tick_size(market_info)
    if raw_tick_size is None:
        raise ValueError(
            f"Polymarket market {instrument_id} missing minimum tick size "
            "metadata; cannot derive price precision"
        )
    price_increment = price_increment_from_minimum_tick_size(raw_tick_size)
    price_precision = price_increment.precision
    # Trades are reported with 6-decimal collateral increments.
    size_increment = Quantity.from_str("0.000001")
    maker_fee, taker_fee = extract_fee_rates(market_info)
    expiration_ns = _expiration_ns(market_info.get("end_date_iso"))
    ts_init = ts_init if ts_init is not None else time.time_ns()

    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=raw_symbol,
        outcome=outcome,
        description=description,
        asset_class=AssetClass.ALTERNATIVE,
        currency=_PUSD,
        price_increment=price_increment,
        price_precision=price_precision,
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
