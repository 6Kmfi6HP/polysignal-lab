from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from nautilus_trader.core.nautilus_pyo3 import Strategy

from polysignal_lab.alpha.types import (
    AlphaCore,
    AlphaDecision,
    MarketView,
)
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.strategy_readiness import StrategyStatus
from polysignal_lab.nautilus_runtime.custom_data_types import unwrap_custom_data
from polysignal_lab.nautilus_runtime.decision_policy import (
    DecisionPolicy,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.strategy_state import (
    load_strategy_state,
    save_strategy_state,
)
from polysignal_lab.nautilus_runtime.strategy import condition_evaluation as cond
from polysignal_lab.nautilus_runtime.strategy import lifecycle as life
from polysignal_lab.nautilus_runtime.strategy import market_data_events as mde
from polysignal_lab.nautilus_runtime.strategy import observability_hooks as obs
from polysignal_lab.nautilus_runtime.strategy import order_events as oev
from polysignal_lab.nautilus_runtime.strategy import readiness as readiness_mod
from polysignal_lab.nautilus_runtime.strategy import snapshot_backstop
from polysignal_lab.nautilus_runtime.strategy import subscriptions as subs
from polysignal_lab.nautilus_runtime.strategy.custom_data_handlers import (
    route_strategy_data,
)
from polysignal_lab.nautilus_runtime.strategy.constants import (
    DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS,
    DEFAULT_NATIVE_DATA_NAMES,
    EVALUATION_HEARTBEAT_INTERVAL,
    EVALUATION_HEARTBEAT_TIMER_NAME,
    MISSING_PROJECTIONS_ERROR,
)
from polysignal_lab.nautilus_runtime.strategy.data_boundary import (
    classify_project_owned_data,
)
from polysignal_lab.nautilus_runtime.strategy.nautilus_objects import (
    _nautilus_instrument_id,
)
from polysignal_lab.nautilus_runtime.strategy.protocols import (
    _Assembler,
    _Observability,
)
from polysignal_lab.nautilus_runtime.strategy.host_init import (
    HostInitRequest,
    bind_host_runtime,
    resolve_host_construction,
    resolve_instrument_from_cache,
)

__all__ = [
    "EVALUATION_HEARTBEAT_INTERVAL",
    "EVALUATION_HEARTBEAT_TIMER_NAME",
    "PolySignalNativeStrategy",
]

logger = logging.getLogger(__name__)


class PolySignalNativeStrategy(Strategy):
    """Nautilus callback host: DI + on_* dispatch; business logic in strategy/*."""

    _execution_mode: str

    def __new__(cls, *args: object, **kwargs: object):
        return super().__new__(cls)

    def __init__(
        self,
        config: object | None = None,
        *,
        core: AlphaCore | None = None,
        assembler: _Assembler | None = None,
        condition_ids: Sequence[str] = (),
        strategy_name: str = "",
        fixed_stake_usdc: float = 10.0,
        orderbook_staleness_ms: float = 60_000.0,
        exit_model: object | None = None,
        data_names: Sequence[str] = DEFAULT_NATIVE_DATA_NAMES,
        book_type: str = "L2_MBP",
        instrument_id_resolver: Callable[[str], object] | None = None,
        registry: MarketCatalog | None = None,
        observability: _Observability | None = None,
        progress_callback: Callable[..., None] | None = None,
        readiness_callback: Callable[[str, bool, dict[str, object]], None]
        | None = None,
        unsubscribe_exited: bool = True,
        l1_book_snapshot_interval_ms: int = DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS,
        policy: DecisionPolicy | None = None,
    ) -> None:
        host = resolve_host_construction(
            HostInitRequest(
                config=config,
                core=core,
                assembler=assembler,
                condition_ids=condition_ids,
                strategy_name=strategy_name,
                fixed_stake_usdc=fixed_stake_usdc,
                orderbook_staleness_ms=orderbook_staleness_ms,
                exit_model=exit_model,
                data_names=data_names,
                book_type=book_type,
                instrument_id_resolver=instrument_id_resolver,
                registry=registry,
                observability=observability,
                progress_callback=progress_callback,
                readiness_callback=readiness_callback,
                unsubscribe_exited=unsubscribe_exited,
                l1_book_snapshot_interval_ms=l1_book_snapshot_interval_ms,
                policy=policy,
            )
        )
        super().__init__(config=host.nautilus_config)
        bind_host_runtime(self, host)
        self._settled_position_keys: set[tuple[str, str]] = set()

    def _require_registry(self) -> MarketCatalog:
        if self.registry is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)
        return self.registry

    def _require_assembler(self) -> _Assembler:
        return self.assembler

    def _note_runtime_progress(
        self,
        phase: str,
        *,
        active_condition_ids: Sequence[str] | None = None,
    ) -> None:
        readiness_mod.note_runtime_progress(
            self,
            phase,
            active_condition_ids=active_condition_ids,
        )

    def _note_runtime_readiness(
        self,
        condition_id: str,
        *,
        ready: bool,
        status: StrategyStatus | None = None,
        reason: str | None = None,
    ) -> None:
        readiness_mod.note_runtime_readiness(
            self,
            condition_id,
            ready=ready,
            status=status,
            reason=reason,
        )

    def _readiness_detail(
        self, condition_id: str, *, now: datetime
    ) -> dict[str, object]:
        return readiness_mod.readiness_detail(self, condition_id, now=now)

    def _framework_now(self) -> datetime:
        return life.framework_now(self)

    @property
    def cache(self) -> object | None:
        override = getattr(self, "_cache_override", None)
        if override is not None:
            return override
        if getattr(self, "trader_id", None) is None:
            return None
        return super().cache

    @property
    def order_factory(self) -> object | None:
        override = getattr(self, "_order_factory_override", None)
        if override is not None:
            return override
        if getattr(self, "trader_id", None) is None:
            return None
        return super().order_factory

    def _start_evaluation_heartbeat(self) -> None:
        life.start_evaluation_heartbeat(self, self._on_evaluation_heartbeat)

    def on_start(self) -> None:
        life.on_strategy_start(self, self._on_evaluation_heartbeat)

    def on_stop(self) -> None:
        snapshot_backstop.fail_all(self, reason="strategy_stop")
        life.on_strategy_stop(self)

    def on_save(self) -> dict[str, bytes]:
        return save_strategy_state(self.strategy_name, self.core)

    def on_load(self, state: Mapping[str, bytes]) -> None:
        load_strategy_state(self.strategy_name, self.core, state)
        self._market_epoch = None

    def _on_evaluation_heartbeat(self, event: object) -> None:
        snapshot_backstop.expire(self)
        life.on_evaluation_heartbeat(self, event)

    def on_data(self, data: object) -> None:
        route_strategy_data(
            self, unwrap_custom_data(data), classify=classify_project_owned_data
        )

    def on_instrument(self, instrument: object) -> None:
        """Subscribe only when Actor-owned metadata marks the instrument wanted."""
        _ = subs.on_instrument_available(self, instrument)

    def on_quote(self, tick: object) -> None:
        mde.evaluate_order_book_event(self, tick)

    def on_book(self, book: object) -> None:
        if snapshot_backstop.record_historical(self, book):
            return
        mde.evaluate_order_book_event(self, book)

    def _evaluate_market_data_condition(
        self, condition_id: str, *, event: object | None = None
    ) -> None:
        mde.evaluate_market_data_condition(self, condition_id, event=event)

    def _cancel_market_data_recovery_evaluation(self, condition_id: str) -> None:
        mde.cancel_pending_market_data_evaluation(self, condition_id)

    def on_trade(self, tick: object) -> None:
        condition_id = mde.condition_from_market_data(self, tick)
        if condition_id is not None:
            self._evaluate_market_data_condition(condition_id, event=tick)

    def on_book_deltas(self, deltas: object) -> None:
        snapshot_backstop.record_live_applied(self, deltas)
        mde.evaluate_order_book_event(self, deltas)

    def on_order_submitted(self, event: object) -> None:
        oev.handle_order_lifecycle_event(self, "on_order_submitted", event)

    def on_order_accepted(self, event: object) -> None:
        oev.handle_order_lifecycle_event(self, "on_order_accepted", event)

    def on_order_rejected(self, event: object) -> None:
        oev.handle_order_lifecycle_event(
            self, "on_order_rejected", event, forget_metrics=True
        )

    def on_order_denied(self, event: object) -> None:
        oev.handle_order_lifecycle_event(
            self, "on_order_denied", event, forget_metrics=True
        )

    def on_order_updated(self, event: object) -> None:
        oev.handle_order_lifecycle_event(self, "on_order_updated", event)

    def on_order_canceled(self, event: object) -> None:
        oev.handle_order_lifecycle_event(
            self, "on_order_canceled", event, forget_metrics=True
        )

    def on_order_expired(self, event: object) -> None:
        oev.handle_order_lifecycle_event(
            self, "on_order_expired", event, forget_metrics=True
        )

    def on_order_filled(self, event: object) -> None:
        oev.handle_order_filled(self, event)

    def on_position_opened(self, position: object) -> None:
        oev.handle_position_event(self, position)

    def on_position_changed(self, position: object) -> None:
        oev.handle_position_event(self, position)

    def on_position_closed(self, position: object) -> None:
        oev.handle_position_closed(self, position)

    def evaluate_condition(
        self,
        condition_id: str,
        *,
        created_at: datetime | None = None,
        trading_state: object | None = None,
    ) -> None:
        cond.evaluate_condition(
            self,
            condition_id,
            created_at=created_at,
            trading_state=trading_state,
        )

    def _apply_decision_batch(
        self, decisions: Sequence[AlphaDecision], view: MarketView
    ) -> None:
        """Evaluate decisions through the strategy-owned DecisionPolicy (no Actor bus)."""
        self._decision_pipeline.apply(decisions, view)

    def _evaluate_decisions(
        self,
        market_view: MarketView,
        *,
        now: datetime,
        evaluate_core: bool = True,
    ) -> tuple[AlphaDecision, ...]:
        return cond.evaluate_decisions(
            self, market_view, now=now, evaluate_core=evaluate_core
        )

    def _handle_decision(self, decision: AlphaDecision, view: MarketView) -> None:
        cond.handle_decision(self, decision, view)

    def _resolved_instrument(self, token_id: str) -> object:
        return resolve_instrument_from_cache(
            token_id,
            instrument_id_resolver=self.instrument_id_resolver,
            cache=getattr(self, "cache", None),
            nautilus_instrument_id=_nautilus_instrument_id,
        )

    def _record_signal(self, signal: SignalCandidate) -> None:
        obs.record_signal(self, signal)

    def _notify_accepted_signal(self, signal: SignalCandidate) -> None:
        obs.notify_accepted_signal(self, signal)

    def _record_decision(self, decision: AlphaDecision, *, accepted: bool) -> None:
        obs.record_decision(self, decision, accepted=accepted)

    def _record_rejected(self, rejected: RejectedDecision) -> None:
        obs.record_rejected(self, rejected)

    def _record_nautilus_order(
        self, event: object, metrics: Mapping[str, object]
    ) -> None:
        obs.record_nautilus_order(self, event, metrics)

    def _record_nautilus_fill(
        self, event: object, metrics: Mapping[str, object]
    ) -> None:
        obs.record_nautilus_fill(self, event, metrics)

    def _record_nautilus_position(self, position: object) -> None:
        obs.record_nautilus_position(self, position)

    def _refresh_asset_conditions(self) -> None:
        subs.refresh_asset_conditions(self)

    def _subscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        subs.subscribe_market_conditions(self, condition_ids, now=self._framework_now())

    def _subscribe_market_instrument(self, instrument_id: object) -> bool:
        return subs.subscribe_market_instrument(self, instrument_id)

    def _unsubscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        subs.unsubscribe_market_conditions(self, condition_ids)

    def _unsubscribe_all_market_instruments(self) -> None:
        subs.unsubscribe_all_market_instruments(self)

    def request_order_book_snapshot(
        self,
        instrument_id: object,
        *,
        limit: int = 0,
        client_id: object | None = None,
        params: Mapping[str, object] | None = None,
    ) -> object:
        """Request a live-book snapshot backstop after a managed resubscription."""
        instrument_key = str(instrument_id)
        _ = snapshot_backstop.begin(self, instrument_id, depth=limit or None)
        try:
            return super().request_book_snapshot(
                instrument_id,
                depth=limit or None,
                client_id=client_id,
                params=dict(params) if params is not None else None,
            )
        except Exception:
            snapshot_backstop.fail(
                self,
                instrument_key,
                reason="request_exception",
                exc_info=True,
            )
            return None
