"""Bypass-path zero fallback convergence: missing numbers never become zero.

Behavior tests for issue #78 sites: telegram render payload, market
discovery window, and confidence bucketing. Value present means the
number is written as-is; missing means the key is omitted (or degraded)
and the collapse is counted via the missing_values counter.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

from polysignal_lab.data.market_discovery_helpers import is_allowed_window
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.missing_values import bind_missing_value_counter
from polysignal_lab.observability.health import HealthRegistry, MetricValue
from polysignal_lab.publish.telegram_render import position_display_payload
from polysignal_lab.reporting.aggregates import confidence_bucket


@pytest.fixture(autouse=True)
def _reset_missing_value_counter_after_test() -> Iterator[None]:
    bind_missing_value_counter(None)
    yield
    bind_missing_value_counter(None)


def _collapse_metrics(registry: HealthRegistry) -> dict[str, MetricValue]:
    components = {c.name: c for c in registry.snapshot().components}
    component = components.get("missing_values")
    return dict(component.metrics) if component is not None else {}


def test_position_display_payload_writes_present_numbers_and_keeps_zero() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    payload = position_display_payload(
        {
            "report_position_id": "pp-1",
            "signal_id": "sig_1",
            "strategy": "vwap_momentum",
            "asset": "BTC",
            "timeframe": "15m",
            "token_id": "token-up",
            "side": "UP",
            "entry_price": 0.0,
            "shares": 500.0,
            "stake_usdc": 320.0,
            "opened_at": datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc).isoformat(),
            "status": "OPEN",
        }
    )

    assert payload["entry_price"] == 0.0  # zero is a legal value, not a collapse
    assert payload["shares"] == 500.0
    assert payload["stake_usdc"] == 320.0
    assert _collapse_metrics(registry) == {}


def test_position_display_payload_omits_missing_numbers_and_counts() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    payload = position_display_payload(
        {
            "report_position_id": "pp-2",
            "signal_id": "sig_1",
            "strategy": "vwap_momentum",
            "asset": "BTC",
            "timeframe": "15m",
            "token_id": "token-up",
            "side": "UP",
            "opened_at": datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc).isoformat(),
            "status": "OPEN",
        }
    )

    assert "entry_price" not in payload
    assert "shares" not in payload
    assert "stake_usdc" not in payload
    metrics = _collapse_metrics(registry)
    assert metrics["collapsed_entry_price"] == 1
    assert metrics["collapsed_shares"] == 1
    assert metrics["collapsed_stake_usdc"] == 1


def test_is_allowed_window_counts_unknown_timeframe_seconds() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)
    now = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)
    market = Market(
        market_id="m-1",
        market_slug="btc-15m",
        condition_id="c-1",
        asset="BTC",
        timeframe="unknown",
        start_ts=now - timedelta(hours=1),
        end_ts=now + timedelta(hours=1),
    )

    result = is_allowed_window(
        market,
        active_only=True,
        closed=False,
        include_next_periods=2,
        now=now,
    )

    assert result is True
    assert _collapse_metrics(registry)["collapsed_timeframe_seconds"] == 1


def test_is_allowed_window_does_not_count_known_timeframe() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)
    now = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)
    market = Market(
        market_id="m-1",
        market_slug="btc-15m",
        condition_id="c-1",
        asset="BTC",
        timeframe="15m",
        start_ts=now - timedelta(hours=1),
        end_ts=now + timedelta(hours=1),
    )

    result = is_allowed_window(
        market,
        active_only=True,
        closed=False,
        include_next_periods=2,
        now=now,
    )

    assert result is True
    assert _collapse_metrics(registry) == {}


def test_confidence_bucket_keeps_none_and_zero_as_low() -> None:
    assert confidence_bucket(None) == "low"
    assert confidence_bucket(0.0) == "low"  # zero is a legal confidence value
