from __future__ import annotations

from dataclasses import replace

import pytest
from nautilus_trader.core import nautilus_pyo3

from factories import sample_market_view
from nautilus_runtime_contracts_harness import (
    build_backtest_engine,
    synthetic_quotes,
)
from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.config import Settings
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.decision_messages import (
    DecisionCandidateData,
    DecisionResultData,
)
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    BatchArbitrationResult,
    DecisionPolicy,
    RejectedDecision,
    candidate_from_decision,
)
from polysignal_lab.nautilus_runtime.decision_policy_actor import (
    DecisionPolicyActor,
    DecisionPolicyActorConfig,
)
from polysignal_lab.nautilus_runtime.custom_data_types import (
    custom_data_type,
    unwrap_custom_data,
    wrap_custom_data,
)


def test_candidate_message_is_immutable_and_round_trips_domain_values() -> None:
    view = sample_market_view()
    decision = AlphaDecision(
        strategy="ptb_diff",
        asset=view.asset,
        timeframe=view.timeframe,
        market_id=view.market_id,
        market_slug=view.market_slug,
        condition_id=view.condition_id,
        token_id=view.up.token_id,
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.51,
        max_entry_price=0.52,
        seconds_to_close=view.seconds_to_close,
        data_freshness_ms=view.freshness.max_ms,
        reason_codes=("PTB_EDGE",),
        metrics={"edge": 0.1},
    )

    message = DecisionCandidateData.from_domain(
        request_id="request-1",
        batch_id="batch-1",
        batch_index=0,
        batch_size=1,
        decision=decision,
        view=view,
        ts_event=1,
        ts_init=1,
    )

    restored_decision, restored_view = message.to_domain()
    assert restored_decision == decision
    assert restored_view.condition_id == view.condition_id
    assert restored_view.up == view.up
    wrapped = wrap_custom_data(message)
    assert wrapped.data_type == custom_data_type(DecisionCandidateData)
    assert unwrap_custom_data(wrapped) is message
    with pytest.raises(AttributeError, match="immutable"):
        message.request_id = "mutated"


def test_policy_actor_evaluates_the_complete_batch_as_single_owner() -> None:
    view = sample_market_view()
    decision = AlphaDecision(
        strategy="ptb_diff",
        asset=view.asset,
        timeframe=view.timeframe,
        market_id=view.market_id,
        market_slug=view.market_slug,
        condition_id=view.condition_id,
        token_id=view.up.token_id,
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.51,
        max_entry_price=0.52,
        seconds_to_close=view.seconds_to_close,
        data_freshness_ms=view.freshness.max_ms,
        reason_codes=("PTB_EDGE",),
        metrics={"edge": 0.1},
    )

    class AllowPolicy(DecisionPolicy):
        def batch_arbitrate(
            self,
            decisions: list[tuple[AlphaDecision, MarketView]],
        ) -> BatchArbitrationResult:
            return BatchArbitrationResult(item[0] for item in decisions)

        def decide(self, decision: AlphaDecision, view: MarketView) -> ApprovedDecision:
            return ApprovedDecision(signal=candidate_from_decision(decision, view))

    actor = DecisionPolicyActor(policy=AllowPolicy())
    request = DecisionCandidateData.from_domain(
        request_id="request-1",
        batch_id="batch-1",
        batch_index=0,
        batch_size=1,
        decision=decision,
        view=view,
        ts_event=1,
        ts_init=1,
    )

    result = actor.evaluate_batch((request,))

    assert result == (
        DecisionResultData.from_approved(
            request_id="request-1",
            signal=candidate_from_decision(decision, view),
            ts_event=1,
            ts_init=1,
        ),
    )


def test_policy_actor_builds_its_only_policy_from_serialized_config() -> None:
    config = DecisionPolicyActorConfig(settings_json=Settings().model_dump_json())

    actor = DecisionPolicyActor(config=config)

    assert str(actor.config.actor_id) == DecisionPolicyActor.POLICY_OWNER_ID
    assert isinstance(actor.policy, DecisionPolicy)


