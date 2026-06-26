from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult, PaperWalletSnapshot
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.execution_types import PaperExecutionResult
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.utils import utc_now, utc_iso


def signal_candidate_from_order(order: PaperOrder) -> SignalCandidate:
    """Rebuild the accepted signal payload from the paper order metadata."""
    metrics = dict(order.metrics)
    signal = SignalCandidate.build(
        strategy=order.strategy or str(metrics.get("strategy", "")),
        asset=order.asset or str(metrics.get("asset", "")),
        timeframe=order.timeframe or str(metrics.get("timeframe", "")),
        market_id=order.market_id or str(metrics.get("market_id", "")),
        market_slug=order.market_slug or str(metrics.get("market_slug", "")),
        condition_id=str(metrics.get("condition_id", "")),
        token_id=order.token_id,
        side=order.side,
        confidence=_metric_float(metrics, "confidence", order.signal_confidence or 0.0),
        entry_reference_price=_metric_float(
            metrics, "entry_reference_price", order.reference_price
        ),
        max_entry_price=_metric_float(metrics, "max_entry_price", order.limit_price),
        seconds_to_close=_metric_int(metrics, "seconds_to_close"),
        data_freshness_ms=_metric_int(metrics, "data_freshness_ms"),
        reason_codes=_metric_list(metrics, "reason_codes"),
        metrics=metrics,
        order_intent=order.order_intent,
        expiry_seconds=_metric_int(metrics, "expire_seconds"),
        pair_id=order.pair_id,
        hedge_leg=order.hedge_leg,
    )
    updates: dict[str, object] = {"created_at": order.created_at}
    if order.signal_id:
        updates["signal_id"] = order.signal_id
    return signal.model_copy(update=updates)


def _metric_float(metrics: Mapping[str, object], key: str, default: float) -> float:
    try:
        return float(metrics.get(key, default))
    except (TypeError, ValueError):
        return default


def _metric_int(metrics: Mapping[str, object], key: str) -> int | None:
    value = metrics.get(key)
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _metric_list(metrics: Mapping[str, object], key: str) -> list[str]:
    value = metrics.get(key)
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [part for part in value.split("|") if part]
    if isinstance(value, Sequence):
        return [str(part) for part in value]
    return [str(value)]



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
            "signals": persistence.insert_signal,
            "rejected_signals": persistence.insert_rejected_signal,
            "orders": persistence.upsert_paper_order,
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

    def record_signal_from_order(self, order: PaperOrder) -> None:
        self._event_count += 1
        if self.store is None:
            return
        signal = signal_candidate_from_order(order)
        self.store.insert_json("signals", signal.model_dump(mode="json"))

    def record_rejected_decision(self, rejected: object) -> None:
        self._event_count += 1
        candidate = getattr(rejected, "candidate", None)
        if self.store is None or not isinstance(candidate, SignalCandidate):
            return
        self.store.insert_json(
            "rejected_signals",
            RejectedSignal(
                candidate=candidate,
                gate_name="nautilus_decision_policy",
                reason_code=str(getattr(rejected, "reason_code", "")),
                details=dict(getattr(rejected, "detail", {}) or {}),
            ).model_dump(),
        )

    def record_order(self, result: PaperExecutionResult) -> None:
        self._event_count += 1
        if self.store is None or result.order is None:
            return
        payload = result.order.model_dump(mode="json")
        payload["status"] = result.status.value if result.status else "UNKNOWN"
        self.store.insert_json("orders", payload)


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
            "metrics": dict(fill.metrics),
        })

    def record_position(self, position: PaperPosition) -> None:
        self._event_count += 1
        if self.store is None:
            return
        self.store.insert_json("positions", {
            "paper_position_id": position.paper_position_id,
            "signal_id": position.signal_id,
            "paper_order_id": position.paper_order_id,
            "paper_fill_id": position.paper_fill_id,
            "strategy": position.strategy or "",
            "asset": position.asset or "",
            "timeframe": position.timeframe or "",
            "market_id": position.market_id or "",
            "market_slug": position.market_slug or "",
            "token_id": position.token_id,
            "side": position.side,
            "entry_price": position.entry_price,
            "shares": position.shares,
            "stake_usdc": position.stake_usdc,
            "signal_confidence": position.signal_confidence,
            "signal_metrics": dict(position.signal_metrics),
            "status": position.status,
            "opened_at": position.opened_at,
            "closed_at": position.closed_at,
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

    async def notify_startup(
        self,
        strategy_names: Sequence[str] = (),
        *,
        paper_engine: str = "nautilus_matching",
        accuracy_mode: str = "depth_l2",
    ) -> None:
        msg = (
            f"Nautilus runtime started — {len(strategy_names)} strategies loaded — "
            f"paper_engine={paper_engine} accuracy_mode={accuracy_mode}"
        )
        self.health.mark_ok(
            "observability_actor",
            paper_engine=paper_engine,
            accuracy_mode=accuracy_mode,
        )
        if self.notifier is None:
            return
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
