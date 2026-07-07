"""
Input: __future__, __future__.annotations, polysignal_lab.strategies.readiness, polysignal_lab.strategies.readiness.StrategyReadiness, polysignal_lab.strategies.readiness.check_strategy_market, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.strategies.factory, polysignal_lab.strategies.factory.build_strategies
Output: test_readiness_rejects_unsupported_asset_before_evaluate, test_readiness_reports_missing_data, test_all_loaded_strategies_expose_readiness, test_production_vwap_readiness_does_not_require_snapshot_spot_history_metric, _Market, _Snapshot, _VwapMarket, _VwapSnapshot
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from polysignal_lab.strategies.readiness import StrategyReadiness, check_strategy_market
from polysignal_lab.config import Settings
from polysignal_lab.strategies.factory import build_strategies


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



class _VwapMarket:
    asset = "ETH"
    timeframe = "5m"
    end_ts = object()


class _VwapSnapshot:
    market = _VwapMarket()
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


def test_all_loaded_strategies_expose_readiness() -> None:
    settings = Settings.from_yaml("config/signal_bot.lab.yaml")
    strategies = build_strategies(settings.strategies)

    names = {strategy.name for strategy in strategies}
    readiness = {strategy.name: strategy.readiness for strategy in strategies}

    assert names == set(readiness)
    assert readiness["ninety_nine_cent_sniper"].supported_assets == ("BTC", "ETH", "SOL", "XRP")
    assert readiness["one_cent_buy"].supported_timeframes == ("5m", "15m")
    assert readiness["ninety_nine_cent_sniper"].calibration_required is True
    assert readiness["one_cent_buy"].required_fields == ("up_book", "down_book", "market_end_ts")
    assert readiness["late_consensus"].required_fields == ("up_book", "down_book", "market_end_ts")


def test_production_vwap_readiness_does_not_require_snapshot_spot_history_metric() -> None:
    settings = Settings.from_yaml("config/signal_bot.lab.yaml")
    strategies = build_strategies(settings.strategies)
    readiness = {strategy.name: strategy.readiness for strategy in strategies}

    _VwapMarket.asset = readiness["vwap_momentum"].supported_assets[0]
    _VwapMarket.timeframe = readiness["vwap_momentum"].supported_timeframes[0]

    status = check_strategy_market(readiness["vwap_momentum"], _VwapSnapshot())

    assert status.status == "active"
    assert status.reason is None
