from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, cast

from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.utils import utc_iso
from polysignal_lab.nautilus_runtime.projections import (
    project_fill_event,
    project_order_event,
    project_position,
)


class PersistenceWriter(Protocol):
    def insert_signal(self, signal: object) -> None: ...
    def insert_rejected_signal(self, rejected: object) -> None: ...
    def upsert_paper_order(self, order: object) -> None: ...
    def insert_paper_fill(self, fill: object) -> None: ...
    def upsert_paper_position(self, position: object) -> None: ...
    def insert_paper_trade_result(self, result: object) -> None: ...
    def insert_system_event(self, event: dict[str, object]) -> None: ...
    def append_log(self, stream: str, payload: object) -> None: ...


class Publisher(Protocol):
    async def send(self, message: str, message_type: str, signal_id: str | None = None) -> object: ...


class AcceptedSignalNotifier(Protocol):
    def __call__(self, signal: SignalCandidate, stake_usdc: float) -> None: ...


class PaperFillNotifier(Protocol):
    def __call__(self, payload: dict[str, object]) -> None: ...


class PaperFillMirror(Protocol):
    def __call__(self, payload: dict[str, object]) -> None: ...


def signal_candidate_from_order(order: PaperOrder) -> SignalCandidate:
    """Rebuild the accepted signal payload from the paper order metadata."""
    metrics = dict(cast(Mapping[str, object], order.metrics))
    signal = SignalCandidate.build(
        strategy=_text_or_fallback(cast(object, order.strategy), metrics.get("strategy", "")),
        asset=_text_or_fallback(cast(object, order.asset), metrics.get("asset", "")),
        timeframe=_text_or_fallback(cast(object, order.timeframe), metrics.get("timeframe", "")),
        market_id=_text_or_fallback(cast(object, order.market_id), metrics.get("market_id", "")),
        market_slug=_text_or_fallback(cast(object, order.market_slug), metrics.get("market_slug", "")),
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
        order_intent=_order_intent(order.order_intent),
        expiry_seconds=_metric_int(metrics, "expire_seconds"),
        pair_id=order.pair_id,
        hedge_leg=order.hedge_leg,
    )
    updates: dict[str, object] = {"created_at": order.created_at}
    if order.signal_id:
        updates["signal_id"] = order.signal_id
    return signal.model_copy(update=updates)


def _text_or_fallback(value: object, fallback: object) -> str:
    return str(value or fallback)


def _metric_float(metrics: Mapping[str, object], key: str, default: float) -> float:
    value = metrics.get(key, default)
    if not isinstance(value, (int, float, str)):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _metric_int(metrics: Mapping[str, object], key: str) -> int | None:
    value = metrics.get(key)
    if value in (None, "") or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(float(value))
    except ValueError:
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

def _order_intent(value: str | None) -> OrderIntent | None:
    if value is None:
        return None
    try:
        return OrderIntent(value)
    except ValueError:
        return None




class EventStore(Protocol):
    """Protocol for storing observability events."""

    def insert_json(self, table: str, data: Mapping[str, object]) -> None: ...
    def insert_many_json(self, table: str, rows: Sequence[Mapping[str, object]]) -> None: ...


class Notifier(Protocol):
    """Protocol for sending notifications."""

    async def send(self, message: str, msg_type: str = "") -> None: ...


def _event_identity(payload: Mapping[str, object]) -> str:
    for key in (
        "event_id",
        "trade_id",
        "paper_fill_id",
        "client_order_id",
        "paper_order_id",
        "position_id",
        "paper_position_id",
    ):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _system_event_id(table: str, payload: Mapping[str, object]) -> str:
    created_at = str(payload.get("created_at", ""))
    identity = _event_identity(payload)
    if identity:
        return f"{table}:{identity}:{created_at}"
    return f"{table}:{created_at}"


