from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from polysignal_lab.config import ExitModelConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.paper_order import PaperFill
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.paper.wallet import PaperWallet

COMPATIBILITY_ONLY = True


class _PaperTradingSettings(Protocol):
    starting_balance_usdc: float
    exit_model: ExitModelConfig


class _SchedulerSettings(Protocol):
    paper_trading: _PaperTradingSettings


class _Persistence(Protocol):
    def append_log(self, stream: str, payload: object) -> None: ...
    def insert_paper_fill(self, fill: object) -> None: ...
    def upsert_paper_position(self, position: object) -> None: ...
    def insert_wallet_snapshot(self, snapshot: object) -> None: ...


class _PaperPortfolio(Protocol):
    def configure(
        self,
        *,
        wallet: PaperWallet,
        paper: object | None,
        exits: object,
        settlement: object,
        markets: object,
        books: object,
        persistence: object,
    ) -> None: ...


class _SchedulerCompat(Protocol):
    settings: _SchedulerSettings
    wallet: PaperWallet
    paper: object | None
    exits: object
    settlement: object
    persistence: _Persistence
    paper_portfolio: _PaperPortfolio
    ctx: object


def init_scheduler_paper_components(scheduler: object) -> None:
    """Create a compat paper ledger fed by Nautilus fills for settlement/reporting.

    This does not revive the legacy paper simulator. It only creates the
    wallet/exits/settlement projection objects required by
    ``scheduler.check_settlements()`` and related reporting paths.
    """
    sched = cast(_SchedulerCompat, scheduler)
    if getattr(sched, "_nautilus_runtime_compat_only", False):
        return
    settings = getattr(sched, "settings", None)
    if settings is None or getattr(settings, "paper_trading", None) is None:
        return

    from polysignal_lab.paper.exit_engine import PaperExitEngine
    from polysignal_lab.paper.settlement import PaperSettlementEngine

    sched.wallet = PaperWallet(settings.paper_trading.starting_balance_usdc)
    sched.paper = None
    sched.exits = PaperExitEngine(settings.paper_trading.exit_model, sched.wallet)
    sched.settlement = PaperSettlementEngine(sched.wallet)
    paper_portfolio = getattr(sched, "paper_portfolio", None)
    configure = getattr(paper_portfolio, "configure", None)
    if callable(configure):
        _ = configure(
            wallet=sched.wallet,
            paper=None,
            exits=sched.exits,
            settlement=sched.settlement,
            markets=getattr(getattr(sched, "ctx", None), "markets", None),
            books=getattr(getattr(sched, "ctx", None), "books", None),
            persistence=sched.persistence,
        )
    setattr(sched, "_nautilus_runtime_compat_only", True)


def mirror_nautilus_fill_into_scheduler(
    scheduler: object,
    payload: Mapping[str, object],
) -> PaperPosition | None:
    sched = cast(_SchedulerCompat, scheduler)
    if not getattr(sched, "_nautilus_runtime_compat_only", False):
        return None

    signal_id = _text(payload.get("signal_id"))
    market_id = _text(payload.get("market_id"))
    market_slug = _text(payload.get("market_slug"))
    token_id = _text(payload.get("token_id"))
    strategy = _text(payload.get("strategy"))
    asset = _text(payload.get("asset"))
    timeframe = _text(payload.get("timeframe"))
    paper_order_id = _text(payload.get("client_order_id") or payload.get("order_id"))
    paper_fill_id = _text(payload.get("paper_fill_id") or paper_order_id)
    side_text = _text(payload.get("side")).upper()
    fill_price = _float(payload.get("fill_price"))
    shares = _float(payload.get("shares"))
    stake_usdc = _float(payload.get("stake_usdc"))
    metrics = _metrics(payload.get("metrics"))

    if (
        not signal_id
        or not market_id
        or not token_id
        or not strategy
        or not asset
        or not timeframe
        or not paper_order_id
        or not paper_fill_id
        or side_text not in {"UP", "DOWN"}
        or fill_price <= 0.0
        or shares <= 0.0
        or stake_usdc <= 0.0
    ):
        return None

    existing_positions = sched.wallet.open_positions
    if any(position.paper_fill_id == paper_fill_id for position in existing_positions.values()):
        return None

    side = Side(side_text)
    fill = PaperFill(
        paper_fill_id=paper_fill_id,
        paper_order_id=paper_order_id,
        signal_id=signal_id,
        token_id=token_id,
        side=side,
        raw_best_ask=fill_price,
        slippage_bps=0.0,
        fill_price=fill_price,
        stake_usdc=stake_usdc,
        shares=shares,
        depth_checked=True,
        available_depth_usdc=stake_usdc,
        fill_ratio=1.0,
        metrics=metrics,
    )
    position = PaperPosition(
        paper_position_id=paper_fill_id,
        signal_id=signal_id,
        paper_order_id=paper_order_id,
        paper_fill_id=paper_fill_id,
        strategy=strategy,
        asset=asset,
        timeframe=timeframe,
        market_id=market_id,
        market_slug=market_slug,
        token_id=token_id,
        side=side,
        entry_price=fill_price,
        shares=shares,
        stake_usdc=stake_usdc,
        signal_confidence=_confidence(metrics.get("confidence")),
        signal_metrics=metrics,
    )

    sched.wallet.apply_fill(position)
    sched.persistence.append_log("paper_fills", fill)
    sched.persistence.insert_paper_fill(fill)
    sched.persistence.append_log("paper_positions", position)
    sched.persistence.upsert_paper_position(position)
    wallet_snapshot = sched.wallet.snapshot()
    sched.persistence.append_log("paper_wallet_snapshots", wallet_snapshot)
    sched.persistence.insert_wallet_snapshot(wallet_snapshot)
    return position


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _float(value: object) -> float:
    if not isinstance(value, (int, float, str)):
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def _confidence(value: object) -> float | None:
    if value in (None, ""):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _metrics(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(cast(Mapping[str, object], value))
    return {}
