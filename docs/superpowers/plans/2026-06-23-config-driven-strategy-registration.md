# Config-Driven Strategy Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hard-coded PRD strategy whitelist with config-driven strategy activation.

**Architecture:** `Settings.from_yaml()` records which strategy sections were explicitly present after YAML plus environment overrides. `StrategyConfig` exposes those names in YAML order. `factory.build_strategies()` uses the complete implementation registry but instantiates only explicit enabled strategies.

**Tech Stack:** Python 3, Pydantic v2, pydantic-settings, pytest, Docker scheduler runtime.

## Global Constraints

- Only strategies explicitly present in `config/signal_bot.yaml` and set `enabled: true` should start by default.
- Unknown strategy names must still fail validation via `extra="forbid"`.
- Do not change strategy trading logic, thresholds, paper trading, Telegram, or dashboard behavior.
- Do not enable additional strategies in `config/signal_bot.yaml` unless requested separately.
- PRD wording changes from code whitelist to recommended default production strategy set.

---

## File Structure

- Modify `src/polysignal_lab/strategies/config.py`: remove Non-PRD rejection; add explicit strategy name private state, public helper, and explicit-aware `__iter__()`.
- Modify `src/polysignal_lab/config.py`: capture explicit strategy names in `Settings.from_yaml()` after YAML plus env overrides, then attach them to `settings.strategies`.
- Modify `src/polysignal_lab/strategies/factory.py`: register all implemented strategy classes and build only explicit enabled names.
- Modify `tests/test_config.py`: replace PRD-whitelist assertions with config-driven activation tests.
- Verify with focused tests: `pytest tests/test_config.py -v`.

---

### Task 1: Explicit Strategy Metadata

**Files:**
- Modify: `tests/test_config.py`
- Modify: `src/polysignal_lab/strategies/config.py`
- Modify: `src/polysignal_lab/config.py`

**Interfaces:**
- Produces: `StrategyConfig.explicit_strategy_names() -> tuple[str, ...]`
- Produces: `StrategyConfig.set_explicit_strategy_names(names: Iterable[str]) -> None`
- Produces: `StrategyConfig.__iter__() -> Iterator[BaseModel]` yielding explicit strategy configs in recorded order.

- [ ] **Step 1: Write failing metadata tests**

Add imports and tests to `tests/test_config.py`:

```python
from pathlib import Path


def test_load_settings_records_explicit_strategy_names(tmp_path: Path) -> None:
    config_path = tmp_path / "signal_bot.yaml"
    config_path.write_text(
        """
strategies:
  late_consensus:
    enabled: true
  fibonacci_bot:
    enabled: true
    require_momentum_confirmation: false
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.strategies.explicit_strategy_names() == (
        "late_consensus",
        "fibonacci_bot",
    )
    assert [strategy_config.name for strategy_config in settings.strategies] == [
        "late_consensus",
        "fibonacci_bot",
    ]


def test_settings_model_validate_has_no_explicit_strategy_names() -> None:
    settings = Settings.model_validate(
        {
            "strategies": {
                "late_consensus": {
                    "enabled": True,
                },
            },
        }
    )

    assert settings.strategies.explicit_strategy_names() == ()
    assert list(settings.strategies) == []
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_config.py::test_load_settings_records_explicit_strategy_names tests/test_config.py::test_settings_model_validate_has_no_explicit_strategy_names -v`

Expected: FAIL because `explicit_strategy_names` / explicit-aware iteration does not exist yet.

- [ ] **Step 3: Implement explicit metadata on `StrategyConfig`**

In `src/polysignal_lab/strategies/config.py`:

```python
from collections.abc import Iterable, Iterator, Mapping
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, RootModel
```

Inside `StrategyConfig`:

```python
    _explicit_strategy_names: tuple[str, ...] = PrivateAttr(default=())

    def set_explicit_strategy_names(self, names: Iterable[str]) -> None:
        self._explicit_strategy_names = tuple(names)

    def explicit_strategy_names(self) -> tuple[str, ...]:
        return self._explicit_strategy_names
```

Replace `__iter__()` with:

