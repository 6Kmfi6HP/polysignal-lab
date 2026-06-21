from __future__ import annotations

import asyncio
from datetime import UTC, date
from pathlib import Path

from polysignal_lab.app.demo_data import sample_book, sample_market, sample_spot
from polysignal_lab.config import Settings, load_settings
from polysignal_lab.data.market_snapshot import MarketSnapshotBuilder
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import OrderBookRegistry, SpotRegistry
from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.observability.logger import configure_logging
from polysignal_lab.paper.report import PaperReportService
from polysignal_lab.paper.settlement import PaperSettlementEngine
from polysignal_lab.paper.simulator import PaperSimulator
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.publish.telegram_publisher import TelegramPublisher
from polysignal_lab.signal_layer.consensus import ConsensusEngine
from polysignal_lab.signal_layer.formatter import MessageFormatter
from polysignal_lab.signal_layer.gate import SignalGate
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore
from polysignal_lab.strategies.factory import build_strategies

import random as _rnd


async def run_demo(settings: Settings | None = None, base_dir: str | Path = ".") -> dict:
    """Run a demo cycle with randomized market state and realistic paper trading.

    Each call produces different signals, reliable fills, and mixed WIN/LOSS
    outcomes so the demo is useful for visualisation and end-to-end testing.
    """
    settings = settings or load_settings()
    settings.validate_runtime_environment(environ={})
    configure_logging(settings.app.log_level)
    base = Path(base_dir)
    logs = JSONLStore(base / settings.storage.jsonl_dir)
    state = StateStore(base / settings.storage.state_dir)
    sqlite = SQLiteStore(base / settings.storage.sqlite_path)
    books = OrderBookRegistry()
    spots = SpotRegistry()

    # ------------------------------------------------------------------
    # 1. Randomised market state — each run gets different prices
    # ------------------------------------------------------------------
    _rnd.seed()  # fresh entropy each call

    random_offset = _rnd.randint(0, 10)
    secs = 90 + random_offset * 5  # 90 – 140 seconds to close
    ptb = round(99800.0 + random_offset * 40, 2)
    # Spot is always above PTB (so PTB Diff strategy triggers for UP side)
    spot_price = round(ptb + 80.0 + _rnd.random() * 60.0, 2)

    market = sample_market("BTC", "5m", seconds_to_close=secs, price_to_beat=ptb)

    # UP ask kept ≤ 0.78 so PTB Diff trigger (max_token_price=0.78) can fire
    up_ask = round(0.45 + _rnd.random() * 0.33, 2)  # 0.45 – 0.78
    up_bid = max(0.01, round(up_ask - 0.04, 2))
    # DOWN ask ≈ complement of UP ask with ±5% noise
    down_ask = round(1.0 - up_ask + (-0.05 + _rnd.random() * 0.10), 2)
    down_bid = max(0.01, round(down_ask - 0.04, 2))
    book_size = 300 + _rnd.randint(0, 400)  # 300 – 700

    up = sample_book(market.token_for(Side.UP).token_id,
                     ask=up_ask, bid=up_bid, size=book_size)
    down = sample_book(market.token_for(Side.DOWN).token_id,
                       ask=down_ask, bid=down_bid, size=book_size)
    books.update(up)
    books.update(down)
    spots.update(sample_spot("BTC", spot_price))

    # ------------------------------------------------------------------
    # 2. Infrastructure
    # ------------------------------------------------------------------
    builder = MarketSnapshotBuilder(books, spots, PriceToBeatProvider())
    strategies = build_strategies(settings.strategies)
    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    consensus = ConsensusEngine(settings.signal.consensus_window_sec,
                                settings.signal.consensus_enabled)
    wallet = PaperWallet(settings.paper_trading.starting_balance_usdc)
    paper = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)
    settlement = PaperSettlementEngine(wallet)
    formatter = MessageFormatter(settings.telegram.max_message_chars)
    publisher = TelegramPublisher(settings.telegram)

    accepted: list = []
    rejected: list = []

    # ------------------------------------------------------------------
    # 3. Seed VWAP rolling windows with prices trending toward up_ask
    # ------------------------------------------------------------------
    trend_start = max(0.35, round(up_ask - 0.12, 2))
    seed_prices = [
        trend_start,
        round(trend_start + 0.03, 2),
        round(trend_start + 0.06, 2),
        round(up_ask - 0.02, 2),
    ]
    for ask in seed_prices:
        books.update(sample_book(market.token_for(Side.UP).token_id,
                                 ask=ask, bid=max(0.01, ask - 0.03),
                                 size=500))
        books.update(down)
        snapshot = await builder.build(market)
        for strategy in strategies:
            strategy.evaluate(snapshot)

    # Final push to the randomised up_ask price
    books.update(up)
    snapshot = await builder.build(market)

    # ------------------------------------------------------------------
    # 4. Evaluate strategies & enforce Gate
    # ------------------------------------------------------------------
    for strategy in strategies:
        for candidate in strategy.evaluate(snapshot):
            decision = gate.evaluate(candidate, snapshot)
            if decision.accepted and decision.signal:
                sig = decision.signal
                accepted.append(sig)
                logs.append("signals", sig)
                sqlite.insert_signal(sig)
                publish = await publisher.send(
                    formatter.signal_message(sig, settings.paper_trading.fixed_stake_usdc),
                    "signal", sig.signal_id,
                )
                logs.append("telegram_publish", publish.as_dict())
                sqlite.insert_telegram_publish(publish.as_dict())
                cons_sig = consensus.add(sig)
                if cons_sig:
                    accepted.append(cons_sig)
                    logs.append("signals", cons_sig)
                    sqlite.insert_signal(cons_sig)
            elif decision.rejected:
                rej = decision.rejected
                rejected.append(rej)
                logs.append("rejected_signals", rej)
                sqlite.insert_rejected_signal(rej)

    # ------------------------------------------------------------------
    # 5. Paper trade simulation — with fresh books so fills always succeed
    # ------------------------------------------------------------------
    sim_results = []
    trade_results = []
    for sig in accepted:
        # Build a brand-new book right now — the microsecond difference
        # vs. order.created_at guarantees the STALE_ORDERBOOK check passes.
        ask_price = snapshot.ask_for(sig.side) or up_ask
        bid_price = snapshot.bid_for(sig.side)
        fresh_book = sample_book(
            token_id=sig.token_id,
            ask=ask_price,
            bid=bid_price,
            size=book_size,
        )
        sim = paper.process_signal(sig, fresh_book)
        sim_results.append(sim)
        logs.append("paper_orders", sim.order)
        sqlite.insert_paper_order(sim.order)
        if sim.fill and sim.position:
            logs.append("paper_fills", sim.fill)
            logs.append("paper_positions", sim.position)
            sqlite.insert_paper_fill(sim.fill)
            sqlite.upsert_paper_position(sim.position)

            # ---- Randomised settlement: ~60 % WIN, ~40 % LOSS ----
            market_copy = market.model_copy(deep=True)
            if _rnd.random() < 0.6:
                market_copy.resolved_outcome = sig.side       # WIN
            else:
                market_copy.resolved_outcome = sig.side.opposite  # LOSS
            market_copy.status = MarketStatus.RESOLVED
            result = settlement.settle(sim.position, market_copy)

            trade_results.append(result)
            logs.append("paper_results", result)
            sqlite.upsert_paper_position(sim.position)
            sqlite.insert_paper_trade_result(result)
            publish = await publisher.send(
                formatter.result_message(result), "paper_result", result.signal_id,
            )
            logs.append("telegram_publish", publish.as_dict())
            sqlite.insert_telegram_publish(publish.as_dict())

    # ------------------------------------------------------------------
    # 6. Snapshot & Report
    # ------------------------------------------------------------------
    wallet_snapshot = wallet.snapshot()
    logs.append("paper_wallet_snapshots", wallet_snapshot)
    sqlite.insert_wallet_snapshot(wallet_snapshot)
    report = PaperReportService().build_daily_report(
        report_date=date.today(),
        starting_equity=settings.paper_trading.starting_balance_usdc,
        ending_equity=wallet.equity,
        total_signals=len(accepted),
        paper_orders=len(sim_results),
        paper_fills=sum(1 for r in sim_results if r.fill),
        rejected_paper_orders=sum(1 for r in sim_results if not r.fill),
        open_positions=wallet.open_position_count,
        results=trade_results,
        equity_curve=[settings.paper_trading.starting_balance_usdc, wallet.equity],
    )
    logs.append("daily_reports", report)
    sqlite.insert_daily_report(report)
    state.write("paper_wallet", wallet_snapshot)
    state.write("open_positions",
                [p.model_dump(mode="json") for p in wallet.open_positions.values()])
    state.write("market_cache", [market.model_dump(mode="json")])
    state.write("signal_dedupe", gate.deduper.snapshot())
    return {
        "accepted_signals": len(accepted),
        "rejected_signals": len(rejected),
        "paper_orders": len(sim_results),
        "paper_fills": sum(1 for r in sim_results if r.fill),
        "paper_results": len(trade_results),
        "ending_equity": wallet.equity,
        "sqlite_counts": sqlite.counts(),
    }


def main() -> None:
    result = asyncio.run(run_demo(load_settings()))
    print(result)


if __name__ == "__main__":
    main()
