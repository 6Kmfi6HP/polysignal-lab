import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Static-only: keeps the lazy runtime import below from erasing these to `object`.
    from polysignal_lab.nautilus_runtime.node import (
        NautilusRuntimeBundle as NautilusRuntimeBundle,
        build_live_node as build_live_node,
        build_nautilus_runtime as build_nautilus_runtime,
        run_nautilus_cli as run_nautilus_cli,
        run_nautilus_cli_async as run_nautilus_cli_async,
    )

__all__ = [
    "NautilusRuntimeBundle",
    "build_nautilus_runtime",
    "build_live_node",
    "run_nautilus_cli",
    "run_nautilus_cli_async",
]


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(name)
    # import_module honours sys.modules, so callers see the same node module a
    # direct `from ...node import name` would resolve to.
    node = importlib.import_module("polysignal_lab.nautilus_runtime.node")
    return getattr(node, name)
