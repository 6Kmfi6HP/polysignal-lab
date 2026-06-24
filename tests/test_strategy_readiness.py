from __future__ import annotations

from polysignal_lab.strategies.readiness import StrategyReadiness, check_strategy_market


class _Market:
    asset = "ETH"
    timeframe = "5m"
    end_ts = None


class _Snapshot:
    market = _Market()
    up_book = object()
    down_book = object()
    spot = object()
    price_to_beat = None
    metrics: dict[str, object] = {}


def test_readiness_rejects_unsupported_asset_before_evaluate() -> None:
    readiness = StrategyReadiness(
        name="ptb_diff",
        production_enabled=True,
        supported_assets=("BTC",),
        supported_timeframes=("5m", "15m"),
        required_fields=("price_to_beat",),
        calibration_required=False,
        calibration_status="calibrated",
    )

    status = check_strategy_market(readiness, _Snapshot())

    assert status.status == "unsupported_market"
    assert status.reason == "UNSUPPORTED_ASSET"


def test_readiness_reports_missing_data() -> None:
    readiness = StrategyReadiness(
        name="ptb_diff",
        production_enabled=True,
        supported_assets=("ETH",),
        supported_timeframes=("5m",),
        required_fields=("price_to_beat",),
        calibration_required=False,
        calibration_status="calibrated",
    )

    status = check_strategy_market(readiness, _Snapshot())

    assert status.status == "missing_data"
    assert status.reason == "MISSING_PRICE_TO_BEAT"
