"""Alpha equivalence harness — test infrastructure only.

Compares the *semantic* output of a legacy ``BaseStrategy.evaluate(MarketSnapshot)``
against an extracted alpha core's ``evaluate(MarketView)``. Host-generated fields
(``signal_id``, ``snapshot_id``/``view_id``, ``created_at``, ``dedupe_key`` and
its default prefix, ``source_signal_ids``, ``schema_version``, ``action``,
``freshness_policy``) are excluded: only :data:`SEMANTIC_FIELDS` are compared.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from polysignal_lab.alpha.ptb_diff_core import market_view_from_snapshot
from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot

# Fields that describe the strategy's *decision*, not the host's bookkeeping.
# Both normalizers emit exactly these keys so a candidate and a decision that
# mean the same thing compare equal.
SEMANTIC_FIELDS = (
    "strategy",
    "asset",
    "timeframe",
    "market_id",
    "market_slug",
    "condition_id",
    "token_id",
    "side",
    "confidence",
    "entry_reference_price",
    "max_entry_price",
    "seconds_to_close",
    "data_freshness_ms",
    "reason_codes",
    "metrics",
    "order_intent",
    "expiry_seconds",
    "pair_id",
    "hedge_leg",
)


def normalize_candidate(candidate: SignalCandidate) -> dict[str, Any]:
    """Project a legacy ``SignalCandidate`` onto :data:`SEMANTIC_FIELDS`.

    ``reason_codes`` (a list on the candidate) is normalized to a tuple so it
    compares equal to the decision's tuple. Host-generated fields
    (``signal_id``, ``dedupe_key``, ``snapshot_id``, ``created_at``, ...) are
    dropped.
    """
    return {
        "strategy": candidate.strategy,
        "asset": candidate.asset,
        "timeframe": candidate.timeframe,
        "market_id": candidate.market_id,
        "market_slug": candidate.market_slug,
        "condition_id": candidate.condition_id,
        "token_id": candidate.token_id,
        "side": candidate.side,
        "confidence": candidate.confidence,
        "entry_reference_price": candidate.entry_reference_price,
        "max_entry_price": candidate.max_entry_price,
        "seconds_to_close": candidate.seconds_to_close,
        "data_freshness_ms": candidate.data_freshness_ms,
        "reason_codes": tuple(candidate.reason_codes),
        "metrics": dict(candidate.metrics),
        "order_intent": candidate.order_intent,
        "expiry_seconds": candidate.expiry_seconds,
        "pair_id": candidate.pair_id,
        "hedge_leg": candidate.hedge_leg,
    }


def normalize_decision(decision: AlphaDecision) -> dict[str, Any]:
    """Project an ``AlphaDecision`` onto :data:`SEMANTIC_FIELDS`.

    The decision's ``order_intent`` is an :class:`OrderIntentSpec` (or ``None``);
    it is flattened to the bare ``OrderIntent`` plus its ``expiry_seconds`` /
    ``pair_id`` so it lines up with the candidate's flat fields.
    """
    spec = decision.order_intent
    return {
        "strategy": decision.strategy,
        "asset": decision.asset,
        "timeframe": decision.timeframe,
        "market_id": decision.market_id,
        "market_slug": decision.market_slug,
        "condition_id": decision.condition_id,
        "token_id": decision.token_id,
        "side": decision.side,
        "confidence": decision.confidence,
        "entry_reference_price": decision.entry_reference_price,
        "max_entry_price": decision.max_entry_price,
        "seconds_to_close": decision.seconds_to_close,
        "data_freshness_ms": decision.data_freshness_ms,
        "reason_codes": tuple(decision.reason_codes),
        "metrics": dict(decision.metrics),
        "order_intent": spec.intent if spec is not None else None,
        "expiry_seconds": spec.expiry_seconds if spec is not None else None,
        "pair_id": spec.pair_id if spec is not None else None,
        "hedge_leg": decision.hedge_leg,
    }


class _LegacyStrategy(Protocol):
    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]: ...


class _AlphaCore(Protocol):
    def evaluate(self, view: MarketView) -> list[AlphaDecision]: ...


def _canonical(normalized: dict[str, Any]) -> str:
    """Stable, order-independent serialization for multiset comparison.

    Enums become their ``str``; tuples/lists serialize identically, so a
    candidate's tuple ``reason_codes`` and any list form compare equal.
    """
    return json.dumps(normalized, sort_keys=True, default=str)


def assert_legacy_core_equivalent(
    strategy: _LegacyStrategy,
    core: _AlphaCore,
    snapshot: MarketSnapshot,
) -> None:
    """Assert a legacy strategy and its extracted alpha core agree semantically.

    Builds a :class:`MarketView` from ``snapshot`` via
    :func:`market_view_from_snapshot`, runs both evaluators, and compares the
    normalized outputs as order-independent multisets (the legacy and core
    implementations may emit decisions in different side order). Only
    :data:`SEMANTIC_FIELDS` are compared; host-generated fields are ignored.

    A snapshot that cannot assemble a view must yield no legacy signals either.
    """
    view = market_view_from_snapshot(snapshot)
    legacy = strategy.evaluate(snapshot)

    if view is None:
        # ponytail: no view → core cannot run; require legacy also empty.
        assert legacy == [], (
            "snapshot produced no MarketView but legacy strategy emitted signals"
        )
        return

    core_decisions = core.evaluate(view)

    legacy_norm = sorted(
        (normalize_candidate(c) for c in legacy), key=_canonical
    )
    core_norm = sorted(
        (normalize_decision(d) for d in core_decisions), key=_canonical
    )

    assert legacy_norm == core_norm, (
        f"legacy and core outputs differ:\n"
        f"  legacy={[_canonical(n) for n in legacy_norm]}\n"
        f"  core  ={[_canonical(n) for n in core_norm]}"
    )
