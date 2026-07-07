"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, typing, typing.cast, polysignal_lab.nautilus_bridge.state, polysignal_lab.nautilus_bridge.state.JsonValue, polysignal_lab.nautilus_bridge.state.decode_state, polysignal_lab.nautilus_bridge.state.encode_state
Output: NautilusDecisionPolicyActor
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig

from polysignal_lab.nautilus_bridge.state import JsonValue, decode_state, encode_state
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor


class NautilusDecisionPolicyActor(DecisionPolicyActor, Actor):
    """Nautilus lifecycle seam for the pure decision policy engine.

    Inherits Actor directly so the class is Nautilus-registerable without a
    runtime_classes wrapper.  The on_save/on_load lifecycle hooks call
    DecisionPolicyActor.save_state() / load_state() and encode/decode through
    the Nautilus state bridge.
    """

    state_name = "decision_policy"

    def __init__(self, **kwargs: object) -> None:
        Actor.__init__(self, config=ActorConfig())
        DecisionPolicyActor.__init__(self, **kwargs)

    def on_save(self) -> dict[str, bytes]:
        payload = cast(Mapping[str, JsonValue], self.save_state())
        return encode_state(self.state_name, payload)

    def on_load(self, state: Mapping[str, bytes]) -> None:
        payload = cast(Mapping[str, object], decode_state(self.state_name, state))
        self.load_state(payload)
