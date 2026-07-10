"""
Input: __future__, __future__.annotations, collections.abc, concurrent.futures, dataclasses, threading, polysignal_lab.domain.market
Output: MarketDiscoveryResult, MarketDiscoveryWorker
Pos: Nautilus runtime transport boundary

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock

from polysignal_lab.domain.market import Market


@dataclass(frozen=True, slots=True)
class MarketDiscoveryResult:
    epoch: int
    markets: tuple[Market, ...]
    error: str | None = None


class MarketDiscoveryWorker:
    """Single-thread boundary for blocking market discovery transport."""

    def __init__(self, refresh: Callable[[], Sequence[Market]]) -> None:
        self._refresh = refresh
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="polysignal-market-discovery",
        )
        self._future: Future[MarketDiscoveryResult] | None = None
        self._closed = False
        self._lock = Lock()

    def request(self, epoch: int) -> bool:
        with self._lock:
            if self._closed or self._future is not None:
                return False
            self._future = self._executor.submit(self._run, epoch)
            return True

    def take_result(self) -> MarketDiscoveryResult | None:
        with self._lock:
            future = self._future
            if future is None or not future.done():
                return None
            self._future = None
        return future.result()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            future = self._future
            self._future = None
        if future is not None:
            _ = future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, epoch: int) -> MarketDiscoveryResult:
        try:
            return MarketDiscoveryResult(
                epoch=epoch,
                markets=tuple(self._refresh()),
            )
        except Exception as exc:
            return MarketDiscoveryResult(
                epoch=epoch,
                markets=(),
                error=f"{type(exc).__name__}: {exc}",
            )
