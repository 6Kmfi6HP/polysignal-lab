"""
Input: none
Output: none
Pos: Application code — RETIRED with PolySignalScheduler

This smoke-test runtime was coupled to the legacy PolySignalScheduler.
The Nautilus runtime provides equivalent health probes via
``polysignal_lab.nautilus_runtime.node_probes``.

🔄 Self-reference: When this file changes, update this header
"""

def __getattr__(name: str) -> object:
    raise RuntimeError(
        "readonly_smoke_runtime was retired with PolySignalScheduler. "
        "Use Nautilus runtime health probes instead."
    )
