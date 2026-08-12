from __future__ import annotations

from collections.abc import Iterator

import pytest

from factories import sample_report_result

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.domain.missing_values import bind_missing_value_counter
from polysignal_lab.observability.health import HealthRegistry, MetricValue
from polysignal_lab.publish.message_formatter import MessageFormatter


@pytest.fixture(autouse=True)
def _reset_missing_value_counter_after_test() -> Iterator[None]:
    bind_missing_value_counter(None)
    yield
    bind_missing_value_counter(None)


def _collapse_metrics(registry: HealthRegistry) -> dict[str, MetricValue]:
    components = {c.name: c for c in registry.snapshot().components}
    component = components.get("missing_values")
    return dict(component.metrics) if component is not None else {}


def test_result_message_renders_present_values_unchanged() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    result = sample_report_result()
    message = MessageFormatter().result_message(result)

    assert " · WIN</b>" in message
    assert "Entry  0.5000" in message
    assert "Stake  10.00 USDC" in message
    assert "Shares 20.0000" in message
    assert "PnL    +10.0000 USDC" in message
    assert "ROI    +100.00%" in message
    assert "Settle 20.0000 USDC" in message
    assert "ID: <code>sig-test</code>" in message
    assert "missing_values" not in {c.name for c in registry.snapshot().components}


def test_result_message_degrades_missing_numeric_fields_without_failing() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    result = sample_report_result(
        pnl_usdc=None,
        roi=None,
        entry_price=None,
        stake_usdc=None,
        shares=None,
        settlement_value=None,
    )

    message = MessageFormatter().result_message(result)

    # Missing numeric fields degrade to n/a; the push still renders.
    assert "PnL    n/a" in message
    assert "ROI    n/a" in message
    assert "Entry  n/a" in message
    assert "Stake  n/a" in message
    assert "Shares n/a" in message
    assert "Settle n/a" in message
    assert " · WIN</b>" in message
    metrics = _collapse_metrics(registry)
    assert metrics.get("collapsed_pnl_usdc") == 1
    assert metrics.get("collapsed_roi") == 1
    assert metrics.get("collapsed_entry_price") == 1
    assert metrics.get("collapsed_stake_usdc") == 1
    assert metrics.get("collapsed_shares") == 1
    assert metrics.get("collapsed_settlement_value") == 1


def test_result_message_real_zero_pnl_renders_zero_not_na() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    result = sample_report_result(
        result=TradeResultStatus.VOID.value,
        pnl_usdc=0.0,
        roi=0.0,
    )

    message = MessageFormatter().result_message(result)

    # Real zero is a legitimate value: render 0, never n/a, never count.
    assert "PnL    +0.0000 USDC" in message
    assert "ROI    +0.00%" in message
    assert "n/a" not in message
    assert "missing_values" not in {c.name for c in registry.snapshot().components}


def test_result_message_missing_display_fields_render_blank_without_failing() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    result = sample_report_result(
        asset=None,
        timeframe=None,
        strategy=None,
        side=None,
    )

    message = MessageFormatter().result_message(result)

    # Display fields degrade to empty; the push still renders and is not interrupted.
    assert " · WIN</b>" in message
    assert "Side   " in message
    assert "missing_values" not in {c.name for c in registry.snapshot().components}


def test_result_message_missing_signal_id_degrades_and_counts() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    result = sample_report_result(signal_id=None)

    message = MessageFormatter().result_message(result)

    # signal_id is an identifier; in the publish bypass it must not raise — it
    # degrades to a blank id line and counts the collapse.
    assert "ID: <code></code>" in message
    metrics = _collapse_metrics(registry)
    assert metrics.get("collapsed_signal_id") == 1


def test_result_message_unbound_counter_degrades_without_failing() -> None:
    # Unbound counter (offline/script): missing values still degrade, no raise.
    result = sample_report_result(pnl_usdc=None, roi=None, signal_id=None)

    message = MessageFormatter().result_message(result)

    assert "PnL    n/a" in message
    assert "ROI    n/a" in message
    assert "ID: <code></code>" in message
