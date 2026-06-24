from __future__ import annotations

import logging
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
    ) -> None:
        self.strategies = strategies
        self.gate = gate
        self.consensus = consensus
        self.persistence = persistence
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

    def evaluate_snapshot(self, snapshot: Any) -> list[SignalCandidate]:
        accepted: list[SignalCandidate] = []
        for strategy in self.strategies:
            strategy_name = strategy.name if hasattr(strategy, "name") else "?"
            try:
                for candidate in strategy.evaluate(snapshot):
                    decision = self.gate.evaluate(candidate, snapshot)
                    if decision.accepted and decision.signal:
                        strategy.notify_signal_accepted(decision.signal)
                        accepted.append(decision.signal)
                        consensus = self.consensus.add(decision.signal)
                        if consensus:
                            accepted.append(consensus)
                    elif decision.rejected:
                        strategy.notify_signal_rejected(
                            decision.rejected.candidate, decision.rejected
                        )
                        self._persist_rejection(decision.rejected, snapshot, strategy_name)
            except Exception:
                self.logger.exception("Strategy %s evaluate failed", strategy_name)
        return accepted

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
