"""
Input: __future__, __future__.annotations, nautilus_trader.common.actor, nautilus_trader.common.actor.Actor, nautilus_trader.config, nautilus_trader.config.ActorConfig, polysignal_lab.nautilus_runtime.decision_policy_actor, polysignal_lab.nautilus_runtime.decision_policy_actor.(, polysignal_lab.nautilus_runtime.market_rotation, polysignal_lab.nautilus_runtime.market_rotation.(
Output: LiveDecisionPolicyActor
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig

from polysignal_lab.nautilus_runtime.decision_policy_actor import (
    NautilusDecisionPolicyActor,
)
from polysignal_lab.nautilus_runtime.market_rotation import (
    MarketRotationActor,
)
from polysignal_lab.nautilus_runtime.native_strategy import (
    PolySignalNativeStrategy,
)

# Direct inheritance — classes already subclass their Nautilus base.
NautilusPolySignalNativeStrategy = PolySignalNativeStrategy
NautilusMarketRotationActor = MarketRotationActor

# NautilusDecisionPolicyActor needs Nautilus Actor registration.
# This wrapper will be eliminated when on_save/on_load migrate into
# DecisionPolicyActor directly via Nautilus-native persistence.
class LiveDecisionPolicyActor(NautilusDecisionPolicyActor, Actor):
    """Nautilus-registerable policy actor."""

    def __init__(self, **kwargs: object) -> None:
        Actor.__init__(self, config=ActorConfig())
        NautilusDecisionPolicyActor.__init__(self, **kwargs)


__all__ = (
    "LiveDecisionPolicyActor",
    "NautilusDecisionPolicyActor",
    "NautilusMarketRotationActor",
    "NautilusPolySignalNativeStrategy",
)
