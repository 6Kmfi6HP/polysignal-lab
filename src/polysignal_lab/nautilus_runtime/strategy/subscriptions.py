"""
Input: __future__, collections.abc, dataclasses, datetime, typing, polysignal_lab.domain.enums
Output: market subscription lifecycle and wire-operation helpers
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.strategy.helpers import (
    _asset_conditions,
    _instrument_ids,
    _nautilus_book_type,
    _nautilus_instrument_id,
)


_MAX_STALE_REFRESH_INTERVAL_SEC = 300
_REFRESH_BATCH_WINDOW = timedelta(seconds=1)
_RESUBSCRIBE_SETTLE_DELAY = timedelta(seconds=30)


@dataclass(slots=True)
class MarketSubscriptionState:
    """Track wire subscriptions separately from active-condition membership."""

    wire_condition_ids: set[str] = field(default_factory=set)
    pending_metadata_condition_ids: set[str] = field(default_factory=set)
    pending_subscribe_condition_ids: set[str] = field(default_factory=set)
    retained_wire_condition_ids: set[str] = field(default_factory=set)
    deferred_resubscribe_condition_ids: set[str] = field(default_factory=set)
    stale_refresh_attempts_by_condition: dict[str, int] = field(default_factory=dict)
    last_stale_refresh_at: dict[str, datetime] = field(default_factory=dict)
    awaiting_book_sides_by_condition: dict[str, set[Side]] = field(default_factory=dict)
    book_generation_started_at_by_condition: dict[str, datetime] = field(default_factory=dict)
    last_book_at_by_condition: dict[str, dict[Side, datetime]] = field(default_factory=dict)
    last_book_received_at_by_condition: dict[str, dict[Side, datetime]] = field(
        default_factory=dict
    )


class _SubscriptionStateOwner(Protocol):
    _subscription_state: MarketSubscriptionState


class _SubscriptionStrategy(Protocol):
    @property
    def registry(self) -> MarketCatalog | None: ...
    book_type: str
    unsubscribe_exited: bool
    _startup_condition_ids: tuple[str, ...]
    _active_condition_ids: set[str]
    _subscription_state: MarketSubscriptionState
    _asset_condition_ids: dict[str, tuple[str, ...]]

    def _readiness_detail(
        self,
        condition_id: str,
        *,
        now: datetime,
    ) -> dict[str, object]: ...

    def request_instrument(self, instrument_id: object) -> object: ...
    def subscribe_quote_ticks(self, instrument_id: object) -> object: ...
    def subscribe_trade_ticks(self, instrument_id: object) -> object: ...
    def subscribe_order_book_deltas(
        self, instrument_id: object, *, book_type: object
    ) -> object: ...
    def unsubscribe_quote_ticks(self, instrument_id: object) -> object: ...
    def unsubscribe_trade_ticks(self, instrument_id: object) -> object: ...
    def unsubscribe_order_book_deltas(self, instrument_id: object) -> object: ...


class MarketSubscriptionCoordinator:
    """Reset a shared venue subscription only after every strategy releases it."""

    def __init__(self) -> None:
        self._strategies: list[_SubscriptionStrategy] = []
        self._attempts_by_condition: dict[str, int] = {}
        self._last_refresh_at: dict[str, datetime] = {}
        self._ready_strategy_ids_by_condition: dict[str, set[int]] = {}
        self._resubscribe_not_before_by_condition: dict[str, datetime] = {}
        self._unsubscribe_not_before_by_condition: dict[str, datetime] = {}
        self._wire_restore_not_before_by_condition: dict[str, datetime] = {}
        self._wire_restore_strategy_ids_by_condition: dict[str, set[int]] = {}
        self._batch_refresh_condition_ids: set[str] = set()
        self._wire_restore_by_condition: dict[
            str,
            dict[int, tuple[bool, bool]],
        ] = {}

    def register(self, strategy: _SubscriptionStrategy) -> None:
        if all(candidate is not strategy for candidate in self._strategies):
            self._strategies.append(strategy)
        setattr(strategy, "_subscription_coordinator", self)

    def unregister(self, strategy: _SubscriptionStrategy) -> None:
        strategy_id = id(strategy)
        self._strategies = [
            candidate for candidate in self._strategies if candidate is not strategy
        ]
        affected_condition_ids = set(strategy._active_condition_ids)
        affected_condition_ids.update(
            strategy._subscription_state.deferred_resubscribe_condition_ids
        )
        for condition_id, ready_ids in self._ready_strategy_ids_by_condition.items():
            if strategy_id in ready_ids:
                affected_condition_ids.add(condition_id)
                ready_ids.discard(strategy_id)
        for condition_id, owners in tuple(self._wire_restore_by_condition.items()):
            if owners.pop(strategy_id, None) is not None:
                affected_condition_ids.add(condition_id)
            restore_ids = self._wire_restore_strategy_ids_by_condition.get(condition_id)
            if restore_ids is not None:
                restore_ids.discard(strategy_id)
                if not restore_ids:
                    self._wire_restore_strategy_ids_by_condition.pop(condition_id, None)
            if not owners:
                self._wire_restore_by_condition.pop(condition_id, None)
                self._wire_restore_not_before_by_condition.pop(condition_id, None)
        for condition_id in affected_condition_ids:
            self.note_readiness(strategy, condition_id, ready=False)
            if not any(
                condition_id in candidate._active_condition_ids
                or condition_id
                in candidate._subscription_state.deferred_resubscribe_condition_ids
                for candidate in self._strategies
            ):
                self._batch_refresh_condition_ids.discard(condition_id)
                self._resubscribe_not_before_by_condition.pop(condition_id, None)
                self._unsubscribe_not_before_by_condition.pop(condition_id, None)
        strategy._subscription_state.deferred_resubscribe_condition_ids.clear()

    def pending_condition_ids(
        self,
        strategy: _SubscriptionStrategy,
    ) -> set[str]:
        strategy_id = id(strategy)
        pending = set(strategy._subscription_state.deferred_resubscribe_condition_ids)
        pending.update(
            condition_id
            for condition_id, owners in self._wire_restore_by_condition.items()
            if strategy_id in owners
        )
        return pending

    def defer_subscription(
        self,
        strategy: _SubscriptionStrategy,
        condition_id: str,
    ) -> bool:
        pending_deadlines = (
            *self._resubscribe_not_before_by_condition.values(),
            *self._unsubscribe_not_before_by_condition.values(),
            *self._wire_restore_not_before_by_condition.values(),
        )
        if not pending_deadlines:
            return False
        not_before = min(pending_deadlines)
        self._resubscribe_not_before_by_condition.setdefault(
            condition_id,
            not_before,
        )
        strategy._subscription_state.deferred_resubscribe_condition_ids.add(
            condition_id
        )
        return True

    def note_readiness(
        self,
        strategy: _SubscriptionStrategy,
        condition_id: str,
        *,
        ready: bool,
    ) -> bool:
        ready_ids = self._ready_strategy_ids_by_condition.setdefault(
            condition_id,
            set(),
        )
        strategy_id = id(strategy)
        active_ids = {
            id(candidate)
            for candidate in self._strategies
            if condition_id in candidate._active_condition_ids
        }
        if ready and strategy_id in active_ids:
            ready_ids.add(strategy_id)
        else:
            ready_ids.discard(strategy_id)
        condition_ready = active_ids <= ready_ids
        if condition_ready:
            if condition_id not in self._wire_restore_by_condition:
                self._attempts_by_condition.pop(condition_id, None)
                self._last_refresh_at.pop(condition_id, None)
            if condition_id in self._unsubscribe_not_before_by_condition:
                self._unsubscribe_not_before_by_condition.pop(condition_id, None)
                for candidate in self._strategies:
                    candidate._subscription_state.deferred_resubscribe_condition_ids.discard(
                        condition_id
                    )
            if not active_ids:
                self._ready_strategy_ids_by_condition.pop(condition_id, None)
                if condition_id not in self._wire_restore_by_condition:
                    self._resubscribe_not_before_by_condition.pop(condition_id, None)
                self._unsubscribe_not_before_by_condition.pop(condition_id, None)
                for candidate in self._strategies:
                    candidate._subscription_state.deferred_resubscribe_condition_ids.discard(
                        condition_id
                    )
        return condition_ready

    def unready_consumer(
        self,
        condition_id: str,
    ) -> _SubscriptionStrategy | None:
        ready_ids = self._ready_strategy_ids_by_condition.get(condition_id, set())
        return next(
            (
                strategy
                for strategy in self._strategies
                if condition_id in strategy._active_condition_ids
                and id(strategy) not in ready_ids
            ),
            None,
        )

    def resume_pending(
        self,
        requester: _SubscriptionStrategy,
        condition_id: str,
        *,
        now: datetime,
    ) -> bool:
        if not (
            self._unsubscribe_not_before_by_condition
            or self._resubscribe_not_before_by_condition
            or self._wire_restore_not_before_by_condition
        ):
            return False
        observed = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        observed = observed.astimezone(UTC)
        if any(
            observed >= not_before
            for not_before in self._unsubscribe_not_before_by_condition.values()
        ):
            return self._begin_refresh_batch(observed=observed)
        restored = self._restore_due_wire_owners(observed=observed)
        completed = self._drain_due_resubscriptions(
            observed=observed,
            min_interval_sec=30,
        )
        if self._resubscribe_not_before_by_condition:
            return True
        if self._unsubscribe_not_before_by_condition:
            return True
        if self._wire_restore_not_before_by_condition:
            return True
        return restored or bool(completed)

    def _complete_refresh(
        self,
        consumers: Sequence[_SubscriptionStrategy],
        condition_id: str,
        *,
        observed: datetime,
        min_interval_sec: int,
    ) -> bool:
        attempts = self._attempts_by_condition.get(condition_id, 0)
        restore_owners = self._wire_restore_by_condition.get(condition_id, {})
        self._subscribe_refresh_consumers(
            consumers,
            condition_id,
            observed=observed,
            restore_owners=restore_owners,
        )
        refreshed = all(
            condition_id in strategy._subscription_state.wire_condition_ids
            for strategy in consumers
        )
        next_attempts = attempts + 1
        retry_interval_sec = min(
            int(min_interval_sec) * (2 ** min(attempts, 10)),
            max(int(min_interval_sec), _MAX_STALE_REFRESH_INTERVAL_SEC),
        )
        self._last_refresh_at[condition_id] = observed
        self._finish_refresh(
            consumers,
            condition_id,
            observed=observed,
            refreshed=refreshed,
            retry_interval_sec=retry_interval_sec,
        )
        self._attempts_by_condition[condition_id] = next_attempts
        for strategy in consumers:
            strategy._subscription_state.last_stale_refresh_at[condition_id] = observed
            strategy._subscription_state.stale_refresh_attempts_by_condition[
                condition_id
            ] = next_attempts
        return refreshed

    @staticmethod
    def _subscribe_refresh_consumers(
        consumers: Sequence[_SubscriptionStrategy],
        condition_id: str,
        *,
        observed: datetime,
        restore_owners: dict[int, tuple[bool, bool]],
    ) -> None:
        for strategy in consumers:
            registry = strategy.registry
            if registry is None:
                continue
            restore_owner = restore_owners.get(id(strategy))
            if condition_id in strategy._active_condition_ids:
                _subscribe_market_condition(
                    strategy,
                    registry,
                    condition_id,
                    now=observed,
                    allow_deferred=True,
                )
            elif restore_owner is not None and (
                not restore_owner[0]
                or not strategy.unsubscribe_exited
            ):
                _subscribe_market_condition(
                    strategy,
                    registry,
                    condition_id,
                    now=observed,
                    allow_inactive=(
                        not restore_owner[0]
                        or not strategy.unsubscribe_exited
                    ),
                    allow_deferred=True,
                )

    def _finish_refresh(
        self,
        consumers: Sequence[_SubscriptionStrategy],
        condition_id: str,
        *,
        observed: datetime,
        refreshed: bool,
        retry_interval_sec: int,
    ) -> None:
        owners = self._wire_restore_by_condition.get(condition_id, {})
        restore_ids = self._wire_restore_strategy_ids_by_condition.get(condition_id)
        self._clear_restored_owner_state(condition_id, owners, restore_ids)
        if not refreshed:
            retry_not_before = observed + timedelta(seconds=retry_interval_sec)
            self._resubscribe_not_before_by_condition[condition_id] = retry_not_before
            if restore_ids is not None and not restore_ids:
                self._wire_restore_strategy_ids_by_condition.pop(condition_id, None)
            if self._wire_restore_by_condition.get(condition_id):
                self._wire_restore_not_before_by_condition[condition_id] = (
                    retry_not_before
                )
            for strategy in consumers:
                if condition_id in strategy._active_condition_ids:
                    strategy._subscription_state.deferred_resubscribe_condition_ids.add(
                        condition_id
                    )
            return
        self._resubscribe_not_before_by_condition.pop(condition_id, None)
        if not owners:
            self._wire_restore_by_condition.pop(condition_id, None)
            self._wire_restore_not_before_by_condition.pop(condition_id, None)
            self._wire_restore_strategy_ids_by_condition.pop(condition_id, None)
        for strategy in self._strategies:
            strategy._subscription_state.deferred_resubscribe_condition_ids.discard(
                condition_id
            )

    def _clear_restored_owner_state(
        self,
        condition_id: str,
        owners: dict[int, tuple[bool, bool]],
        restore_ids: set[int] | None,
    ) -> None:
        for strategy in self._strategies:
            if condition_id not in strategy._subscription_state.wire_condition_ids:
                continue
            restore_owner = owners.pop(id(strategy), None)
            if restore_ids is not None:
                restore_ids.discard(id(strategy))
            if restore_owner is None:
                continue
            exited_retained = (
                restore_owner[0]
                and condition_id not in strategy._active_condition_ids
                and not strategy.unsubscribe_exited
            )
            if restore_owner[1] or exited_retained:
                strategy._subscription_state.retained_wire_condition_ids.add(
                    condition_id
                )

    def _begin_refresh_batch(self, *, observed: datetime) -> bool:
        refresh_condition_ids = set(self._unsubscribe_not_before_by_condition)
        reset_condition_ids = {
            *refresh_condition_ids,
            *self._wire_restore_by_condition,
            *self._resubscribe_not_before_by_condition,
        }
        self._capture_wire_restore_owners(reset_condition_ids)
        self._unsubscribe_not_before_by_condition.clear()
        if not reset_condition_ids:
            return False
        resubscribe_not_before = observed + _RESUBSCRIBE_SETTLE_DELAY
        self._batch_refresh_condition_ids.update(refresh_condition_ids)
        for condition_id in reset_condition_ids:
            if condition_id in self._wire_restore_by_condition:
                self._wire_restore_not_before_by_condition[condition_id] = (
                    resubscribe_not_before
                )
            if condition_id in refresh_condition_ids:
                self._resubscribe_not_before_by_condition[condition_id] = (
                    resubscribe_not_before
                )
            elif condition_id in self._resubscribe_not_before_by_condition:
                self._resubscribe_not_before_by_condition[condition_id] = max(
                    self._resubscribe_not_before_by_condition[condition_id],
                    resubscribe_not_before,
                )
            self._ready_strategy_ids_by_condition.pop(condition_id, None)
            for strategy in self._strategies:
                if condition_id in strategy._active_condition_ids:
                    strategy._subscription_state.deferred_resubscribe_condition_ids.add(
                        condition_id
                    )
        return True

    def _capture_wire_restore_owners(self, reset_condition_ids: set[str]) -> None:
        for strategy in self._strategies:
            wire_condition_ids = tuple(
                strategy._subscription_state.wire_condition_ids
            )
            for condition_id in wire_condition_ids:
                reset_condition_ids.add(condition_id)
                owners = self._wire_restore_by_condition.setdefault(
                    condition_id,
                    {},
                )
                owners.setdefault(
                    id(strategy),
                    (
                        condition_id in strategy._active_condition_ids,
                        condition_id
                        in strategy._subscription_state.retained_wire_condition_ids,
                    ),
                )
                self._wire_restore_strategy_ids_by_condition.setdefault(
                    condition_id,
                    set(),
                ).add(id(strategy))
            if wire_condition_ids:
                unsubscribe_market_conditions(strategy, wire_condition_ids)

    def _restore_due_wire_owners(self, *, observed: datetime) -> bool:
        due_condition_ids = {
            condition_id
            for condition_id, not_before in self._wire_restore_not_before_by_condition.items()
            if observed >= not_before
        }
        restored = False
        processed_condition_ids: set[str] = set()
        for condition_id in due_condition_ids:
            if condition_id in self._batch_refresh_condition_ids:
                continue
            retry_not_before = self._resubscribe_not_before_by_condition.get(condition_id)
            if retry_not_before is not None and observed >= retry_not_before:
                continue
            processed_condition_ids.add(condition_id)
            restored = (
                self._restore_due_condition_owners(
                    condition_id,
                    observed=observed,
                )
                or restored
            )
            if condition_id not in self._resubscribe_not_before_by_condition:
                for strategy in self._strategies:
                    strategy._subscription_state.deferred_resubscribe_condition_ids.discard(
                        condition_id
                    )
        self._batch_refresh_condition_ids.difference_update(processed_condition_ids)
        return restored

    def _restore_due_condition_owners(
        self,
        condition_id: str,
        *,
        observed: datetime,
    ) -> bool:
        owners = self._wire_restore_by_condition.get(condition_id, {})
        restore_ids = self._wire_restore_strategy_ids_by_condition.get(
            condition_id, set()
        )
        restored = False
        if restore_ids:
            restored = self._restore_condition_wire_owners(
                condition_id,
                owners,
                observed=observed,
                strategy_ids=restore_ids,
            )
        self._schedule_failed_owner_restore(
            condition_id,
            owners,
            observed=observed,
        )
        if not restore_ids:
            self._wire_restore_strategy_ids_by_condition.pop(condition_id, None)
        return restored

    def _schedule_failed_owner_restore(
        self,
        condition_id: str,
        owners: dict[int, tuple[bool, bool]],
        *,
        observed: datetime,
    ) -> None:
        self._wire_restore_not_before_by_condition.pop(condition_id, None)
        if not owners:
            self._wire_restore_by_condition.pop(condition_id, None)
            self._wire_restore_strategy_ids_by_condition.pop(condition_id, None)
            return
        retry_not_before = observed + timedelta(seconds=30)
        self._resubscribe_not_before_by_condition.setdefault(
            condition_id,
            retry_not_before,
        )
        self._wire_restore_not_before_by_condition[condition_id] = retry_not_before
        for strategy in self._strategies:
            if condition_id in strategy._active_condition_ids:
                strategy._subscription_state.deferred_resubscribe_condition_ids.add(
                    condition_id
                )

    def _restore_condition_wire_owners(
        self,
        condition_id: str,
        owners: dict[int, tuple[bool, bool]],
        *,
        observed: datetime,
        strategy_ids: set[int] | None = None,
    ) -> bool:
        restored = False
        for strategy in self._strategies:
            if strategy_ids is not None and id(strategy) not in strategy_ids:
                continue
            restore_owner = self._current_restore_owner(
                strategy,
                condition_id,
                owners,
                strategy_ids,
            )
            if restore_owner is None:
                continue
            registry = strategy.registry
            if registry is None:
                continue
            _subscribe_market_condition(
                strategy,
                registry,
                condition_id,
                now=observed,
                allow_inactive=(
                    not restore_owner[0]
                    or not strategy.unsubscribe_exited
                ),
                allow_deferred=True,
            )
            if condition_id not in strategy._subscription_state.wire_condition_ids:
                continue
            if restore_owner[1] or (
                restore_owner[0]
                and condition_id not in strategy._active_condition_ids
                and not strategy.unsubscribe_exited
            ):
                strategy._subscription_state.retained_wire_condition_ids.add(
                    condition_id
                )
            owners.pop(id(strategy), None)
            if strategy_ids is not None:
                strategy_ids.discard(id(strategy))
            restored = True
        return restored

    @staticmethod
    def _current_restore_owner(
        strategy: _SubscriptionStrategy,
        condition_id: str,
        owners: dict[int, tuple[bool, bool]],
        strategy_ids: set[int] | None,
    ) -> tuple[bool, bool] | None:
        strategy_id = id(strategy)
        restore_owner = owners.get(strategy_id)
        if restore_owner is None:
            return None
        if not restore_owner[0] or condition_id in strategy._active_condition_ids:
            return restore_owner
        if strategy.unsubscribe_exited:
            owners.pop(strategy_id, None)
            if strategy_ids is not None:
                strategy_ids.discard(strategy_id)
            return None
        retained_owner = (False, True)
        owners[strategy_id] = retained_owner
        return retained_owner

    def _drain_due_resubscriptions(
        self,
        *,
        observed: datetime,
        min_interval_sec: int,
    ) -> dict[str, bool]:
        due_condition_ids = {
            condition_id
            for condition_id, not_before in (
                self._resubscribe_not_before_by_condition.items()
            )
            if observed >= not_before
        }
        if not due_condition_ids:
            return {}
        restarted = self._restart_unready_wire_consumers(
            due_condition_ids,
            observed=observed,
        )
        if restarted:
            return dict.fromkeys(restarted, True)
        completed: dict[str, bool] = {}
        for condition_id in due_condition_ids:
            restore_owners = self._wire_restore_by_condition.get(condition_id, {})
            consumers = self._refresh_consumers(condition_id, restore_owners)
            if not consumers:
                self._resubscribe_not_before_by_condition.pop(condition_id, None)
                self._wire_restore_by_condition.pop(condition_id, None)
                self._wire_restore_not_before_by_condition.pop(condition_id, None)
                self._wire_restore_strategy_ids_by_condition.pop(condition_id, None)
                self._batch_refresh_condition_ids.discard(condition_id)
                for strategy in self._strategies:
                    strategy._subscription_state.deferred_resubscribe_condition_ids.discard(
                        condition_id
                    )
                completed[condition_id] = True
                continue
            completed[condition_id] = self._complete_refresh(
                consumers,
                condition_id,
                observed=observed,
                min_interval_sec=min_interval_sec,
            )
            self._batch_refresh_condition_ids.discard(condition_id)
        return completed

    def _refresh_consumers(
        self,
        condition_id: str,
        restore_owners: dict[int, tuple[bool, bool]],
    ) -> list[_SubscriptionStrategy]:
        return [
            strategy
            for strategy in self._strategies
            if condition_id in strategy._active_condition_ids
            or (
                (restore_owner := restore_owners.get(id(strategy))) is not None
                and (
                    not restore_owner[0]
                    or not strategy.unsubscribe_exited
                )
            )
        ]

    def _restart_unready_wire_consumers(
        self,
        condition_ids: set[str],
        *,
        observed: datetime,
    ) -> set[str]:
        restart_condition_ids = {
            condition_id
            for condition_id in condition_ids
            if condition_id not in self._batch_refresh_condition_ids
            and self._has_unready_wire_consumer(condition_id)
        }
        if not restart_condition_ids:
            return set()
        for condition_id in restart_condition_ids:
            self._unsubscribe_not_before_by_condition[condition_id] = observed
        self._begin_refresh_batch(observed=observed)
        return restart_condition_ids

    def _has_unready_wire_consumer(self, condition_id: str) -> bool:
        ready_ids = self._ready_strategy_ids_by_condition.get(condition_id, set())
        return any(
            condition_id in strategy._active_condition_ids
            and condition_id in strategy._subscription_state.wire_condition_ids
            and id(strategy) not in ready_ids
            for strategy in self._strategies
        )

    def _schedule_condition_refresh(
        self,
        consumers: Sequence[_SubscriptionStrategy],
        condition_id: str,
        *,
        observed: datetime,
        min_interval_sec: int,
    ) -> bool:
        attempts = self._attempts_by_condition.get(condition_id, 0)
        retry_interval_sec = min(
            int(min_interval_sec) * (2 ** min(attempts, 10)),
            max(int(min_interval_sec), _MAX_STALE_REFRESH_INTERVAL_SEC),
        )
        last = self._last_refresh_at.get(condition_id)
        if last is not None and (observed - last).total_seconds() < retry_interval_sec:
            return False
        self._unsubscribe_not_before_by_condition[condition_id] = (
            observed + _REFRESH_BATCH_WINDOW
        )
        for strategy in consumers:
            strategy._subscription_state.deferred_resubscribe_condition_ids.add(
                condition_id
            )
        return True

    def refresh(
        self,
        requester: _SubscriptionStrategy,
        condition_id: str,
        *,
        now: datetime,
        min_interval_sec: int = 30,
    ) -> bool:
        observed = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        observed = observed.astimezone(UTC)
        if any(
            observed >= not_before
            for not_before in self._unsubscribe_not_before_by_condition.values()
        ):
            return self._begin_refresh_batch(observed=observed)
        self._restore_due_wire_owners(observed=observed)
        completed = self._drain_due_resubscriptions(
            observed=observed,
            min_interval_sec=min_interval_sec,
        )
        if condition_id in completed:
            return completed[condition_id]
        if self._unsubscribe_not_before_by_condition:
            return True
        if condition_id in self._resubscribe_not_before_by_condition:
            return True
        if condition_id in self._wire_restore_not_before_by_condition:
            return True
        if condition_id not in requester._active_condition_ids:
            return False
        consumers = [
            strategy
            for strategy in self._strategies
            if condition_id in strategy._active_condition_ids
        ]
        if not consumers:
            return False
        return self._schedule_condition_refresh(
            consumers,
            condition_id,
            observed=observed,
            min_interval_sec=min_interval_sec,
        )


class InstrumentSubscriptionManager:
    """Thin bridge used by custom-data handlers to re-request missing instruments."""

    def __init__(self, strategy: _SubscriptionStrategy) -> None:
        self._strategy = strategy

    def retry_instrument_requests(self, condition_ids: tuple[str, ...]) -> None:
        retry_market_instrument_requests(
            self._strategy,
            condition_ids,
            retry_after=timedelta(seconds=10),
        )


def refresh_asset_conditions(strategy: _SubscriptionStrategy) -> None:
    tracked_condition_ids = tuple(
        dict.fromkeys((*strategy._startup_condition_ids, *strategy._active_condition_ids))
    )
    strategy._asset_condition_ids = _asset_conditions(
        strategy.registry, tracked_condition_ids
    )


def retry_market_instrument_requests(
    strategy: _SubscriptionStrategy,
    condition_ids: Sequence[str],
    *,
    retry_after: timedelta | None = None,
) -> None:
    _ = retry_after
    if strategy.registry is None:
        return
    for instrument_id in _instrument_ids(strategy.registry, condition_ids):
        _ = strategy.request_instrument(instrument_id)


def _subscribe_market_condition(
    strategy: _SubscriptionStrategy,
    registry: MarketCatalog,
    condition_id: str,
    *,
    now: datetime | None,
    allow_inactive: bool = False,
    allow_deferred: bool = False,
) -> None:
    if not allow_inactive and condition_id not in strategy._active_condition_ids:
        return
    state = strategy._subscription_state
    coordinator = getattr(strategy, "_subscription_coordinator", None)
    if (
        not allow_deferred
        and coordinator is not None
        and coordinator.defer_subscription(strategy, condition_id)
    ):
        return
    if condition_id in state.wire_condition_ids:
        state.pending_metadata_condition_ids.discard(condition_id)
        state.pending_subscribe_condition_ids.discard(condition_id)
        state.retained_wire_condition_ids.discard(condition_id)
        return
    instrument_ids = _instrument_ids(registry, (condition_id,))
    if not instrument_ids:
        state.pending_metadata_condition_ids.add(condition_id)
        state.pending_subscribe_condition_ids.discard(condition_id)
        return
    if condition_id in strategy._active_condition_ids:
        begin_market_book_generation(strategy, condition_id, now=now)
    state.pending_metadata_condition_ids.discard(condition_id)
    subscribed = True
    for instrument_id in condition_instruments(strategy, condition_id):
        if not subscribe_market_instrument(strategy, instrument_id):
            subscribed = False
    if subscribed:
        state.pending_subscribe_condition_ids.discard(condition_id)
        state.retained_wire_condition_ids.discard(condition_id)
        state.wire_condition_ids.add(condition_id)
        return
    state.pending_subscribe_condition_ids.add(condition_id)


def subscribe_market_conditions(
    strategy: _SubscriptionStrategy,
    condition_ids: Sequence[str],
    *,
    now: datetime | None = None,
) -> None:
    registry = strategy.registry
    if registry is None:
        return
    for condition_id in condition_ids:
        _subscribe_market_condition(
            strategy,
            registry,
            condition_id,
            now=now,
        )


def subscribe_market_instrument(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
) -> bool:
    instrument_id = _nautilus_instrument_id(instrument_id)
    book_type = _nautilus_book_type(strategy.book_type)
    subscribed = call_subscription(strategy, strategy.subscribe_quote_ticks, instrument_id)
    if not call_subscription(strategy, strategy.subscribe_trade_ticks, instrument_id):
        subscribed = False
    if not call_subscription(
        strategy,
        strategy.subscribe_order_book_deltas,
        instrument_id,
        book_type=book_type,
    ):
        subscribed = False
    return subscribed


def unsubscribe_market_conditions(
    strategy: _SubscriptionStrategy,
    condition_ids: Sequence[str],
) -> None:
    if strategy.registry is None:
        return
    for condition_id in condition_ids:
        for instrument_id in condition_instruments(strategy, condition_id):
            _ = unsubscribe_market_instrument(strategy, instrument_id)
        clear_condition_subscription_state(strategy, condition_id)


def condition_instruments(
    strategy: _SubscriptionStrategy,
    condition_id: str,
) -> tuple[object, ...]:
    if strategy.registry is None:
        return ()
    return _instrument_ids(strategy.registry, (condition_id,))


def clear_condition_subscription_state(
    strategy: _SubscriptionStrategy,
    condition_id: str,
) -> None:
    strategy._subscription_state.wire_condition_ids.discard(condition_id)
    strategy._subscription_state.retained_wire_condition_ids.discard(condition_id)
    strategy._subscription_state.pending_subscribe_condition_ids.discard(condition_id)
    strategy._subscription_state.pending_metadata_condition_ids.discard(condition_id)
    strategy._subscription_state.deferred_resubscribe_condition_ids.discard(
        condition_id
    )
    strategy._subscription_state.stale_refresh_attempts_by_condition.pop(
        condition_id,
        None,
    )
    strategy._subscription_state.last_stale_refresh_at.pop(condition_id, None)
    retire_market_book_generation(strategy, condition_id, clear_history=False)


def mark_market_subscription_ready(
    strategy: _SubscriptionStrategy,
    condition_id: str,
) -> None:
    strategy._subscription_state.deferred_resubscribe_condition_ids.discard(
        condition_id
    )
    strategy._subscription_state.stale_refresh_attempts_by_condition.pop(
        condition_id,
        None,
    )
    strategy._subscription_state.last_stale_refresh_at.pop(condition_id, None)


def begin_market_book_generation(
    strategy: _SubscriptionStateOwner,
    condition_id: str,
    *,
    now: datetime | None = None,
) -> None:
    """Invalidate cached-book readiness before a real subscribe attempt."""
    observed = now or datetime.now(UTC)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    strategy._subscription_state.awaiting_book_sides_by_condition[condition_id] = {
        Side.UP,
        Side.DOWN,
    }
    strategy._subscription_state.book_generation_started_at_by_condition[
        condition_id
    ] = observed.astimezone(UTC)


def observe_market_book_side(
    strategy: _SubscriptionStateOwner,
    condition_id: str,
    side: Side,
    *,
    received_at: datetime,
    book_at: datetime,
) -> bool:
    received = received_at.astimezone(UTC)
    observed_book = book_at.astimezone(UTC)
    last_receipts = (
        strategy._subscription_state.last_book_received_at_by_condition.setdefault(
            condition_id,
            {},
        )
    )
    previous_received = last_receipts.get(side)
    if previous_received is None or received >= previous_received:
        last_receipts[side] = received
    last_books = strategy._subscription_state.last_book_at_by_condition.setdefault(
        condition_id,
        {},
    )
    previous = last_books.get(side)
    if previous is None or observed_book >= previous:
        last_books[side] = observed_book
    pending = strategy._subscription_state.awaiting_book_sides_by_condition.get(
        condition_id
    )
    if pending is None:
        return True
    started_at = (
        strategy._subscription_state.book_generation_started_at_by_condition.get(
            condition_id
        )
    )
    if started_at is not None and received < started_at:
        return False
    pending.discard(side)
    return not pending


def market_book_generation_ready(
    strategy: _SubscriptionStateOwner,
    condition_id: str,
) -> bool:
    return not strategy._subscription_state.awaiting_book_sides_by_condition.get(
        condition_id
    )


def market_book_generation_stalled(
    strategy: _SubscriptionStateOwner,
    condition_id: str,
    *,
    now: datetime,
    timeout_sec: int = 30,
) -> bool:
    started_at = (
        strategy._subscription_state.book_generation_started_at_by_condition.get(
            condition_id
        )
    )
    if started_at is None:
        return True
    observed = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return (observed.astimezone(UTC) - started_at).total_seconds() >= timeout_sec


def retire_market_book_generation(
    strategy: _SubscriptionStateOwner,
    condition_id: str,
    *,
    clear_history: bool = True,
) -> None:
    strategy._subscription_state.awaiting_book_sides_by_condition.pop(
        condition_id,
        None,
    )
    strategy._subscription_state.book_generation_started_at_by_condition.pop(
        condition_id,
        None,
    )
    if clear_history:
        strategy._subscription_state.last_book_at_by_condition.pop(condition_id, None)
        strategy._subscription_state.last_book_received_at_by_condition.pop(
            condition_id,
            None,
        )


def refresh_stale_market_subscription(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime | None = None,
    min_interval_sec: int = 30,
) -> bool:
    """Force unsubscribe+resubscribe for a stale active market condition.

    Subscribe is no-op when already wired; clear wire state first so a fresh
    quote/trade/book subscription can recover after rotation or silent drop.
    """
    if condition_id not in strategy._active_condition_ids:
        return False
    observed = now or datetime.now(UTC)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    attempts = strategy._subscription_state.stale_refresh_attempts_by_condition.get(
        condition_id,
        0,
    )
    retry_interval_sec = min(
        int(min_interval_sec) * (2 ** min(attempts, 10)),
        max(int(min_interval_sec), _MAX_STALE_REFRESH_INTERVAL_SEC),
    )
    last = strategy._subscription_state.last_stale_refresh_at.get(condition_id)
    if last is not None:
        elapsed = (observed - last.astimezone(UTC)).total_seconds()
        if elapsed < retry_interval_sec:
            return False
    unsubscribe_market_conditions(strategy, (condition_id,))
    subscribe_market_conditions(strategy, (condition_id,), now=observed)
    strategy._subscription_state.last_stale_refresh_at[condition_id] = observed
    refreshed = condition_id in strategy._subscription_state.wire_condition_ids
    strategy._subscription_state.stale_refresh_attempts_by_condition[condition_id] = (
        attempts + 1 if refreshed else 0
    )
    return refreshed


def unsubscribe_market_instrument(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
) -> bool:
    instrument_id = _nautilus_instrument_id(instrument_id)
    unsubscribed = call_subscription(
        strategy, strategy.unsubscribe_quote_ticks, instrument_id
    )
    if not call_subscription(strategy, strategy.unsubscribe_trade_ticks, instrument_id):
        unsubscribed = False
    if not call_subscription(
        strategy, strategy.unsubscribe_order_book_deltas, instrument_id
    ):
        unsubscribed = False
    return unsubscribed


def call_subscription(
    strategy: _SubscriptionStrategy,
    callback: Callable[..., object],
    *args: object,
    **kwargs: object,
) -> bool:
    _ = strategy
    try:
        _ = callback(*args, **kwargs)
    except ValueError as e:
        message = str(e)
        if "not been registered" not in message:
            raise
        if message == "The actor has not been registered":
            return True
        return False
    return True
