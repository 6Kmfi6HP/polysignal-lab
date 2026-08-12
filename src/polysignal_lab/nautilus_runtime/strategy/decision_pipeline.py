from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, SupportsFloat, cast

from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    BatchArbitrationResult,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.native_order import (
    OrderSubmittingStrategy,
    submit_approved_decision,
)
from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module
from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision

_pyo3 = load_nautilus_module("nautilus_trader.core.nautilus_pyo3")
AccountId = _pyo3.AccountId
Venue = _pyo3.Venue

logger = logging.getLogger(__name__)


class DecisionPolicyPort(Protocol):
    def batch_arbitrate(
        self, decisions: list[tuple[AlphaDecision, MarketView]]
    ) -> BatchArbitrationResult: ...


class _NativeTelemetryStrategy(Protocol):
    def _record_signal(self, signal: object) -> None: ...
    def _notify_accepted_signal(self, signal: object) -> None: ...
    def _record_decision(self, decision: AlphaDecision, *, accepted: bool) -> None: ...
    def _record_rejected(self, rejected: RejectedDecision) -> None: ...
    def _note_runtime_progress(self, event: str) -> None: ...


class OrderSubmitter(Protocol):
    def submit(self, approved: ApprovedDecision, view: MarketView) -> object: ...


class BalanceReader(Protocol):
    """Reads free cash available for new orders, in the strategy's base currency."""

    def read_free_balance(self) -> float | None: ...


@dataclass(slots=True)
class NautilusCashBalanceReader:
    """Reads the account's free base-currency balance from the Nautilus Cache.

    Uses ``cache.account(account_id)`` (native Cache API) or falls back to
    ``cache.account_for_venue(venue)``; both return ``None`` when the account
    has not arrived yet, which the preflight treats as fail-closed. ``base_currency``
    defaults to the settings value (pUSD in sandbox).

    ``cache`` may be a Cache instance or a zero-arg callable resolving the Cache
    lazily. The latter is required when the reader is bound before the strategy
    registers with its Trader (the ``cache`` property is unavailable until then),
    so production wiring passes a resolver while tests pass a concrete fake.
    """

    cache: object
    account_id: str = "POLYMARKET-001"
    base_currency: str = "pUSD"
    venue: str = "POLYMARKET"

    def read_free_balance(self) -> float | None:
        account = self._account()
        if account is None:
            return None
        balances = _account_balances(account)
        if balances is None:
            return None
        for key, balance in _balance_items(balances):
            if _balance_currency(key, balance) != self.base_currency:
                continue
            free = getattr(balance, "free", None)
            if callable(free):
                free = free()
            return _to_float(free)
        return None

    def _resolve_cache(self) -> object | None:
        cache = self.cache
        if callable(cache):
            try:
                return cache()
            except (TypeError, LookupError):
                return None
        return cache

    def _account(self) -> object | None:
        cache = self._resolve_cache()
        if cache is None:
            return None
        account = getattr(cache, "account", None)
        if callable(account):
            try:
                found = account(AccountId(self.account_id))
            except (TypeError, LookupError):
                found = None
            if found is not None:
                return found
        venue_lookup = getattr(cache, "account_for_venue", None)
        if callable(venue_lookup):
            try:
                return venue_lookup(Venue(self.venue))
            except (TypeError, LookupError):
                return None
        return None


def _account_balances(account: object) -> object | None:
    balances = getattr(account, "balances", None)
    if callable(balances):
        balances = balances()
    return balances


def _balance_items(balances: object) -> Sequence[tuple[object, object]]:
    items = getattr(balances, "items", None)
    if callable(items):
        return list(cast(Sequence[tuple[object, object]], items()))
    if isinstance(balances, Sequence) and not isinstance(balances, (str, bytes)):
        return [(getattr(balance, "currency", None), balance) for balance in balances]
    return ()


def _balance_currency(key: object, balance: object) -> str:
    currency = getattr(key, "code", key)
    if callable(currency):
        currency = currency()
    if currency is None or currency is balance:
        currency = getattr(balance, "currency", None)
        if callable(currency):
            currency = currency()
    return str(currency)


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    for name in ("as_double", "as_decimal"):
        numeric = getattr(value, name, None)
        if callable(numeric):
            try:
                parsed = _to_float(numeric())
            except (TypeError, ValueError):
                continue
            if parsed is not None:
                return parsed
    coerced = (
        value
        if isinstance(value, (int, float, str, bytes, bytearray))
        else cast(SupportsFloat, value)
    )
    try:
        return float(coerced)
    except (TypeError, ValueError):
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None


