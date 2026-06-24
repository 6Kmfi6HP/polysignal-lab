from __future__ import annotations

from datetime import UTC, datetime

from pydantic import JsonValue

from polysignal_lab.data.market_snapshot import MarketSnapshotBuilder
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import OrderBookRegistry, SpotRegistry
from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.domain.market import Market
from factories import BookFactoryConfig, SpotFactoryConfig, sample_book, sample_spot


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
        "clobTokenIds": '["token-up", "token-down"]',
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
    assert market.token_for(Side.UP).token_id == "token-up"
    assert market.token_for(Side.DOWN).token_id == "token-down"


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
    payload["winning_asset_id"] = "token-down"

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


async def test_normalized_snapshot_carries_ptb_resolution_and_token_metadata() -> None:
    market = Market.from_gamma(_gamma_payload(), asset="BTC", timeframe="5m")
    books = OrderBookRegistry()
    spots = SpotRegistry()
    books.update(sample_book("token-up", BookFactoryConfig(ask=0.72, bid=0.70)))
    books.update(sample_book("token-down", BookFactoryConfig(ask=0.30, bid=0.28)))
    spots.update(sample_spot(SpotFactoryConfig(asset="BTC", price=105200.0)))

    snapshot = await MarketSnapshotBuilder(
        books, spots, PriceToBeatProvider()
    ).build(market)

    assert snapshot.price_to_beat == 105150.25
    assert snapshot.metrics["price_to_beat_source"] == "market_metadata"
    assert snapshot.metrics["price_to_beat_verified"] is True
    assert snapshot.metrics["price_to_beat_from_anchor_service"] is False
    assert snapshot.metrics["anchor_price_source"] is None
    assert snapshot.metrics["anchor_price_lag_ms"] is None
    assert snapshot.metrics["market_status"] == "RESOLVED"
    assert snapshot.metrics["resolved_outcome"] == "UP"
    assert snapshot.metrics["resolution_source"] == "gamma"
    assert snapshot.metrics["up_token_id"] == "token-up"
    assert snapshot.metrics["down_token_id"] == "token-down"
    assert snapshot.metrics["market_start_ts"] == "2026-06-22T12:00:00Z"
    assert snapshot.metrics["market_end_ts"] == "2026-06-22T12:05:00Z"
