"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, pydantic, pydantic.JsonValue, polysignal_lab.domain.enums, polysignal_lab.domain.enums.MarketStatus, polysignal_lab.domain.enums.Side
Output: test_gamma_resolved_payload_sets_resolved_outcome, test_gamma_payload_uses_nautilus_parser_for_binary_option_tokens, test_gamma_crypto_payload_prefers_event_window_over_listing_start_date, test_gamma_down_resolution_can_be_parsed_from_winning_token_id, test_gamma_void_resolution_is_cancelled_without_winning_side, test_gamma_malformed_official_resolution_stays_unknown, test_gamma_uma_resolved_outcome_prices_sets_resolved_outcome, test_gamma_half_half_outcome_prices_resolved_without_side_winner
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from datetime import UTC, datetime

from pydantic import JsonValue

from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.domain.market import Market
import polysignal_lab.domain.market as market_module


def _gamma_payload(outcome: JsonValue = "Up") -> dict[str, JsonValue]:
    return {
        "id": "gamma-market-1",
        "conditionId": "0xcondition",
        "slug": "btc-updown-5m-1710000000",
        "questionID": "question-1",
        "question": "BTC Up or Down - 5m",
        "startDate": "2026-06-22T12:00:00Z",
        "endDate": "2026-06-22T12:05:00Z",
        "active": False,
        "closed": True,
        "resolved": True,
        "priceToBeat": "105150.25",
        "resolutionSource": "gamma",
        "outcomes": '["Up", "Down"]',
        # Numeric token ids: NT instrument_id is `{condition_id}-{token_id}` (no extra hyphens).
        "clobTokenIds": '["111", "222"]',
        "winning_outcome": outcome,
    }


def test_gamma_resolved_payload_sets_resolved_outcome() -> None:
    market = Market.from_gamma(_gamma_payload(), asset="btc", timeframe="5m")

    assert market.market_id == "gamma-market-1"
    assert market.condition_id == "0xcondition"
    assert market.market_slug == "btc-updown-5m-1710000000"
    assert market.status == MarketStatus.RESOLVED
    assert market.start_ts == datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
    assert market.end_ts == datetime(2026, 6, 22, 12, 5, tzinfo=UTC)
    assert market.price_to_beat == 105150.25
    assert market.resolution_source == "gamma"
    assert market.resolved_outcome == Side.UP
    assert market.token_for(Side.UP).token_id == "111"
    assert market.token_for(Side.DOWN).token_id == "222"


def test_gamma_payload_uses_nautilus_parser_for_binary_option_tokens(monkeypatch) -> None:
    payload = _gamma_payload()
    payload["clobTokenIds"] = '["123", "456"]'
    seen: list[tuple[dict[str, object], str, str]] = []

    def parse_binary_option(
        market_info: dict[str, object],
        token_id: str,
        outcome: str,
        ts_init: int | None = None,
    ) -> object:
        seen.append((market_info, token_id, outcome))
        return type("ParsedBinaryOption", (), {"outcome": f"Parsed {outcome}"})()

    import polysignal_lab.data.provider.gamma_market as gamma_market

    monkeypatch.setattr(
        gamma_market,
        "parse_nautilus_polymarket_instrument",
        parse_binary_option,
    )

    market = Market.from_gamma(payload, asset="BTC", timeframe="5m")

    assert [token.outcome_name for token in market.outcome_tokens] == [
        "Parsed Up",
        "Parsed Down",
    ]
    assert [(token_id, outcome) for _, token_id, outcome in seen] == [
        ("123", "Up"),
        ("456", "Down"),
    ]
    assert seen[0][0]["condition_id"] == "0xcondition"
    assert seen[0][0]["end_date_iso"] == "2026-06-22T12:05:00Z"
    assert seen[0][0]["minimum_tick_size"] == "0.01"


def test_gamma_crypto_payload_prefers_event_window_over_listing_start_date() -> None:
    payload = _gamma_payload()
    payload["startDate"] = "2026-06-23T10:39:56Z"
    payload["eventStartTime"] = "2026-06-24T10:30:00Z"
    payload["endDate"] = "2026-06-24T10:35:00Z"

    market = Market.from_gamma(payload, asset="BTC", timeframe="5m")

    assert market.start_ts == datetime(2026, 6, 24, 10, 30, tzinfo=UTC)
    assert market.end_ts == datetime(2026, 6, 24, 10, 35, tzinfo=UTC)


def test_gamma_down_resolution_can_be_parsed_from_winning_token_id() -> None:
    payload = _gamma_payload(outcome=None)
    payload["winning_asset_id"] = "222"

    market = Market.from_gamma(payload, asset="BTC", timeframe="5m")

    assert market.status == MarketStatus.RESOLVED
    assert market.resolved_outcome == Side.DOWN


def test_gamma_void_resolution_is_cancelled_without_winning_side() -> None:
    payload = _gamma_payload(outcome="Void")
    payload["cancelled"] = True

    market = Market.from_gamma(payload, asset="BTC", timeframe="5m")

    assert market.status == MarketStatus.CANCELLED
    assert market.resolved_outcome is None


def test_gamma_malformed_official_resolution_stays_unknown() -> None:
    payload = _gamma_payload(outcome="Moon")
    payload["question"] = "BTC resolved Up according to this non-authoritative text"

    market = Market.from_gamma(payload, asset="BTC", timeframe="5m")

    assert market.status == MarketStatus.RESOLVED
    assert market.resolved_outcome is None




def test_gamma_uma_resolved_outcome_prices_sets_resolved_outcome() -> None:
    payload = _gamma_payload()
    payload.pop("resolved")
    payload.pop("winning_outcome")
    payload["closed"] = True
    payload["active"] = False
    payload["umaResolutionStatus"] = "resolved"
    payload["outcomePrices"] = '["1", "0"]'

    market = Market.from_gamma(payload, asset="BTC", timeframe="5m")

    assert market.status == MarketStatus.RESOLVED
    assert market.resolved_outcome == Side.UP


def test_gamma_half_half_outcome_prices_resolved_without_side_winner() -> None:
    payload = _gamma_payload()
    payload.pop("resolved")
    payload.pop("winning_outcome")
    payload["closed"] = True
    payload["active"] = False
    payload["umaResolutionStatus"] = "resolved"
    payload["outcomePrices"] = '["0.5", "0.5"]'

    market = Market.from_gamma(payload, asset="BTC", timeframe="5m")

    assert market.status == MarketStatus.RESOLVED
    assert market.resolved_outcome is None