class DecisionTelemetry(Protocol):
    def accepted(self, approved: ApprovedDecision, order: object) -> None: ...
    def rejected(self, rejected: RejectedDecision, decision: AlphaDecision) -> None: ...
    def progress(self, event: str) -> None: ...


def _cash_balance_unavailable_rejection(
    approved: ApprovedDecision,
    log_extra: Mapping[str, object] | None,
    view_id: str,
) -> RejectedDecision:
    decision = approved.decision
    extra = dict(log_extra or {})
    extra.update(
        {
            "balance_unavailable": True,
            "skip_reason": "free balance unavailable",
            "signal_id": decision.signal_id(view_id),
        }
    )
    logger.warning("order_skipped_cash_balance_unavailable", extra=extra)
    return RejectedDecision(
        reason_code="INSUFFICIENT_CASH_BALANCE",
        detail={
            "free_balance_usdc": None,
            "notional_usdc": None,
            "reason": "free balance unavailable",
        },
        decision=decision,
        publish=approved.publish,
    )


def _insufficient_cash_rejection(
    approved: ApprovedDecision,
    log_extra: Mapping[str, object] | None,
    free_balance: float,
    notional: float,
    view_id: str,
) -> RejectedDecision:
    decision = approved.decision
    rounded_free = round(free_balance, 6)
    rounded_notional = round(notional, 6)
    extra = dict(log_extra or {})
    extra.update(
        {
            "free_balance_usdc": rounded_free,
            "notional_usdc": rounded_notional,
            "signal_id": decision.signal_id(view_id),
        }
    )
    logger.warning("order_skipped_insufficient_cash_balance", extra=extra)
    return RejectedDecision(
        reason_code="INSUFFICIENT_CASH_BALANCE",
        detail={
            "free_balance_usdc": rounded_free,
            "notional_usdc": rounded_notional,
            "reason": "free balance below order notional",
        },
        decision=decision,
        publish=approved.publish,
    )


def default_cash_preflight(
    balance_reader: BalanceReader,
    base_currency: str,
    *,
    fixed_stake_usdc: float,
    log_extra: Mapping[str, object] | None = None,
) -> Callable[[ApprovedDecision, MarketView], RejectedDecision | None]:
    """Build the default balance preflight: reject orders whose notional exceeds
    the free cash balance.

    Reduce-only orders are exempt (closing a position collects cash rather than
    spending it). If the free balance cannot be read, we fail closed — skip the
    order rather than risk another cash rejection — and log the ambiguity once
    per decision. ``log_extra`` lets the caller stamp runtime/strategy context.
    ``fixed_stake_usdc`` mirrors the strategy's stake so quantity resolves the
    same way the real order path does.
    """

    def preflight(
        approved: ApprovedDecision, view: MarketView
    ) -> RejectedDecision | None:
        decision = approved.decision
        if decision.reduce_only:
            return None
        free_balance = balance_reader.read_free_balance()
        if free_balance is None:
            return _cash_balance_unavailable_rejection(
                approved, log_extra, view.view_id
            )
        book = view.book_for(decision.side)
        spec = order_spec_from_decision(
            decision,
            fixed_stake_usdc=fixed_stake_usdc,
            best_ask=book.best_ask,
            best_bid=getattr(book, "best_bid", None),
            view_id=view.view_id,
        )
        notional = spec.quantity * spec.price
        if free_balance >= notional:
            return None
        return _insufficient_cash_rejection(
            approved, log_extra, free_balance, notional, view.view_id
        )

    return preflight


@dataclass(slots=True)
class NautilusOrderSubmitter:
    strategy: OrderSubmittingStrategy[object]
    fixed_stake_usdc: float
    instrument_id_resolver: Callable[[str], object]
    now: Callable[[], datetime] | None = None
    use_native_reduce_only: bool = False
    cash_preflight: Callable[[ApprovedDecision, MarketView], RejectedDecision | None] | None = None

    def submit(self, approved: ApprovedDecision, view: MarketView) -> object:
        if self.cash_preflight is not None:
            rejected = self.cash_preflight(approved, view)
            if rejected is not None:
                raise _CashPreflightRejection(rejected)
        book = view.book_for(approved.decision.side)
        return submit_approved_decision(
            self.strategy,
            approved,
            fixed_stake_usdc=self.fixed_stake_usdc,
            best_ask=book.best_ask,
            best_bid=getattr(book, "best_bid", None),
            instrument_id_resolver=self.instrument_id_resolver,
            now=self.now,
            view_id=view.view_id,
            use_native_reduce_only=self.use_native_reduce_only,
        )


