from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from polysignal_lab.alpha.types import (
    FreshnessView,
    MarketView,
    SideBookView,
    SpotView,
    TradeView,
)
from polysignal_lab.domain.enums import (
    ExitMode,
    MarketStatus,
    PositionStatus,
    Side,
    TradeResultStatus,
)
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.reporting_result import DailyReport, ReportAccountSnapshot
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.utils import new_id, utc_now


@dataclass(frozen=True, slots=True)
class MarketFactoryConfig:
    asset: str = "BTC"
    timeframe: str = "5m"
    seconds_to_close: int = 120
    price_to_beat: float = 100000.0


@dataclass(frozen=True, slots=True)
class BookFactoryConfig:
    ask: float = 0.82
    bid: float | None = None
    size: float = 100.0


@dataclass(frozen=True, slots=True)
class SpotFactoryConfig:
    asset: str = "BTC"
    price: float = 100120.0


@dataclass(frozen=True, slots=True)
class StorageLifecycle:
    rejected: RejectedSignal
    order: dict[str, object]
    fill: dict[str, object]
    position: dict[str, object]
    result: dict[str, object]
    account_snapshot: ReportAccountSnapshot
    report: DailyReport
    publish: dict[str, str | None]
    event: dict[str, str]


DEFAULT_MARKET: Final = MarketFactoryConfig()
DEFAULT_BOOK: Final = BookFactoryConfig()
DEFAULT_SPOT: Final = SpotFactoryConfig()


def sample_market(config: MarketFactoryConfig = DEFAULT_MARKET) -> Market:
    now = utc_now()
    market_id = f"{config.asset.lower()}-{config.timeframe}-test"
    return Market(
        market_id=market_id,
        market_slug=f"{config.asset.lower()}-updown-{config.timeframe}-test",
        condition_id=f"condition-{market_id}",
        question_id=f"question-{market_id}",
        question=f"{config.asset} Up or Down {config.timeframe}? Price to beat ${config.price_to_beat}",
        asset=config.asset,
        timeframe=config.timeframe,
        start_ts=now - timedelta(seconds=180),
        end_ts=now + timedelta(seconds=config.seconds_to_close),
        status=MarketStatus.ACTIVE,
        resolution_source="test",
        price_to_beat=config.price_to_beat,
        outcome_tokens=[
            OutcomeToken(
                token_id=f"{market_id}-UP",
                side=Side.UP,
                outcome_name="Up",
                market_id=market_id,
            ),
            OutcomeToken(
                token_id=f"{market_id}-DOWN",
                side=Side.DOWN,
                outcome_name="Down",
                market_id=market_id,
            ),
        ],
    )


def sample_book(
    token_id: str, config: BookFactoryConfig = DEFAULT_BOOK
) -> SideBookView:
    """Cache-projection shaped book fixture (not domain OrderBook)."""
    bid = config.bid if config.bid is not None else max(0.01, config.ask - 0.03)
    return _side_book_view(
        token_id=token_id,
        ask=config.ask,
        bid=bid,
        size=config.size,
        freshness_ms=0,
        received_at=utc_now(),
    )


def sample_spot(config: SpotFactoryConfig = DEFAULT_SPOT) -> SpotPrice:
    return SpotPrice(
        asset=config.asset,
        symbol=f"{config.asset}USDT",
        price=config.price,
        received_at=utc_now(),
        event_time=utc_now(),
    )


def _side_book_view(
    *,
    token_id: str,
    ask: float,
    bid: float | None = None,
    size: float = 100.0,
    freshness_ms: int | None = 0,
    received_at: datetime | None = None,
    ask_levels: tuple[tuple[float, float], ...] | None = None,
) -> SideBookView:
    resolved_bid = bid if bid is not None else max(0.01, ask - 0.03)
    levels = ask_levels
    if levels is None:
        levels = (
            (ask, size),
            (min(0.99, ask + 0.02), size),
        )
    return SideBookView(
        token_id=token_id,
        best_bid=resolved_bid,
        best_ask=ask,
        spread=ask - resolved_bid,
        freshness_ms=freshness_ms,
        min_order_size=None,
        tick_size=None,
        last_trade_price=(ask + resolved_bid) / 2,
        last_trade_size=None,
        last_trade_timestamp=None,
        received_at=received_at,
        ask_levels=levels,
    )


