from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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


class NautilusEventStoreAdapter:
    """Adapts a PersistenceService-like object to the EventStore protocol."""

    def __init__(self, persistence: object) -> None:
        self.persistence = persistence
        self._routes: dict[str, Callable[[object], None]] = {
            "orders": persistence.insert_paper_order,
            "fills": persistence.insert_paper_fill,
            "positions": persistence.upsert_paper_position,
            "settlements": persistence.insert_paper_trade_result,
            "health_snapshot": persistence.insert_system_event,
            "system_events": persistence.insert_system_event,
        }

    def insert_json(self, table: str, data: Mapping[str, object]) -> None:
        route = self._routes.get(table)
        if route is None:
            raise ValueError(f"Unknown Nautilus event table: {table}")
        payload = dict(data)
        if table == "health_snapshot":
            payload.setdefault("event_type", "health_snapshot")
            payload.setdefault("severity", "info")
            payload.setdefault("created_at", payload.get("ts", utc_iso()))
            payload.setdefault("event_id", f"nautilus_health:{payload['created_at']}")
        route(payload)

    def insert_many_json(self, table: str, rows: Sequence[Mapping[str, object]]) -> None:
        for row in rows:
            self.insert_json(table, row)


class NautilusNotifierAdapter:
    """Adapts a publisher (e.g. TelegramPublisher) to the Notifier protocol."""

    def __init__(self, publisher: object) -> None:
        self.publisher = publisher

    async def send(self, message: str, msg_type: str = "") -> None:
        await self.publisher.send(message, msg_type)


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
        # Pass PaperOrder directly so sqlite_store.to_jsonable() extracts all fields
        self.store.insert_json("orders", {
            "paper_order_id": result.order.paper_order_id,
            "signal_id": result.order.signal_id or "",
            "strategy": result.order.strategy or "",
            "asset": result.order.asset or "",
            "timeframe": result.order.timeframe or "",
            "market_id": result.order.market_id or "",
            "token_id": result.order.token_id,
            "side": result.order.side.value,
            "price": result.order.limit_price,
            "quantity": result.order.stake_usdc,
            "status": result.status.value if result.status else "UNKNOWN",
            "created_at": result.order.created_at.isoformat() if hasattr(result.order.created_at, 'isoformat') else str(result.order.created_at),
        })

    async def notify_order_result(self, result: PaperExecutionResult) -> None:
        """Send a Telegram notification for a paper execution result."""
        if self.notifier is None or result.order is None:
            return
        strategy = result.order.strategy or "?"
        asset = result.order.asset or "?"
        side = result.order.side.value.upper() if hasattr(result.order.side, 'value') else str(result.order.side)
        price = result.order.limit_price
        status = result.status.value if result.status else "UNKNOWN"
        msg = (
            f"<b>{strategy}</b> — {asset} {side}\n"
            f"Price: {price}\n"
            f"Status: {status}"
        )
        await self.notifier.send(msg, "paper_order")

    def record_fill(self, fill: PaperFill) -> None:
        self._event_count += 1
        if self.store is None:
            return
        self.store.insert_json("fills", {
            "paper_fill_id": fill.paper_fill_id,
            "paper_order_id": fill.paper_order_id,
            "signal_id": fill.signal_id or "",
            "fill_price": fill.fill_price,
            "stake_usdc": fill.stake_usdc,
            "shares": fill.shares,
            "token_id": fill.token_id,
            "side": fill.side.value,
            "created_at": utc_iso(),
        })

    def record_position(self, position: PaperPosition) -> None:
        self._event_count += 1
        if self.store is None:
            return
        self.store.insert_json("positions", {
            "paper_position_id": position.paper_position_id,
            "signal_id": "",
            "strategy": position.strategy or "",
            "asset": "",
            "timeframe": "",
            "market_id": position.market_id or "",
            "side": position.side.value,
            "entry_price": position.entry_price,
            "shares": position.shares,
            "stake_usdc": position.stake_usdc,
            "status": "OPEN",
            "opened_at": utc_iso(),
        })

    def record_settlement(self, result: PaperTradeResult) -> None:
        self._event_count += 1
        if self.store is None:
            return
        self.store.insert_json("settlements", {
            "paper_trade_id": result.paper_trade_id,
            "signal_id": result.signal_id or "",
            "strategy": result.strategy or "",
            "asset": result.asset or "",
            "timeframe": result.timeframe or "",
            "market_id": result.market_id or "",
            "paper_position_id": result.paper_position_id,
            "side": result.side.value,
            "entry_price": result.entry_price,
            "shares": result.shares,
            "stake_usdc": result.stake_usdc,
            "outcome_value": result.outcome_value,
            "settlement_value": getattr(result, "settlement_value", 0.0),
            "pnl_usdc": getattr(result, "pnl_usdc", 0.0),
            "roi": getattr(result, "roi", 0.0),
            "result": getattr(result, "result", "").value if hasattr(getattr(result, "result", ""), "value") else str(getattr(result, "result", "")),
            "exit_mode": result.exit_mode.value,
            "closed_at": utc_iso(),
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