class _CashPreflightRejection(Exception):
    """Raised inside OrderSubmitter.submit to reject before order construction."""

    def __init__(self, rejected: RejectedDecision) -> None:
        super().__init__("insufficient cash for order")
        self.rejected = rejected


def _order_mapping_rejection(
    approved: ApprovedDecision,
    exc: ValueError,
) -> RejectedDecision:
    return RejectedDecision(
        reason_code="ORDER_MAPPING_FAILED",
        detail={"error": str(exc)},
        decision=approved.decision,
        publish=approved.publish,
    )


@dataclass(slots=True)
class NativeDecisionTelemetry:
    strategy: _NativeTelemetryStrategy

    def accepted(self, approved: ApprovedDecision, order: object) -> None:
        _ = order
        self.strategy._record_signal(approved.publish)
        self.strategy._notify_accepted_signal(approved.publish)
        self.strategy._record_decision(approved.decision, accepted=True)

    def rejected(self, rejected: RejectedDecision, decision: AlphaDecision) -> None:
        self.strategy._record_decision(decision, accepted=False)
        self.strategy._record_rejected(rejected)

    def progress(self, event: str) -> None:
        self.strategy._note_runtime_progress(event)


@dataclass(frozen=True, slots=True)
class SubmittedDecision:
    approved: ApprovedDecision
    order: object


@dataclass(slots=True)
class DecisionPipeline:
    policy: DecisionPolicyPort
    submitter: OrderSubmitter
    telemetry: DecisionTelemetry
    rejected_decisions: deque[RejectedDecision] = field(
        default_factory=lambda: deque(maxlen=1000)
    )

    def apply(
        self,
        decisions: Sequence[AlphaDecision],
        view: MarketView,
    ) -> list[SubmittedDecision | RejectedDecision]:
        if not decisions:
            return []
        arbitration = self.policy.batch_arbitrate(
            [(decision, view) for decision in decisions]
        )
        approved_by_id, rejected_by_id = _arbitration_results(arbitration)
        active_dedupe_keys = _active_dedupe_keys(view)
        return [
            self._apply_one(
                decision,
                view,
                approved_by_id=approved_by_id,
                rejected_by_id=rejected_by_id,
                active_dedupe_keys=active_dedupe_keys,
            )
            for decision in decisions
        ]

    def _apply_one(
        self,
        decision: AlphaDecision,
        view: MarketView,
        *,
        approved_by_id: Mapping[int, ApprovedDecision],
        rejected_by_id: Mapping[int, RejectedDecision],
        active_dedupe_keys: set[str],
    ) -> SubmittedDecision | RejectedDecision:
        """Resolve one decision. Rejections are recorded here; ``active_dedupe_keys``
        is mutated so later decisions in the same batch see this one in flight."""
        approved = approved_by_id.get(id(decision))
        if approved is None:
            return self._reject(
                rejected_by_id.get(id(decision))
                or RejectedDecision(
                    reason_code="ARBITRATION_SUPPRESSED",
                    detail={},
                    decision=decision,
                ),
                decision,
            )
        dedupe_key = approved.decision.dedupe_key()
        if dedupe_key in active_dedupe_keys:
            return self._reject(
                RejectedDecision(
                    reason_code="DUPLICATE_IN_FLIGHT_SIGNAL",
                    detail={"dedupe_key": dedupe_key},
                    decision=approved.decision,
                    publish=approved.publish,
                ),
                decision,
            )
        try:
            order = self.submitter.submit(approved, view)
        except _CashPreflightRejection as rejection:
            return self._reject(rejection.rejected, decision)
        except ValueError as exc:
            return self._reject(_order_mapping_rejection(approved, exc), decision)
        active_dedupe_keys.add(dedupe_key)
        self.telemetry.accepted(approved, order)
        return SubmittedDecision(approved=approved, order=order)

    def _reject(
        self, rejected: RejectedDecision, decision: AlphaDecision
    ) -> RejectedDecision:
        self.rejected_decisions.append(rejected)
        self.telemetry.rejected(rejected, decision)
        return rejected


def _arbitration_results(
    arbitration: BatchArbitrationResult,
) -> tuple[dict[int, ApprovedDecision], dict[int, RejectedDecision]]:
    return (
        {id(approved.decision): approved for approved in arbitration.approvals},
        {id(decision): rejected for decision, rejected in arbitration.rejections},
    )


def _active_dedupe_keys(view: MarketView) -> set[str]:
    return {
        order.dedupe_key
        for order in view.trading.orders
        if order.dedupe_key is not None and (order.is_open or order.is_inflight)
    }
