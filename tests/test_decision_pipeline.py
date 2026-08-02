from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast

from polysignal_lab.alpha.types import AlphaDecision, MarketView, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    BatchArbitrationResult,
    RejectedDecision,
    candidate_from_decision,
)
from polysignal_lab.nautilus_runtime.strategy.decision_pipeline import (
    DecisionPipeline,
    NautilusCashBalanceReader,
    SubmittedDecision,
    default_cash_preflight,
)
from factories import sample_market_view


def _decision(*, market_id: str = "market", side: Side = Side.UP) -> AlphaDecision:
    return AlphaDecision(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id=market_id,
        market_slug=market_id,
        condition_id=f"condition-{market_id}",
        token_id=f"token-{side.value}",
        side=side,
        confidence=0.9,
        entry_reference_price=0.5,
        max_entry_price=0.6,
        seconds_to_close=120,
        data_freshness_ms=10,
        reason_codes=("test",),
        metrics={},
    )


def _view(*dedupe_keys: str) -> MarketView:
    return cast(
        MarketView,
        cast(
            object,
            SimpleNamespace(
                trading=SimpleNamespace(
                    orders=tuple(
                        SimpleNamespace(
                            dedupe_key=key,
                            is_open=True,
                            is_inflight=False,
                        )
                        for key in dedupe_keys
                    )
                )
            ),
        ),
    )


def _publish() -> SignalCandidate:
    return cast(SignalCandidate, object())


@dataclass
class _Policy:
    approvals: dict[int, ApprovedDecision] = field(default_factory=dict)
    rejections: dict[int, RejectedDecision] = field(default_factory=dict)

    def batch_arbitrate(
        self, decisions: list[tuple[AlphaDecision, MarketView]]
    ) -> BatchArbitrationResult:
        return BatchArbitrationResult(
            approvals=tuple(
                self.approvals[id(decision)]
                for decision, _ in decisions
                if id(decision) in self.approvals
            ),
            rejections=tuple(
                (decision, self.rejections[id(decision)])
                for decision, _ in decisions
                if id(decision) in self.rejections
            ),
        )


@dataclass
class _Submitter:
    submitted: list[ApprovedDecision] = field(default_factory=list)
    failure: ValueError | None = None

    def submit(self, approved: ApprovedDecision, view: MarketView) -> object:
        _ = view
        if self.failure is not None:
            raise self.failure
        self.submitted.append(approved)
        return object()


@dataclass
class _Telemetry:
    accepted_calls: list[tuple[ApprovedDecision, object]] = field(default_factory=list)
    rejected_calls: list[tuple[RejectedDecision, AlphaDecision]] = field(
        default_factory=list
    )

    def accepted(self, approved: ApprovedDecision, order: object) -> None:
        self.accepted_calls.append((approved, order))

    def rejected(self, rejected: RejectedDecision, decision: AlphaDecision) -> None:
        self.rejected_calls.append((rejected, decision))

    def progress(self, event: str) -> None:
        _ = event


def test_apply_submits_approved_decision_and_records_telemetry_once() -> None:
    decision = _decision()
    approved = ApprovedDecision(decision=decision, publish=_publish())
    submitter = _Submitter()
    telemetry = _Telemetry()
    pipeline = DecisionPipeline(
        policy=_Policy(approvals={id(decision): approved}),
        submitter=submitter,
        telemetry=telemetry,
    )

    results = pipeline.apply((decision,), _view())

    assert len(results) == 1
    assert isinstance(results[0], SubmittedDecision)
    assert results[0].approved is approved
    assert results[0].order is telemetry.accepted_calls[0][1]
    assert submitter.submitted == [approved]
    assert len(telemetry.accepted_calls) == 1
    assert telemetry.accepted_calls[0][0] is approved
    assert telemetry.rejected_calls == []


def test_apply_records_policy_rejection_once() -> None:
    decision = _decision()
    rejected = RejectedDecision("GATE_REJECTED", {}, decision=decision)
    telemetry = _Telemetry()
    pipeline = DecisionPipeline(
        policy=_Policy(rejections={id(decision): rejected}),
        submitter=_Submitter(),
        telemetry=telemetry,
    )

    results = pipeline.apply((decision,), _view())

    assert results == [rejected]
    assert telemetry.rejected_calls == [(rejected, decision)]
    assert list(pipeline.rejected_decisions) == [rejected]


