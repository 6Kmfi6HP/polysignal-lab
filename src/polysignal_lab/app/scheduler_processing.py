from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.paper.simulator import SimulationResult

if TYPE_CHECKING:
    from polysignal_lab.app.scheduler import PolySignalScheduler


class ProcessSignalResult(TypedDict):
    signal_id: str
    stored: bool
    published: bool
    publish_status: str | None
    paper_order: PaperOrder | None
    paper_fill: PaperFill | None
    paper_position: PaperPosition | None


class AcceptedSignalSummary(TypedDict):
    total: int
    stored: int
    published: int
    filled: int


async def evaluate_once(scheduler: PolySignalScheduler) -> list[SignalCandidate]:
    accepted: list[SignalCandidate] = []
    for market in scheduler.ctx.markets.active():
        try:
            snapshot = await scheduler.snapshot_builder.build(market)
        except Exception:
            scheduler.logger.exception(
                "Failed to build snapshot for market %s", market.market_slug
            )
            continue
        scheduler.logger.info(
            "DIAG ev %-40s asset=%-5s tf=%-3s secs=%-8s up=%-5s down=%-5s spot=%-8s spread=%-5s",
            market.market_slug,
            market.asset,
            market.timeframe,
            snapshot.seconds_to_close if snapshot.seconds_to_close else "N/A",
            snapshot.up_ask,
            snapshot.down_ask,
            snapshot.spot.price if snapshot.spot else "NONE",
            snapshot.max_spread,
        )
        for strategy in scheduler.strategies:
            try:
                for candidate in strategy.evaluate(snapshot):
                    decision = scheduler.gate.evaluate(candidate, snapshot)
                    if decision.accepted and decision.signal:
                        strategy.notify_signal_accepted(decision.signal)
                        accepted.append(decision.signal)
                        consensus = scheduler.consensus.add(decision.signal)
                        if consensus:
                            accepted.append(consensus)
                    elif decision.rejected:
                        strategy.notify_signal_rejected(
                            decision.rejected.candidate, decision.rejected
                        )
                        try:
                            scheduler.logs.append("rejected_signals", decision.rejected)
                            scheduler.sqlite.insert_rejected_signal(decision.rejected)
                        except Exception:
                            scheduler.logger.exception(
                                "Failed to persist rejected signal for market %s strategy %s reason %s",
                                market.market_slug,
                                strategy.name if hasattr(strategy, "name") else "?",
                                decision.rejected.reason_code,
                            )
            except Exception:
                scheduler.logger.exception(
                    "Strategy %s evaluate failed",
                    strategy.name if hasattr(strategy, "name") else "?",
                )
    return accepted


async def process_signal(
    scheduler: PolySignalScheduler, signal: SignalCandidate
) -> ProcessSignalResult:
    result = ProcessSignalResult(
        signal_id=signal.signal_id,
        stored=False,
        published=False,
        publish_status=None,
        paper_order=None,
        paper_fill=None,
        paper_position=None,
    )

    try:
        scheduler.logs.append("signals", signal)
        scheduler.sqlite.insert_signal(signal)
        result["stored"] = True
    except Exception as exc:
        scheduler.logger.error("Failed to store signal %s: %s", signal.signal_id, exc)

    if scheduler.settings.telegram.send_signals:
        try:
            message = scheduler.formatter.signal_message(
                signal, scheduler.settings.paper_trading.fixed_stake_usdc
            )
            publish = await scheduler.publisher.send(message, "signal", signal.signal_id)
            scheduler.logs.append("telegram_publishes", publish.as_dict())
            scheduler.sqlite.insert_telegram_publish(publish.as_dict())
            result["published"] = True
            result["publish_status"] = publish.status
        except Exception as exc:
            scheduler.logger.error("Failed to publish signal %s: %s", signal.signal_id, exc)

    try:
        book = scheduler.ctx.books.get(signal.token_id)
        if scheduler.settings.paper_trading.enabled:
            if book is None:
                scheduler.logger.warning(
                    "No order book for token %s (signal %s)",
                    signal.token_id,
                    signal.signal_id,
                )
            sim = scheduler.paper.process_signal(signal, book)
            _store_simulation_result(scheduler, sim, result)
    except Exception:
        scheduler.logger.exception(
            "Failed to paper-trade signal %s token %s",
            signal.signal_id,
            signal.token_id,
        )

    return result


