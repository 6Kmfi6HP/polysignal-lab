"""
Input: None
Output: None
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





def __getattr__(name: str) -> object:
    raise RuntimeError(
        "readonly_smoke_runtime was retired with PolySignalScheduler. "
        "Use Nautilus runtime health probes instead."
    )
