from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Final, cast

from nautilus_trader.common.config import ActorConfig
from nautilus_trader.core import nautilus_pyo3
from nautilus_trader.core.nautilus_pyo3 import ActorId, DataActor

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.custom_data_types import (
    custom_data_type,
    unwrap_custom_data,
    wrap_custom_data,
)
from polysignal_lab.nautilus_runtime.decision_messages import (
    DecisionCandidateData,
    DecisionResultData,
)
from polysignal_lab.nautilus_runtime.decision_policy import (
    DecisionPolicy,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.runtime_configs import importable_config_dict
from polysignal_lab.nautilus_runtime.state import JsonValue, decode_state, encode_state
from polysignal_lab.signal_layer.arbiter import SignalArbiter
from polysignal_lab.signal_layer.consensus import ConsensusEngine
from polysignal_lab.signal_layer.gate import SignalGate


_DEFAULT_ACTOR_ID: Final = "PolySignal-DecisionPolicy"


class DecisionPolicyActorConfig(ActorConfig, frozen=True):
    settings_json: str
    strategy_names: tuple[str, ...] = ()
    actor_id: str = _DEFAULT_ACTOR_ID

    @classmethod
    def build(cls, settings: Settings) -> DecisionPolicyActorConfig:
        actor_id = _DEFAULT_ACTOR_ID
        return cls(
            settings_json=settings.model_dump_json(),
            strategy_names=tuple(settings.strategies.explicit_strategy_names()),
            actor_id=actor_id,
            component_id=actor_id,
        )

    def settings(self) -> Settings:
        settings = Settings.model_validate_json(self.settings_json)
        settings.strategies.set_explicit_strategy_names(tuple(self.strategy_names))
        return settings

    def importable_dict(self) -> dict[str, object]:
        return importable_config_dict(self)


class DecisionPolicyActor(DataActor):
    POLICY_OWNER_ID = _DEFAULT_ACTOR_ID
    state_name = "decision_policy"

    def __new__(
        cls,
        config: DecisionPolicyActorConfig | None = None,
        *,
        policy: DecisionPolicy | None = None,
    ) -> DecisionPolicyActor:
        return super().__new__(cls)

    def __init__(
        self,
        config: DecisionPolicyActorConfig | None = None,
        *,
        policy: DecisionPolicy | None = None,
    ) -> None:
        resolved = config or DecisionPolicyActorConfig(
            settings_json=Settings().model_dump_json(),
            component_id=_DEFAULT_ACTOR_ID,
        )
        config_type = getattr(nautilus_pyo3, "DataActorConfig")
        actor_config = config_type(actor_id=ActorId(str(resolved.actor_id)))
        super().__init__(actor_config)
        self.policy = policy or _policy_from_settings(resolved.settings())
        self._pending_batches: dict[str, dict[int, DecisionCandidateData]] = {}

    def on_start(self) -> None:
        self.subscribe_data(custom_data_type(DecisionCandidateData))

    def on_data(self, data: object) -> None:
        payload = unwrap_custom_data(data)
        if not isinstance(payload, DecisionCandidateData):
            return
        if payload.batch_size < 1 or not 0 <= payload.batch_index < payload.batch_size:
            self._publish_rejection(payload, "INVALID_BATCH_METADATA")
            return
        batch = self._pending_batches.setdefault(payload.batch_id, {})
        if payload.batch_index in batch:
            self._publish_rejection(payload, "DUPLICATE_BATCH_INDEX")
            return
        if batch and any(item.batch_size != payload.batch_size for item in batch.values()):
            pending = tuple(batch.values())
            del self._pending_batches[payload.batch_id]
            for item in (*pending, payload):
                self._publish_rejection(item, "INCONSISTENT_BATCH_SIZE")
            return
        batch[payload.batch_index] = payload
        if len(batch) != payload.batch_size:
            return
        requests = tuple(batch[index] for index in range(payload.batch_size))
        del self._pending_batches[payload.batch_id]
        for result in self.evaluate_batch(requests):
            self._publish(result)

    def on_stop(self) -> None:
        self._pending_batches.clear()

    def on_save(self) -> dict[str, bytes]:
        policy_state = cast(Mapping[str, JsonValue], self.policy.save_state())
        return encode_state(self.state_name, {"policy": dict(policy_state)})

    def on_load(self, state: Mapping[str, bytes]) -> None:
        payload = cast(Mapping[str, object], decode_state(self.state_name, state))
        policy_state = payload.get("policy", {})
        if isinstance(policy_state, Mapping):
            self.policy.load_state(policy_state)
        self._pending_batches.clear()

    def evaluate_batch(
        self,
        requests: Sequence[DecisionCandidateData],
    ) -> tuple[DecisionResultData, ...]:
        decoded = tuple(request.to_domain() for request in requests)
        arbitration = self.policy.batch_arbitrate(list(decoded))
        survivor_ids = {id(decision) for decision in arbitration}
        rejected_by_id = {
            id(decision): rejected for decision, rejected in arbitration.rejections
        }
        results: list[DecisionResultData] = []
        for request, (decision, view) in zip(requests, decoded, strict=True):
            if id(decision) not in survivor_ids:
                rejected = rejected_by_id.get(id(decision)) or RejectedDecision(
                    reason_code="ARBITRATION_SUPPRESSED",
                    detail={},
                )
                results.append(
                    DecisionResultData.from_rejected(
                        request_id=request.request_id,
                        rejected=rejected,
                        ts_event=request.ts_event,
                        ts_init=request.ts_init,
                    )
                )
                continue
            policy_result = self.policy.decide(decision, view)
            if isinstance(policy_result, RejectedDecision):
                results.append(
                    DecisionResultData.from_rejected(
                        request_id=request.request_id,
                        rejected=policy_result,
                        ts_event=request.ts_event,
                        ts_init=request.ts_init,
                    )
                )
                continue
            results.append(
                DecisionResultData.from_approved(
                    request_id=request.request_id,
                    signal=policy_result.signal,
                    ts_event=request.ts_event,
                    ts_init=request.ts_init,
                )
            )
        return tuple(results)

    def _publish_rejection(
        self,
        request: DecisionCandidateData,
        reason_code: str,
    ) -> None:
        result = DecisionResultData.from_rejected(
            request_id=request.request_id,
            rejected=RejectedDecision(reason_code=reason_code, detail={}),
            ts_event=request.ts_event,
            ts_init=request.ts_init,
        )
        self._publish(result)

    def _publish(self, result: DecisionResultData) -> None:
        publish_data = cast(
            Callable[[object, object], None],
            object.__getattribute__(self, "publish_data"),
        )
        publish_data(
            custom_data_type(DecisionResultData),
            wrap_custom_data(result),
        )


def _policy_from_settings(settings: Settings) -> DecisionPolicy:
    dependencies: dict[str, tuple[str, ...]] = {}
    for name in settings.strategies.explicit_strategy_names():
        strategy_config = getattr(settings.strategies, name, None)
        if strategy_config is None or not bool(getattr(strategy_config, "enabled", False)):
            continue
        execution = getattr(strategy_config, "execution")
        dependencies[name] = tuple(str(item) for item in getattr(execution, "depends_on"))
    return DecisionPolicy(
        gate=SignalGate(
            settings.signal,
            settings.data.polymarket,
            settings.data.binance,
        ),
        arbiter=SignalArbiter(),
        consensus=ConsensusEngine(
            window_sec=settings.signal.consensus_window_sec,
            enabled=settings.signal.consensus_enabled,
        ),
        dependencies=dependencies,
    )
