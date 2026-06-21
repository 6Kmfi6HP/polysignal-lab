from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from polysignal_lab.config import Settings
from polysignal_lab.data.binance_spot_ws import BinanceSpotFeed
from polysignal_lab.data.market_snapshot import MarketSnapshotBuilder
from polysignal_lab.data.polymarket_clob_rest import PolymarketCLOBRestClient
from polysignal_lab.data.polymarket_clob_ws import PolymarketMarketWebSocket
from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import MarketRegistry, OrderBookRegistry, SpotRegistry
from polysignal_lab.domain.enums import MarketStatus
from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult
from polysignal_lab.domain.signal import SignalCandidate
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


@dataclass
class ServiceContext:
    settings: Settings
    markets: MarketRegistry = field(default_factory=MarketRegistry)
    books: OrderBookRegistry = field(default_factory=OrderBookRegistry)
    spots: SpotRegistry = field(default_factory=SpotRegistry)


class PolySignalScheduler:
    def __init__(self, settings: Settings, base_dir: str | Path = "."):
        self.settings = settings
        self.ctx = ServiceContext(settings=settings)
        self.discovery = MarketDiscovery(settings.data.polymarket, settings.markets)
        self.rest = PolymarketCLOBRestClient(settings.data.polymarket)
        self.ptb = PriceToBeatProvider()
        self.snapshot_builder = MarketSnapshotBuilder(self.ctx.books, self.ctx.spots, self.ptb)
        self.strategies = build_strategies(settings.strategies)
        self.gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
        self.consensus = ConsensusEngine(settings.signal.consensus_window_sec, settings.signal.consensus_enabled)
        self.wallet = PaperWallet(settings.paper_trading.starting_balance_usdc)
        self.paper = PaperSimulator(settings.paper_trading, settings.data.polymarket, self.wallet)
        self.settlement = PaperSettlementEngine(self.wallet)
        self.formatter = MessageFormatter(settings.telegram.max_message_chars)
        self.publisher = TelegramPublisher(settings.telegram)
        self.logger = logging.getLogger("polysignal_lab.scheduler")

        # WebSocket connections
        self.poly_ws = PolymarketMarketWebSocket(settings.data.polymarket, self.ctx.books)
        self.binance_ws = BinanceSpotFeed(settings.data.binance, self.ctx.spots)

        # Storage
        base = Path(base_dir)
        self.logs = JSONLStore(base / settings.storage.jsonl_dir)
        self.state = StateStore(base / settings.storage.state_dir)
        self.sqlite = SQLiteStore(base / settings.storage.sqlite_path)

        # Background tasks
        self._ws_tasks: list[asyncio.Task] = []
        self._running = False

    async def _restore_wallet_state(self) -> None:
        """Restore wallet from persisted state on restart.

        Reads state/open_positions.json and state/paper_wallet.json
        to rebuild in-memory wallet state so open positions from
        before a container restart can still be settled.

        Priority: SQLite > state files (SQLite is the authoritative store).
        """
        from polysignal_lab.domain.paper_position import PaperPosition
        from polysignal_lab.domain.enums import PositionStatus

        restored = 0

        # Phase 1: restore from SQLite (most reliable, has all data)
        try:
            sqlite_positions = self.sqlite.query_json(
                "paper_positions",
                where="WHERE status = ?",
                params=(PositionStatus.OPEN.value,),
            )
            for pdata in sqlite_positions:
                try:
                    position = PaperPosition.model_validate(pdata)
                    self.wallet.open_positions[position.paper_position_id] = position
                    restored += 1
                except Exception as exc:
                    self.logger.warning("Failed to restore position from SQLite: %s", exc)
            if restored > 0:
                self.logger.info("Restored %d open positions from SQLite", restored)
        except Exception as exc:
            self.logger.warning("SQLite restore failed: %s", exc)

        # Phase 2: supplement from state files (for cash balance / realized_pnl)
        if restored == 0:
            # Fallback to state files if SQLite has nothing
            positions_data = self.state.read("open_positions", default=[])
            for pdata in positions_data:
                try:
                    position = PaperPosition.model_validate(pdata)
                    if position.paper_position_id not in self.wallet.open_positions:
                        self.wallet.open_positions[position.paper_position_id] = position
                        restored += 1
                except Exception as exc:
                    self.logger.warning("Failed to restore position %s: %s", pdata.get("paper_position_id", "?"), exc)

        # Restore cash balance and realized PnL from wallet snapshot
        wallet_data = self.state.read("paper_wallet", default=None)
        if wallet_data:
            cash = wallet_data.get("cash_balance")
            if cash is not None:
                self.wallet.cash_balance = float(cash)
            rpnl = wallet_data.get("realized_pnl")
            if rpnl is not None:
                self.wallet.realized_pnl = float(rpnl)

        if restored > 0:
            self.logger.info(
                "Restored wallet: %d open positions, cash=%.2f, realized_pnl=%.2f",
                restored, self.wallet.cash_balance or 0, self.wallet.realized_pnl or 0,
            )

    async def refresh_markets_once(self) -> None:
        """Discover markets from Gamma API, fetch order books, and persist to storage."""

        # 1. Fetch active markets (for signal generation)
        markets = await self.discovery.discover()
        self.ctx.markets.upsert_many(markets)
        for m in markets:
            try:
                self.sqlite.upsert_market(m)
                self.logs.append("markets", m)
            except Exception:
                pass
        token_ids = [token.token_id for market in markets for token in market.outcome_tokens]
        if token_ids:
            try:
                books = await self.rest.get_books(token_ids)
                for book in books:
                    self.ctx.books.update(book)
            except Exception:
                self.logger.exception("Failed to fetch order books for %d tokens", len(token_ids))

    async def _fetch_resolved_markets(self) -> None:
        """Fetch recently resolved markets from Gamma API so settlements can be processed.

        Called periodically (every ~5 refresh cycles) to update the status of
        markets the bot has open positions in. Uses closed=true to find resolved
        markets that no longer appear in the active-only query.
        """
        import httpx
        from polysignal_lab.domain.market import Market as MarketModel

        # Get market_ids we care about (open positions)
        open_market_ids = set()
        for pos in self.wallet.open_positions.values():
            if pos.market_id:
                open_market_ids.add(pos.market_id)

        if not open_market_ids:
            return

        # Query Gamma for closed markets
        params = {
            "closed": "true",
            "limit": "200",
            "offset": "0",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.settings.data.polymarket.gamma_base_url}/markets",
                    params=params,
                )
                if response.status_code != 200:
                    return
                data = response.json()
                if not isinstance(data, list):
                    return

                payloads = self.discovery._flatten_markets(data)
                updated = 0
                for payload in payloads:
                    market_id = str(payload.get("id") or payload.get("market") or "")
                    if market_id not in open_market_ids:
                        continue

                    resolved = bool(payload.get("resolved") or payload.get("resolved_outcome"))
                    if resolved:
                        # Re-build market from gamma to get status=RESOLVED
                        try:
                            match = self.discovery._match_crypto_updown(payload)
                            asset, timeframe = match if match else ("UNKNOWN", "UNKNOWN")
                            m = MarketModel.from_gamma(payload, asset=asset, timeframe=timeframe)
                            self.ctx.markets.upsert_many([m])
                            self.sqlite.upsert_market(m)
                            updated += 1
                        except Exception:
                            pass

                if updated > 0:
                    self.logger.info("Fetched %d resolved markets from Gamma API", updated)
        except Exception as exc:
            self.logger.warning("Failed to fetch resolved markets: %s", exc)

    async def evaluate_once(self) -> list[SignalCandidate]:
        """Evaluate all active markets through strategies and gate, return accepted signals."""
        accepted: list[SignalCandidate] = []
        for market in self.ctx.markets.active():
            try:
                snapshot = await self.snapshot_builder.build(market)
            except Exception:
                self.logger.exception("Failed to build snapshot for market %s", market.market_slug)
                continue
            secs = snapshot.seconds_to_close
            self.logger.info("DIAG ev %-40s asset=%-5s tf=%-3s secs=%-8s up=%-5s down=%-5s spot=%-8s spread=%-5s",
                             market.market_slug, market.asset, market.timeframe,
                             secs if secs else "N/A",
                             snapshot.up_ask, snapshot.down_ask,
                             snapshot.spot.price if snapshot.spot else "NONE",
                             snapshot.max_spread)
            for strategy in self.strategies:
                try:
                    for candidate in strategy.evaluate(snapshot):
                        decision = self.gate.evaluate(candidate, snapshot)
                        if decision.accepted and decision.signal:
                            accepted.append(decision.signal)
                            cons = self.consensus.add(decision.signal)
                            if cons:
                                accepted.append(cons)
                        elif decision.rejected:
                            try:
                                self.logs.append("rejected_signals", decision.rejected)
                                self.sqlite.insert_rejected_signal(decision.rejected)
                            except Exception:
                                pass
                except Exception:
                    self.logger.exception("Strategy %s evaluate failed", strategy.name if hasattr(strategy, "name") else "?")
        return accepted

    async def start_websockets(self) -> list[asyncio.Task]:
        """Start Polymarket Market WebSocket and Binance Spot WebSocket as background tasks."""
        tasks: list[asyncio.Task] = []

        # Start Polymarket WebSocket if enabled
        if self.settings.data.polymarket.use_market_ws:
            token_ids = [
                token.token_id
                for market in self.ctx.markets.markets.values()
                for token in market.outcome_tokens
                if token.token_id
            ]
            if token_ids:
                self.logger.info(
                    "Starting Polymarket WebSocket with %d token subscriptions", len(token_ids)
                )
                task = asyncio.create_task(self.poly_ws.subscribe(token_ids))
                tasks.append(task)
            else:
                self.logger.info(
                    "No token IDs available for Polymarket WebSocket, falling back to REST polling"
                )
        else:
            self.logger.info("Polymarket WebSocket disabled in config, using REST polling")

        # Start Binance Spot WebSocket if enabled
        if self.settings.data.binance.enabled:
            self.logger.info("Starting Binance Spot WebSocket feed")
            task = asyncio.create_task(self.binance_ws.run())
            tasks.append(task)
        else:
            self.logger.info("Binance Spot WebSocket disabled in config")

        self._ws_tasks = tasks
        return tasks

    async def stop(self) -> None:
        """Clean up WebSocket connections and persist final state."""
        self.logger.info("Shutting down scheduler")
        self._running = False

        # Stop WebSocket loops
        self.poly_ws.stop()
        self.binance_ws.stop()

        # Cancel background tasks
        for task in self._ws_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._ws_tasks.clear()

        # Persist final state
        self._persist_state()

        # Close SQLite connection
        try:
            self.sqlite.close()
        except Exception:
            pass

        self.logger.info("Scheduler shutdown complete")

    def _persist_state(self) -> None:
        """Persist wallet snapshot, open positions, market cache, and dedupe state to JSON files."""
        try:
            wallet_snapshot = self.wallet.snapshot()
            self.logs.append("paper_wallet_snapshots", wallet_snapshot)
            self.sqlite.insert_wallet_snapshot(wallet_snapshot)
            self.state.write("paper_wallet", wallet_snapshot)
            self.state.write(
                "open_positions",
                [p.model_dump(mode="json") for p in self.wallet.open_positions.values()],
            )
            self.state.write(
                "market_cache",
                [m.model_dump(mode="json") for m in self.ctx.markets.markets.values()],
            )
            self.state.write("signal_dedupe", self.gate.deduper.snapshot())
        except Exception as exc:
            self.logger.warning("Failed to persist state: %s", exc)

    async def process_signal(self, signal: SignalCandidate) -> dict:
        """Process a single accepted signal through the full pipeline: store -> publish -> paper trade.

        Steps:
        1. Record signal to JSONL and SQLite
        2. Publish to Telegram (if enabled and not dry_run)
        3. Attempt paper trade (build order, fill, position)
        """
        result: dict = {
            "signal_id": signal.signal_id,
            "stored": False,
            "published": False,
            "publish_status": None,
            "paper_order": None,
            "paper_fill": None,
            "paper_position": None,
        }

        # 1. Store to JSONL and SQLite
        try:
            self.logs.append("signals", signal)
            self.sqlite.insert_signal(signal)
            result["stored"] = True
        except Exception as exc:
            self.logger.error("Failed to store signal %s: %s", signal.signal_id, exc)

        # 2. Publish to Telegram
        if self.settings.telegram.send_signals:
            try:
                msg = self.formatter.signal_message(
                    signal, self.settings.paper_trading.fixed_stake_usdc
                )
                publish = await self.publisher.send(msg, "signal", signal.signal_id)
                self.logs.append("telegram_publish", publish.as_dict())
                self.sqlite.insert_telegram_publish(publish.as_dict())
                result["published"] = True
                result["publish_status"] = publish.status
            except Exception as exc:
                self.logger.error("Failed to publish signal %s: %s", signal.signal_id, exc)

        # 3. Attempt paper trade
        try:
            book = self.ctx.books.get(signal.token_id)
            if book and self.settings.paper_trading.enabled:
                sim = self.paper.process_signal(signal, book)
                result["paper_order"] = sim.order
                self.logs.append("paper_orders", sim.order)
                self.sqlite.insert_paper_order(sim.order)
                if sim.fill and sim.position:
                    result["paper_fill"] = sim.fill
                    result["paper_position"] = sim.position
                    self.logs.append("paper_fills", sim.fill)
                    self.logs.append("paper_positions", sim.position)
                    self.sqlite.insert_paper_fill(sim.fill)
                    self.sqlite.upsert_paper_position(sim.position)
            elif not book:
                self.logger.warning(
                    "No order book for token %s (signal %s)", signal.token_id, signal.signal_id
                )
        except Exception as exc:
            self.logger.error("Failed to paper-trade signal %s: %s", signal.signal_id, exc)

        return result

    async def process_accepted_signals(self, signals: list[SignalCandidate]) -> dict:
        """Batch-process all accepted signals and return a summary.

        Returns a dict with total, stored, published, and filled counts.
        """
        results = []
        for signal in signals:
            r = await self.process_signal(signal)
            results.append(r)
        return {
            "total": len(signals),
            "stored": sum(1 for r in results if r.get("stored")),
            "published": sum(1 for r in results if r.get("published")),
            "filled": sum(1 for r in results if r.get("paper_fill")),
        }

    async def check_settlements(self) -> list[PaperTradeResult]:
        """Check all open positions for market resolution and settle if resolved.

        Iterates wallet.open_positions, looks up each position's market in ctx.markets.
        If market.status == RESOLVED, calls settlement.settle(position, market)
        and persists the result.
        """
        settled: list[PaperTradeResult] = []
        if not self.wallet.open_positions:
            return settled

        # Iterate over a snapshot of items since settle() modifies the dict
        for position_id, position in list(self.wallet.open_positions.items()):
            market = self.ctx.markets.get(position.market_id)
            if market is None:
                # Try loading from SQLite (market may have resolved and no longer active)
                try:
                    market_data = self.sqlite.query_json(
                        "markets",
                        where="WHERE market_id = ?",
                        params=(position.market_id,),
                    )
                    if market_data:
                        from polysignal_lab.domain.market import Market
                        market = Market.model_validate(market_data[0])
                except Exception:
                    pass
            if market is None:
                continue
            if market.status != MarketStatus.RESOLVED:
                continue
            if market.resolved_outcome is None:
                self.logger.warning(
                    "Market %s (%s) is RESOLVED but has no resolved_outcome",
                    market.market_slug,
                    market.market_id,
                )
                continue

            try:
                result = self.settlement.settle(position, market)
                settled.append(result)
                self.logger.info(
                    "Settled position %s for market %s: %s (pnl=%.2f)",
                    position.paper_position_id,
                    market.market_slug,
                    result.result.value,
                    result.pnl_usdc,
                )

                # Persist settlement
                self.logs.append("paper_results", result)
                self.sqlite.upsert_paper_position(position)
                self.sqlite.insert_paper_trade_result(result)

                # Publish result to Telegram
                if self.settings.telegram.send_paper_results:
                    try:
                        msg = self.formatter.result_message(result)
                        publish = await self.publisher.send(
                            msg, "paper_result", result.signal_id
                        )
                        self.logs.append("telegram_publish", publish.as_dict())
                        self.sqlite.insert_telegram_publish(publish.as_dict())
                    except Exception as exc:
                        self.logger.error(
                            "Failed to publish settlement result for %s: %s",
                            position.paper_position_id,
                            exc,
                        )

            except Exception as exc:
                self.logger.error(
                    "Failed to settle position %s: %s", position.paper_position_id, exc
                )

        return settled

    async def generate_daily_report(self) -> DailyReport | None:
        """Generate and publish a daily paper-trading report if one hasn't been generated today.

        Queries today's trade results from SQLite, builds a DailyReport via PaperReportService,
        persists it, and publishes to Telegram.
        """
        today = date.today()
        today_iso = today.isoformat()

        # Check if we already have a report for today
        existing = self.sqlite.query_json(
            "daily_reports", where="WHERE report_date = ?", params=(today_iso,)
        )
        if existing:
            self.logger.info("Daily report already exists for %s, skipping", today_iso)
            return None

        # Collect today's trade results from SQLite
        today_results_raw = self.sqlite.query_json(
            "paper_trade_results",
            where="WHERE DATE(closed_at) = ?",
            params=(today_iso,),
        )
        trade_results = [PaperTradeResult(**r) for r in today_results_raw]

        # Count today's paper fills (positions opened today)
        today_fills_raw = self.sqlite.query_json(
            "paper_fills",
            where="WHERE DATE(created_at) = ?",
            params=(today_iso,),
        )
        today_fills_count = len(today_fills_raw)

        # Build the report
        try:
            report = PaperReportService().build_daily_report(
                report_date=today,
                starting_equity=self.wallet.starting_balance,
                ending_equity=self.wallet.equity,
                total_signals=len(trade_results),
                paper_orders=len(trade_results),
                paper_fills=today_fills_count,
                rejected_paper_orders=0,
                open_positions=self.wallet.open_position_count,
                results=trade_results,
                equity_curve=[self.wallet.starting_balance, self.wallet.equity],
            )
        except Exception as exc:
            self.logger.error("Failed to build daily report: %s", exc)
            return None

        # Store report
        try:
            self.logs.append("daily_reports", report)
            self.sqlite.insert_daily_report(report)
        except Exception as exc:
            self.logger.error("Failed to store daily report: %s", exc)

        # Publish to Telegram
        if self.settings.telegram.send_daily_report:
            try:
                msg = self.formatter.daily_report_message(report)
                publish = await self.publisher.send(msg, "daily_report", None)
                self.logs.append("telegram_publish", publish.as_dict())
                self.sqlite.insert_telegram_publish(publish.as_dict())
            except Exception as exc:
                self.logger.error("Failed to publish daily report: %s", exc)

        self.logger.info(
            "Generated daily report for %s: %d closed trades, pnl=%.2f",
            today_iso,
            len(trade_results),
            report.paper_pnl,
        )
        return report

    async def run(self) -> None:
        """Main run loop. Starts WebSocket connections, then loops:

        1. refresh_markets_once() every 5 iterations
        2. evaluate_once() to run strategies and gate
        3. process_accepted_signals() to store, publish, and paper-trade
        4. check_settlements() to settle resolved markets
        5. generate_daily_report() once per day
        6. Persist state every 10 iterations
        7. Sleep for refresh_interval_sec
        """
        self.logger.info("Starting PolySignal Lab scheduler run loop")
        self._running = True

        # Restore wallet state from previous runs (if any)
        await self._restore_wallet_state()

        # Start WebSocket background tasks
        await self.start_websockets()

        loop_count = 0
        last_report_date: date | None = None

        try:
            while self._running:
                self.logger.info("=== Run %d ===", loop_count)

                # Re-discover markets every 5 iterations
                if loop_count % 5 == 0:
                    try:
                        await self.refresh_markets_once()
                        await self._fetch_resolved_markets()
                    except Exception as exc:
                        self.logger.error("refresh_markets_once failed: %s", exc)

                # Evaluate strategies
                # Log market & strategy state for debugging
                active_markets = self.ctx.markets.active()
                for m in active_markets:
                    secs = None
                    if m.end_ts:
                        secs = int((m.end_ts - __import__('datetime').datetime.now(__import__('datetime').timezone.utc)).total_seconds())
                    self.logger.info("MARKET %-40s asset=%-5s tf=%-3s secs=%-8s up_ask=%-5s down_ask=%-5s",
                                     m.market_slug, m.asset, m.timeframe,
                                     secs if secs else "N/A",
                                     getattr(m, 'up_ask', '?'), getattr(m, 'down_ask', '?'))

                accepted: list[SignalCandidate] = []
                try:
                    accepted = await self.evaluate_once()
                except Exception as exc:
                    self.logger.error("evaluate_once failed: %s", exc)

                # Log why no signals
                if not accepted:
                    self.logger.info("SIGNAL_DIAG: %d active markets, %d strategies loaded, 0 signals passed all gates",
                                     len(active_markets), len(self.strategies))
                    # Log per-strategy skip counts
                    for strategy in self.strategies:
                        strategy_name = strategy.name if hasattr(strategy, "name") else type(strategy).__name__
                        self.logger.info("SIGNAL_DIAG: strategy=%s window_checks=active", strategy_name)

                # Process accepted signals
                if accepted:
                    try:
                        summary = await self.process_accepted_signals(accepted)
                        self.logger.info(
                            "Processed %d signals: %d stored, %d published, %d filled",
                            summary["total"],
                            summary["stored"],
                            summary["published"],
                            summary["filled"],
                        )
                    except Exception as exc:
                        self.logger.error("process_accepted_signals failed: %s", exc)
                else:
                    self.logger.info("No accepted signals this iteration")

                # Check settlements for resolved markets
                try:
                    settled = await self.check_settlements()
                    if settled:
                        self.logger.info("Settled %d positions", len(settled))
                except Exception as exc:
                    self.logger.error("check_settlements failed: %s", exc)

                # Generate daily report once per day
                today = date.today()
                if last_report_date != today:
                    try:
                        report = await self.generate_daily_report()
                        if report:
                            last_report_date = today
                    except Exception as exc:
                        self.logger.error("generate_daily_report failed: %s", exc)

                # Persist state every iteration (critical for crash recovery)
                self._persist_state()

                loop_count += 1
                await asyncio.sleep(self.settings.markets.refresh_interval_sec)

        except asyncio.CancelledError:
            self.logger.info("Scheduler cancelled, shutting down")
        finally:
            await self.stop()


async def run_scheduler(
    settings: Settings | None = None, base_dir: str | Path = "."
) -> None:
    """Convenience entry point: create and run a PolySignalScheduler."""
    from polysignal_lab.config import load_settings
    from polysignal_lab.observability.logger import configure_logging

    settings = settings or load_settings()
    settings.validate_runtime_environment(environ={})
    configure_logging(settings.app.log_level)

    scheduler = PolySignalScheduler(settings, base_dir=base_dir)
    await scheduler.run()
