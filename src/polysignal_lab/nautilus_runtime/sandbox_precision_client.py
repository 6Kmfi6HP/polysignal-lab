"""
Input: __future__, asyncio, logging, typing, nautilus_trader.adapters.sandbox, nautilus_trader.cache, nautilus_trader.common, nautilus_trader.core, nautilus_trader.model, nautilus_trader.portfolio
Output: PolySignalSandboxExecutionClient, SandboxLiveExecClientFactory, PolySignalSandboxLiveExecClientFactory
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import asyncio
import logging
from typing import cast

from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig
from nautilus_trader.adapters.sandbox.execution import (
    SandboxExecutionClient as _NautilusSandboxExecutionClient,
)
from nautilus_trader.adapters.sandbox.factory import (
    SandboxLiveExecClientFactory as _NautilusSandboxLiveExecClientFactory,
)
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.core.data import Data
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.portfolio.base import PortfolioFacade

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


class PolySignalSandboxExecutionClient(_NautilusSandboxExecutionClient):
    """Sandbox execution client that normalizes market-data precision.

    QuoteTick / OrderBookDelta prices are normalized to the current instrument
    before the Nautilus SimulatedExchange validates them.
    """

    def on_data(self, data: Data) -> None:
        if type(data).__name__ not in _MARKET_DATA_TYPES:
            super().on_data(data)
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

        normalized = cast(Data, normalize_market_data_to_instrument(data, instrument))
        super().on_data(normalized)

    def _instrument_for(self, instrument_id: object) -> Instrument | None:
        if not isinstance(instrument_id, InstrumentId):
            return None
        return self._cache.instrument(instrument_id)


class SandboxLiveExecClientFactory(_NautilusSandboxLiveExecClientFactory):
    """Factory that builds precision-safe sandbox execution clients."""

    @staticmethod
    def create(
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: SandboxExecutionClientConfig,
        portfolio: PortfolioFacade,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> PolySignalSandboxExecutionClient:
        client = PolySignalSandboxExecutionClient(
            loop=loop,
            portfolio=portfolio,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
        logger.debug("created precision-safe sandbox execution client for %s", name)
        return client


PolySignalSandboxLiveExecClientFactory = SandboxLiveExecClientFactory
