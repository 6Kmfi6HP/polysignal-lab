from __future__ import annotations

from types import SimpleNamespace

from factories import BookFactoryConfig, MarketFactoryConfig, sample_book, sample_market
from polysignal_lab.app import scheduler_processing
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
from polysignal_lab.strategies.readiness import StrategyReadiness


class _UnsupportedStrategy:
    name = "unsupported"

    @property
    def readiness(self) -> StrategyReadiness:
        return StrategyReadiness(
            name=self.name,
            production_enabled=True,
            supported_assets=("BTC",),
            supported_timeframes=("5m",),
            required_fields=("up_book",),
            calibration_required=False,
            calibration_status="calibrated",
        )

    def evaluate(self, snapshot: MarketSnapshot):
        raise AssertionError("unsupported strategy should not be evaluated")


class _Markets:
    def __init__(self, market) -> None:
        self._market = market

    def active(self) -> list:
        return [self._market]


class _SnapshotBuilder:
    def __init__(self, snapshot: MarketSnapshot) -> None:
        self.snapshot = snapshot

    async def build(self, market) -> MarketSnapshot:
        return self.snapshot


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def exception(self, *args, **kwargs) -> None:
        pass


class _Logs:
    def __init__(self) -> None:
        self.rows: list[tuple[str, object]] = []

    def append(self, stream: str, row: object) -> None:
        self.rows.append((stream, row))


class _SQLite:
    def __init__(self) -> None:
        self.strategy_statuses: list[object] = []

    def insert_strategy_status(self, status: object) -> None:
        self.strategy_statuses.append(status)


def _snapshot(asset: str = "ETH", timeframe: str = "5m") -> MarketSnapshot:
    market = sample_market(MarketFactoryConfig(asset=asset, timeframe=timeframe))
    return MarketSnapshot(
        snapshot_id="snap-readiness",
        market=market,
        up_book=sample_book(market.token_for(Side.UP).token_id, BookFactoryConfig(ask=0.54)),
        down_book=sample_book(market.token_for(Side.DOWN).token_id, BookFactoryConfig(ask=0.49)),
        freshness=FreshnessState(max_ms=1),
    )


async def test_unsupported_strategy_is_skipped_before_evaluate() -> None:
    snapshot = _snapshot()
    scheduler = SimpleNamespace(
        ctx=SimpleNamespace(markets=_Markets(snapshot.market)),
        snapshot_builder=_SnapshotBuilder(snapshot),
        logger=_Logger(),
        strategies=[_UnsupportedStrategy()],
        logs=_Logs(),
        sqlite=_SQLite(),
    )

    accepted = await scheduler_processing.evaluate_once(scheduler)

    assert accepted == []
    assert scheduler.sqlite.strategy_statuses[-1].status == "unsupported_market"
    assert scheduler.logs.rows[-1][0] == "strategy_status"
