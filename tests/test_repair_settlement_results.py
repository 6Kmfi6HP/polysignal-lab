from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.domain.enums import MarketStatus, PositionStatus, Side, TradeResultStatus
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.paper_order import PaperFill
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperWalletSnapshot
from polysignal_lab.paper.settlement import PaperSettlementEngine
from polysignal_lab.paper.settlement_sources import ResolutionDecision
from polysignal_lab.utils import utc_now
from scripts.repair_settlement_results import RepairConfig, audit, backfill, reconcile_wallet, run_repair

from factories import MarketFactoryConfig, sample_market


class _LedgerWallet:
    def __init__(self, starting_balance: float) -> None:
        self.starting_balance = starting_balance
        self.cash_balance = starting_balance
        self.realized_pnl = 0.0
        self.open_positions: dict[str, PaperPosition] = {}

    def apply_fill(self, position: PaperPosition) -> None:
        self.open_positions[position.paper_position_id] = position
        self.cash_balance -= position.stake_usdc

    @property
    def open_position_count(self) -> int:
        return len(self.open_positions)

    def close_position(self, position_id: str, settlement_value: float, pnl: float) -> None:
        self.open_positions.pop(position_id, None)
        self.cash_balance += settlement_value
        self.realized_pnl += pnl

    def snapshot(self) -> PaperWalletSnapshot:
        equity = self.cash_balance + sum(
            position.stake_usdc for position in self.open_positions.values()
        )
        return PaperWalletSnapshot(
            starting_balance=self.starting_balance,
            cash_balance=self.cash_balance,
            realized_pnl=self.realized_pnl,
            equity=equity,
            open_position_count=self.open_position_count,
            created_at=utc_now(),
        )


class _NoopExitEngine:
    def evaluate(self, position: PaperPosition, book: object) -> None:
        return None


def _resolved_market() -> Market:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=-60))
    return market.model_copy(update={"status": MarketStatus.CLOSED})


def _open_position(market: Market, *, position_id: str = "pp-repair-1") -> PaperPosition:
    token = market.token_for(Side.UP)
    now = utc_now()
    return PaperPosition(
        paper_position_id=position_id,
        signal_id="sig-repair-1",
        paper_order_id="po-repair-1",
        paper_fill_id="pf-repair-1",
        strategy="ptb_diff",
        asset=market.asset,
        timeframe=market.timeframe,
        market_id=market.market_id,
        market_slug=market.market_slug,
        token_id=token.token_id,
        side=Side.UP,
        entry_price=0.40,
        shares=25.0,
        stake_usdc=10.0,
        status=PositionStatus.OPEN,
        opened_at=now,
    )


def _scheduler(tmp_path: Path, settings) -> PolySignalScheduler:
    settings.data.binance.enabled = False
    settings.data.polymarket.use_market_ws = False
    settings.telegram.send_paper_results = False
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler.wallet = _LedgerWallet(scheduler.settings.paper_trading.starting_balance_usdc)
    scheduler.paper = None
    scheduler.exits = _NoopExitEngine()
    scheduler.settlement = PaperSettlementEngine()
    return scheduler


def _seed_open_position(
    tmp_path: Path,
    settings,
    *,
    market: Market | None = None,
    position_id: str = "pp-repair-1",
    wallet_cash: float | None = None,
) -> tuple[PolySignalScheduler, PaperPosition, Market]:
    market = market or _resolved_market()
    position = _open_position(market, position_id=position_id)
    scheduler = _scheduler(tmp_path, settings)
    scheduler.sqlite.upsert_market(market)
    scheduler.persistence.upsert_paper_position(position)
    scheduler.persistence.insert_paper_fill(
        PaperFill(
            paper_fill_id=position.paper_fill_id,
            paper_order_id=position.paper_order_id,
            signal_id=position.signal_id,
            token_id=position.token_id,
            side=position.side,
            raw_best_ask=position.entry_price,
            slippage_bps=0.0,
            fill_price=position.entry_price,
            stake_usdc=position.stake_usdc,
            shares=position.shares,
            depth_checked=True,
            available_depth_usdc=position.stake_usdc,
            fill_ratio=1.0,
            created_at=position.opened_at,
        )
    )
    starting = settings.paper_trading.starting_balance_usdc
    cash = wallet_cash if wallet_cash is not None else starting - position.stake_usdc
    scheduler.persistence.insert_wallet_snapshot(
        PaperWalletSnapshot(
            starting_balance=starting,
            cash_balance=cash,
            realized_pnl=0.0,
            equity=cash + position.stake_usdc,
            open_position_count=1,
            created_at=utc_now(),
        )
    )
    return scheduler, position, market


