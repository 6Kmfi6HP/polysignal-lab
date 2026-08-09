from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from polysignal_lab.config import SecurityConfigError, Settings, load_settings
from polysignal_lab.domain.strategy_config import ExternalStrategySpec
from polysignal_lab.nautilus_runtime.runtime_registration import enabled_strategy_names
from polysignal_lab.nautilus_runtime.strategy_loader import build_external_core


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