def test_policy_actor_returns_one_result_for_every_batch_request() -> None:
    view = sample_market_view()
    first = AlphaDecision(
        strategy="ptb_diff",
        asset=view.asset,
        timeframe=view.timeframe,
        market_id=view.market_id,
        market_slug=view.market_slug,
        condition_id=view.condition_id,
        token_id=view.up.token_id,
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.51,
        max_entry_price=0.52,
        seconds_to_close=view.seconds_to_close,
        data_freshness_ms=view.freshness.max_ms,
        reason_codes=("PTB_EDGE",),
        metrics={"edge": 0.1},
    )
    second = replace(first, token_id=view.down.token_id, side=Side.DOWN)

    class PartialPolicy(DecisionPolicy):
        def batch_arbitrate(
            self,
            decisions: list[tuple[AlphaDecision, MarketView]],
        ) -> BatchArbitrationResult:
            return BatchArbitrationResult(
                (decisions[0][0],),
                ((
                    decisions[1][0],
                    RejectedDecision(
                        reason_code="ARBITRATION_SUPPRESSED",
                        detail={"strategy": decisions[1][0].strategy},
                    ),
                ),),
            )

        def decide(self, decision: AlphaDecision, view: MarketView) -> ApprovedDecision:
            return ApprovedDecision(signal=candidate_from_decision(decision, view))

    actor = DecisionPolicyActor(policy=PartialPolicy())
    requests = tuple(
        DecisionCandidateData.from_domain(
            request_id=f"request-{index}",
            batch_id="batch-1",
            batch_index=index,
            batch_size=2,
            decision=decision,
            view=view,
            ts_event=1,
            ts_init=1,
        )
        for index, decision in enumerate((first, second))
    )

    results = actor.evaluate_batch(requests)

    assert [result.request_id for result in results] == ["request-0", "request-1"]
    assert results[0].approved is True
    assert results[1].approved is False
    assert results[1].reason_code == "ARBITRATION_SUPPRESSED"
    assert results[1].detail() == {"strategy": "ptb_diff"}


def test_native_message_bus_routes_strategy_batch_through_policy_actor() -> None:
    view = sample_market_view()
    decision = AlphaDecision(
        strategy="ptb_diff",
        asset=view.asset,
        timeframe=view.timeframe,
        market_id=view.market_id,
        market_slug=view.market_slug,
        condition_id=view.condition_id,
        token_id=view.up.token_id,
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.51,
        max_entry_price=0.52,
        seconds_to_close=view.seconds_to_close,
        data_freshness_ms=view.freshness.max_ms,
        reason_codes=("PTB_EDGE",),
        metrics={"edge": 0.1},
    )

    class AllowPolicy(DecisionPolicy):
        def batch_arbitrate(
            self,
            decisions: list[tuple[AlphaDecision, MarketView]],
        ) -> BatchArbitrationResult:
            return BatchArbitrationResult(item[0] for item in decisions)

        def decide(self, decision: AlphaDecision, view: MarketView) -> ApprovedDecision:
            return ApprovedDecision(signal=candidate_from_decision(decision, view))

    class ProbeStrategy(nautilus_pyo3.Strategy):
        def __init__(self, instrument_id: object) -> None:
            super().__init__(
                nautilus_pyo3.StrategyConfig(
                    strategy_id=nautilus_pyo3.StrategyId("PolySignal-Probe"),
                    order_id_tag="probe",
                )
            )
            self.instrument_id = instrument_id
            self.results: list[DecisionResultData] = []

        def on_start(self) -> None:
            self.subscribe_data(custom_data_type(DecisionResultData))
            self.subscribe_quotes(self.instrument_id)

        def on_quote(self, quote: object) -> None:
            candidate = DecisionCandidateData.from_domain(
                request_id="request-native",
                batch_id="batch-native",
                batch_index=0,
                batch_size=1,
                decision=decision,
                view=view,
                ts_event=int(getattr(quote, "ts_event")),
                ts_init=int(getattr(quote, "ts_init")),
            )
            self.publish_data(
                custom_data_type(DecisionCandidateData),
                wrap_custom_data(candidate),
            )

        def on_data(self, data: object) -> None:
            payload = unwrap_custom_data(data)
            if isinstance(payload, DecisionResultData):
                self.results.append(payload)

    engine, instrument = build_backtest_engine(trader_id="POLICY-001")
    engine.add_data(
        synthetic_quotes(
            instrument.id,
            [100.0],
        )
    )
    actor = DecisionPolicyActor(policy=AllowPolicy())
    strategy = ProbeStrategy(instrument.id)
    engine.add_actor(actor)
    engine.add_strategy(strategy)

    engine.run()

    assert len(strategy.results) == 1
    assert strategy.results[0].request_id == "request-native"
    assert strategy.results[0].approved is True
    engine.dispose()
