"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, dataclasses, dataclasses.dataclass, typing, typing.Any, nautilus_trader.core, nautilus_trader.core.nautilus_pyo3
Output: ContractProbeConfig, ContractProbeStrategy
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nautilus_trader.core import nautilus_pyo3 as pyo3

@dataclass(frozen=True, slots=True)
class ContractProbeConfig:
    instrument_id: str
    order_id_tag: str
    strategy_id: str
    quantity: str = "0.001000"
    auto_buy: bool = True
    auto_close_after_quotes: int = 0
    workflow_marker: str = ""


class ContractProbeStrategy(pyo3.Strategy):
    """Minimal Importable pyo3 Strategy used by runtime contract tests.

    Exercises Clock, quote DataEngine dispatch, order submit, and optional
    settlement close — the same class registers on BacktestEngine and LiveNode.
    """

    def __init__(self, config: ContractProbeConfig) -> None:
        order_id_tag = str(config.order_id_tag)
        instrument_id = pyo3.InstrumentId.from_str(str(config.instrument_id))
        super().__init__(
            pyo3.StrategyConfig(
                strategy_id=pyo3.StrategyId(str(config.strategy_id)),
                order_id_tag=order_id_tag,
            )
        )
        self._instrument_id = instrument_id
        self._quantity = str(config.quantity)
        self._auto_buy = bool(config.auto_buy)
        self._auto_close_after_quotes = int(config.auto_close_after_quotes)
        self._submitted = False
        self._close_requested = False
        self._quote_count = 0
        self.workflow_marker = str(config.workflow_marker)
        self.events: list[tuple[Any, ...]] = []
        self.clock_samples: list[int] = []

    def on_start(self) -> None:
        clock = self.clock
        ts = getattr(clock, "timestamp_ns", None)
        if callable(ts):
            self.clock_samples.append(int(ts()))
        self.subscribe_quotes(self._instrument_id)
        subscribe_instrument_close = getattr(self, "subscribe_instrument_close", None)
        if callable(subscribe_instrument_close):
            subscribe_instrument_close(self._instrument_id)

    def on_quote(self, tick: object) -> None:
        bid = getattr(tick, "bid_price", None)
        self._quote_count += 1
        self.events.append(("quote", float(bid) if bid is not None else None))
        if self._auto_buy and not self._submitted:
            self._submitted = True
            order = self.order_factory.market(
                instrument_id=self._instrument_id,
                order_side=pyo3.OrderSide.BUY,
                quantity=pyo3.Quantity.from_str(self._quantity),
            )
            self.submit_order(order)
            return
        if (
            self._auto_close_after_quotes > 0
            and self._quote_count >= self._auto_close_after_quotes
            and not self._close_requested
            and self._submitted
        ):
            self._close_requested = True
            self.close_all_positions(self._instrument_id)

    def on_order_accepted(self, event: object) -> None:
        self.events.append(("accepted", str(getattr(event, "client_order_id", ""))))

    def on_order_filled(self, event: object) -> None:
        last_qty = getattr(event, "last_qty", None)
        self.events.append(
            (
                "filled",
                str(getattr(event, "client_order_id", "")),
                float(last_qty) if last_qty is not None else None,
            )
        )

    def on_order_rejected(self, event: object) -> None:
        self.events.append(("rejected", str(getattr(event, "client_order_id", ""))))

    def on_position_opened(self, event: object) -> None:
        self.events.append(("pos_opened", str(getattr(event, "instrument_id", ""))))

    def on_position_closed(self, event: object) -> None:
        self.events.append(("pos_closed", str(getattr(event, "instrument_id", ""))))

    def on_instrument_close(self, event: object) -> None:
        self.events.append(("instr_close", str(getattr(event, "close_type", ""))))

    def on_save(self) -> dict[str, bytes]:
        return {"workflow_marker": self.workflow_marker.encode("utf-8")}

    def on_load(self, state: Mapping[str, bytes]) -> None:
        raw = state.get("workflow_marker")
        if isinstance(raw, (bytes, bytearray)):
            self.workflow_marker = raw.decode("utf-8")
