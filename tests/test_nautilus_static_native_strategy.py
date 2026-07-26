from __future__ import annotations

from types import SimpleNamespace

from polysignal_lab.alpha.types import AlphaCore
from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy


class _FakeAssembler:
    def build(self, condition_id: str, *, created_at=None):  # noqa: ANN001
        _ = condition_id, created_at
        return None

    def with_custom_data(self, custom_data: object) -> _FakeAssembler:
        _ = custom_data
        return self


class _FakeRegistry:
    def by_condition(self, _condition_id: str) -> None:
        return None


class _FakeCore:
    def evaluate(self, view: object) -> list[object]:
        _ = view
        return []


def test_static_native_strategy_initializes_nautilus_base() -> None:
    strategy = PolySignalNativeStrategy(
        core=_FakeCore(),  # type: ignore[arg-type]
        assembler=_FakeAssembler(),
        condition_ids=(),
        strategy_name="polysignal",
        registry=_FakeRegistry(),  # type: ignore[arg-type]
    )

    assert strategy.strategy_name == "polysignal"
    assert hasattr(strategy, "strategy_id")
    assert isinstance(strategy.core, _FakeCore)
    assert hasattr(strategy, "policy")
    assert callable(strategy.policy.decide)
    _ = AlphaCore, SimpleNamespace  # keep alpha protocol import used for typing intent
