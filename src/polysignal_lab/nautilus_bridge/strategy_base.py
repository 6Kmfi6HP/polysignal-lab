from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from typing import Any, cast

from polysignal_lab.alpha.types import AlphaCore, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_bridge.state import decode_state, encode_state


def _load_strategy_base() -> type:
    try:
        Strategy = cast(type, getattr(import_module("nautilus_trader.trading.strategy"), "Strategy"))
    except ModuleNotFoundError:
        return object
    return Strategy


def is_nautilus_available() -> bool:
    return _load_strategy_base() is not object


_NautilusBase = _load_strategy_base()


class PolySignalNautilusStrategy(_NautilusBase):
    def __init__(
        self,
        *,
        core: AlphaCore,
        assembler: MarketViewAssembler,
        condition_ids: Sequence[str],
        strategy_name: str,
    ) -> None:
        if _NautilusBase is not object:
            super().__init__()
        self.core = core
        self.assembler = assembler
        self.condition_ids = tuple(condition_ids)
        self.strategy_name = strategy_name
        self.submitted_intents: list[OrderIntentSpec] = []
        self.accepted_state: dict[str, str] = {}
        self.fill_state: dict[str, str] = {}
        self.cancel_state: dict[str, str] = {}
        self.migration_reasons: list[str] = []

    def on_start(self) -> None:
        for condition_id in self.condition_ids:
            self.evaluate_condition(condition_id)

    def evaluate_condition(self, condition_id: str) -> list[OrderIntentSpec]:
        view = self.assembler.build(condition_id)
        if view is None:
            return []
        intents = [
            decision.order_intent or OrderIntentSpec(intent=OrderIntent.PASSIVE_GTD)
            for decision in self.core.evaluate(view)
        ]
        self.submitted_intents.extend(intents)
        return intents

    def on_order_submitted(self, event: Any) -> None:
        self.accepted_state[str(getattr(event, "client_order_id", getattr(event, "id", "unknown")))] = "submitted"

    def on_order_accepted(self, event: Any) -> None:
        self.accepted_state[str(getattr(event, "client_order_id", getattr(event, "id", "unknown")))] = "accepted"

    def on_order_rejected(self, event: Any) -> None:
        self.cancel_state[str(getattr(event, "client_order_id", getattr(event, "id", "unknown")))] = "rejected"

    def on_order_canceled(self, event: Any) -> None:
        self.cancel_state[str(getattr(event, "client_order_id", getattr(event, "id", "unknown")))] = "canceled"

    def on_order_expired(self, event: Any) -> None:
        self.cancel_state[str(getattr(event, "client_order_id", getattr(event, "id", "unknown")))] = "expired"

    def on_order_filled(self, event: Any) -> None:
        self.fill_state[str(getattr(event, "client_order_id", getattr(event, "id", "unknown")))] = "filled"

    def on_save(self) -> dict[str, bytes]:
        return encode_state(
            self.strategy_name,
            {
                "accepted_state": self.accepted_state,
                "fill_state": self.fill_state,
                "cancel_state": self.cancel_state,
                "migration_reasons": self.migration_reasons,
            },
        )

    def on_load(self, state: dict[str, bytes]) -> None:
        payload = decode_state(self.strategy_name, state)
        self.accepted_state = dict(payload.get("accepted_state", {}))
        self.fill_state = dict(payload.get("fill_state", {}))
        self.cancel_state = dict(payload.get("cancel_state", {}))
        self.migration_reasons = list(payload.get("migration_reasons", []))
