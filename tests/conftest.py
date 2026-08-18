from __future__ import annotations

import sys
import types
from importlib import import_module
from typing import Any

import pytest

from polysignal_lab.config import Settings
from factories import MarketFactoryConfig, sample_market, sample_market_view

from nautilus_test_kit_compat import TestEventStubs as _TestEventStubs
from nautilus_test_kit_compat import TestEventsProviderPyo3 as _TestEventsProviderPyo3
from nautilus_test_kit_compat import TestExecStubs as _TestExecStubs


def _install_legacy_nautilus_aliases() -> None:
    """Transparently remap legacy 1.x nautilus_trader import paths to their 2.0
    homes before any test module imports (upgrade migration, issue69 root fix).

    Registered publicly (package attributes / sys.modules) so existing test
    imports keep working unchanged:
    - ``nautilus_trader.core.nautilus_pyo3`` (flat re-export)
    - ``nautilus_trader.model.identifiers`` / ``nautilus_trader.model.enums``
    - ``nautilus_trader.test_kit.rust.instruments_pyo3.TestInstrumentProviderPyo3``

    The namespaces are the same aggregate objects the runtime resolves through
    ``load_nautilus_module``, so tests and runtime code share symbol identity.
    Idempotent: re-runs (e.g. pytest --pdb re-imports) are no-ops.
    """
    try:
        import nautilus_trader.core as nt_core
        from polysignal_lab.nautilus_runtime.optional_imports import (
            load_nautilus_module,
        )
    except ImportError:
        return  # nautilus_trader not installed (non-runtime test env)

    if hasattr(nt_core, "nautilus_pyo3"):
        return  # already installed

    pyo3_ns = load_nautilus_module("nautilus_trader.core.nautilus_pyo3")

    # from nautilus_trader.core import nautilus_pyo3 as pyo3
    nt_core.nautilus_pyo3 = pyo3_ns
    sys.modules["nautilus_trader.core.nautilus_pyo3"] = pyo3_ns

    # from nautilus_trader.model.identifiers / .enums / .events import ...
    sys.modules["nautilus_trader.model.identifiers"] = pyo3_ns
    sys.modules["nautilus_trader.model.enums"] = pyo3_ns
    sys.modules["nautilus_trader.model.events"] = pyo3_ns

    # from nautilus_trader.common.config / trading.config import ... (project compat)
    sys.modules["nautilus_trader.common.config"] = load_nautilus_module(
        "nautilus_trader.common.config"
    )
    sys.modules["nautilus_trader.trading.config"] = load_nautilus_module(
        "nautilus_trader.trading.config"
    )

    # from nautilus_trader.adapters.polymarket.common import gamma_markets as official
    polymarket_common = types.ModuleType("nautilus_trader.adapters.polymarket.common")
    polymarket_common.gamma_markets = load_nautilus_module(
        "nautilus_trader.adapters.polymarket.common.gamma_markets"
    )
    sys.modules["nautilus_trader.adapters.polymarket.common"] = polymarket_common

    # from nautilus_trader.test_kit.rust.instruments_pyo3 import TestInstrumentProviderPyo3
    # (2.0 renamed the package to ``testkit``; parent packages must be present
    # for the import system to accept the child paths)
    sys.modules["nautilus_trader.test_kit"] = types.ModuleType(
        "nautilus_trader.test_kit"
    )
    sys.modules["nautilus_trader.test_kit.rust"] = types.ModuleType(
        "nautilus_trader.test_kit.rust"
    )
    testkit = types.ModuleType("nautilus_trader.test_kit.rust.instruments_pyo3")
    testkit.TestInstrumentProviderPyo3 = _LegacyTestInstrumentProvider
    sys.modules["nautilus_trader.test_kit.rust.instruments_pyo3"] = testkit
    testkit = types.ModuleType("nautilus_trader.test_kit.rust.events_pyo3")
    testkit.TestEventsProviderPyo3 = _TestEventsProviderPyo3
    sys.modules["nautilus_trader.test_kit.rust.events_pyo3"] = testkit

    # from nautilus_trader.test_kit.providers import ... (2.0 renamed the package
    # to ``testkit`` and dropped the Polymarket binary_option fixture)
    providers = types.ModuleType("nautilus_trader.test_kit.providers")
    real_providers = import_module("nautilus_trader.testkit.providers")
    providers.TestInstrumentProvider = _LegacyTestInstrumentProvider
    # 2.0 provider also exposes TestDataProvider; re-export it verbatim.
    providers.TestDataProvider = real_providers.TestDataProvider
    sys.modules["nautilus_trader.test_kit.providers"] = providers

    # from nautilus_trader.test_kit.stubs.events / .stubs.execution import ...
    sys.modules["nautilus_trader.test_kit.stubs"] = types.ModuleType(
        "nautilus_trader.test_kit.stubs"
    )
    stubs = types.ModuleType("nautilus_trader.test_kit.stubs.events")
    stubs.TestEventStubs = _TestEventStubs
    sys.modules["nautilus_trader.test_kit.stubs.events"] = stubs
    stubs = types.ModuleType("nautilus_trader.test_kit.stubs.execution")
    stubs.TestExecStubs = _TestExecStubs
    sys.modules["nautilus_trader.test_kit.stubs.execution"] = stubs


