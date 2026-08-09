from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol
from uuid import uuid4

from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.config import SecurityConfigError
from polysignal_lab.domain.strategy_config import ExternalStrategySpec

DEFAULT_STRATEGY_ROOT: Final = "strategies"
_ENV_STRATEGY_ROOT: Final = "POLYSIGNAL_STRATEGY_ROOT"

# Cache resolved classes by path/module so a plugin is imported once per process.
_LOADED_CLASSES: dict[str, type] = {}


@dataclass(frozen=True, slots=True)
class ExternalCoreConfig:
    """Config object handed to an external alpha core constructor.

    Mirrors the shape the native host reads for subscriptions: ``assets`` and
    ``timeframes`` drive market subscriptions, while ``params`` carries the
    free-form plugin parameters declared in YAML.
    """

    name: str
    assets: list[str]
    timeframes: list[str]
    params: dict[str, Any] = field(default_factory=dict)


class ExternalAlphaCore(Protocol):
    """Runtime shape of an external alpha core plugin.

    Satisfies the ``AlphaCore`` protocol (``evaluate``) plus the host-injected
    ``name`` and ``config`` attributes that the runtime relies on for identity
    and market subscriptions.
    """

    name: str
    config: ExternalCoreConfig

    def evaluate(self, view: MarketView) -> list[AlphaDecision]: ...


def external_strategy_root() -> Path:
    """Root directory scanned for file-based external strategy modules."""
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
    target = (root / path_str).resolve() if not candidate.is_absolute() else candidate.resolve()
    # Refuse anything that escapes the sandboxed strategy root.
    try:
        target.relative_to(root)
    except ValueError:
        raise SecurityConfigError(
            f"External strategy module {path_str!r} is outside the strategy root "
            f"{root}; loading is refused."
        )
    if not target.is_file():
        raise FileNotFoundError(f"External strategy module not found: {target}")

    cache_key = f"path:{target}"
    cached = _LOADED_CLASSES.get(cache_key)
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
        raise RuntimeError(f"Failed to execute external strategy {target}: {exc}") from exc

    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(f"{class_name} not found in {target}")
    _LOADED_CLASSES[cache_key] = cls
    return cls


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
        return _load_class_from_path(spec.module, spec.class_name)
    return _load_class_by_name(spec.module, spec.class_name)


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
        params=dict(spec.params),
    )
    try:
        core = cls(core_config)
    except TypeError as exc:
        raise RuntimeError(
            f"External strategy {spec.name!r} core {spec.class_name!r} failed to "
            f"construct from config: {exc}"
        ) from exc
    core.config = core_config
    core.name = spec.name
    return core
