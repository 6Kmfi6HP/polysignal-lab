from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from polysignal_lab.domain.snapshot import MarketSnapshot

CalibrationStatus = Literal["unknown", "insufficient_data", "calibrated"]
StrategyStatus = Literal[
    "active",
    "disabled",
    "inactive",
    "unsupported_market",
    "missing_data",
    "uncalibrated",
]


@dataclass(frozen=True, slots=True)
class StrategyReadiness:
    name: str
    production_enabled: bool
    supported_assets: tuple[str, ...]
    supported_timeframes: tuple[str, ...]
    required_fields: tuple[str, ...]
    calibration_required: bool
    calibration_status: CalibrationStatus


@dataclass(frozen=True, slots=True)
class StrategyMarketStatus:
    strategy: str
    asset: str
    timeframe: str
    status: StrategyStatus
    reason: str | None


def _has_required(snapshot: MarketSnapshot, field: str) -> bool:
    if field == "up_book":
        return snapshot.up_book is not None
    if field == "down_book":
        return snapshot.down_book is not None
    if field == "spot":
        return snapshot.spot is not None
    if field == "price_to_beat":
        return snapshot.price_to_beat is not None
    if field == "spot_history":
        return bool(snapshot.metrics.get("spot_history_count"))
    if field == "market_end_ts":
        return snapshot.market.end_ts is not None
    return bool(snapshot.metrics.get(field))


def check_strategy_market(
    readiness: StrategyReadiness, snapshot: MarketSnapshot
) -> StrategyMarketStatus:
    asset = snapshot.market.asset.upper()
    timeframe = snapshot.market.timeframe
    supported_assets = tuple(asset.upper() for asset in readiness.supported_assets)
    if not readiness.production_enabled:
        return StrategyMarketStatus(
            readiness.name, asset, timeframe, "disabled", "STRATEGY_DISABLED"
        )
    if asset not in supported_assets:
        return StrategyMarketStatus(
            readiness.name, asset, timeframe, "unsupported_market", "UNSUPPORTED_ASSET"
        )
    if timeframe not in readiness.supported_timeframes:
        return StrategyMarketStatus(
            readiness.name,
            asset,
            timeframe,
            "unsupported_market",
            "UNSUPPORTED_TIMEFRAME",
        )
    for field in readiness.required_fields:
        if not _has_required(snapshot, field):
            return StrategyMarketStatus(
                readiness.name, asset, timeframe, "missing_data", f"MISSING_{field.upper()}"
            )
    if readiness.calibration_required and readiness.calibration_status != "calibrated":
        return StrategyMarketStatus(
            readiness.name, asset, timeframe, "uncalibrated", "CALIBRATION_REQUIRED"
        )
    return StrategyMarketStatus(readiness.name, asset, timeframe, "active", None)
