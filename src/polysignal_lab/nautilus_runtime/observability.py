from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.domain.paper_order import PaperFill
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult, PaperWalletSnapshot
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.execution import PaperExecutionResult
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.utils import utc_now, utc_iso


class EventStore(Protocol):
    """Protocol for storing observability events."""

    def insert_json(self, table: str, data: Mapping[str, object]) -> None: ...
    def insert_many_json(self, table: str, rows: Sequence[Mapping[str, object]]) -> None: ...


class Notifier(Protocol):
    """Protocol for sending notifications."""

    async def send(self, message: str, msg_type: str = "") -> None: ...


class ObservabilityActor:
    """Receives typed events and writes them to SQLite + JSONL + health registry.

    Reuses existing PersistenceService patterns without Nautilus runtime dependency.
    """

    def __init__(
        self,
        store: EventStore | None = None,
        health: HealthRegistry | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        self.store = store
        self.health = health or HealthRegistry()
        self.notifier = notifier
        self._event_count = 0

    @property
    def event_count(self) -> int:
        return self._event_count

    # -- Event recording --

    def record_decision(self, decision: AlphaDecision, accepted: bool) -> None:
        self._event_count += 1
        if self.store is None:
            return
        self.store.insert_json("signals", {
            "ts": utc_iso(),
            "strategy": decision.strategy,
            "condition_id": decision.condition_id,
            "side": decision.side.value,
            "confidence": decision.confidence,
            "accepted": accepted,
            "reason_codes": list(decision.reason_codes),
        })

    def record_order(self, result: PaperExecutionResult) -> None:
        self._event_count += 1
        if self.store is None or result.order is None:
            return
        self.store.insert_json("orders", {
            "ts": utc_iso(),
            "order_id": result.order.paper_order_id,
            "token_id": result.order.token_id,
            "side": result.order.side.value,
            "price": result.order.limit_price,
            "quantity": result.order.stake_usdc,
            "status": result.status.value if result.status else "UNKNOWN",
            "strategy": result.order.strategy,
        })

    def record_fill(self, fill: PaperFill) -> None:
        self._event_count += 1
        if self.store is None:
            return
        self.store.insert_json("fills", {
            "ts": utc_iso(),
            "fill_id": fill.paper_fill_id,
            "order_id": fill.paper_order_id,
            "token_id": fill.token_id,
            "side": fill.side.value,
            "fill_price": fill.fill_price,
            "shares": fill.shares,
            "stake_usdc": fill.stake_usdc,
        })

    def record_position(self, position: PaperPosition) -> None:
        self._event_count += 1
        if self.store is None:
            return
        self.store.insert_json("positions", {
            "ts": utc_iso(),
            "position_id": position.paper_position_id,
            "market_id": position.market_id,
            "side": position.side.value,
            "entry_price": position.entry_price,
            "shares": position.shares,
            "stake_usdc": position.stake_usdc,
            "strategy": position.strategy,
        })

    def record_settlement(self, result: PaperTradeResult) -> None:
        self._event_count += 1
        if self.store is None:
            return
        self.store.insert_json("settlements", {
            "ts": utc_iso(),
            "position_id": result.paper_position_id,
            "strategy": result.strategy,
            "side": result.side.value,
            "outcome_value": result.outcome_value,
            "settlement_value": result.settlement_value,
            "pnl_usdc": result.pnl_usdc,
            "result": result.result.value,
            "exit_mode": result.exit_mode.value,
        })

    def record_health_snapshot(self) -> None:
        self._event_count += 1
        if self.store is None:
            return
        snapshot = self.health.snapshot()
        self.store.insert_json("health_snapshot", {
            "ts": snapshot.generated_at,
            "status": snapshot.status,
            "components": [c.as_dict() for c in snapshot.components],
        })

    # -- Notifications --

    async def notify_startup(self, strategy_names: Sequence[str] = ()) -> None:
        if self.notifier is None:
            return
        msg = f"Nautilus runtime started — {len(strategy_names)} strategies loaded"
        self.health.mark_ok("observability_actor")
        await self.notifier.send(msg, "startup")

    async def notify_shutdown(self) -> None:
        if self.notifier is None:
            return
        await self.notifier.send("🛑 Nautilus runtime shutdown", "shutdown")

    async def notify_daily_report(self, summary: str) -> None:
        if self.notifier is None:
            return
        await self.notifier.send(summary, "daily_report")


class StrategyControl(Protocol):
    """Protocol for runtime strategy control used by Telegram."""

    def set_strategy_enabled(self, name: str, enabled: bool) -> None: ...
    def is_strategy_enabled(self, name: str) -> bool: ...
    def status_payload(self) -> dict[str, object]: ...


class DecisionPolicyControl:
    """Adapts DecisionPolicyActor to StrategyControl protocol."""

    def __init__(self, policy: DecisionPolicyActor) -> None:
        self._policy = policy

    def set_strategy_enabled(self, name: str, enabled: bool) -> None:
        self._policy.set_strategy_enabled(name, enabled)

    def is_strategy_enabled(self, name: str) -> bool:
        return name not in self._policy.disabled_strategies

    def status_payload(self) -> dict[str, object]:
        return {
            "disabled_strategies": sorted(str(s) for s in self._policy.disabled_strategies),
        }