def test_apply_rejects_view_and_batch_duplicates() -> None:
    first = _decision()
    duplicate = _decision()
    approved = ApprovedDecision(decision=first, publish=_publish())
    policy = _Policy(
        approvals={
            id(first): approved,
            id(duplicate): ApprovedDecision(duplicate, _publish()),
        }
    )
    telemetry = _Telemetry()
    pipeline = DecisionPipeline(
        policy=policy, submitter=_Submitter(), telemetry=telemetry
    )

    view_results = pipeline.apply((first,), _view(first.dedupe_key()))
    batch_results = pipeline.apply((first, duplicate), _view())

    assert isinstance(view_results[0], RejectedDecision)
    assert view_results[0].reason_code == "DUPLICATE_IN_FLIGHT_SIGNAL"
    assert isinstance(batch_results[0], SubmittedDecision)
    assert batch_results[0].approved is approved
    assert isinstance(batch_results[1], RejectedDecision)
    assert batch_results[1].reason_code == "DUPLICATE_IN_FLIGHT_SIGNAL"
    assert len(telemetry.rejected_calls) == 2


def test_apply_converts_submit_mapping_failure_to_rejection() -> None:
    decision = _decision()
    approved = ApprovedDecision(decision=decision, publish=_publish())
    telemetry = _Telemetry()
    pipeline = DecisionPipeline(
        policy=_Policy(approvals={id(decision): approved}),
        submitter=_Submitter(failure=ValueError("unmapped token")),
        telemetry=telemetry,
    )

    results = pipeline.apply((decision,), _view())

    assert isinstance(results[0], RejectedDecision)
    assert results[0].reason_code == "ORDER_MAPPING_FAILED"
    assert results[0].detail == {"error": "unmapped token"}
    assert telemetry.rejected_calls[0][1] is decision


def test_apply_bounds_rejected_history() -> None:
    decisions = tuple(_decision(market_id=f"market-{index}") for index in range(1001))
    rejections = {
        id(decision): RejectedDecision("GATE_REJECTED", {}, decision=decision)
        for decision in decisions
    }
    pipeline = DecisionPipeline(
        policy=_Policy(rejections=rejections),
        submitter=_Submitter(),
        telemetry=_Telemetry(),
    )

    _ = pipeline.apply(decisions, _view())

    assert len(pipeline.rejected_decisions) == 1000
    assert pipeline.rejected_decisions[0].decision is decisions[1]


class _FixedBalanceReader:
    """BalanceReader fake whose free balance is fixed or None (unreadable)."""

    def __init__(self, free: float | None) -> None:
        self.free = free

    def read_free_balance(self) -> float | None:
        return self.free


def test_cash_balance_reader_uses_typed_cache_keys_and_native_balance() -> None:
    from nautilus_trader.core.nautilus_pyo3 import (
        AccountBalance,
        AccountId,
        Currency,
        Money,
        Venue,
    )

    currency = Currency.from_str("USDC")
    balance = AccountBalance(
        Money(15.0, currency),
        Money(2.5, currency),
        Money(12.5, currency),
    )
    native_account = SimpleNamespace(balances=lambda: {currency: balance})

    class _TypedCache:
        def __init__(self) -> None:
            self.account_ids: list[object] = []
            self.venues: list[object] = []

        def account(self, account_id: object) -> None:
            if not isinstance(account_id, AccountId):
                raise TypeError("account_id must be AccountId")
            self.account_ids.append(account_id)
            return None

        def account_for_venue(self, venue: object) -> object:
            if not isinstance(venue, Venue):
                raise TypeError("venue must be Venue")
            self.venues.append(venue)
            return native_account

    cache = _TypedCache()
    reader = NautilusCashBalanceReader(cache=cache, base_currency="USDC")

    assert reader.read_free_balance() == 12.5
    assert [str(account_id) for account_id in cache.account_ids] == [
        "POLYMARKET-SANDBOX-001"
    ]
    assert [str(venue) for venue in cache.venues] == ["POLYMARKET"]