def _win_decision(market: Market) -> ResolutionDecision:
    token = market.token_for(Side.UP)
    return ResolutionDecision(
        market.market_id,
        market.condition_id,
        "resolved",
        "chain",
        {token.token_id: 1.0, market.token_for(Side.DOWN).token_id: 0.0},
        False,
        (),
        {"settlement_source": "chain", "condition_id": market.condition_id},
    )


def _cancelled_decision(market: Market) -> ResolutionDecision:
    return ResolutionDecision(
        market.market_id,
        market.condition_id,
        "cancelled",
        "gamma",
        {},
        False,
        (),
        {"settlement_source": "gamma"},
    )


def _unknown_decision(market: Market) -> ResolutionDecision:
    return ResolutionDecision(
        market.market_id,
        market.condition_id,
        "unknown",
        "none",
        {},
        False,
        (),
        {"reason": "NO_RESOLVED_EVIDENCE"},
    )


def _repair_config(
    tmp_path: Path,
    *,
    mode: str = "audit",
    apply: bool = False,
    backup: Path | None = None,
) -> RepairConfig:
    return RepairConfig(
        config_path=None,
        data_dir=tmp_path,
        mode=mode,
        dry_run=not apply,
        backup_path=backup,
        since=None,
        until=None,
        market_id=None,
        position_id=None,
        publish_telegram=False,
        force_correct=False,
    )


@pytest.mark.anyio
async def test_audit_finds_open_position_on_resolved_market(tmp_path, settings) -> None:
    scheduler, position, market = _seed_open_position(tmp_path, settings)
    scheduler.settlement_resolver = AsyncMock()
    scheduler.settlement_resolver.resolve_market.return_value = _win_decision(market)
    await scheduler._restore_wallet_state()

    report = await audit(scheduler, _repair_config(tmp_path))

    assert len(report.classes["C1_missed_settlement"]) == 1
    assert report.classes["C1_missed_settlement"][0]["paper_position_id"] == position.paper_position_id
    rows = scheduler.sqlite.query_json("paper_trade_results")
    assert rows == []
    assert scheduler.sqlite.query_json("paper_positions")[0]["status"] == "OPEN"


@pytest.mark.anyio
async def test_backfill_closes_position_and_inserts_result(tmp_path, settings) -> None:
    scheduler, position, market = _seed_open_position(tmp_path, settings)
    scheduler.settlement_resolver = AsyncMock()
    scheduler.settlement_resolver.resolve_market.return_value = _win_decision(market)
    await scheduler._restore_wallet_state()
    backup = tmp_path / "backup.sqlite3"
    config = _repair_config(tmp_path, mode="backfill", apply=True, backup=backup)

    report = await backfill(scheduler, config)

    assert report["applied"] == 1
    position_rows = scheduler.sqlite.query_json("paper_positions")
    result_rows = scheduler.sqlite.query_json("paper_trade_results")
    assert position_rows[0]["status"] == "CLOSED"
    assert result_rows[0]["result"] == "WIN"
    assert result_rows[0]["details"]["settlement_source"] == "chain"
    assert backup.exists()


