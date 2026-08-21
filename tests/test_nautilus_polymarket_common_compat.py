from __future__ import annotations
# pyright: reportAttributeAccessIssue=false, reportUnknownVariableType=false, reportUnknownMemberType=false

import pytest

from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
    build_markets_query,
)
from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
    get_polymarket_condition_id,
)
from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
    get_polymarket_instrument_id,
)
from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
    get_polymarket_token_id,
)
from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module


# --- symbol helpers (mirrors old nautilus_trader.adapters.polymarket.common.symbol) ---


def test_polymarket_instrument_id_roundtrip() -> None:
    instrument_id = get_polymarket_instrument_id("condition1", 12345)
    assert str(instrument_id) == "condition1-12345.POLYMARKET"
    assert get_polymarket_condition_id(instrument_id) == "condition1"
    assert get_polymarket_token_id(instrument_id) == "12345"


def test_polymarket_instrument_id_accepts_str_token() -> None:
    instrument_id = get_polymarket_instrument_id("condition1", "98765")
    assert get_polymarket_token_id(instrument_id) == "98765"


def test_polymarket_condition_id_invalid_format() -> None:
    instrument_id = get_polymarket_instrument_id("condition1", 1)
    # Rebuild a malformed id on the same venue to exercise the guard.
    from nautilus_trader._libnautilus.model import InstrumentId

    malformed = InstrumentId.from_str("no-dash-here.POLYMARKET")
    with pytest.raises(ValueError, match="Invalid Polymarket instrument ID"):
        get_polymarket_condition_id(malformed)
    assert instrument_id is not None  # keep the roundtrip id referenced


def test_polymarket_token_id_invalid_format() -> None:
    from nautilus_trader._libnautilus.model import InstrumentId

    malformed = InstrumentId.from_str("no-dash-here.POLYMARKET")
    with pytest.raises(ValueError, match="Invalid Polymarket instrument ID"):
        get_polymarket_token_id(malformed)


# --- build_markets_query (mirrors old gamma_markets.build_markets_query) ---


def test_build_markets_query_empty_filters() -> None:
    assert build_markets_query() == {}
    assert build_markets_query(None) == {}


def test_build_markets_query_is_active_expansion() -> None:
    params = build_markets_query({"is_active": True})
    assert params == {
        "active": "true",
        "archived": "false",
        "closed": "false",
    }


def test_build_markets_query_passthrough_and_none_filtering() -> None:
    params = build_markets_query(
        {
            "slug": "will-btc-close-above-100k",
            "limit": 42,
            "active": "true",
            "none_key": None,
        }
    )
    assert params == {
        "slug": "will-btc-close-above-100k",
        "limit": 42,
        "active": "true",
    }


# --- legacy module path resolution (how runtime files access these symbols) ---


def test_legacy_common_symbol_path_resolves() -> None:
    symbol = load_nautilus_module("nautilus_trader.adapters.polymarket.common.symbol")
    instrument_id = symbol.get_polymarket_instrument_id("condition1", 1)
    assert symbol.get_polymarket_condition_id(instrument_id) == "condition1"
    assert symbol.get_polymarket_token_id(instrument_id) == "1"


def test_legacy_gamma_markets_path_resolves() -> None:
    gamma = load_nautilus_module(
        "nautilus_trader.adapters.polymarket.common.gamma_markets"
    )
    assert gamma.build_markets_query({"slug": "x"}) == {"slug": "x"}


def test_legacy_adapters_polymarket_top_level_resolves() -> None:
    adapter = load_nautilus_module("nautilus_trader.adapters.polymarket")
    assert callable(adapter.get_polymarket_instrument_id)
    instrument_id = adapter.get_polymarket_instrument_id("condition1", 1)
    assert get_polymarket_token_id(instrument_id) == "1"


# --- price precision (issue69: authoritative tick -> precision mapping) ---


def test_price_precision_from_tick_matrix() -> None:
    from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
        price_precision_from_minimum_tick_size,
    )

    cases = {
        "0.01": 2,
        "0.001": 3,
        "1": 0,
        1: 0,
        0.001: 3,
        0.01: 2,
        "0.0010": 3,  # trailing zeros must not leak into precision
        "0.010": 2,
        "1.0": 0,
        "1e-3": 3,
        "0.000001": 6,
        "100": 0,
    }
    for raw, expected in cases.items():
        assert price_precision_from_minimum_tick_size(raw) == expected, raw


def test_canonical_minimum_tick_size_normalizes_forms() -> None:
    from decimal import Decimal

    from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
        canonical_minimum_tick_size,
    )

    assert canonical_minimum_tick_size("0.0010") == Decimal("0.001")
    assert canonical_minimum_tick_size("1.0") == Decimal("1")
    assert canonical_minimum_tick_size(0.1) == Decimal("0.1")
    assert canonical_minimum_tick_size("1e-3") == Decimal("0.001")


