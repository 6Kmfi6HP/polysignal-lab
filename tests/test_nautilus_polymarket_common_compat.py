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
    gamma = load_nautilus_module("nautilus_trader.adapters.polymarket.common.gamma_markets")
    assert gamma.build_markets_query({"slug": "x"}) == {"slug": "x"}


def test_legacy_adapters_polymarket_top_level_resolves() -> None:
    adapter = load_nautilus_module("nautilus_trader.adapters.polymarket")
    assert callable(adapter.get_polymarket_instrument_id)
    instrument_id = adapter.get_polymarket_instrument_id("condition1", 1)
    assert get_polymarket_token_id(instrument_id) == "1"
