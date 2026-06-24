from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from pydantic import JsonValue

from polysignal_lab.utils import new_id, utc_iso

ComponentStatus: TypeAlias = Literal["ok", "degraded", "down"]
MetricValue: TypeAlias = int | float | str | bool | None


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    name: str
    status: ComponentStatus
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error: str | None = None
    metrics: dict[str, MetricValue] = field(default_factory=dict)

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "status": self.status,
            "last_success_at": self.last_success_at,
            "last_error_at": self.last_error_at,
            "last_error": self.last_error,
            "metrics": self.metrics,
        }


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    status: ComponentStatus
    generated_at: str
    components: list[ComponentHealth]

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "status": self.status,
            "generated_at": self.generated_at,
            "components": [component.as_dict() for component in self.components],
        }


@dataclass
class HealthRegistry:
    components: dict[str, ComponentHealth] = field(default_factory=dict)
    _last_statuses: dict[str, ComponentStatus] = field(default_factory=dict)
    _pending_transitions: list[dict[str, JsonValue]] = field(default_factory=list)

    def mark_ok(self, name: str, **metrics: MetricValue) -> None:
        self._set(name, "ok", None, **metrics)

    def mark_degraded(self, name: str, error: str | None = None, **metrics: MetricValue) -> None:
        self._set(name, "degraded", error, **metrics)

    def mark_down(self, name: str, error: str | None = None, **metrics: MetricValue) -> None:
        self._set(name, "down", error, **metrics)

    def set(self, name: str, status: str, **details: MetricValue) -> None:
        normalized = status.lower()
        metrics = dict(details)
        error_detail = metrics.pop("last_error", None) or metrics.pop("error", None)
        if normalized == "ok":
            self.mark_ok(name, **metrics)
        elif normalized == "down":
            self.mark_down(name, str(error_detail or "down"), **metrics)
        else:
            self.mark_degraded(name, str(error_detail or "degraded"), **metrics)

    def inc_metric(self, name: str, metric: str, amount: int = 1) -> None:
        current = self.components.get(name)
        metrics = dict(current.metrics if current else {})
        metrics[metric] = int(metrics.get(metric) or 0) + amount
        status: ComponentStatus = current.status if current else "ok"
        self._set(name, status, current.last_error if current else None, **metrics)

    def set_metric(self, name: str, metric: str, value: MetricValue) -> None:
        current = self.components.get(name)
        metrics = dict(current.metrics if current else {})
        metrics[metric] = value
        status: ComponentStatus = current.status if current else "ok"
        self._set(name, status, current.last_error if current else None, **metrics)

    def snapshot(self) -> HealthSnapshot:
        statuses = [component.status for component in self.components.values()]
        if any(status == "down" for status in statuses):
            overall: ComponentStatus = "down"
        elif any(status == "degraded" for status in statuses):
            overall = "degraded"
        else:
            overall = "ok"
        return HealthSnapshot(
            status=overall,
            generated_at=utc_iso(),
            components=[self.components[name] for name in sorted(self.components)],
        )

    def consume_transition_events(self) -> list[dict[str, JsonValue]]:
        events = list(self._pending_transitions)
        self._pending_transitions.clear()
        return events

    def _set(self, name: str, status: ComponentStatus, error: str | None, **metrics: MetricValue) -> None:
        now = utc_iso()
        previous = self.components.get(name)
        merged_metrics = dict(previous.metrics if previous else {})
        merged_metrics.update(metrics)
        component = ComponentHealth(
            name=name,
            status=status,
            last_success_at=now if status == "ok" else (previous.last_success_at if previous else None),
            last_error_at=now if status != "ok" else (previous.last_error_at if previous else None),
            last_error=error if status != "ok" else None,
            metrics=merged_metrics,
        )
        self.components[name] = component
        if self._last_statuses.get(name) != status:
            self._last_statuses[name] = status
            severity = "ERROR" if status == "down" else "WARNING" if status == "degraded" else "INFO"
            self._pending_transitions.append(
                {
                    "event_id": new_id("health"),
                    "event_type": "component_health_transition",
                    "severity": severity,
                    "created_at": now,
                    "component": name,
                    "status": status,
                    "last_error": component.last_error,
                    "metrics": component.metrics,
                }
            )
