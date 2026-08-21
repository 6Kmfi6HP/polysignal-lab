# Test-only stand-ins for nautilus_trader 1.x ``test_kit.stubs`` modules that
# were removed in 2.0 (upgrade migration, issue69 root fix). Mounted into
# ``sys.modules`` under the legacy paths by tests/conftest.py so existing test
# imports keep working unchanged.
#
# Implementations mirror the 1.x stubs with 2.0 pyo3 constructor signatures
# (new required kwargs: LimitOrder.quote_quantity, Order*Event.reconciliation).

from __future__ import annotations
# pyright: reportAttributeAccessIssue=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportExplicitAny=false, reportMissingParameterType=false, reportUnusedParameter=false

from typing import Any

from nautilus_trader._libnautilus import core
from nautilus_trader._libnautilus import model


class TestIdStubs:
    """Minimal 1.x TestIdStubs: deterministic, unique-enough test ids."""

    @staticmethod
    def trader_id() -> model.TraderId:
        return model.TraderId("TESTER-001")

    @staticmethod
    def strategy_id() -> model.StrategyId:
        return model.StrategyId("TESTER-001")

    @staticmethod
    def client_order_id() -> model.ClientOrderId:
        return model.ClientOrderId(f"O-{core.UUID4()}")

    @staticmethod
    def account_id() -> model.AccountId:
        return model.AccountId("TESTER-001-001")

    @staticmethod
    def venue_order_id() -> model.VenueOrderId:
        return model.VenueOrderId("1")

    @staticmethod
    def uuid() -> Any:
        return core.UUID4()


class TestExecStubs:
    @staticmethod
    def limit_order(
        instrument: Any = None,
        order_side: Any = None,
        price: Any = None,
        quantity: Any = None,
        time_in_force: Any = None,
        post_only: bool = False,
        reduce_only: bool = False,
        tags: list[str] | None = None,
    ) -> model.LimitOrder:
        assert instrument is not None
        return model.LimitOrder(
            trader_id=TestIdStubs.trader_id(),
            strategy_id=TestIdStubs.strategy_id(),
            instrument_id=instrument.id,
            client_order_id=TestIdStubs.client_order_id(),
            order_side=order_side or model.OrderSide.BUY,
            quantity=quantity or instrument.make_qty(100),
            price=price or instrument.make_price(55.0),
            time_in_force=time_in_force or model.TimeInForce.GTC,
            init_id=TestIdStubs.uuid(),
            ts_init=0,
            post_only=post_only,
            reduce_only=reduce_only,
            display_qty=None,
            contingency_type=model.ContingencyType.NO_CONTINGENCY,
            order_list_id=None,
            linked_order_ids=None,
            parent_order_id=None,
            tags=tags,
            quote_quantity=False,
        )


class TestEventsProviderPyo3:
    """1.x test_kit.rust.events_pyo3: standalone event factories."""

    @staticmethod
    def order_submitted() -> model.OrderSubmitted:
        return model.OrderSubmitted(
            trader_id=TestIdStubs.trader_id(),
            strategy_id=TestIdStubs.strategy_id(),
            instrument_id=model.InstrumentId.from_str("0x1-1.POLYMARKET"),
            client_order_id=TestIdStubs.client_order_id(),
            account_id=TestIdStubs.account_id(),
            ts_event=0,
            event_id=core.UUID4(),
            ts_init=0,
        )

    @staticmethod
    def order_accepted() -> model.OrderAccepted:
        return model.OrderAccepted(
            trader_id=TestIdStubs.trader_id(),
            strategy_id=TestIdStubs.strategy_id(),
            instrument_id=model.InstrumentId.from_str("0x1-1.POLYMARKET"),
            client_order_id=TestIdStubs.client_order_id(),
            venue_order_id=TestIdStubs.venue_order_id(),
            account_id=TestIdStubs.account_id(),
            ts_event=0,
            event_id=core.UUID4(),
            ts_init=0,
            reconciliation=False,
        )

    @staticmethod
    def order_updated() -> model.OrderUpdated:
        return model.OrderUpdated(
            trader_id=TestIdStubs.trader_id(),
            strategy_id=TestIdStubs.strategy_id(),
            instrument_id=model.InstrumentId.from_str("0x1-1.POLYMARKET"),
            client_order_id=TestIdStubs.client_order_id(),
            venue_order_id=TestIdStubs.venue_order_id(),
            account_id=TestIdStubs.account_id(),
            quantity=model.Quantity.from_str("1.5"),
            price=model.Price.from_str("1500.0"),
            ts_event=0,
            event_id=core.UUID4(),
            ts_init=0,
            reconciliation=False,
        )


class TestEventStubs:
    @staticmethod
    def order_submitted(
        order: Any,
        account_id: Any = None,
        ts_event: int = 0,
    ) -> model.OrderSubmitted:
        return model.OrderSubmitted(
            trader_id=order.trader_id,
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            account_id=account_id or TestIdStubs.account_id(),
            ts_event=ts_event,
            event_id=core.UUID4(),
            ts_init=0,
        )

    @staticmethod
    def order_accepted(
        order: Any,
        account_id: Any = None,
        venue_order_id: Any = None,
        ts_event: int = 0,
    ) -> model.OrderAccepted:
        return model.OrderAccepted(
            trader_id=order.trader_id,
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            venue_order_id=venue_order_id or TestIdStubs.venue_order_id(),
            account_id=account_id or TestIdStubs.account_id(),
            ts_event=ts_event,
            event_id=core.UUID4(),
            ts_init=0,
            reconciliation=False,
        )

    @staticmethod
    def order_filled(
        order: Any,
        instrument: Any,
        strategy_id: Any = None,
        account_id: Any = None,
        venue_order_id: Any = None,
        trade_id: Any = None,
        position_id: Any = None,
        last_qty: Any = None,
        last_px: Any = None,
        side: Any = None,
        liquidity_side: Any = model.LiquiditySide.TAKER,
        commission: Any = None,
        currency: Any = None,
        ts_event: int = 0,
    ) -> model.OrderFilled:
        return model.OrderFilled(
            trader_id=order.trader_id,
            strategy_id=strategy_id or order.strategy_id,
            instrument_id=instrument.id,
            client_order_id=order.client_order_id,
            venue_order_id=venue_order_id or TestIdStubs.venue_order_id(),
            account_id=account_id or TestIdStubs.account_id(),
            trade_id=trade_id or model.TradeId("E-1"),
            position_id=position_id or order.position_id,
            order_side=side or order.side,
            order_type=order.order_type,
            last_qty=last_qty or order.quantity,
            last_px=last_px,
            currency=currency or instrument.quote_currency,
            commission=commission
            or model.Money(0, currency or instrument.quote_currency),
            liquidity_side=liquidity_side,
            ts_event=ts_event,
            event_id=core.UUID4(),
            ts_init=0,
            reconciliation=False,
        )