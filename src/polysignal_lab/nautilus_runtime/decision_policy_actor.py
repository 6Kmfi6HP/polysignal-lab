"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, typing, typing.cast, polysignal_lab.nautilus_bridge.state, polysignal_lab.nautilus_bridge.state.JsonValue, polysignal_lab.nautilus_bridge.state.decode_state, polysignal_lab.nautilus_bridge.state.encode_state
Output: NautilusDecisionPolicyActor
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from polysignal_lab.nautilus_bridge.state import JsonValue, decode_state, encode_state
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor


class NautilusDecisionPolicyActor(DecisionPolicyActor):
    """Nautilus lifecycle seam for the pure decision policy engine."""

    state_name = "decision_policy"

    def on_save(self) -> dict[str, bytes]:
        payload = cast(Mapping[str, JsonValue], self.save_state())
        return encode_state(self.state_name, payload)

    def on_load(self, state: Mapping[str, bytes]) -> None:
        payload = cast(Mapping[str, object], decode_state(self.state_name, state))
        self.load_state(payload)