def _store_simulation_result(
    scheduler: PolySignalScheduler,
    sim: SimulationResult,
    result: ProcessSignalResult,
) -> None:
    scheduler.logs.append("paper_orders", sim.order)
    scheduler.sqlite.insert_paper_order(sim.order)
    wallet_snapshot = scheduler.wallet.snapshot()
    scheduler.logs.append("paper_wallet_snapshots", wallet_snapshot)
    scheduler.sqlite.insert_wallet_snapshot(wallet_snapshot)
    result["paper_order"] = sim.order
    if sim.fill and sim.position:
        scheduler.logs.append("paper_fills", sim.fill)
        scheduler.logs.append("paper_positions", sim.position)
        scheduler.sqlite.insert_paper_fill(sim.fill)
        scheduler.sqlite.upsert_paper_position(sim.position)
        result["paper_fill"] = sim.fill
        result["paper_position"] = sim.position
        scheduler.logger.info(
            "Paper order %s filled for signal %s at %.4f",
            sim.order.paper_order_id,
            sim.order.signal_id,
            sim.fill.fill_price,
        )
        # Notify the originating strategy of the fill
        if scheduler.paper.fill_notifier:
            scheduler.paper.fill_notifier(sim.order, "filled", sim.fill)
    elif sim.order.reject_reason:
        scheduler.logger.info(
            "Paper order %s rejected for signal %s: %s",
            sim.order.paper_order_id,
            sim.order.signal_id,
            sim.order.reject_reason,
        )
        # Notify strategy of rejection/cancellation
        if scheduler.paper.fill_notifier:
            scheduler.paper.fill_notifier(sim.order, "cancelled", None)


async def process_accepted_signals(
    scheduler: PolySignalScheduler, signals: list[SignalCandidate]
) -> AcceptedSignalSummary:
    results: list[ProcessSignalResult] = []
    for signal in signals:
        result = await process_signal(scheduler, signal)
        results.append(result)
    return AcceptedSignalSummary(
        total=len(signals),
        stored=sum(1 for result in results if result["stored"]),
        published=sum(1 for result in results if result["published"]),
        filled=sum(1 for result in results if result["paper_fill"]),
    )


def tick_resting_orders(scheduler: PolySignalScheduler) -> list:
    """Poll resting GTD orders for fills/expiry each scheduler cycle."""
    from polysignal_lab.domain.enums import OrderStatus
    from polysignal_lab.paper.preflight import normalize_paper_reject_reason
    def _risk_check(order):
        """Check paper trading risk limits before filling a resting order."""
        cfg = scheduler.settings.paper_trading
        if scheduler.wallet.open_position_count >= cfg.max_open_positions:
            return False
        if scheduler.wallet.exposure_by_market(order.market_id) + order.stake_usdc > cfg.max_market_exposure_usdc:
            return False
        if scheduler.wallet.exposure_by_strategy(order.strategy) + order.stake_usdc > cfg.max_strategy_exposure_usdc:
            return False
        return True
    results = scheduler.paper.passive.tick(scheduler.ctx.books, scheduler.wallet, risk_check=_risk_check)
    for result in results:
        if result.fills:
            for fill in result.fills:
                scheduler.logs.append("paper_fills", fill)
                scheduler.sqlite.insert_paper_fill(fill)
            for position in result.positions:
                scheduler.logs.append("paper_positions", position)
                scheduler.sqlite.upsert_paper_position(position)
            if scheduler.paper.fill_notifier:
                scheduler.paper.fill_notifier(result.order, "filled", result.fills[0] if result.fills else None)
        elif result.status == OrderStatus.REJECTED:
            original_reason = result.reject_reason or result.order.reject_reason
            normalized_reason = normalize_paper_reject_reason(original_reason)
            result.reject_reason = normalized_reason
            result.order.reject_reason = normalized_reason
            result.order.metrics["paper_original_reason"] = original_reason
            result.order.metrics["paper_normalized_reason"] = normalized_reason
            scheduler.logs.append("paper_orders", result.order)
            scheduler.sqlite.upsert_paper_order(result.order)
            wallet_snapshot = scheduler.wallet.snapshot()
            scheduler.logs.append("paper_wallet_snapshots", wallet_snapshot)
            scheduler.sqlite.insert_wallet_snapshot(wallet_snapshot)
            scheduler.logger.info(
                "Resting paper order %s rejected: %s",
                result.order.paper_order_id,
                result.reject_reason or result.order.reject_reason,
            )
            if scheduler.paper.fill_notifier:
                scheduler.paper.fill_notifier(result.order, "cancelled", None)
        elif result.status == OrderStatus.CANCELLED:
            if scheduler.paper.fill_notifier:
                scheduler.paper.fill_notifier(result.order, "cancelled", None)
    return results