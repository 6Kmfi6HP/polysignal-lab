from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any


@dataclass(frozen=True, slots=True)
class LiveRuntimeSymbols:
    live_node: object
    trader_id: Callable[[str], object]
    environment: object
    polymarket_data_factory: object
    sandbox_exec_factory: object
    polymarket_exec_factory: object
    venue: Callable[[str], object]
    money: Callable[..., object]
    currency_from_str: Callable[[str], object]


def load_live_runtime_symbols() -> LiveRuntimeSymbols:
    """Single load surface for pyo3 LiveNode + factory symbols used by live_node."""
    pyo3 = load_nautilus_module("nautilus_trader.core.nautilus_pyo3")
    return LiveRuntimeSymbols(
        live_node=pyo3.LiveNode,
        trader_id=pyo3.TraderId,
        environment=pyo3.Environment,
        polymarket_data_factory=pyo3.PolymarketDataClientFactory,
        sandbox_exec_factory=pyo3.SandboxExecutionClientFactory,
        polymarket_exec_factory=pyo3.PolymarketExecutionClientFactory,
        venue=pyo3.Venue,
        money=pyo3.Money,
        currency_from_str=pyo3.Currency.from_str,
    )


# Mapping of legacy 1.x module paths to their 2.0 _libnautilus submodule
# equivalents. In nautilus_trader 2.0 the flat ``nautilus_pyo3`` re-export module
# was removed; symbols now live under ``nautilus_trader._libnautilus.<sub>``.
_LEGACY_MODULE_MAP: dict[str, tuple[str, ...]] = {
    "nautilus_trader.core.nautilus_pyo3": (
        # model before common: both expose CustomData and the Rust custom-data
        # registry (register_custom_data_class) keys on the model class object.
        "model",
        "common",
        "core",
        "live",
        "execution",
        "trading",
        "data",
        "sandbox",
        "polymarket",
        "portfolio",
        "infrastructure",
        "persistence",
        "backtest",
        "network",
        "testkit",
    ),
    "nautilus_trader.core.data": ("data", "model"),
    "nautilus_trader.model.enums": ("model",),
}

# Legacy module paths whose 1.x implementations were fully removed in 2.0
# (pure-Python files deleted, no Rust replacement) and are re-provided by
# project-side compatibility modules. Checked BEFORE import_module so paths
# that still exist as real 2.0 modules but lost the needed symbols (e.g.
# ``nautilus_trader.adapters.polymarket`` kept its Rust factories but dropped
# ``get_polymarket_instrument_id``) resolve to the compat module too.
_COMPAT_MODULE_MAP: dict[str, str] = {
    "nautilus_trader.common.config": (
        "polysignal_lab.nautilus_runtime._nautilus_config_compat"
    ),
    "nautilus_trader.trading.config": (
        "polysignal_lab.nautilus_runtime._nautilus_config_compat"
    ),
    "nautilus_trader.model.custom": (
        "polysignal_lab.nautilus_runtime._customdataclass_compat"
    ),
    "nautilus_trader.core.data": "polysignal_lab.nautilus_runtime._customdataclass_compat",
    "nautilus_trader.adapters.polymarket": (
        "polysignal_lab.nautilus_runtime._polymarket_common_compat"
    ),
    "nautilus_trader.adapters.polymarket.common.symbol": (
        "polysignal_lab.nautilus_runtime._polymarket_common_compat"
    ),
    "nautilus_trader.adapters.polymarket.common.gamma_markets": (
        "polysignal_lab.nautilus_runtime._polymarket_common_compat"
    ),
}


class _AggregatedNamespace:
    """A namespace that aggregates attributes from multiple submodules.

    Mirrors the old ``nautilus_pyo3`` flat re-export by transparently
    delegating attribute access to the first submodule that defines it.

    Attributes are resolved lazily via ``getattr`` on the real submodules
    rather than copied at build time: pyo3 module attributes (pyclass
    objects) are not guaranteed to be identity-stable across ``dir()``/``getattr``
    copies, and Rust-side registries (``register_custom_data_class``) key on
    class identity — a copied class object would silently fail registration.
    """

    def __init__(self, submodule_names: tuple[str, ...]) -> None:
        object.__setattr__(self, "_submodule_names", submodule_names)
        object.__setattr__(self, "_modules", [])
        for sub_name in submodule_names:
            full_path = f"nautilus_trader._libnautilus.{sub_name}"
            try:
                mod = import_module(full_path)
            except ImportError:
                continue
            self._modules.append(mod)

    def __getattr__(self, name: str) -> Any:
        # First submodule wins (legacy nautilus_pyo3 resolution order).
        for mod in self._modules:
            if hasattr(mod, name):
                return getattr(mod, name)
        _ensure_compat_extra_symbols()
        if name in _COMPAT_EXTRA_SYMBOLS:
            return _COMPAT_EXTRA_SYMBOLS[name]
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute {name!r}"
        )

    def __dir__(self) -> list[str]:
        names = set(_COMPAT_EXTRA_SYMBOLS)
        for mod in self._modules:
            names.update(a for a in dir(mod) if not a.startswith("_"))
        return sorted(names)


# Symbols removed outright in 2.0 (no _libnautilus home) injected into every
# aggregated legacy namespace. Loaded lazily so project compat modules that
# import this module themselves do not create an import cycle.
_COMPAT_EXTRA_SYMBOLS: dict[str, object] = {}


def _ensure_compat_extra_symbols() -> None:
    if _COMPAT_EXTRA_SYMBOLS:
        return
    from importlib import import_module as _import

    config_compat = _import("polysignal_lab.nautilus_runtime._nautilus_config_compat")
    _COMPAT_EXTRA_SYMBOLS["ActorConfig"] = config_compat.ActorConfig


def _aggregate_submodules(submodule_names: tuple[str, ...]) -> Any:
    """Build a namespace exposing symbols from all given _libnautilus submodules."""
    return _AggregatedNamespace(submodule_names)


def load_nautilus_module(module_path: str) -> object:
    """Single import surface for any NautilusTrader module.

    Every runtime/data/promotion module that previously did a direct
    ``from nautilus_trader.<path> import ...`` now resolves the module object
    through this entrypoint and binds attributes off it. ``import_module``
    returns the same module object a ``from`` import binds, so attribute
    identity (class objects used as bases, ``isinstance`` targets, enum
    members) is preserved exactly — this is a pure import migration with no
    runtime semantic change.

    For legacy 1.x paths (``nautilus_trader.core.nautilus_pyo3`` etc.) that no
    longer exist in 2.0, this returns an aggregated namespace that
    transparently re-exports the symbols from their new ``_libnautilus``
    submodule homes.

    Callers are responsible for only invoking this when Nautilus is available
    (i.e. the module is already importable in the running process). It is not
    used at ``polysignal_lab`` package import time, so the package stays
    importable without Nautilus installed.
    """
    compat_module = _COMPAT_MODULE_MAP.get(module_path)
    if compat_module is not None:
        return import_module(compat_module)
    try:
        return import_module(module_path)
    except ImportError:
        # Fall back to the legacy->2.0 aggregate mapping.
        submodules = _LEGACY_MODULE_MAP.get(module_path)
        if submodules is None:
            raise
        return _aggregate_submodules(submodules)
