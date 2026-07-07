"""
Input: __future__, __future__.annotations, logging, collections.abc, collections.abc.Iterable, typing, typing.Any, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate
Output: SignalPipeline
Pos: Service Layer - Business logic

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from polysignal_lab.domain.signal import SignalCandidate


class SignalPipeline:
    name = "signal_pipeline"

    def __init__(
        self,
        strategies: list[Any],
        gate: Any,
        consensus: Any,
        persistence: Any | None,
        *,
        logger: logging.Logger | None = None,
        disabled_strategies: Iterable[str] = (),
        strategy_dependencies: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.strategies = strategies
        self.gate = gate
        self.consensus = consensus
        self.persistence = persistence
        self.disabled_strategies = set(disabled_strategies)
        self.strategy_dependencies = dict(strategy_dependencies or {})
        self.logger = logger or logging.getLogger("polysignal_lab.scheduler.signal_pipeline")

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def health(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": "ok",
            "metrics": {"strategies": len(self.strategies)},
        }

    def set_strategy_enabled(self, name: str, enabled: bool) -> None:
        if enabled:
            self.disabled_strategies.discard(name)
        else:
            self.disabled_strategies.add(name)

    def is_strategy_enabled(self, name: str) -> bool:
        return name not in self.disabled_strategies

    def set_strategy_dependencies(self, dependencies: dict[str, tuple[str, ...]]) -> None:
        self.strategy_dependencies = dict(dependencies)

    def skip_reason_for(self, name: str) -> str | None:
        if name in self.disabled_strategies:
            return "manual_disabled"
        for dependency_name in self.strategy_dependencies.get(name, ()):
            if dependency_name in self.disabled_strategies:
                return f"dependency_disabled:{dependency_name}"
        return None

    def evaluate_snapshot(self, snapshot: Any) -> list[SignalCandidate]:
        _ = snapshot
        raise RuntimeError(
            "SignalPipeline.evaluate_snapshot was removed; use Nautilus strategy callbacks"
        )

    def _persist_rejection(self, rejected: Any, snapshot: Any, strategy_name: str) -> None:
        if self.persistence is None:
            return
        try:
            self.persistence.append_log("rejected_signals", rejected)
            self.persistence.insert_rejected_signal(rejected)
        except Exception:
            market = getattr(snapshot, "market", None)
            self.logger.exception(
                "Failed to persist rejected signal for market %s strategy %s reason %s",
                getattr(market, "market_slug", "?"),
                strategy_name,
                getattr(rejected, "reason_code", "?"),
            )

    def _persist_inactive_strategy(self, snapshot: Any, strategy_name: str, reason: str) -> None:
        from polysignal_lab.strategies.readiness import StrategyMarketStatus

        market = getattr(snapshot, "market", None)
        status = StrategyMarketStatus(
            strategy=strategy_name,
            asset=getattr(market, "asset", "?"),
            timeframe=getattr(market, "timeframe", "?"),
            status="inactive",
            reason=reason,
        )
        self._persist_strategy_status(status, snapshot, strategy_name)


    def _persist_strategy_status(self, status: Any, snapshot: Any, strategy_name: str) -> None:
        if self.persistence is None:
            return
        try:
            self.persistence.append_log("strategy_status", status)
            self.persistence.insert_strategy_status(status)
        except Exception:
            market = getattr(snapshot, "market", None)
            self.logger.exception(
                "Failed to persist strategy status for market %s strategy %s status %s",
                getattr(market, "market_slug", "?"),
                strategy_name,
                getattr(status, "status", "?"),
            )