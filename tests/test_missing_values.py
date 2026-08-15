from __future__ import annotations

from collections.abc import Iterator

import pytest

from polysignal_lab.domain.missing_values import (
    MissingIdentifierError,
    bind_missing_value_counter,
    count_collapse,
    display,
    identifier,
    number,
    set_number,
)
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.storage.event_projection import normalize_report_order


@pytest.fixture(autouse=True)
def _reset_missing_value_counter_after_test() -> Iterator[None]:
    bind_missing_value_counter(None)
    yield
    bind_missing_value_counter(None)


def test_identifier_missing_key_empty_string_and_whitespace_raise() -> None:
    for row in ({}, {"symbol": None}, {"symbol": ""}, {"symbol": "   "}):
        with pytest.raises(MissingIdentifierError) as exc:
            identifier(row, {}, "symbol")
        assert "symbol" in str(exc.value)

    with pytest.raises(MissingIdentifierError) as exc:
        identifier({}, {"symbol": "   "}, metric_keys=("symbol",))
    assert "symbol" in str(exc.value)


def test_identifier_error_names_the_field_and_the_source_record() -> None:
    with pytest.raises(MissingIdentifierError) as exc:
        identifier({}, {}, "signal_id", source="report_order:order-1")

    message = str(exc.value)
    assert "signal_id" in message
    assert "report_order:order-1" in message


def test_identifier_returns_stripped_present_value() -> None:
    assert identifier({"symbol": "  BTC  "}, {}, "symbol") == "BTC"


def test_display_missing_returns_empty_and_present_value_unchanged() -> None:
    assert display({}, {}, "symbol") == ""
    assert display({"symbol": None}, {}, "symbol") == ""
    assert display({"symbol": ""}, {}, "symbol") == ""
    assert display({"symbol": "  BTC  "}, {}, "symbol") == "  BTC  "


def test_number_missing_returns_none_and_invalid_candidates_are_skipped() -> None:
    for row in ({}, {"value": None}, {"value": ""}):
        assert number(row, {}, "value") is None

    assert number({"value": "not-a-number"}, {}, "value") is None
    assert number(
        {"value": "not-a-number", "fallback": "2.5"}, {}, "value", "fallback"
    ) == (2.5)


def test_number_nan_and_inf_return_none() -> None:
    for value in (float("nan"), float("inf"), -float("inf")):
        assert number({"value": value}, {}, "value") is None


def test_number_zero_is_preserved_as_float_zero() -> None:
    for value in (0, 0.0, "0"):
        result = number({"value": value}, {}, "value")
        assert result is not None
        assert isinstance(result, float)
        assert result == 0.0


def test_set_number_drops_none_writes_real_values_and_preserves_zero() -> None:
    payload: dict[str, object] = {}

    set_number(payload, "score", None)
    assert "score" not in payload

    set_number(payload, "score", 2.5)
    assert payload["score"] == 2.5

    set_number(payload, "score", 0.0)
    assert payload["score"] == 0.0

    set_number(payload, "invalid", float("nan"))
    assert "invalid" not in payload


def test_multi_source_fallback_primary_wins_for_all_readers() -> None:
    row: dict[str, object] = {}
    metrics = {"weight": 3.5}
    assert identifier(row, metrics, "missing", metric_keys=("weight",)) == "3.5"
    assert display(row, metrics, "missing", metric_keys=("weight",)) == "3.5"
    assert number(row, metrics, "missing", metric_keys=("weight",)) == 3.5

    row = {"name": "row", "weight": 1.0}
    metrics = {"name": "metrics", "weight": 2.0}
    assert identifier(row, metrics, "name", metric_keys=("name",)) == "row"
    assert display(row, metrics, "name", metric_keys=("name",)) == "row"
    assert number(row, metrics, "weight", metric_keys=("weight",)) == 1.0


def test_collapse_counting_groups_by_field_in_health_registry() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)
    payload: dict[str, object] = {}

    set_number(payload, "alpha", None)
    set_number(payload, "beta", None)
    set_number(payload, "alpha", None)

    components = {
        component.name: component for component in registry.snapshot().components
    }
    assert components["missing_values"].metrics["collapsed_alpha"] == 2
    assert components["missing_values"].metrics["collapsed_beta"] == 1


def test_count_collapse_increments_when_counter_bound() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    count_collapse("x")
    count_collapse("x")
    count_collapse("y")

    components = {
        component.name: component for component in registry.snapshot().components
    }
    metrics = components["missing_values"].metrics
    assert metrics["collapsed_x"] == 2
    assert metrics["collapsed_y"] == 1


def test_count_collapse_is_silent_when_unbound() -> None:
    # No counter bound — must not raise.
    count_collapse("unbound")


def test_report_order_projection_counts_collapsed_numbers_through_vocabulary() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    payload = normalize_report_order(
        {
            "report_order_id": "order-1",
            "signal_id": "sig-1",
            "status": "SUBMITTED",
        }
    )

    assert "limit_price" not in payload
    assert "shares" not in payload
    components = {
        component.name: component for component in registry.snapshot().components
    }
    metrics = components["missing_values"].metrics
    assert metrics["collapsed_limit_price"] == 1
    assert metrics["collapsed_shares"] == 1


def test_report_order_projection_keeps_present_numbers_and_counts_nothing() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    payload = normalize_report_order(
        {
            "report_order_id": "order-1",
            "signal_id": "sig-1",
            "status": "SUBMITTED",
            "limit_price": 0.55,
            "shares": 0.0,
            "stake_usdc": 1.0,
            "reference_price": 0.55,
        }
    )

    assert payload["limit_price"] == 0.55
    assert payload["shares"] == 0.0
    components = {
        component.name: component for component in registry.snapshot().components
    }
    assert "missing_values" not in components


def test_unbound_counter_collapse_is_silent_and_does_not_create_key() -> None:
    payload: dict[str, object] = {}

    set_number(payload, "x", None)
    assert "x" not in payload

    set_number(payload, "x", float("nan"))
    assert "x" not in payload
