from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from polysignal_lab.app import scheduler_market_data
from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
from polysignal_lab.nautilus_runtime.data_ingestor import NautilusDataIngestor
from polysignal_lab.nautilus_runtime.execution import (
    PaperExecutionResult,
    PolySignalPaperExecutionClient,
)
from polysignal_lab.nautilus_runtime.observability import ObservabilityActor
from polysignal_lab.nautilus_runtime.position_policy import PositionPolicyActor
from polysignal_lab.nautilus_runtime.settlement import SettlementActor
from polysignal_lab.nautilus_runtime.strategies.base import (
    PolySignalNautilusStrategy,
    StrategyEvaluationBatch,
)
from polysignal_lab.observability.health import HealthRegistry


class NautilusOrchestrator:
    def __init__(
        self,
        *,
        scheduler: PolySignalScheduler,
        registered_strategies: Sequence[PolySignalNautilusStrategy],
        data_ingestor: NautilusDataIngestor,
        book_data_provider: NautilusBookDataProvider,
        paper_client: PolySignalPaperExecutionClient,
        position_policy: PositionPolicyActor,
        settlement_actor: SettlementActor,
        observability: ObservabilityActor,
        health: HealthRegistry,
        refresh_interval_sec: float,
        logger: logging.Logger | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.registered_strategies = list(registered_strategies)
        self.data_ingestor = data_ingestor
        self.book_data_provider = book_data_provider
        self.paper_client = paper_client
        self.position_policy = position_policy
        self.settlement_actor = settlement_actor
        self.observability = observability
        self.health = health
        self.refresh_interval_sec = refresh_interval_sec
        self.logger = logger or logging.getLogger(__name__)
        self._stop = asyncio.Event()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def stop(self) -> None:
        self._stop.set()

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        try:
            while not self._stop.is_set() and not (
                stop_event is not None and stop_event.is_set()
            ):
                await self.run_once()
                waiters = [asyncio.create_task(self._stop.wait())]
                if stop_event is not None:
                    waiters.append(asyncio.create_task(stop_event.wait()))
                done, pending = await asyncio.wait(
                    waiters,
                    timeout=self.refresh_interval_sec,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    task.result()
        except asyncio.CancelledError:
            raise
        finally:
            await self.observability.notify_shutdown()

    # ── Single cycle ───────────────────────────────────────────────────────

    async def run_once(self) -> None:
        await self._phase_market_refresh()
        condition_ids = self._phase_sync()
        if condition_ids:
            self._phase_strategy_eval(condition_ids)
        self._phase_position_policy()
        await self._phase_settlement()
        self._phase_health()

    # ── Phases ─────────────────────────────────────────────────────────────

    async def _phase_market_refresh(self) -> None:
        """Refresh market metadata from discovery."""
        try:
            await scheduler_market_data.refresh_markets_once(self.scheduler)
            self.health.mark_ok("market_refresh")
        except Exception as exc:
            self.logger.exception("Market refresh failed")
            self.health.mark_down("market_refresh", reason=str(exc)[:200])

    def _phase_sync(self) -> tuple[str, ...]:
        """Sync bridge registries, orderbooks, spots, PTB.

        Returns active condition IDs for the strategy evaluation phase.
        """
        try:
            ids = self.data_ingestor.sync_all()
            self.health.mark_ok("data_sync")
            return ids
        except Exception as exc:
            self.logger.exception("Data sync failed")
            self.health.mark_down("data_sync", reason=str(exc)[:200])
            return ()

    def _phase_strategy_eval(
        self, condition_ids: Sequence[str]
    ) -> None:
        """Evaluate all registered strategies and record execution results."""
        for strategy in self.registered_strategies:
            try:
                batch = strategy.evaluate_all_conditions(condition_ids)
                for result in batch.execution_results:
                    self._record_execution_result(result)
                self.health.mark_ok(f"strategy_{strategy.strategy_name}")
            except Exception as exc:
                self.logger.exception(
                    "Strategy %s evaluation failed", strategy.strategy_name,
                )
                self.health.mark_degraded(
                    f"strategy_{strategy.strategy_name}",
                    reason=str(exc)[:200],
                )

    def _phase_position_policy(self) -> None:
        """Evaluate open positions for exit conditions."""
        try:
            open_positions = self.paper_client.wallet.open_positions
            for token_id, position in open_positions.items():
                snapshot = self.book_data_provider.snapshot_for_token(token_id)
                current_bid = snapshot.bid if snapshot is not None else None
                exit_result = self.position_policy.evaluate(
                    position, current_bid=current_bid,
                )
                if exit_result is not None:
                    self.observability.record_settlement(exit_result)
            self.health.mark_ok("position_policy")
        except Exception as exc:
            self.logger.exception("Position policy evaluation failed")
            self.health.mark_degraded(
                "position_policy", reason=str(exc)[:200],
            )

    async def _phase_settlement(self) -> None:
        """Resolve open positions against their markets."""
        try:
            markets = self.scheduler.ctx.markets.markets
            results = await self.settlement_actor.periodic_check(markets)
            for result in results:
                self.observability.record_settlement(result)
            self.health.mark_ok("settlement")
        except Exception as exc:
            self.logger.exception("Settlement check failed")
            self.health.mark_degraded("settlement", reason=str(exc)[:200])

    def _phase_health(self) -> None:
        """Record a health snapshot."""
        try:
            self.health.mark_ok("orchestrator")
            self.observability.record_health_snapshot()
        except Exception as exc:
            self.logger.exception("Health recording failed")

    # ── Helpers ────────────────────────────────────────────────────────────

    def _record_execution_result(self, result: PaperExecutionResult) -> None:
        """Record an execution result's order, fills, and positions."""
        self.observability.record_order(result)
        for fill in result.fills:
            self.observability.record_fill(fill)
        for position in result.positions:
            self.observability.record_position(position)
