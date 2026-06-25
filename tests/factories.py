from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from polysignal_lab.domain.enums import (
    ExitMode,
    MarketStatus,
    OrderStatus,
    PositionStatus,
    Side,
    TradeResultStatus,
)
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult, PaperWalletSnapshot
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
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
    order: PaperOrder
    fill: PaperFill
    position: PaperPosition
    result: PaperTradeResult
    wallet: PaperWalletSnapshot
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
            OutcomeToken(token_id=f"{market_id}-UP", side=Side.UP, outcome_name="Up", market_id=market_id),
            OutcomeToken(token_id=f"{market_id}-DOWN", side=Side.DOWN, outcome_name="Down", market_id=market_id),
        ],
    )


def sample_book(token_id: str, config: BookFactoryConfig = DEFAULT_BOOK) -> OrderBook:
    bid = config.bid if config.bid is not None else max(0.01, config.ask - 0.03)
    return OrderBook(
        market_id=token_id.rsplit("-", 1)[0],
        token_id=token_id,
        bids=[BookLevel(price=bid, size=config.size), BookLevel(price=max(0.01, bid - 0.01), size=config.size)],
        asks=[
            BookLevel(price=config.ask, size=config.size),
            BookLevel(price=min(0.99, config.ask + 0.02), size=config.size),
        ],
        last_trade_price=(config.ask + bid) / 2,
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


def sample_snapshot(
    *,
    up_ask: float = 0.82,
    down_ask: float = 0.18,
    seconds_to_close: int = 120,
    asset: str = "BTC",
    timeframe: str = "5m",
    price_to_beat: float = 100000.0,
    spot_price: float | None = None,
    snapshot_id: str | None = None,
) -> MarketSnapshot:
    """Build a fully-wired ``MarketSnapshot`` from the existing sample helpers.

    Books are stamped at ``created_at`` and freshness is zeroed so
    ``market_view_from_snapshot`` always assembles a non-None ``MarketView``
    for any caller-supplied ask/spot combination.
    """
    created_at = utc_now()
    market = sample_market(
        MarketFactoryConfig(
            asset=asset,
            timeframe=timeframe,
            seconds_to_close=seconds_to_close,
            price_to_beat=price_to_beat,
        )
    ).model_copy(update={"end_ts": created_at + timedelta(seconds=seconds_to_close)})
    up_book = sample_book(
        market.token_for(Side.UP).token_id, BookFactoryConfig(ask=up_ask)
    ).model_copy(update={"received_at": created_at})
    down_book = sample_book(
        market.token_for(Side.DOWN).token_id, BookFactoryConfig(ask=down_ask)
    ).model_copy(update={"received_at": created_at})
    spot_cfg = (
        SpotFactoryConfig(asset=asset, price=spot_price)
        if spot_price is not None
        else SpotFactoryConfig(asset=asset)
    )
    spot = sample_spot(spot_cfg).model_copy(
        update={"source": "polymarket_rtds", "received_at": created_at}
    )
    return MarketSnapshot(
        snapshot_id=snapshot_id or new_id("snapshot"),
        created_at=created_at,
        market=market,
        up_book=up_book,
        down_book=down_book,
        spot=spot,
        price_to_beat=price_to_beat,
        freshness=FreshnessState(up_book_ms=0, down_book_ms=0, spot_ms=0, max_ms=0),
        metrics={},
    )


def sample_storage_lifecycle(signal: SignalCandidate) -> StorageLifecycle:
    now = utc_now()
    rejected = RejectedSignal(candidate=signal, gate_name="gate", reason_code="wide_spread")
    order = PaperOrder(
        paper_order_id="po-1",
        signal_id=signal.signal_id,
        asset=signal.asset,
        timeframe=signal.timeframe,
        strategy=signal.strategy,
        market_id=signal.market_id,
        market_slug=signal.market_slug,
        token_id=signal.token_id,
        side=signal.side,
        limit_price=0.83,
        reference_price=0.82,
        stake_usdc=10.0,
        status=OrderStatus.FILLED,
    )
    fill = PaperFill(
        paper_fill_id="pf-1",
        paper_order_id=order.paper_order_id,
        signal_id=signal.signal_id,
        token_id=signal.token_id,
        side=signal.side,
        raw_best_ask=0.82,
        slippage_bps=10.0,
        fill_price=0.821,
        stake_usdc=10.0,
        shares=12.18,
        depth_checked=True,
    )
    position = PaperPosition(
        paper_position_id="pp-1",
        signal_id=signal.signal_id,
        paper_order_id=order.paper_order_id,
        paper_fill_id=fill.paper_fill_id,
        strategy=signal.strategy,
        asset=signal.asset,
        timeframe=signal.timeframe,
        market_id=signal.market_id,
        market_slug=signal.market_slug,
        token_id=signal.token_id,
        side=signal.side,
        entry_price=fill.fill_price,
        shares=fill.shares,
        stake_usdc=fill.stake_usdc,
        status=PositionStatus.OPEN,
    )
    result = PaperTradeResult(
        paper_trade_id="pt-1",
        signal_id=signal.signal_id,
        paper_position_id=position.paper_position_id,
        strategy=signal.strategy,
        asset=signal.asset,
        timeframe=signal.timeframe,
        market_id=signal.market_id,
        market_slug=signal.market_slug,
        side=signal.side,
        entry_price=fill.fill_price,
        shares=fill.shares,
        stake_usdc=fill.stake_usdc,
        exit_mode=ExitMode.TAKE_PROFIT,
        outcome_value=1.0,
        settlement_value=12.8,
        pnl_usdc=2.8,
        roi=0.28,
        result=TradeResultStatus.WIN,
        opened_at=now,
    )
    wallet = PaperWalletSnapshot(
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
        paper_pnl=2.8,
        paper_roi=0.0028,
        total_signals=1,
        paper_orders=1,
        paper_fills=1,
        rejected_paper_orders=0,
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
        strategy_breakdown={signal.strategy: {"closed_positions": 1, "win_count": 1, "loss_count": 0, "total_pnl_usdc": 2.8}},
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
        wallet=wallet,
        report=report,
        publish=publish,
        event=event,
    )
