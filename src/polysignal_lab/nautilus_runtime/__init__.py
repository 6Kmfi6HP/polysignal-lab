"""
Input: polysignal_lab.nautilus_runtime.node, polysignal_lab.nautilus_runtime.node.(
Output: None
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





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
    from polysignal_lab.nautilus_runtime import node

    return getattr(node, name)
