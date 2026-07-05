from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module
from typing import TYPE_CHECKING, cast

from polysignal_lab.alpha.types import AlphaCore, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_bridge.state import decode_state, encode_state


def _load_strategy_base() -> type[object]:
    try:
        strategy_module: object = import_module("nautilus_trader.trading.strategy")
        strategy = cast(object, getattr(strategy_module, "Strategy"))
    except ModuleNotFoundError:
        return object
    return cast(type[object], strategy)


def is_nautilus_available() -> bool:
    return _load_strategy_base() is not object


_NautilusBaseRuntime = _load_strategy_base()

if TYPE_CHECKING:
    class _NautilusBase:
        def __init__(self) -> None: ...
else:
    _NautilusBase = _NautilusBaseRuntime


class PolySignalNautilusStrategy(_NautilusBase):
    def __init__(
        self,
        *,
        core: AlphaCore,
        assembler: MarketViewAssembler,
        condition_ids: Sequence[str],
        strategy_name: str,
    ) -> None:
        if _NautilusBaseRuntime is not object:
            super().__init__()
        self.core: AlphaCore = core
        self.assembler: MarketViewAssembler = assembler
        self.condition_ids: tuple[str, ...] = tuple(condition_ids)
        self.strategy_name: str = strategy_name
        self.submitted_intents: list[OrderIntentSpec] = []
        self.accepted_state: dict[str, str] = {}
        self.fill_state: dict[str, str] = {}
        self.cancel_state: dict[str, str] = {}
        self.migration_reasons: list[str] = []

    def on_start(self) -> None:
        for condition_id in self.condition_ids:
            _ = self.evaluate_condition(condition_id)

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

    @staticmethod
    def _event_order_id(event: object) -> str:
        fallback: object = getattr(event, "id", "unknown")
        value: object = getattr(event, "client_order_id", fallback)
        return str(value)

    def on_order_submitted(self, event: object) -> None:
        self.accepted_state[self._event_order_id(event)] = "submitted"

    def on_order_accepted(self, event: object) -> None:
        self.accepted_state[self._event_order_id(event)] = "accepted"

    def on_order_rejected(self, event: object) -> None:
        self.cancel_state[self._event_order_id(event)] = "rejected"

    def on_order_canceled(self, event: object) -> None:
        self.cancel_state[self._event_order_id(event)] = "canceled"

    def on_order_expired(self, event: object) -> None:
        self.cancel_state[self._event_order_id(event)] = "expired"

    def on_order_filled(self, event: object) -> None:
        self.fill_state[self._event_order_id(event)] = "filled"

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
        self.accepted_state = dict(cast(Mapping[str, str], payload.get("accepted_state", {})))
        self.fill_state = dict(cast(Mapping[str, str], payload.get("fill_state", {})))
        self.cancel_state = dict(cast(Mapping[str, str], payload.get("cancel_state", {})))
        self.migration_reasons = list(cast(Sequence[str], payload.get("migration_reasons", [])))