```python
    def __iter__(self) -> Iterator[BaseModel]:
        for name in self._explicit_strategy_names:
            yield getattr(self, name)
```

Remove `reject_restored_strategy_overrides()` entirely.

- [ ] **Step 4: Capture explicit names in `Settings.from_yaml()`**

In `src/polysignal_lab/config.py`, after env overrides and before `settings.validate_runtime_environment()`:

```python
        explicit_strategy_names: tuple[str, ...] = ()
        strategies_data = data.get("strategies")
        if isinstance(strategies_data, dict):
            explicit_strategy_names = tuple(strategies_data)
        settings = cls.model_validate(data)
        settings.strategies.set_explicit_strategy_names(explicit_strategy_names)
        settings.validate_runtime_environment()
        return settings
```

- [ ] **Step 5: Run metadata tests**

Run: `pytest tests/test_config.py::test_load_settings_records_explicit_strategy_names tests/test_config.py::test_settings_model_validate_has_no_explicit_strategy_names -v`

Expected: PASS.

---

### Task 2: Complete Strategy Registry and Config-Driven Build

**Files:**
- Modify: `tests/test_config.py`
- Modify: `src/polysignal_lab/strategies/factory.py`

**Interfaces:**
- Consumes: `StrategyConfig.explicit_strategy_names() -> tuple[str, ...]`
- Produces: `build_strategies(config: StrategyConfig) -> list[BaseStrategy]` using explicit enabled strategy names.
- Produces: `_STRATEGY_REGISTRY` containing all implemented strategies.

- [ ] **Step 1: Replace old PRD factory tests**

Replace `test_strategy_factory_builds_only_prd_strategies` and `test_non_prd_strategy_config_rejected` in `tests/test_config.py` with:

```python
def test_strategy_factory_builds_default_configured_strategies() -> None:
    from polysignal_lab.strategies.factory import build_strategy

    settings = load_settings("config/signal_bot.yaml")

    strategy_names = [strategy.name for strategy in build_strategies(settings.strategies)]
    single_strategy_names = [
        build_strategy(strategy_config).name for strategy_config in settings.strategies
    ]

    assert strategy_names == ["vwap_momentum", "late_consensus", "ptb_diff"]
    assert single_strategy_names == strategy_names


def test_explicit_restored_strategy_can_be_built(tmp_path: Path) -> None:
    config_path = tmp_path / "signal_bot.yaml"
    config_path.write_text(
        """
strategies:
  fibonacci_bot:
    enabled: true
    require_momentum_confirmation: false
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert [strategy.name for strategy in build_strategies(settings.strategies)] == [
        "fibonacci_bot"
    ]


def test_disabled_explicit_strategy_is_skipped(tmp_path: Path) -> None:
    config_path = tmp_path / "signal_bot.yaml"
    config_path.write_text(
        """
strategies:
  fibonacci_bot:
    enabled: false
    require_momentum_confirmation: false
  late_consensus:
    enabled: true
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert [strategy.name for strategy in build_strategies(settings.strategies)] == [
        "late_consensus"
    ]


def test_unknown_strategy_config_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "strategies": {
                    "unknown_strategy": {
                        "enabled": True,
                    },
                },
            }
        )
```

- [ ] **Step 2: Run tests to verify factory failure**

Run: `pytest tests/test_config.py::test_explicit_restored_strategy_can_be_built tests/test_config.py::test_disabled_explicit_strategy_is_skipped -v`

Expected: FAIL because `_STRATEGY_REGISTRY` still contains only PRD strategies.

- [ ] **Step 3: Register all implemented strategy classes**

In `src/polysignal_lab/strategies/factory.py`, replace `PrdStrategyConfig` with:

```python
StrategyConfigModel = (
    VWAPMomentumConfig
    | LateConsensusConfig
    | PTBDiffConfig
    | BinaryMomentumConfig
    | CrossMarketBotConfig
    | DumpHedgeConfig
    | FibonacciBotConfig
    | LowSideDualReversionConfig
    | MidPriceSizingConfig
    | NinetyNineCentSniperConfig
    | OneCentBuyConfig
    | PreOrderMarketConfig
    | SkewMeanReversionConfig
)
```