def test_canonical_minimum_tick_size_rejects_invalid_metadata() -> None:
    from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
        canonical_minimum_tick_size,
    )

    for raw in (None, "", "  ", "0", "-0.01", "abc", True, False, float("nan"), "nan"):
        try:
            canonical_minimum_tick_size(raw)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {raw!r}")


def test_tick_precision_respects_nautilus_wei_limit() -> None:
    from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
        price_precision_from_minimum_tick_size,
    )

    assert price_precision_from_minimum_tick_size("0.000000000000000001") == 18
    with pytest.raises(ValueError, match="exceeding Nautilus limit"):
        price_precision_from_minimum_tick_size("0.0000000000000000001")


def test_price_increment_from_tick_is_canonical_precision() -> None:
    from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
        price_increment_from_minimum_tick_size,
    )

    increment = price_increment_from_minimum_tick_size("0.0010")
    assert type(increment).__name__ == "Price"
    assert increment.precision == 3
    assert str(increment) == "0.001"
    assert price_increment_from_minimum_tick_size(1).precision == 0


def test_make_price_and_quantity_at_precision_avoid_binary_float() -> None:
    from decimal import Decimal

    from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
        make_price_at_precision,
        make_quantity_at_precision,
    )

    price = make_price_at_precision("0.42", 3)
    assert price.precision == 3
    assert price.as_decimal() == Decimal("0.420")
    assert make_price_at_precision(0.421, 3).precision == 3
    # float input carries no binary float artifacts through Decimal(str())
    assert str(make_price_at_precision(0.42, 3)) == "0.420"
    # excess decimals quantize via the official Nautilus path
    assert str(make_price_at_precision("0.12345", 3)) == "0.123"

    quantity = make_quantity_at_precision("100", 6)
    assert quantity.precision == 6
    assert quantity.as_decimal() == Decimal("100")

    with pytest.raises(ValueError, match="precision"):
        make_price_at_precision("0.42", 19)
    with pytest.raises(ValueError, match="precision"):
        make_price_at_precision("0.42", "3")


def test_extract_minimum_tick_size_prefers_explicit_and_gamma_numeric() -> None:
    from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
        extract_minimum_tick_size,
    )

    assert extract_minimum_tick_size({"tick_size": "0.001"}) == "0.001"
    # official Gamma field is numeric and nested under _gamma_original
    market_info = {"_gamma_original": {"orderPriceMinTickSize": 0.001}}
    assert extract_minimum_tick_size(market_info) == 0.001
    # explicit top-level wins over the original payload
    market_info = {
        "minimum_tick_size": "0.01",
        "_gamma_original": {"orderPriceMinTickSize": 0.001},
    }
    assert extract_minimum_tick_size(market_info) == "0.01"
    assert extract_minimum_tick_size(None) is None
    assert extract_minimum_tick_size({}) is None


def test_parse_polymarket_instrument_uses_gamma_tick_precision() -> None:
    from decimal import Decimal

    from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
        parse_polymarket_instrument,
    )

    instrument = parse_polymarket_instrument(
        {
            "condition_id": "0xcondition1",
            "question": "BTC Up or Down?",
            "end_date_iso": "2026-08-20T00:35:00Z",
            "_gamma_original": {"orderPriceMinTickSize": 0.001},
        },
        "token1",
        "UP",
    )
    assert instrument.price_precision == 3
    assert instrument.price_increment.precision == 3
    assert instrument.price_increment.as_decimal() == Decimal("0.001")
    assert instrument.size_precision == 6


def test_parse_polymarket_instrument_trailing_zero_tick_canonicalized() -> None:
    from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
        parse_polymarket_instrument,
    )

    instrument = parse_polymarket_instrument(
        {
            "condition_id": "0xcondition1",
            "question": "Q?",
            "minimum_tick_size": "0.0010",
            "end_date_iso": "2026-08-20T00:35:00Z",
        },
        "token1",
        "UP",
    )
    assert instrument.price_precision == 3
    assert str(instrument.price_increment) == "0.001"


def test_parse_polymarket_instrument_missing_tick_metadata_fails_closed() -> None:
    from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
        parse_polymarket_instrument,
    )

    with pytest.raises(ValueError, match="missing minimum tick size"):
        parse_polymarket_instrument(
            {
                "condition_id": "0xc1",
                "question": "Q?",
                "end_date_iso": "2026-08-20T00:35:00Z",
            },
            "token1",
            "UP",
        )


def test_parse_polymarket_instrument_invalid_tick_fails_closed() -> None:
    from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
        parse_polymarket_instrument,
    )

    with pytest.raises(ValueError, match="not a decimal"):
        parse_polymarket_instrument(
            {
                "condition_id": "0xc1",
                "question": "Q?",
                "minimum_tick_size": "not-a-tick",
                "end_date_iso": "2026-08-20T00:35:00Z",
            },
            "token1",
            "UP",
        )
