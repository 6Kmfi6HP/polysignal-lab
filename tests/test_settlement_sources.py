from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.paper.settlement_sources import (
    SettlementEvidence,
    WsResolutionCache,
    choose_decision,
    parse_gamma_resolution_payload,
)


def _market() -> Market:
    return Market(
        market_id="market-1",
        market_slug="btc-updown-5m",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="token-up", side=Side.UP, outcome_name="Up", market_id="market-1"),
            OutcomeToken(token_id="token-down", side=Side.DOWN, outcome_name="Down", market_id="market-1"),
        ],
    )


def _evidence(source: str, values: dict[str, float], status: str = "resolved") -> SettlementEvidence:
    return SettlementEvidence(
        source=source,  # type: ignore[arg-type]
        confidence="authoritative" if source == "chain" else "exact" if source == "gamma" else "hint",
        market_id="market-1",
        market_slug="btc-updown-5m",
        condition_id="0x" + "1" * 64,
        outcome_values_by_token=values,
        status=status,  # type: ignore[arg-type]
        observed_at=datetime.now(UTC),
        raw_status=status,
    )


def test_chain_evidence_wins_and_records_conflicting_gamma() -> None:
    decision = choose_decision(
        [
            _evidence("chain", {"token-up": 1.0, "token-down": 0.0}),
            _evidence("gamma", {"token-up": 0.0, "token-down": 1.0}),
        ],
        _market(),
    )

    assert decision.status == "resolved"
    assert decision.source == "chain"
    assert decision.outcome_values_by_token == {"token-up": 1.0, "token-down": 0.0}
    assert decision.conflict is True
    assert decision.conflict_sources == ("gamma",)
    assert decision.details["settlement_conflict"] is True


def test_gamma_ws_conflict_without_chain_stays_unknown() -> None:
    decision = choose_decision(
        [
            _evidence("gamma", {"token-up": 1.0, "token-down": 0.0}),
            _evidence("ws", {"token-up": 0.0, "token-down": 1.0}),
        ],
        _market(),
    )

    assert decision.status == "unknown"
    assert decision.source == "none"
    assert decision.conflict is True
    assert decision.details["reason"] == "GAMMA_WS_CONFLICT"


def test_chain_unresolved_allows_gamma_fallback() -> None:
    decision = choose_decision(
        [
            _evidence("chain", {}, status="unresolved"),
            _evidence("gamma", {"token-up": 0.5, "token-down": 0.5}),
        ],
        _market(),
    )

    assert decision.status == "resolved"
    assert decision.source == "gamma"
    assert decision.details["chain_status"] == "unresolved"


def test_gamma_outcome_prices_parse_real_resolved_shape() -> None:
    evidence = parse_gamma_resolution_payload(
        {
            "id": "market-1",
            "conditionId": "0x" + "1" * 64,
            "umaResolutionStatus": "resolved",
            "closed": True,
            "outcomePrices": '["1", "0"]',
            "outcomes": '["Up", "Down"]',
            "clobTokenIds": '["token-up", "token-down"]',
        },
        _market(),
    )

    assert evidence.status == "resolved"
    assert evidence.outcome_values_by_token == {"token-up": 1.0, "token-down": 0.0}
    assert evidence.raw_status == "resolved"


def test_ws_cache_matches_condition_slug_and_winning_asset() -> None:
    cache = WsResolutionCache()
    cache.remember({"event_id": "evt-condition", "condition_id": "0x" + "1" * 64, "winning_asset_id": "token-up"})
    cache.remember({"event_id": "evt-slug", "slug": "other-slug", "winning_asset_id": "token-down"})

    evidence = cache.evidence_for(_market())

    assert evidence is not None
    assert evidence.source == "ws"
    assert evidence.confidence == "hint"
    assert evidence.outcome_values_by_token == {"token-up": 1.0, "token-down": 0.0}
    assert evidence.event_id == "evt-condition"


def test_ws_cache_prunes_old_events() -> None:
    cache = WsResolutionCache()
    cache.remember({"event_id": "evt", "condition_id": "0x" + "1" * 64, "winning_asset_id": "token-up"})

    cache.prune(datetime.now(UTC) + timedelta(hours=2), ttl_sec=60)

    assert cache.evidence_for(_market()) is None
