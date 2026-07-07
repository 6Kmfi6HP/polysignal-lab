"""
Input: __future__, __future__.annotations, logging, collections.abc, collections.abc.Sequence, typing, typing.Any, typing.cast
Output: _disabled_strategy_names_from_services, _seed_policy_control_from_services, _initialize_services_schedule
Pos: Application code

Bridge between the PolySignalServiceBundle and Nautilus-native runtime.
Renamed from "scheduler bridge" — the scheduler no longer exists.

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, cast

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.signal_layer.arbiter import SignalArbiter
from polysignal_lab.strategies.execution import StrategyScheduleEntry

logger = logging.getLogger(__name__)


def _disabled_strategy_names_from_services(
    services: object,
    known_strategy_names: set[str],
) -> tuple[str, ...]:
    persistence = getattr(services, "persistence", None)
    if persistence is None:
        return ()
    disabled_raw = cast(
        object,
        persistence.read_state("telegram_disabled_strategies", default=[]),
    )
    if not isinstance(disabled_raw, list):
        return ()
    return tuple(
        name
        for name in (str(raw_name) for raw_name in cast(list[object], disabled_raw))
        if name in known_strategy_names
    )


def _seed_policy_control_from_services(
    policy: DecisionPolicyActor,
    services: object,
) -> None:
    """Transfer configuration state and signal-layer instances from services to policy.

    Shares signal-layer instances (SignalGate/ConsensusEngine/SignalArbiter)
    between the service bundle and the policy so that:
    * ``policy.evaluate()`` mutates the same gate (deduper) and consensus
      that state persistence snapshots — no stale dedupe state.
    * The arbiter set during initialization becomes the policy's active arbiter.
    """
    policy.gate = getattr(services, "gate", None) or policy.gate
    policy.arbiter = getattr(services, "arbiter", None) or policy.arbiter
    policy.consensus = getattr(services, "consensus", None) or policy.consensus

    schedule = cast(Sequence[StrategyScheduleEntry], getattr(services, "strategy_schedule", None))
    if schedule is None:
        return
    policy.strategy_dependencies = {
        entry.name: tuple(entry.depends_on) for entry in schedule
    }
    known_strategy_names = {entry.name for entry in schedule}
    for name in _disabled_strategy_names_from_services(services, known_strategy_names):
        policy.set_strategy_enabled(name, False)


def _initialize_services_schedule(services: object) -> None:
    """Initialize strategy schedule and signal-layer arbitration on the service bundle."""
    from polysignal_lab.nautilus_runtime.strategy_builder import _build_nautilus_config_strategy_schedule

    settings = cast(Settings, getattr(services, "settings", None))
    signal_pipeline = getattr(services, "signal_pipeline", None)

    initialized = cast(object, getattr(services, "_trading_components_initialized", False))
    if initialized is True:
        return

    strategy_schedule = _build_nautilus_config_strategy_schedule(settings)
    setattr(services, "strategy_schedule", strategy_schedule)
    setattr(services, "strategies", list(strategy_schedule))
    if signal_pipeline is not None:
        signal_pipeline.strategies = getattr(services, "strategies", [])
        signal_pipeline.set_strategy_dependencies(
            {entry.name: tuple(entry.depends_on) for entry in strategy_schedule}
        )
    known_strategy_names = {entry.name for entry in strategy_schedule}
    for name in _disabled_strategy_names_from_services(services, known_strategy_names):
        if signal_pipeline is not None:
            signal_pipeline.set_strategy_enabled(name, False)

    setattr(services, "arbiter", SignalArbiter())
    setattr(services, "_trading_components_initialized", True)
