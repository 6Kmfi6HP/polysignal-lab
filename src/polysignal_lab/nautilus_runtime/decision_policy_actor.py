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