def _decision_with_intent(
    *,
    reduce_only: bool = False,
    quantity: float | None = None,
    notional: float | None = None,
) -> AlphaDecision:
    return AlphaDecision(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id="market",
        market_slug="market",
        condition_id="condition-market",
        token_id="token-up",
        side=Side.UP,
        confidence=0.9,
        entry_reference_price=0.5,
        max_entry_price=0.6,
        seconds_to_close=120,
        data_freshness_ms=10,
        reason_codes=("test",),
        metrics={},
        order_intent=OrderIntentSpec(
            intent=OrderIntent.PASSIVE_GTD,
            expiry_seconds=45,
            pair_id="pair-1",
            reduce_only=reduce_only,
            quantity=quantity,
            notional=notional,
        ),
        hedge_leg=False,
    )


def test_cash_preflight_rejects_insufficient_balance() -> None:
    decision = _decision_with_intent()
    view = sample_market_view(up_ask=0.5, down_ask=0.4)
    approved = ApprovedDecision(
        decision=decision, publish=candidate_from_decision(decision, view)
    )
    preflight = default_cash_preflight(
        _FixedBalanceReader(free=1.0), "pUSD", fixed_stake_usdc=10.0
    )

    rejected = preflight(approved, view)

    assert rejected is not None
    assert isinstance(rejected, RejectedDecision)
    assert rejected.reason_code == "INSUFFICIENT_CASH_BALANCE"
    assert rejected.detail["free_balance_usdc"] == 1.0
    # fixed_stake / price = 10.0 / 0.5 = 20; notional = 20 * 0.5 = 10.0
    assert rejected.detail["notional_usdc"] == 10.0


def test_cash_preflight_allows_sufficient_balance() -> None:
    decision = _decision_with_intent()
    view = sample_market_view(up_ask=0.5, down_ask=0.4)
    approved = ApprovedDecision(
        decision=decision, publish=candidate_from_decision(decision, view)
    )
    preflight = default_cash_preflight(
        _FixedBalanceReader(free=10.0), "pUSD", fixed_stake_usdc=10.0
    )

    assert preflight(approved, view) is None


def test_cash_preflight_exempts_reduce_only_even_with_zero_balance() -> None:
    decision = _decision_with_intent(reduce_only=True, quantity=3.0)
    view = sample_market_view(up_ask=0.5, down_ask=0.4)
    approved = ApprovedDecision(
        decision=decision, publish=candidate_from_decision(decision, view)
    )
    # free balance None (unreadable) would normally fail closed — reduce_only is exempt.
    preflight = default_cash_preflight(
        _FixedBalanceReader(free=None), "pUSD", fixed_stake_usdc=10.0
    )

    assert preflight(approved, view) is None


def test_cash_preflight_fails_closed_when_balance_unavailable() -> None:
    decision = _decision_with_intent()
    view = sample_market_view(up_ask=0.5, down_ask=0.4)
    approved = ApprovedDecision(
        decision=decision, publish=candidate_from_decision(decision, view)
    )
    preflight = default_cash_preflight(
        _FixedBalanceReader(free=None), "pUSD", fixed_stake_usdc=10.0
    )

    rejected = preflight(approved, view)

    assert rejected is not None
    assert isinstance(rejected, RejectedDecision)
    assert rejected.reason_code == "INSUFFICIENT_CASH_BALANCE"
    assert rejected.detail["reason"] == "free balance unavailable"


def test_cash_preflight_uses_order_spec_price_for_explicit_quantity() -> None:
    decision = _decision_with_intent(quantity=4.0)
    view = sample_market_view(up_ask=0.5, down_ask=0.4)
    approved = ApprovedDecision(
        decision=decision, publish=candidate_from_decision(decision, view)
    )
    preflight = default_cash_preflight(
        _FixedBalanceReader(free=2.2), "pUSD", fixed_stake_usdc=10.0
    )

    rejected = preflight(approved, view)

    assert rejected is not None
    assert isinstance(rejected, RejectedDecision)
    # PASSIVE_GTD uses max_entry_price: 4.0 * 0.6 = 2.4.
    assert rejected.detail["notional_usdc"] == 2.4
