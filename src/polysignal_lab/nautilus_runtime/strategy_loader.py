from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Protocol
from uuid import uuid4

from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.config import SecurityConfigError
from polysignal_lab.domain.strategy_config import ExternalStrategySpec

DEFAULT_STRATEGY_ROOT: Final = "strategies"
_ENV_STRATEGY_ROOT: Final = "POLYSIGNAL_STRATEGY_ROOT"

# A plugin file is executed once per process; several specs may name different
# classes in the same file, so classes are resolved off the cached module rather
# than cached per path. Importable modules are cached per module+class instead,
# since the import system already deduplicates their execution.
_LOADED_MODULES: dict[str, ModuleType] = {}
_LOADED_CLASSES: dict[str, type] = {}


@dataclass(frozen=True, slots=True)
class ExternalCoreConfig:
    """Hold the config handed to an external alpha core constructor.

    Mirror the shape the native host reads for subscriptions: ``assets`` and
    ``timeframes`` drive market subscriptions, while ``parameters`` carries the
    free-form plugin parameters declared in YAML.
    """

    name: str
    assets: list[str]
    timeframes: list[str]
    parameters: dict[str, Any] = field(default_factory=dict)


class ExternalAlphaCore(Protocol):
    """Describe the runtime shape of an external alpha core plugin.

    Satisfy the ``AlphaCore`` protocol (``evaluate``) plus the host-injected
    ``name`` and ``config`` attributes that the runtime relies on for identity
    and market subscriptions.
    """

    name: str
    config: ExternalCoreConfig

    def evaluate(self, view: MarketView) -> list[AlphaDecision]: ...


def external_strategy_root() -> Path:
    """Return the root directory for file-based external strategies."""
    raw = os.environ.get(_ENV_STRATEGY_ROOT)
    return Path(raw) if raw else Path(DEFAULT_STRATEGY_ROOT)


def _is_path_reference(module: str) -> bool:
    return module.endswith(".py") or "/" in module or "\\" in module


def _normalized_assets(values: list[str]) -> list[str]:
    return [v.upper() for v in values]


def _normalized_timeframes(values: list[str]) -> list[str]:
    return [v.strip().lower() for v in values]


def _load_class_from_path(path_str: str, class_name: str) -> type:
    root = external_strategy_root().resolve()
    candidate = Path(path_str)
    target = (
        (root / path_str).resolve()
        if not candidate.is_absolute()
        else candidate.resolve()
    )
    # Refuse anything that escapes the sandboxed strategy root
    try:
        target.relative_to(root)
    except ValueError:
        raise SecurityConfigError(
            f"External strategy module {path_str!r} is outside the strategy root "
            f"{root}; loading is refused."
        )
    if not target.is_file():
        raise FileNotFoundError(f"External strategy module not found: {target}")

    module = _module_from_path(target)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(f"{class_name} not found in {target}")
    return cls


def _module_from_path(target: Path) -> ModuleType:
    cache_key = str(target)
    cached = _LOADED_MODULES.get(cache_key)
    if cached is not None:
        return cached

    mod_name = f"_polysignal_external_{target.stem}_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(mod_name, target)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import external strategy from {target}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - surface user code errors clearly
        sys.modules.pop(mod_name, None)
        raise RuntimeError(
            f"Failed to execute external strategy {target}: {exc}"
        ) from exc

    _LOADED_MODULES[cache_key] = module
    return module


def _load_class_by_name(module_str: str, class_name: str) -> type:
    cache_key = f"module:{module_str}:{class_name}"
    cached = _LOADED_CLASSES.get(cache_key)
    if cached is not None:
        return cached
    module = importlib.import_module(module_str)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(f"{class_name} not found in module {module_str!r}")
    _LOADED_CLASSES[cache_key] = cls
    return cls


def resolve_external_class(spec: ExternalStrategySpec) -> type:
    """Resolve the alpha core class referenced by a plugin spec."""
    if _is_path_reference(spec.module):
        cls = _load_class_from_path(spec.module, spec.class_name)
    else:
        cls = _load_class_by_name(spec.module, spec.class_name)
    _require_alpha_core(spec, cls)
    return cls


def _require_alpha_core(spec: ExternalStrategySpec, cls: type) -> None:
    """Reject a resolved class that cannot act as an ``AlphaCore``.

    The protocol is structural, so it is checked here rather than deep in the
    strategy loop where a missing ``evaluate`` would surface as an opaque
    ``AttributeError`` per market update.
    """
    if not isinstance(cls, type):
        raise TypeError(
            f"External strategy {spec.name!r} target {spec.class_name!r} in "
            f"{spec.module!r} is not a class, was {type(cls).__name__}"
        )
    if not callable(getattr(cls, "evaluate", None)):
        raise TypeError(
            f"External strategy {spec.name!r} core {spec.class_name!r} does not "
            "satisfy the AlphaCore protocol: a callable "
            "evaluate(view) -> list[AlphaDecision] is required"
        )


def build_external_core(spec: ExternalStrategySpec) -> ExternalAlphaCore:
    """Instantiate an external alpha core from a plugin spec.

    The host reads ``core.config.assets`` / ``core.config.timeframes`` for
    market subscriptions and ``core.name`` for identity, so we always set those
    regardless of what the user core does with the config it receives.
    """
    cls = resolve_external_class(spec)
    core_config = ExternalCoreConfig(
        name=spec.name,
        assets=_normalized_assets(spec.assets),
        timeframes=_normalized_timeframes(spec.timeframes),
        parameters=dict(spec.parameters),
    )
    try:
        core = cls(core_config)
    except TypeError as exc:
        raise RuntimeError(
            f"External strategy {spec.name!r} core {spec.class_name!r} failed to "
            f"construct from config: {exc}"
        ) from exc
    _inject_host_identity(spec, core, core_config)
    return core


def _inject_host_identity(
    spec: ExternalStrategySpec,
    core: object,
    core_config: ExternalCoreConfig,
) -> None:
    for attribute, value in (("config", core_config), ("name", spec.name)):
        try:
            setattr(core, attribute, value)
        except AttributeError as exc:
            raise RuntimeError(
                f"External strategy {spec.name!r} core {spec.class_name!r} does "
                f"not accept the host-assigned {attribute!r} attribute: {exc}; "
                "the core must allow attribute assignment (no __slots__ without "
                f"{attribute!r}, no frozen dataclass)"
            ) from exc