class _LegacyTestInstrumentProvider:
    """Project-side stand-in for the 1.x test_kit provider (2.0 moved test
    instrument factories to ``nautilus_trader.testkit.providers`` and dropped
    the Polymarket binary_option helper)."""

    @staticmethod
    def _provider() -> Any:
        from nautilus_trader.testkit.providers import TestInstrumentProvider

        return TestInstrumentProvider

    @staticmethod
    def btcusdt_binance() -> Any:
        return _LegacyTestInstrumentProvider._provider().btcusdt_binance()

    @staticmethod
    def binary_option() -> Any:
        # Minimal 2.0 equivalent of the removed 1.x fixture: same fields, real
        # pyo3 BinaryOption so Parquet round-trips work.
        from decimal import Decimal

        from nautilus_trader._libnautilus import model

        raw_symbol = model.Symbol(
            "0x12a0cb60174abc437bf1178367c72d11f069e1a3add20b148fb0ab4279b772b2"
            "-92544998123698303655208967887569360731013655782348975589292031774495159624905",
        )
        return model.BinaryOption(
            instrument_id=model.InstrumentId(
                symbol=raw_symbol,
                venue=model.Venue("POLYMARKET"),
            ),
            raw_symbol=raw_symbol,
            outcome="Yes",
            description="Will the outcome of this market be 'Yes'?",
            asset_class=model.AssetClass.ALTERNATIVE,
            currency=model.Currency.from_str("USDC"),
            price_precision=3,
            price_increment=model.Price.from_str("0.001"),
            size_precision=2,
            size_increment=model.Quantity.from_str("0.01"),
            activation_ns=0,
            expiration_ns=1704067200000000000,
            margin_init=Decimal(0),
            margin_maint=Decimal(0),
            max_quantity=None,
            min_quantity=model.Quantity.from_int(5),
            maker_fee=Decimal(0),
            taker_fee=Decimal(0),
            ts_event=0,
            ts_init=0,
        )


_install_legacy_nautilus_aliases()


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def market():
    return sample_market(
        MarketFactoryConfig(
            asset="BTC", timeframe="5m", seconds_to_close=120, price_to_beat=100000.0
        )
    )


@pytest.fixture
def market_view(market):
    return sample_market_view(
        asset=market.asset,
        timeframe=market.timeframe,
        seconds_to_close=120,
        price_to_beat=100000.0,
        up_ask=0.82,
        down_ask=0.18,
        spot_price=100120.0,
        spot_source="polymarket_rtds",
        metrics={
            "price_to_beat_source": "market_metadata",
            "price_to_beat_verified": True,
            "price_to_beat_from_anchor_service": False,
            "spot_source": "polymarket_rtds",
        },
    )