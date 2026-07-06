"""Runtime state surface — strategy ``on_save``/``on_load`` codec.

Re-exports the existing versioned-JSON state codec from
``nautilus_bridge.state`` so the runtime package exposes a stable state entry
point without duplicating logic.
"""

from __future__ import annotations

from polysignal_lab.nautilus_bridge.state import (
    StateSchemaError,
    decode_state,
    encode_state,
    state_key,
)

__all__ = [
    "StateSchemaError",
    "decode_state",
    "encode_state",
    "state_key",
]
