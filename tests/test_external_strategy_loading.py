from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from polysignal_lab.config import SecurityConfigError, Settings, load_settings
from polysignal_lab.domain.strategy_config import ExternalStrategySpec
from polysignal_lab.nautilus_runtime.runtime_registration import enabled_strategy_names
from polysignal_lab.nautilus_runtime.strategy_loader import (
    build_external_core,
    resolve_external_class,
)


def _write_plugin(directory: Path, filename: str = "my_plugin.py") -> Path:
    path = directory / filename
    path.write_text(
        """
from polysignal_lab.alpha.types import AlphaDecision, MarketView


class MyCore:
    def __init__(self, config) -> None:
        self.config = config
        self.name = getattr(config, "name", "my_core")

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        return []
""",
        encoding="utf-8",
    )
    return path


def test_settings_rejects_external_strategy_without_safety_unlock(tmp_path: Path) -> None:
    config_path = tmp_path / "signal_bot.yaml"
    config_path.write_text(
        """
strategies:
  external:
    - name: my_strat
      enabled: true
      module: my_plugin.py
      class_name: MyCore
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(SecurityConfigError):
        load_settings(config_path)


def test_settings_loads_external_strategy_when_allowed(tmp_path: Path) -> None:
    config_path = tmp_path / "signal_bot.yaml"
    config_path.write_text(
        """
safety:
  allow_external_strategies: true
strategies:
  external:
    - name: my_strat
      enabled: true
      module: my_plugin.py
      class_name: MyCore
      assets: [btc]
      timeframes: [5m]
      params:
        threshold: 0.42
""".strip(),
        encoding="utf-8",
    )
    settings = load_settings(config_path)
    spec = settings.strategies.external_by_name("my_strat")
    assert spec is not None
    assert spec.params == {"threshold": 0.42}
    # explicit names must not include the "external" key
    assert "external" not in settings.strategies.explicit_strategy_names()


def test_enabled_strategy_names_includes_external_when_allowed(tmp_path: Path) -> None:
    config_path = tmp_path / "signal_bot.yaml"
    config_path.write_text(
        """
safety:
  allow_external_strategies: true
strategies:
  late_consensus:
    enabled: true
  external:
    - name: my_strat
      enabled: true
      module: my_plugin.py
      class_name: MyCore
    - name: disabled_strat
      enabled: false
      module: my_plugin.py
      class_name: MyCore
""".strip(),
        encoding="utf-8",
    )
    settings = load_settings(config_path)
    names = enabled_strategy_names(settings)
    assert "late_consensus" in names
    assert "my_strat" in names
    assert "disabled_strat" not in names


def test_enabled_strategy_names_raises_when_external_disabled() -> None:
    # Programmatic construction bypasses the from_yaml gate; the defensive check
    # in enabled_strategy_names must still refuse disabled external strategies.
    settings = Settings.model_validate(
        {
            "strategies": {
                "external": [
                    {
                        "name": "my_strat",
                        "enabled": True,
                        "module": "my_plugin.py",
                        "class_name": "MyCore",
                    }
                ]
            }
        }
    )
    with pytest.raises(SecurityConfigError):
        enabled_strategy_names(settings)


def test_build_external_core_from_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("POLYSIGNAL_STRATEGY_ROOT", str(tmp_path))
    plugin_path = _write_plugin(tmp_path)
    spec = ExternalStrategySpec(
        name="my_strat",
        enabled=True,
        module=plugin_path.name,
        class_name="MyCore",
        assets=["btc"],
        timeframes=["5m"],
        params={"threshold": 0.42},
    )
    core = build_external_core(spec)
    assert core.name == "my_strat"
    assert core.config.name == "my_strat"
    assert core.config.assets == ["BTC"]
    assert core.config.timeframes == ["5m"]
    assert core.config.params == {"threshold": 0.42}
    from datetime import UTC, datetime

    from polysignal_lab.alpha.types import (
        FreshnessView,
        MarketView,
        SideBookView,
        TradingStateView,
    )

    now = datetime.now(UTC)
    side = SideBookView(
        token_id="t", best_bid=None, best_ask=None, spread=None, freshness_ms=None,
    )
    empty = MarketView(
        view_id="v", market_id="m", market_slug="s", condition_id="c",
        asset="BTC", timeframe="5m", start_ts=now, end_ts=now, created_at=now,
        seconds_to_close=0, up=side, down=side, spot=None, price_to_beat=None,
        up_trades=(), down_trades=(),
        metrics={}, freshness=FreshnessView(None, None, None, None),
        trading=TradingStateView(),
    )
    assert core.evaluate(empty) == []


def test_build_external_core_from_importable_module(
    tmp_path: Path, monkeypatch
) -> None:
    pkg = tmp_path / "ext_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    _write_plugin(pkg, "mod.py")
    monkeypatch.syspath_prepend(str(tmp_path))
    spec = ExternalStrategySpec(
        name="mod_strat",
        enabled=True,
        module="ext_pkg.mod",
        class_name="MyCore",
    )
    core = build_external_core(spec)
    assert core.name == "mod_strat"


def test_loader_refuses_paths_outside_strategy_root(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("POLYSIGNAL_STRATEGY_ROOT", str(tmp_path))
    spec = ExternalStrategySpec(
        name="evil",
        enabled=True,
        module="../escape.py",
        class_name="MyCore",
    )
    with pytest.raises(SecurityConfigError):
        build_external_core(spec)


def test_repo_example_plugin_loads() -> None:
    spec = ExternalStrategySpec(
        name="example_external",
        enabled=True,
        module="example_external_strategy.py",
        class_name="ExampleExternalAlphaCore",
    )
    core = build_external_core(spec)
    assert core.name == "example_external"
    assert core.config.assets == ["BTC"]


def test_external_name_collision_with_builtin_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "strategies": {
                    "external": [
                        {"name": "vwap_momentum", "module": "x", "class_name": "Y"}
                    ]
                }
            }
        )


def test_same_file_different_classes_resolve_independently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two specs naming different classes in one file must not alias each other."""
    monkeypatch.setenv("POLYSIGNAL_STRATEGY_ROOT", str(tmp_path))
    (tmp_path / "pair.py").write_text(
        """
class CoreA:
    marker = "A"

    def __init__(self, config) -> None:
        self.config = config

    def evaluate(self, view):
        return [self.marker]


class CoreB:
    marker = "B"

    def __init__(self, config) -> None:
        self.config = config

    def evaluate(self, view):
        return [self.marker]
""",
        encoding="utf-8",
    )
    first = build_external_core(
        ExternalStrategySpec(name="a", module="pair.py", class_name="CoreA")
    )
    second = build_external_core(
        ExternalStrategySpec(name="b", module="pair.py", class_name="CoreB")
    )

    assert type(first).__name__ == "CoreA"
    assert type(second).__name__ == "CoreB"
    # Distinct behaviour, not just distinct names: aliasing would hand both
    # specs the same class and so the same marker.
    assert getattr(first, "marker") == "A"
    assert getattr(second, "marker") == "B"


def test_plugin_file_executes_once_per_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolving two classes from one file must not re-execute the file."""
    monkeypatch.setenv("POLYSIGNAL_STRATEGY_ROOT", str(tmp_path))
    receipt = tmp_path / "executions.log"
    (tmp_path / "counted.py").write_text(
        f"""
with open({str(receipt)!r}, "a", encoding="utf-8") as handle:
    handle.write("x")


class CoreA:
    def __init__(self, config) -> None:
        self.config = config

    def evaluate(self, view):
        return []


class CoreB:
    def __init__(self, config) -> None:
        self.config = config

    def evaluate(self, view):
        return []
""",
        encoding="utf-8",
    )
    first = resolve_external_class(
        ExternalStrategySpec(name="a", module="counted.py", class_name="CoreA")
    )
    second = resolve_external_class(
        ExternalStrategySpec(name="b", module="counted.py", class_name="CoreB")
    )

    assert first is not second
    assert receipt.read_text() == "x"


def test_class_without_evaluate_is_rejected_at_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The AlphaCore protocol is enforced at load, not inside the strategy loop."""
    monkeypatch.setenv("POLYSIGNAL_STRATEGY_ROOT", str(tmp_path))
    (tmp_path / "not_a_core.py").write_text(
        """
class NotACore:
    def __init__(self, config) -> None:
        self.config = config
""",
        encoding="utf-8",
    )
    spec = ExternalStrategySpec(
        name="bad", module="not_a_core.py", class_name="NotACore"
    )
    with pytest.raises(TypeError, match="AlphaCore protocol"):
        build_external_core(spec)


def test_non_class_target_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POLYSIGNAL_STRATEGY_ROOT", str(tmp_path))
    (tmp_path / "func_mod.py").write_text(
        "def evaluate(view):\n    return []\n", encoding="utf-8"
    )
    spec = ExternalStrategySpec(
        name="fn", module="func_mod.py", class_name="evaluate"
    )
    with pytest.raises(TypeError, match="is not a class"):
        build_external_core(spec)


def test_core_refusing_host_attributes_reports_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A __slots__ core without 'name' cannot take the host identity stamp."""
    monkeypatch.setenv("POLYSIGNAL_STRATEGY_ROOT", str(tmp_path))
    (tmp_path / "slotted.py").write_text(
        """
class SlottedCore:
    __slots__ = ("config",)

    def __init__(self, config) -> None:
        self.config = config

    def evaluate(self, view):
        return []
""",
        encoding="utf-8",
    )
    spec = ExternalStrategySpec(
        name="slotted", module="slotted.py", class_name="SlottedCore"
    )
    with pytest.raises(RuntimeError, match="host-assigned 'name'"):
        build_external_core(spec)


def test_external_name_collision_with_model_attribute_rejected() -> None:
    """A plugin named after a StrategyConfig method would shadow that method."""
    for name in ("external_by_name", "explicit_strategy_names", "model_dump"):
        with pytest.raises(ValidationError):
            Settings.model_validate(
                {
                    "strategies": {
                        "external": [
                            {"name": name, "module": "x.py", "class_name": "Y"}
                        ]
                    }
                }
            )