Replace `_STRATEGY_REGISTRY` with:

```python
_STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "vwap_momentum": VWAPMomentumStrategy,
    "late_consensus": LateConsensusStrategy,
    "ptb_diff": PTBDiffStrategy,
    "binary_momentum": BinaryMomentumStrategy,
    "cross_market_bot": CrossMarketBotStrategy,
    "dump_hedge": DumpHedgeStrategy,
    "fibonacci_bot": FibonacciStrategyBot,
    "low_side_dual_reversion": LowSideDualReversionStrategy,
    "mid_price_sizing": MidPriceSizingStrategy,
    "ninety_nine_cent_sniper": NinetyNineCentSniperStrategy,
    "one_cent_buy": OneCentBuyStrategy,
    "pre_order_market": PreOrderMarketStrategy,
    "skew_mean_reversion": SkewMeanReversionStrategy,
}
```

- [ ] **Step 4: Make `build_strategies()` explicit-driven**

Replace `build_strategies()` with:

```python
def build_strategies(config: StrategyConfig) -> list[BaseStrategy]:
    strategies: list[BaseStrategy] = []
    for name in config.explicit_strategy_names():
        strategy_cls = _STRATEGY_REGISTRY.get(name)
        if strategy_cls is None:
            raise ValueError(
                f"Strategy {name!r} has config but no registered implementation"
            )
        cfg = getattr(config, name)
        if getattr(cfg, "enabled", False):
            strategies.append(strategy_cls(cfg))
    return strategies
```

Change `build_strategy(config: PrdStrategyConfig)` to:

```python
def build_strategy(config: StrategyConfigModel) -> BaseStrategy:
```

- [ ] **Step 5: Run factory tests**

Run: `pytest tests/test_config.py::test_strategy_factory_builds_default_configured_strategies tests/test_config.py::test_explicit_restored_strategy_can_be_built tests/test_config.py::test_disabled_explicit_strategy_is_skipped tests/test_config.py::test_unknown_strategy_config_rejected -v`

Expected: PASS.

---

### Task 3: Focused Verification and Runtime Smoke Check

**Files:**
- Verify only; no planned source edits.

**Interfaces:**
- Consumes: completed Task 1 and Task 2 behavior.

- [ ] **Step 1: Run full config test file**

Run: `pytest tests/test_config.py -v`

Expected: all tests PASS.

- [ ] **Step 2: Verify current production config still builds only three strategies**

Run:

```bash
python - <<'PY'
from polysignal_lab.config import load_settings
from polysignal_lab.strategies.factory import build_strategies
settings = load_settings('config/signal_bot.yaml')
print(settings.strategies.explicit_strategy_names())
print([strategy.name for strategy in build_strategies(settings.strategies)])
PY
```

Expected output includes:

```text
('vwap_momentum', 'late_consensus', 'ptb_diff')
['vwap_momentum', 'late_consensus', 'ptb_diff']
```

- [ ] **Step 3: Verify explicit restored strategy can be built from a temporary config**

Run:

```bash
python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from polysignal_lab.config import load_settings
from polysignal_lab.strategies.factory import build_strategies
with TemporaryDirectory() as td:
    path = Path(td) / 'signal_bot.yaml'
    path.write_text('''
strategies:
  fibonacci_bot:
    enabled: true
    require_momentum_confirmation: false
'''.strip(), encoding='utf-8')
    settings = load_settings(path)
    print(settings.strategies.explicit_strategy_names())
    print([strategy.name for strategy in build_strategies(settings.strategies)])
PY
```

Expected output includes:

```text
('fibonacci_bot',)
['fibonacci_bot']
```

- [ ] **Step 4: Commit implementation**

Run:

```bash
git add src/polysignal_lab/config.py src/polysignal_lab/strategies/config.py src/polysignal_lab/strategies/factory.py tests/test_config.py docs/superpowers/plans/2026-06-23-config-driven-strategy-registration.md
git commit -m "feat: make strategy registration config-driven"
```
