from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module

_pyo3 = load_nautilus_module("nautilus_trader.core.nautilus_pyo3")
ClientId = _pyo3.ClientId


def polymarket_data_client_name(timeframe: str) -> str:
    normalized = timeframe.strip().upper()
    if not normalized:
        raise ValueError("Polymarket data client timeframe is required")
    return f"POLYMARKET-{normalized}"


def polymarket_data_client_id(timeframe: str) -> ClientId:
    return ClientId(polymarket_data_client_name(timeframe))


def polymarket_rtds_data_client_name(timeframes: Sequence[str]) -> str:
    """Primary timeframe owns managed RTDS under multi-client wiring."""
    if not timeframes:
        raise ValueError("Polymarket RTDS data client requires at least one timeframe")
    return polymarket_data_client_name(timeframes[0])


def polymarket_rtds_data_client_id(timeframes: Sequence[str]) -> ClientId:
    return ClientId(polymarket_rtds_data_client_name(timeframes))