@pytest.mark.anyio
async def test_backfill_idempotent_skips_existing_result(tmp_path, settings) -> None:
    scheduler, _, market = _seed_open_position(tmp_path, settings)
    scheduler.settlement_resolver = AsyncMock()
    scheduler.settlement_resolver.resolve_market.return_value = _win_decision(market)
    await scheduler._restore_wallet_state()
    backup = tmp_path / "backup.sqlite3"
    config = _repair_config(tmp_path, mode="backfill", apply=True, backup=backup)

    first = await backfill(scheduler, config)
    second = await backfill(scheduler, config)

    assert first["applied"] == 1
    assert second["applied"] == 0
    assert len(scheduler.sqlite.query_json("paper_trade_results")) == 1


@pytest.mark.anyio
async def test_backfill_unknown_leaves_position_open(tmp_path, settings) -> None:
    scheduler, position, market = _seed_open_position(tmp_path, settings)
    scheduler.settlement_resolver = AsyncMock()
    scheduler.settlement_resolver.resolve_market.return_value = _unknown_decision(market)
    await scheduler._restore_wallet_state()
    backup = tmp_path / "backup.sqlite3"
    config = _repair_config(tmp_path, mode="backfill", apply=True, backup=backup)

    report = await backfill(scheduler, config)

    assert report["applied"] == 0
    assert len(report["skipped_unknown"]) == 1
    assert report["skipped_unknown"][0]["paper_position_id"] == position.paper_position_id
    assert scheduler.sqlite.query_json("paper_positions")[0]["status"] == "OPEN"
    assert scheduler.sqlite.query_json("paper_trade_results") == []


@pytest.mark.anyio
async def test_wallet_reconcile_fixes_cash_after_backfill(tmp_path, settings) -> None:
    scheduler, _, market = _seed_open_position(tmp_path, settings, wallet_cash=500.0)
    scheduler.settlement_resolver = AsyncMock()
    scheduler.settlement_resolver.resolve_market.return_value = _win_decision(market)
    await scheduler._restore_wallet_state()
    backup = tmp_path / "backup.sqlite3"
    config = _repair_config(tmp_path, mode="backfill", apply=True, backup=backup)
    await backfill(scheduler, config)

    wallet_report = reconcile_wallet(scheduler, _repair_config(tmp_path, mode="wallet", apply=True, backup=backup))

    assert wallet_report["applied"] is True
    latest = scheduler.sqlite.restore_latest_wallet_snapshot()
    assert latest is not None
    starting = settings.paper_trading.starting_balance_usdc
    settlement = scheduler.sqlite.query_json("paper_trade_results")[0]["settlement_value"]
    assert latest["cash_balance"] == pytest.approx(starting + settlement - 10.0)


def test_apply_requires_backup(tmp_path, settings, capsys) -> None:
    code = run_repair(
        RepairConfig(
            config_path=None,
            data_dir=tmp_path,
            mode="backfill",
            dry_run=False,
            backup_path=None,
            since=None,
            until=None,
            market_id=None,
            position_id=None,
            publish_telegram=False,
            force_correct=False,
        )
    )

    assert code == 2
    assert "--backup is required" in capsys.readouterr().err


@pytest.mark.anyio
async def test_cancelled_market_refunds_stake(tmp_path, settings) -> None:
    scheduler, position, market = _seed_open_position(tmp_path, settings)
    scheduler.settlement_resolver = AsyncMock()
    scheduler.settlement_resolver.resolve_market.return_value = _cancelled_decision(market)
    await scheduler._restore_wallet_state()
    backup = tmp_path / "backup.sqlite3"
    config = _repair_config(tmp_path, mode="backfill", apply=True, backup=backup)

    await backfill(scheduler, config)

    result = scheduler.sqlite.query_json("paper_trade_results")[0]
    assert result["result"] == "VOID"
    assert result["settlement_value"] == pytest.approx(position.stake_usdc)
