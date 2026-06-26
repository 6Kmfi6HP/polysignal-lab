from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from polysignal_lab.app import scheduler_health, scheduler_market_data
from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
from polysignal_lab.nautilus_runtime.data_ingestor import NautilusDataIngestor
from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient
from polysignal_lab.nautilus_runtime.execution_types import PaperExecutionResult
from polysignal_lab.nautilus_runtime.observability import (
    ObservabilityActor,
    signal_candidate_from_order,
)
from polysignal_lab.nautilus_runtime.position_policy import PositionPolicyActor
from polysignal_lab.nautilus_runtime.settlement import SettlementActor
from polysignal_lab.nautilus_runtime.strategies.base import PolySignalNautilusStrategy
from polysignal_lab.observability.health import HealthRegistry


class NautilusOrchestrator:
    def __init__(
        self,
        *,
        scheduler: PolySignalScheduler,
        registered_strategies: Sequence[PolySignalNautilusStrategy],
        data_ingestor: NautilusDataIngestor,
        book_data_provider: NautilusBookDataProvider,
        paper_client: NautilusMatchingPaperExecutionClient,
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
        await self._phase_event_drain()
        await self._phase_resting_orders()
        if condition_ids:
            await self._phase_strategy_eval(condition_ids)
        await self._phase_event_drain()
        await self._phase_position_exits()
        await self._phase_settlement()
        await self._phase_daily_report()
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

    async def _phase_strategy_eval(
        self, condition_ids: Sequence[str]
    ) -> None:
        """Evaluate all registered strategies and record execution results."""
        for strategy in self.registered_strategies:
            try:
                batch = strategy.evaluate_all_conditions(condition_ids)
                for rejected in batch.rejected_decisions:
                    self.observability.record_rejected_decision(rejected)
                for result in batch.execution_results:
                    await self._record_execution_result(result)
                self.health.mark_ok(f"strategy_{strategy.strategy_name}")
            except Exception as exc:
                self.logger.exception(
                    "Strategy %s evaluation failed", strategy.strategy_name,
                )
                self.health.mark_degraded(
                    f"strategy_{strategy.strategy_name}",
                    reason=str(exc)[:200],
                )


    async def _phase_event_drain(self) -> None:
        """Drain pending execution events from the paper client."""
        try:
            drain = getattr(self.paper_client, "drain_events", None)
            if drain is not None:
                for result in drain():
                    await self._record_execution_result(result)
            self.health.mark_ok("event_drain")
        except Exception as exc:
            self.logger.exception("Execution event drain failed")
            self.health.mark_degraded("event_drain", reason=str(exc)[:200])

    async def _phase_resting_orders(self) -> None:
        """Process resting GTD orders."""
        try:
            process = getattr(self.paper_client, "process_resting_orders", None)
            if process is not None:
                for result in process():
                    await self._record_execution_result(result)
            self.health.mark_ok("resting_orders")
        except Exception as exc:
            self.logger.exception("Resting order processing failed")
            self.health.mark_degraded("resting_orders", reason=str(exc)[:200])

    async def _phase_position_exits(self) -> None:
        """Submit reduce-only exits for positions whose exit policy fires."""
        try:
            submit_exit = getattr(self.paper_client, "submit_exit", None)
            wallet = getattr(self.paper_client, "wallet", None)
            positions = getattr(wallet, "open_positions", {}) if wallet is not None else {}
            if submit_exit is not None:
                for position in list(positions.values()):
                    book = self.book_data_provider.snapshot_for_token(position.token_id)
                    bid_price = getattr(book, "bid", None) if book is not None else None
                    if bid_price is None and book is not None:
                        bid_price = getattr(book, "best_bid", None)
                    if bid_price is None:
                        continue
                    decision_position = (
                        position.model_copy(deep=True)
                        if hasattr(position, "model_copy")
                        else position
                    )
                    policy_wallet = getattr(self.position_policy, "wallet", None)
                    has_policy_wallet = hasattr(self.position_policy, "wallet")
                    if has_policy_wallet:
                        self.position_policy.wallet = None
                    try:
                        decision = self.position_policy.evaluate(
                            decision_position,
                            current_bid=bid_price,
                        )
                    finally:
                        if has_policy_wallet:
                            self.position_policy.wallet = policy_wallet
                    if decision is None:
                        continue
                    result = submit_exit(position, bid_price, _exit_reason(decision))
                    await self._record_execution_result(result)
            self.health.mark_ok("position_exits")
        except Exception as exc:
            self.logger.exception("Position exit processing failed")
            self.health.mark_degraded("position_exits", reason=str(exc)[:200])

    async def _phase_settlement(self) -> None:
        """Close paper positions through the legacy reporting pipeline."""
        try:
            await self.scheduler.check_settlements()
            self.health.mark_ok("settlement")
        except Exception as exc:
            self.logger.exception("Settlement check failed")
            self.health.mark_degraded("settlement", reason=str(exc)[:200])

    async def _phase_daily_report(self) -> None:
        """Generate/publish the daily paper report through scheduler reporting."""
        try:
            await self.scheduler.generate_daily_report()
            self.health.mark_ok("daily_report")
        except Exception as exc:
            self.logger.exception("Daily report generation failed")
            self.health.mark_degraded("daily_report", reason=str(exc)[:200])

    def _phase_health(self) -> None:
        """Record a health snapshot."""
        try:
            self.health.mark_ok("orchestrator")
            self.observability.record_health_snapshot()
        except Exception as exc:
            self.logger.exception("Health recording failed")

    # ── Helpers ────────────────────────────────────────────────────────────

    async def _record_execution_result(self, result: PaperExecutionResult) -> None:
        """Record an execution result's signal, order, fills, and positions."""
        if result.order is not None and not result.order.reduce_only:
            self.observability.record_signal_from_order(result.order)
            await self._publish_signal_from_order(result.order)
        self.observability.record_order(result)
        for fill in result.fills:
            self.observability.record_fill(fill)
        for position in result.positions:
            self.observability.record_position(position)

    async def _publish_signal_from_order(self, order) -> None:
        if not getattr(self.scheduler.settings.telegram, "send_signals", False):
            return
        try:
            signal = signal_candidate_from_order(order)
            stake = getattr(self.scheduler.settings.paper_trading, "fixed_stake_usdc", order.stake_usdc)
            publish = await self.scheduler.publish_service.publish_signal(signal, stake)
            scheduler_health.note_publish_result(self.scheduler, publish.as_dict())
        except Exception:
            self.logger.exception("Failed to publish accepted signal")


def _exit_reason(decision: object) -> str:
    details = getattr(decision, "details", None)
    if isinstance(details, dict) and details.get("exit_mode") is not None:
        return str(details["exit_mode"])
    mode = getattr(decision, "exit_mode", None)
    value = getattr(mode, "value", mode)
    return str(value or "POSITION_EXIT")
