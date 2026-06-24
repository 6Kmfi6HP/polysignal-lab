from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from graphlib import CycleError, TopologicalSorter
from typing import Iterable, Literal

from polysignal_lab.config import StrategyConfig
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.factory import build_strategy

ExecutionMode = Literal["stateless", "stateful", "cross_market"]


@dataclass(frozen=True, slots=True)
class StrategyScheduleEntry:
    strategy: BaseStrategy
    name: str
    priority: int
    depends_on: tuple[str, ...]
    execution_mode: ExecutionMode
    strategy_config_index: int


def order_strategy_schedule(
    entries: Iterable[StrategyScheduleEntry],
) -> list[StrategyScheduleEntry]:
    entries_list = list(entries)
    validate_strategy_dag((entry.name, entry.depends_on) for entry in entries_list)
    entries_by_name = {entry.name: entry for entry in entries_list}
    children_by_name: dict[str, list[str]] = {
        entry.name: [] for entry in entries_list
    }
    remaining_deps = {
        entry.name: set(entry.depends_on) for entry in entries_list
    }
    for entry in entries_list:
        for dependency_name in entry.depends_on:
            children_by_name[dependency_name].append(entry.name)

    ready: list[tuple[int, int, str]] = []
    for entry in entries_list:
        if not remaining_deps[entry.name]:
            heappush(ready, _strategy_sort_key(entry))

    ordered: list[StrategyScheduleEntry] = []
    while ready:
        _, _, name = heappop(ready)
        entry = entries_by_name[name]
        ordered.append(entry)
        for child_name in children_by_name[name]:
            child_deps = remaining_deps[child_name]
            child_deps.remove(name)
            if not child_deps:
                heappush(ready, _strategy_sort_key(entries_by_name[child_name]))
    return ordered


def _strategy_sort_key(entry: StrategyScheduleEntry) -> tuple[int, int, str]:
    return (entry.priority, entry.strategy_config_index, entry.name)


def validate_strategy_dag(items: Iterable[tuple[str, Iterable[str]]]) -> tuple[str, ...]:
    pairs = [(name, tuple(depends_on)) for name, depends_on in items]
    names = {name for name, _ in pairs}
    unknown = sorted({dep for _, depends_on in pairs for dep in depends_on} - names)
    if unknown:
        raise ValueError(f"unknown strategy dependencies: {', '.join(unknown)}")

    sorter = TopologicalSorter()
    for name, depends_on in pairs:
        sorter.add(name, *depends_on)
    try:
        return tuple(sorter.static_order())
    except CycleError as exc:
        raise ValueError("strategy dependency cycle detected") from exc


def build_strategy_schedule(config: StrategyConfig) -> list[StrategyScheduleEntry]:
    entries: list[StrategyScheduleEntry] = []
    for index, name in enumerate(config.explicit_strategy_names()):
        cfg = getattr(config, name)
        if not getattr(cfg, "enabled", False):
            continue
        execution = cfg.execution
        entries.append(
            StrategyScheduleEntry(
                strategy=build_strategy(cfg),
                name=cfg.name,
                priority=execution.priority,
                depends_on=tuple(execution.depends_on),
                execution_mode=execution.execution_mode,
                strategy_config_index=index,
            )
        )
    return order_strategy_schedule(entries)
