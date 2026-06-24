from __future__ import annotations

import pytest

from polysignal_lab.config import Settings
from polysignal_lab.strategies.execution import build_strategy_schedule, validate_strategy_dag


def test_strategy_execution_defaults_preserve_yaml_order() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")
    schedule = build_strategy_schedule(settings.strategies)

    assert [entry.strategy_config_index for entry in schedule] == list(range(len(schedule)))
    assert all(entry.priority == 100 for entry in schedule)
    assert all(entry.execution_mode == "stateful" for entry in schedule)


def test_strategy_dependency_cycle_is_rejected() -> None:
    schedule = [
        ("a", ["b"]),
        ("b", ["a"]),
    ]

    with pytest.raises(ValueError, match="strategy dependency cycle"):
        validate_strategy_dag(schedule)
