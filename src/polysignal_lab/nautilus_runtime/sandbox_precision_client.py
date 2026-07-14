"""
Input: __future__, asyncio, logging, typing
Output: PolySignalSandboxExecutionClient, PolySignalSandboxLiveExecClientFactory
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from polysignal_lab.nautilus_runtime.market_data_precision import (
    normalize_market_data_to_instrument,
)

logger = logging.getLogger("polysignal_lab.nautilus.sandbox_precision")

_MARKET_DATA_TYPES = frozenset(
    {
        "QuoteTick",
        "OrderBookDelta",
        "OrderBookDeltas",
    }
)


class PolySignalSandboxExecutionClient:
    """Sandbox execution client that normalizes market-data precision.

    Wraps Nautilus ``SandboxExecutionClient`` so QuoteTick / OrderBookDelta
    prices match the current instrument before SimulatedExchange validation.
    Does not patch Nautilus installed sources.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def on_data(self, data: object) -> None:
        if type(data).__name__ not in _MARKET_DATA_TYPES:
            self._inner.on_data(data)
            return

        instrument_id = getattr(data, "instrument_id", None)
        instrument = self._instrument_for(instrument_id)
        if instrument is None:
            logger.error(
                "Dropping %s for instrument_id=%s: instrument missing from cache "
                "(cannot normalize price precision before sandbox matching)",
                type(data).__name__,
                instrument_id,
            )
            return

        self._inner.on_data(normalize_market_data_to_instrument(data, instrument))

    def _instrument_for(self, instrument_id: object) -> object | None:
        if instrument_id is None:
            return None
        cache = getattr(self._inner, "_cache", None)
        if cache is None:
            cache = getattr(self._inner, "cache", None)
        if cache is None:
            return None
        finder = getattr(cache, "instrument", None)
        if not callable(finder):
            return None
        return finder(instrument_id)


class PolySignalSandboxLiveExecClientFactory:
    """Factory that builds precision-safe sandbox execution clients."""

    @staticmethod
    def create(  # type: ignore[no-untyped-def]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: object,
        portfolio: object,
        msgbus: object,
        cache: object,
        clock: object,
    ) -> PolySignalSandboxExecutionClient:
        from nautilus_trader.adapters.sandbox.factory import SandboxLiveExecClientFactory

        inner = SandboxLiveExecClientFactory.create(
            loop=loop,
            name=name,
            config=config,
            portfolio=portfolio,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
        )
        logger.debug("created precision-safe sandbox execution client for %s", name)
        return PolySignalSandboxExecutionClient(inner)
