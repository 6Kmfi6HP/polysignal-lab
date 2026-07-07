"""
Input: __future__, __future__.annotations, logging, collections.abc, collections.abc.Sequence, typing, typing.Any, typing.cast, polysignal_lab.app.scheduler, polysignal_lab.app.scheduler.PolySignalScheduler
Output: None
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, cast

from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.signal_layer.arbiter import SignalArbiter
from polysignal_lab.strategies.execution import StrategyScheduleEntry

logger = logging.getLogger(__name__)


def _disabled_strategy_names_from_scheduler(
    scheduler: PolySignalScheduler,
    known_strategy_names: set[str],
) -> tuple[str, ...]:
    disabled_raw = cast(
        object,
        scheduler.persistence.read_state("telegram_disabled_strategies", default=[]),
    )
    if not isinstance(disabled_raw, list):
        return ()
    return tuple(
        name
        for name in (str(raw_name) for raw_name in cast(list[object], disabled_raw))
        if name in known_strategy_names
    )


def _seed_policy_control_from_scheduler(
    policy: DecisionPolicyActor,
    scheduler: PolySignalScheduler,
) -> None:
    """Transfer configuration state and signal-layer instances from scheduler to policy.

    Shares the scheduler's SignalGate/ConsensusEngine/SignalArbiter instances with
    the policy so that:

    * ``policy.evaluate()`` mutates the same gate (deduper) and consensus that
      ``scheduler_state.persist_state()`` snapshots — no stale dedupe state.
    * The scheduler's arbiter (set in ``_initialize_nautilus_scheduler_components``)
      becomes the policy's active arbiter.

    Also seeds disabled-strategy state and dependency topology from the scheduler's
    persistence layer.
    """
    # Share signal-layer instances so dedupe / consensus state is unified.
    # Both sets are created with the same settings, so this is purely a reference
    # swap — no behavioral change, but the scheduler-owned gate now accumulates
    # live evaluation state that scheduler_state.py persists.
    policy.gate = scheduler.gate
    policy.arbiter = getattr(scheduler, "arbiter", None) or policy.arbiter
    policy.consensus = scheduler.consensus

    schedule = cast(Sequence[StrategyScheduleEntry], scheduler.strategy_schedule)
    policy.strategy_dependencies = {
        entry.name: tuple(entry.depends_on) for entry in schedule
    }
    known_strategy_names = {entry.name for entry in schedule}
    for name in _disabled_strategy_names_from_scheduler(scheduler, known_strategy_names):
        policy.set_strategy_enabled(name, False)


def _initialize_nautilus_scheduler_components(scheduler: PolySignalScheduler) -> None:
    """Initialize scheduler state needed by Nautilus without legacy local paper."""
    from polysignal_lab.nautilus_runtime.strategy_builder import _build_nautilus_config_strategy_schedule

    initialized = cast(object, getattr(scheduler, "_trading_components_initialized", False))
    if initialized is True:
        return
    scheduler.strategy_schedule = _build_nautilus_config_strategy_schedule(
        scheduler.settings
    )
    scheduler.strategies = list(scheduler.strategy_schedule)
    scheduler.signal_pipeline.strategies = scheduler.strategies
    scheduler.signal_pipeline.set_strategy_dependencies(
        {entry.name: tuple(entry.depends_on) for entry in scheduler.strategy_schedule}
    )
    known_strategy_names = {entry.name for entry in scheduler.strategy_schedule}
    for name in _disabled_strategy_names_from_scheduler(scheduler, known_strategy_names):
        scheduler.signal_pipeline.set_strategy_enabled(name, False)
    # NOTE: scheduler.arbiter is set here for parity with scheduler.py:237,
    # but is never read during Nautilus runtime operation. The actual arbiter
    # driving evaluate() lives inside DecisionPolicyActor (strategy_builder.py:164).
    # scheduler.gate/scheduler.consensus are set in scheduler.py:102-105 and
    # used for dedupe persistence (scheduler_state.py:27); they are independent
    # of the policy-owned instances. Both the scheduler and policy sets coexist.
    scheduler.arbiter = SignalArbiter()
    setattr(scheduler, "_trading_components_initialized", True)