def sample_market_view(
    *,
    up_ask: float = 0.82,
    down_ask: float = 0.18,
    seconds_to_close: int = 120,
    asset: str = "BTC",
    timeframe: str = "5m",
    price_to_beat: float = 100000.0,
    spot_price: float | None = None,
    view_id: str | None = None,
    created_at: datetime | None = None,
    start_ts: datetime | None = None,
    end_ts: datetime | None = None,
    up_bid: float | None = None,
    down_bid: float | None = None,
    book_freshness_ms: int | None = 0,
    spot_freshness_ms: int | None = 0,
    spot_source: str = "polymarket_rtds",
    include_spot: bool = True,
    include_up_book: bool = True,
    include_down_book: bool = True,
    metrics: Mapping[str, Any] | None = None,
    up_trades: Sequence[TradeView] = (),
    down_trades: Sequence[TradeView] = (),
    up_ask_levels: tuple[tuple[float, float], ...] | None = None,
    down_ask_levels: tuple[tuple[float, float], ...] | None = None,
) -> MarketView:
    """Build a fully-wired ``MarketView`` for alpha/gate fixtures."""
    resolved_created_at = created_at or utc_now()
    market = sample_market(
        MarketFactoryConfig(
            asset=asset,
            timeframe=timeframe,
            seconds_to_close=seconds_to_close,
            price_to_beat=price_to_beat,
        )
    )
    resolved_start = start_ts if start_ts is not None else market.start_ts
    resolved_end = (
        end_ts
        if end_ts is not None
        else resolved_created_at + timedelta(seconds=seconds_to_close)
    )
    empty_book = SideBookView(
        token_id="",
        best_bid=None,
        best_ask=None,
        spread=None,
        freshness_ms=None,
    )
    up = (
        _side_book_view(
            token_id=market.token_for(Side.UP).token_id,
            ask=up_ask,
            bid=up_bid,
            freshness_ms=book_freshness_ms,
            received_at=None,
            ask_levels=up_ask_levels,
        )
        if include_up_book
        else empty_book
    )
    down = (
        _side_book_view(
            token_id=market.token_for(Side.DOWN).token_id,
            ask=down_ask,
            bid=down_bid,
            freshness_ms=book_freshness_ms,
            received_at=None,
            ask_levels=down_ask_levels,
        )
        if include_down_book
        else empty_book
    )
    spot = None
    if include_spot:
        spot_cfg = (
            SpotFactoryConfig(asset=asset, price=spot_price)
            if spot_price is not None
            else SpotFactoryConfig(asset=asset)
        )
        spot_sample = sample_spot(spot_cfg)
        spot = SpotView(
            asset=spot_sample.asset,
            symbol=spot_sample.symbol,
            price=spot_sample.price,
            source=spot_source,
            freshness_ms=spot_freshness_ms,
            received_at=None,
        )
    return MarketView(
        view_id=view_id or new_id("view"),
        market_id=market.market_id,
        market_slug=market.market_slug,
        condition_id=market.condition_id,
        asset=market.asset,
        timeframe=market.timeframe,
        start_ts=resolved_start,
        end_ts=resolved_end,
        created_at=resolved_created_at,
        seconds_to_close=seconds_to_close,
        up=up,
        down=down,
        spot=spot,
        price_to_beat=price_to_beat,
        up_trades=tuple(up_trades),
        down_trades=tuple(down_trades),
        metrics=dict(metrics or {}),
        freshness=FreshnessView(
            up_book_ms=book_freshness_ms if include_up_book else None,
            down_book_ms=book_freshness_ms if include_down_book else None,
            spot_ms=spot_freshness_ms if include_spot else None,
            max_ms=max(
                x
                for x in (
                    book_freshness_ms if include_up_book else None,
                    book_freshness_ms if include_down_book else None,
                    spot_freshness_ms if include_spot else None,
                )
                if x is not None
            )
            if any(
                x is not None
                for x in (
                    book_freshness_ms if include_up_book else None,
                    book_freshness_ms if include_down_book else None,
                    spot_freshness_ms if include_spot else None,
                )
            )
            else None,
        ),
    )


