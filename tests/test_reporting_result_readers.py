from __future__ import annotations

import pytest

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.missing_values import MissingIdentifierError
from polysignal_lab.domain.reporting_result import (
    trade_result_display,
    trade_result_identifier,
    trade_result_number,
)


def test_number_missing_returns_none_instead_of_zero() -> None:
    for row in ({}, {"pnl_usdc": None}, {"pnl_usdc": ""}):
        assert trade_result_number(row, "pnl_usdc") is None


def test_number_keeps_zero_as_a_real_value() -> None:
    for value in (0, 0.0, "0"):
        result = trade_result_number({"pnl_usdc": value}, "pnl_usdc")
        assert result is not None
        assert isinstance(result, float)
        assert result == 0.0


def test_number_non_finite_and_non_numeric_return_none() -> None:
    for value in (float("nan"), float("inf"), -float("inf"), "n/a", True):
        assert trade_result_number({"pnl_usdc": value}, "pnl_usdc") is None


def test_number_falls_back_across_row_keys_then_metrics() -> None:
    assert trade_result_number({"roi": None, "return": 0.25}, "roi", "return") == 0.25
    assert (
        trade_result_number({"roi": float("nan"), "return": 0.25}, "roi", "return")
        == 0.25
    )
    assert (
        trade_result_number(
            {},
            "roi",
            metrics={"roi": 0.5},
            metric_keys=("roi",),
        )
        == 0.5
    )
    assert (
        trade_result_number(
            {"roi": float("inf")},
            "roi",
            metrics={"roi": 0.5},
            metric_keys=("roi",),
        )
        == 0.5
    )
    assert (
        trade_result_number(
            {"roi": 0.1},
            "roi",
            metrics={"roi": 0.9},
            metric_keys=("roi",),
        )
        == 0.1
    )


def test_identifier_missing_raises_and_names_field_and_record() -> None:
    for row in ({}, {"signal_id": None}, {"signal_id": ""}, {"signal_id": "   "}):
        with pytest.raises(MissingIdentifierError) as exc:
            trade_result_identifier({**row, "report_result_id": "res-1"}, "signal_id")
        message = str(exc.value)
        assert "signal_id" in message
        assert "res-1" in message


def test_identifier_returns_stripped_value_and_falls_back_to_metrics() -> None:
    assert trade_result_identifier({"signal_id": "  sig-1  "}, "signal_id") == "sig-1"
    assert (
        trade_result_identifier(
            {},
            "signal_id",
            metrics={"signal_id": "sig-2"},
            metric_keys=("signal_id",),
        )
        == "sig-2"
    )


def test_identifier_error_names_a_usable_record_or_omits_it() -> None:
    with pytest.raises(MissingIdentifierError) as blank:
        trade_result_identifier({"report_result_id": "   "}, "signal_id")
    assert str(blank.value) == "missing identifier: signal_id from report_results"

    with pytest.raises(MissingIdentifierError) as fallback:
        trade_result_identifier(
            {"report_result_id": "  ", "signal_id": "sig-9"}, "strategy"
        )
    assert "sig-9" in str(fallback.value)


def test_display_missing_returns_empty_string() -> None:
    for row in ({}, {"market_slug": None}, {"market_slug": ""}):
        assert trade_result_display(row, "market_slug") == ""


def test_display_renders_present_values_including_side_enum() -> None:
    assert trade_result_display({"market_slug": "btc-up"}, "market_slug") == "btc-up"
    assert trade_result_display({"side": Side.UP}, "side") == "UP"
    assert (
        trade_result_display(
            {},
            "market_slug",
            metrics={"slug": "fallback-slug"},
            metric_keys=("slug",),
        )
        == "fallback-slug"
    )