class NautilusEventStoreAdapter:
    """Adapts a PersistenceService-like object to the EventStore protocol."""

    def __init__(self, persistence: PersistenceWriter) -> None:
        self.persistence: PersistenceWriter = persistence
        self._routes: dict[str, Callable[[dict[str, object]], None]] = {
            "signals": persistence.insert_signal,
            "rejected_signals": persistence.insert_rejected_signal,
            "orders": persistence.upsert_paper_order,
            "fills": persistence.insert_paper_fill,
            "positions": persistence.upsert_paper_position,
            "settlements": persistence.insert_paper_trade_result,
            "health_snapshot": persistence.insert_system_event,
            "system_events": persistence.insert_system_event,
            "nautilus_decision": persistence.insert_system_event,
            "nautilus_order": persistence.insert_system_event,
            "nautilus_fill": persistence.insert_system_event,
            "nautilus_position": persistence.insert_system_event,
        }
        self._streams: dict[str, str] = {
            "signals": "signals",
            "rejected_signals": "rejected_signals",
            "orders": "paper_orders",
            "fills": "paper_fills",
            "positions": "paper_positions",
            "settlements": "paper_trade_results",
            "health_snapshot": "system_events",
            "system_events": "system_events",
            "nautilus_decision": "nautilus_decisions",
            "nautilus_order": "nautilus_orders",
            "nautilus_fill": "nautilus_fills",
            "nautilus_position": "nautilus_positions",
        }
        self._append_log: Callable[[str, object], None] | None = persistence.append_log

    def insert_json(self, table: str, data: Mapping[str, object]) -> None:
        route = self._routes.get(table)
        if route is None:
            raise ValueError(f"Unknown Nautilus event table: {table}")
        payload = dict(data)
        if table == "health_snapshot":
            _ = payload.setdefault("event_type", "health_snapshot")
            _ = payload.setdefault("severity", "info")
            created_at = payload.get("ts") or utc_iso()
            _ = payload.setdefault("created_at", created_at)
            _ = payload.setdefault("event_id", _system_event_id("health_snapshot", payload))
        elif table.startswith("nautilus_"):
            _ = payload.setdefault("event_type", table)
            _ = payload.setdefault("severity", "info")
            created_at = payload.get("ts") or utc_iso()
            _ = payload.setdefault("created_at", created_at)
            _ = payload.setdefault("event_id", _system_event_id(table, payload))
        route(payload)
        if self._append_log is not None:
            self._append_log(self._streams[table], payload)

    def insert_many_json(self, table: str, rows: Sequence[Mapping[str, object]]) -> None:
        for row in rows:
            self.insert_json(table, row)


class NautilusNotifierAdapter:
    """Adapts a publisher (e.g. TelegramPublisher) to the Notifier protocol."""

    def __init__(self, publisher: Publisher) -> None:
        self.publisher: Publisher = publisher

    async def send(self, message: str, msg_type: str = "") -> None:
        _ = await self.publisher.send(message, msg_type)


# Per-tick evaluation re-emits the same rejected decision on every market data
# event (measured ~220/s during entry windows, ~1GB/day across SQLite + JSONL).
# Identical rejection records within this window are suppressed; accepted
# decisions are never suppressed.
REPEAT_SUPPRESS_TTL_SEC = 60.0


