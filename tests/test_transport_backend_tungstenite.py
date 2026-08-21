"""Transport backend selection for the Polymarket data client.

2.0.0rc3 defaults to the SOCKUDO WS transport, but Polymarket's WS endpoint
rejects its subscription payload with code=1008 "invalid subscription payload",
causing a 10-second reconnect loop.  The legacy TUNGSTENITE transport (the only
option in 1.x) produces a payload the server accepts.
"""
from __future__ import annotations

# ruff: noqa: E402

from nautilus_optional import require_nautilus

require_nautilus()

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.live_node import (
    build_polymarket_data_client_config,
)


def _make_instrument_config() -> object:
    """Build a minimal PolymarketInstrumentProviderConfig accepted by the pyo3 constructor."""
    from nautilus_trader._libnautilus import polymarket

    return polymarket.PolymarketInstrumentProviderConfig()


def test_data_client_config_uses_tungstenite_transport() -> None:
    """The data client config must select TUNGSTENITE, not the SOCKUDO default."""
    settings = Settings()
    config = build_polymarket_data_client_config(
        settings,
        instrument_config=_make_instrument_config(),
    )
    backend = getattr(config, "transport_backend", None)
    backend_name = str(backend)
    assert "TUNGSTENITE" in backend_name, (
        f"expected TUNGSTENITE transport, got {backend_name!r}"
    )