def sample_storage_lifecycle(signal: SignalCandidate) -> StorageLifecycle:
    now = utc_now()
    rejected = RejectedSignal(
        candidate=signal, gate_name="gate", reason_code="wide_spread"
    )
    order = {
        "report_order_id": "po-1",
        "signal_id": signal.signal_id,
        "created_at": now.isoformat(),
        "asset": signal.asset,
        "timeframe": signal.timeframe,
        "strategy": signal.strategy,
        "market_id": signal.market_id,
        "market_slug": signal.market_slug,
        "token_id": signal.token_id,
        "side": signal.side.value,
        "order_type": "SIMULATED_MARKETABLE_LIMIT",
        "order_intent": None,
        "limit_price": 0.83,
        "reference_price": 0.82,
        "stake_usdc": 10.0,
        "status": "FILLED",
    }
    fill = {
        "report_fill_id": "pf-1",
        "report_order_id": order["report_order_id"],
        "signal_id": signal.signal_id,
        "created_at": now.isoformat(),
        "token_id": signal.token_id,
        "side": signal.side.value,
        "raw_best_ask": 0.82,
        "slippage_bps": 10.0,
        "fill_price": 0.821,
        "stake_usdc": 10.0,
        "shares": 12.18,
        "depth_checked": True,
    }
    position = {
        "report_position_id": "pp-1",
        "position_id": "pp-1",
        "signal_id": signal.signal_id,
        "report_order_id": order["report_order_id"],
        "report_fill_id": fill["report_fill_id"],
        "strategy": signal.strategy,
        "asset": signal.asset,
        "timeframe": signal.timeframe,
        "market_id": signal.market_id,
        "market_slug": signal.market_slug,
        "token_id": signal.token_id,
        "side": signal.side.value,
        "entry_price": fill["fill_price"],
        "shares": fill["shares"],
        "stake_usdc": fill["stake_usdc"],
        "opened_at": now.isoformat(),
        "status": PositionStatus.OPEN.value,
        "is_closed": False,
    }
    result = {
        "report_result_id": "pt-1",
        "signal_id": signal.signal_id,
        "report_position_id": str(position["report_position_id"]),
        "strategy": signal.strategy,
        "asset": signal.asset,
        "timeframe": signal.timeframe,
        "market_id": signal.market_id,
        "market_slug": signal.market_slug,
        "side": signal.side.value,
        "entry_price": float(fill["fill_price"]),
        "shares": float(fill["shares"]),
        "stake_usdc": float(fill["stake_usdc"]),
        "exit_mode": ExitMode.TAKE_PROFIT.value,
        "outcome_value": 1.0,
        "settlement_value": 12.8,
        "pnl_usdc": 2.8,
        "roi": 0.28,
        "result": TradeResultStatus.WIN.value,
        "opened_at": now.isoformat(),
        "closed_at": now.isoformat(),
    }
    account_snapshot = ReportAccountSnapshot(
        starting_balance=1000.0,
        cash_balance=990.0,
        realized_pnl=2.8,
        equity=1002.8,
        open_position_count=1,
    )
    report = DailyReport(
        report_id="dr-1",
        report_date=now.date(),
        starting_equity=1000.0,
        ending_equity=1002.8,
        net_pnl=2.8,
        return_rate=0.0028,
        total_signals=1,
        order_count=1,
        fill_count=1,
        rejected_order_count=0,
        open_positions=1,
        closed_positions=1,
        win_count=1,
        loss_count=0,
        void_count=0,
        win_rate=1.0,
        total_pnl_usdc=2.8,
        average_roi=0.28,
        max_drawdown=0.0,
        profit_factor=None,
        strategy_breakdown={
            signal.strategy: {
                "closed_positions": 1,
                "win_count": 1,
                "loss_count": 0,
                "total_pnl_usdc": 2.8,
            }
        },
    )
    publish = {
        "publish_id": "pub-1",
        "message_type": "daily_report",
        "signal_id": signal.signal_id,
        "status": "DRY_RUN",
        "sent_at": now.isoformat(),
    }
    event = {
        "event_id": "evt-1",
        "event_type": "storage_check",
        "severity": "INFO",
        "created_at": now.isoformat(),
    }
    return StorageLifecycle(
        rejected=rejected,
        order=order,
        fill=fill,
        position=position,
        result=result,
        account_snapshot=account_snapshot,
        report=report,
        publish=publish,
        event=event,
    )


def sample_report_result(**overrides: object) -> dict[str, object]:
    now = utc_now()
    base: dict[str, object] = {
        "schema_version": 1,
        "report_result_id": "pt-test",
        "signal_id": "sig-test",
        "report_position_id": "pos-test",
        "strategy": "ptb_diff",
        "asset": "BTC",
        "timeframe": "5m",
        "market_id": "market-test",
        "market_slug": "btc-updown-5m-test",
        "side": Side.UP.value,
        "entry_price": 0.50,
        "shares": 20.0,
        "stake_usdc": 10.0,
        "exit_mode": ExitMode.RESOLUTION.value,
        "outcome_value": 1.0,
        "settlement_value": 20.0,
        "pnl_usdc": 10.0,
        "roi": 1.0,
        "result": TradeResultStatus.WIN.value,
        "opened_at": now.isoformat(),
        "closed_at": now.isoformat(),
        "details": {},
    }
    base.update(overrides)
    return base