class ObservabilityActor:
    """Receives typed events and writes them to SQLite + JSONL + health registry.

    Reuses existing PersistenceService patterns without Nautilus runtime dependency.
    """

    def __init__(
        self,
        store: EventStore | None = None,
        health: HealthRegistry | None = None,
        notifier: Notifier | None = None,
        accepted_signal_notifier: AcceptedSignalNotifier | None = None,
        paper_fill_notifier: PaperFillNotifier | None = None,
        paper_fill_mirror: PaperFillMirror | None = None,
    ) -> None:
        self.store: EventStore | None = store
        self.health: HealthRegistry = health or HealthRegistry()
        self.notifier: Notifier | None = notifier
        self.accepted_signal_notifier: AcceptedSignalNotifier | None = (
            accepted_signal_notifier
        )
        self.paper_fill_notifier: PaperFillNotifier | None = paper_fill_notifier
        self.paper_fill_mirror: PaperFillMirror | None = paper_fill_mirror
        self._event_count: int = 0
        self._recent_rejections: dict[tuple[object, ...], float] = {}

    @property
    def event_count(self) -> int:
        return self._event_count

    def _suppress_repeat(self, key: tuple[object, ...]) -> bool:
        now = time.monotonic()
        last = self._recent_rejections.get(key)
        if last is not None and now - last < REPEAT_SUPPRESS_TTL_SEC:
            return True
        if len(self._recent_rejections) > 4096:
            cutoff = now - REPEAT_SUPPRESS_TTL_SEC
            self._recent_rejections = {
                k: t for k, t in self._recent_rejections.items() if t >= cutoff
            }
        self._recent_rejections[key] = now
        return False

    # -- Event recording --

    def record_decision(self, decision: AlphaDecision, accepted: bool) -> None:
        self._event_count += 1
        if self.store is None:
            return
        if not accepted and self._suppress_repeat((
            "decision",
            decision.strategy,
            decision.market_id,
            decision.side.value,
            tuple(decision.reason_codes),
        )):
            return
        self.store.insert_json("nautilus_decision", {
            "ts": utc_iso(),
            "strategy": decision.strategy,
            "asset": decision.asset,
            "timeframe": decision.timeframe,
            "market_id": decision.market_id,
            "market_slug": decision.market_slug,
            "condition_id": decision.condition_id,
            "token_id": decision.token_id,
            "side": decision.side.value,
            "confidence": decision.confidence,
            "accepted": accepted,
            "reason_codes": list(decision.reason_codes),
            "seconds_to_close": decision.seconds_to_close,
            "data_freshness_ms": decision.data_freshness_ms,
            "metrics": dict(decision.metrics),
        })

    def record_signal(self, signal: SignalCandidate) -> None:
        self._event_count += 1
        if self.store is None:
            return
        self.store.insert_json("signals", signal.model_dump(mode="json"))

    def record_signal_from_order(self, order: PaperOrder) -> None:
        self.record_signal(signal_candidate_from_order(order))

    def record_rejected_decision(self, rejected: object) -> None:
        self._event_count += 1
        candidate = getattr(rejected, "candidate", None)
        if self.store is None or not isinstance(candidate, SignalCandidate):
            return
        reason_code = str(getattr(rejected, "reason_code", ""))
        if self._suppress_repeat((
            "rejected",
            candidate.strategy,
            candidate.market_id,
            candidate.side.value,
            reason_code,
        )):
            return
        self.store.insert_json(
            "rejected_signals",
            RejectedSignal(
                candidate=candidate,
                gate_name="nautilus_decision_policy",
                reason_code=reason_code,
                details=dict(getattr(rejected, "detail", {}) or {}),
            ).model_dump(),
        )

    def record_order(self, result: object) -> None:
        self._event_count += 1
        order = getattr(result, "order", None)
        dump = getattr(order, "model_dump", None)
        if self.store is None or not callable(dump):
            return
        raw_payload = dump(mode="json")
        if not isinstance(raw_payload, Mapping):
            return
        payload = dict(cast(Mapping[str, object], raw_payload))
        status = cast(object, getattr(result, "status", None))
        payload["status"] = getattr(status, "value", "UNKNOWN") if status is not None else "UNKNOWN"
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
            "result": result.result.value,
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

    def record_event(self, table: str, data: Mapping[str, object]) -> None:
        self._event_count += 1
        if self.store is None:
            return
        self.store.insert_json(table, data)

    def record_nautilus_order_event(self, event: object) -> None:
        self.record_event("nautilus_order", project_order_event(event))

    def record_nautilus_fill_event(self, event: object) -> None:
        self.record_event("nautilus_fill", project_fill_event(event))

    def record_nautilus_position(self, position: object) -> None:
        self.record_event("nautilus_position", project_position(position))

    def notify_accepted_signal(
        self,
        signal: SignalCandidate,
        stake_usdc: float,
    ) -> None:
        if self.accepted_signal_notifier is None:
            return
        self.accepted_signal_notifier(signal, stake_usdc)

    def notify_nautilus_paper_fill(self, payload: dict[str, object]) -> None:
        if self.paper_fill_notifier is None:
            return
        self.paper_fill_notifier(dict(payload))

    def mirror_nautilus_paper_fill(self, payload: dict[str, object]) -> None:
        if self.paper_fill_mirror is None:
            return
        self.paper_fill_mirror(dict(payload))

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
        self._policy: DecisionPolicyActor = policy

    def set_strategy_enabled(self, name: str, enabled: bool) -> None:
        self._policy.set_strategy_enabled(name, enabled)

    def is_strategy_enabled(self, name: str) -> bool:
        return name not in self._policy.disabled_strategies

    def status_payload(self) -> dict[str, object]:
        return {
            "disabled_strategies": sorted(str(s) for s in self._policy.disabled_strategies),
        }
