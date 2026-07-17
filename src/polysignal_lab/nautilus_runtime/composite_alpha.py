from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from polysignal_lab.alpha.types import (
    AlphaCore,
    AlphaDecision,
    AlphaFillEvent,
    AlphaOrderEvent,
    MarketGroupView,
    MarketView,
)


class CompositeAlphaCore:
    """Single strategy host that dispatches lifecycle events to alpha cores."""

    def __init__(self, cores: Mapping[str, AlphaCore]) -> None:
        self.cores = dict(cores)

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        decisions: list[AlphaDecision] = []
        for core in self.cores.values():
            decisions.extend(core.evaluate(view))
        return decisions

    def evaluate_group(self, view: MarketGroupView) -> list[AlphaDecision]:
        decisions: list[AlphaDecision] = []
        for core in self.cores.values():
            evaluator = getattr(core, "evaluate_group", None)
            if callable(evaluator):
                decisions.extend(evaluator(view))
        return decisions

    def _core_for_event(self, event: AlphaOrderEvent) -> AlphaCore | None:
        strategy = str(getattr(event, "strategy", "") or "")
        if strategy in self.cores:
            return self.cores[strategy]
        metrics = getattr(event, "metrics", {})
        if isinstance(metrics, Mapping):
            tagged = metrics.get("strategy") or metrics.get("alpha")
            if tagged is not None:
                return self.cores.get(str(tagged))
        return None

    def _route(self, method: str, event: AlphaOrderEvent) -> Any:
        core = self._core_for_event(event)
        handler = getattr(core, method, None) if core is not None else None
        return handler(event) if callable(handler) else ()

    def on_order_submitted(self, event: AlphaOrderEvent) -> None:
        self._route("on_order_submitted", event)

    def on_order_accepted(self, event: AlphaOrderEvent) -> None:
        self._route("on_order_accepted", event)

    def on_order_rejected(self, event: AlphaOrderEvent) -> None:
        self._route("on_order_rejected", event)

    def on_order_canceled(self, event: AlphaOrderEvent) -> None:
        self._route("on_order_canceled", event)

    def on_order_expired(self, event: AlphaOrderEvent) -> None:
        self._route("on_order_expired", event)

    def on_order_filled(self, event: AlphaFillEvent) -> list[AlphaDecision]:
        result = self._route("on_order_filled", event)
        return list(result) if result else []

    def save_state(self) -> dict[str, object]:
        return {
            name: core.save_state()
            for name, core in self.cores.items()
            if callable(getattr(core, "save_state", None))
        }

    def load_state(self, payload: Mapping[str, object]) -> None:
        for name, core in self.cores.items():
            state = payload.get(name)
            loader = getattr(core, "load_state", None)
            if isinstance(state, Mapping) and callable(loader):
                loader(state)
