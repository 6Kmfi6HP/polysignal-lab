from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from polysignal_lab.alpha.types import AlphaCore, MarketView
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision, DecisionPolicyActor, RejectedDecision
from polysignal_lab.nautilus_runtime.native_order import submit_approved_decision

DEFAULT_NATIVE_DATA_NAMES = ("quote_ticks", "trade_ticks", "order_book_deltas")


class PolySignalNativeStrategy:
    """Nautilus callback-shaped strategy wrapper around a PolySignal alpha core."""

    def __init__(
        self,
        *,
        core: AlphaCore,
        assembler: Any,
        condition_ids: Sequence[str],
        strategy_name: str,
        policy: DecisionPolicyActor | None = None,
        fixed_stake_usdc: float = 10.0,
        data_names: Sequence[str] = DEFAULT_NATIVE_DATA_NAMES,
        instrument_id_resolver: Callable[[str], Any] | None = None,
    ) -> None:
        self.core = core
        self.assembler = assembler
        self.condition_ids = tuple(condition_ids)
        self.strategy_name = strategy_name
        self.policy = policy or DecisionPolicyActor()
        self.fixed_stake_usdc = fixed_stake_usdc
        self.data_names = tuple(data_names)
        self.instrument_id_resolver = instrument_id_resolver or (lambda token_id: token_id)
        self.rejected_decisions: list[RejectedDecision] = []
        self.submitted_orders: list[Any] = []
        # Compatibility sentinels: native strategy never uses these paths.
        # Kept as empty containers so tests can assert the native path is clean.
        self.submitted_specs: list[Any] = []
        self.execution_results: list[Any] = []

    def on_start(self) -> None:
        for name in self.data_names:
            self.subscribe_data(name)

    def on_data(self, data: object) -> None:
        updater = getattr(self.assembler, "on_data", None) or getattr(self.assembler, "update", None)
        if callable(updater):
            updater(data)
        condition_id = getattr(data, "condition_id", None)
        if condition_id is not None:
            self.evaluate_condition(str(condition_id))
            return
        for candidate in self.condition_ids:
            self.evaluate_condition(candidate)

    def evaluate_condition(self, condition_id: str) -> None:
        view = self.assembler.build(condition_id)
        if view is None:
            return
        for decision in self.core.evaluate(view):
            policy_result = self.policy.evaluate(decision, view)
            if isinstance(policy_result, ApprovedDecision):
                order = self._submit_approved(policy_result, view=view)
                self.submitted_orders.append(order)
            else:
                self.rejected_decisions.append(policy_result)

    def _submit_approved(self, approved: ApprovedDecision, *, view: MarketView) -> Any:
        signal = approved.signal
        book = view.book_for(signal.side)
        return submit_approved_decision(
            self,
            approved,
            fixed_stake_usdc=self.fixed_stake_usdc,
            best_ask=book.best_ask,
            available_shares=_visible_ask_shares(book.ask_levels, signal.max_entry_price),
            instrument_id_resolver=self.instrument_id_resolver,
        )

    def subscribe_data(self, data_type: object) -> None:
        method = getattr(self, f"subscribe_{data_type}", None)
        if callable(method):
            for condition_id in self.condition_ids:
                method(condition_id)


def _visible_ask_shares(levels: Sequence[tuple[float, float]], limit_price: float | None) -> float | None:
    if not levels or limit_price is None:
        return None
    return sum(float(size) for price, size in levels if float(price) <= limit_price)
