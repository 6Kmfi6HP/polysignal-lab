from __future__ import annotations
import asyncio
import sqlite3

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from polysignal_lab.app import scheduler_health
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.domain.snapshot_batch import (
    CrossMarketEvaluationContext,
    SnapshotBatch,
)
from polysignal_lab.strategies.execution import (
    StrategyScheduleEntry,
    order_strategy_schedule,
)
from polysignal_lab.strategies.readiness import check_strategy_market
from polysignal_lab.utils import utc_now


class _LegacyRejectionPersistence:
    def __init__(self, scheduler: object) -> None:
        self.scheduler = scheduler

    def append_log(self, stream: str, payload: object) -> None:
        self.scheduler.logs.append(stream, payload)

    def insert_rejected_signal(self, rejected: object) -> None:
        self.scheduler.sqlite.insert_rejected_signal(rejected)

    def insert_strategy_status(self, status: object) -> None:
        self.scheduler.sqlite.insert_strategy_status(status)


if TYPE_CHECKING:
    from polysignal_lab.app.scheduler import PolySignalScheduler


def _append_persistence_log(
    scheduler: PolySignalScheduler, stream: str, payload: object
) -> None:
    try:
        scheduler.persistence.append_log(stream, payload)
        scheduler_health.note_storage_success(scheduler, "jsonl")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "jsonl", exc)
        raise


def _write_persistence_sqlite(
    scheduler: PolySignalScheduler, write, payload: object
) -> None:
    try:
        write(payload)
        scheduler_health.note_storage_success(scheduler, "sqlite")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "sqlite", exc)
        raise


def _note_snapshot_success(scheduler: PolySignalScheduler, snapshot: MarketSnapshot) -> None:
    health = getattr(scheduler, "health", None)
    if health is None:
        return
    health.inc_metric("snapshot_builder", "build_count")
    if snapshot.freshness.max_ms is not None:
        health.set_metric(
            "snapshot_builder", "max_freshness_lag_ms", snapshot.freshness.max_ms
        )
    health.mark_ok("snapshot_builder")


def _note_snapshot_failure(scheduler: PolySignalScheduler, market: Market) -> None:
    health = getattr(scheduler, "health", None)
    if health is None:
        return
    health.inc_metric("snapshot_builder", "failure_count")
    health.mark_degraded(
        "snapshot_builder", f"snapshot failed for {market.market_slug}"
    )


async def _build_snapshot_for_market(
    scheduler: PolySignalScheduler, market: Market
) -> MarketSnapshot:
    snapshot_service = getattr(scheduler, "snapshot_service", scheduler.snapshot_builder)
    snapshot = await snapshot_service.build(market)
    _note_snapshot_success(scheduler, snapshot)
    return snapshot


class ProcessSignalResult(TypedDict):
    signal_id: str
    stored: bool
    published: bool
    publish_status: str | None


class AcceptedSignalSummary(TypedDict):
    total: int
    stored: int
    published: int
    filled: int


@dataclass(frozen=True, slots=True)
class CandidateEnvelope:
    candidate: SignalCandidate
    snapshot: MarketSnapshot
    strategy_name: str
    strategy_config_index: int
    market_config_index: int
    candidate_index: int
    strategy: object


async def build_snapshots_serial(
    scheduler: PolySignalScheduler, markets: list[Market]
) -> list[tuple[int, MarketSnapshot]]:
    snapshots: list[tuple[int, MarketSnapshot]] = []
    for market_index, market in enumerate(markets):
        try:
            snapshot = await _build_snapshot_for_market(scheduler, market)
        except Exception:
            _note_snapshot_failure(scheduler, market)
            scheduler.logger.exception(
                "Failed to build snapshot for market %s", market.market_slug
            )
            continue
        _log_snapshot(scheduler, market, snapshot)
        snapshots.append((market_index, snapshot))
    return snapshots

async def build_snapshots_bounded(
    scheduler: PolySignalScheduler, markets: list[Market]
) -> list[tuple[int, MarketSnapshot]]:
    signal_settings = getattr(getattr(scheduler, "settings", None), "signal", None)
    max_concurrency = max(1, getattr(signal_settings, "max_snapshot_concurrency", 1))
    if max_concurrency == 1:
        return await build_snapshots_serial(scheduler, markets)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def build_one(
        market_index: int, market: Market
    ) -> tuple[int, MarketSnapshot] | None:
        async with semaphore:
            try:
                snapshot = await _build_snapshot_for_market(scheduler, market)
            except Exception:
                _note_snapshot_failure(scheduler, market)
                scheduler.logger.exception(
                    "Failed to build snapshot for market %s", market.market_slug
                )
                return None
            _log_snapshot(scheduler, market, snapshot)
            return market_index, snapshot

    results = await asyncio.gather(
        *(build_one(index, market) for index, market in enumerate(markets))
    )
    return [result for result in results if result is not None]


def evaluate_candidates_serial(
    scheduler: PolySignalScheduler,
    snapshots: list[tuple[int, MarketSnapshot]],
) -> list[CandidateEnvelope]:
    envelopes: list[CandidateEnvelope] = []
    for market_index, snapshot in snapshots:
        for entry in _strategy_schedule(scheduler):
            envelopes.extend(_evaluate_entry_serial(scheduler, entry, snapshot, market_index))
    return envelopes


async def evaluate_candidates_ordered(
    scheduler: PolySignalScheduler,
    snapshots: list[tuple[int, MarketSnapshot]],
) -> list[CandidateEnvelope]:
    envelopes: list[CandidateEnvelope] = []
    entries = _strategy_schedule(scheduler)
    per_market_entries = [
        entry for entry in entries if entry.execution_mode != "cross_market"
    ]
    entry_levels = _strategy_schedule_levels(per_market_entries)
    for level_entries in entry_levels:
        for market_index, snapshot in snapshots:
            entry_results: list[list[CandidateEnvelope]] = [
                [] for _ in level_entries
            ]
            stateless_tasks: list[tuple[int, asyncio.Task[list[CandidateEnvelope]]]] = []
            for entry_index, entry in enumerate(level_entries):
                if entry.execution_mode == "stateless":
                    stateless_tasks.append(
                        (
                            entry_index,
                            asyncio.create_task(
                                _evaluate_stateless_entry(
                                    scheduler, entry, snapshot, market_index
                                )
                            ),
                        )
                    )
                elif entry.execution_mode == "stateful":
                    entry_results[entry_index] = _evaluate_entry_serial(
                        scheduler, entry, snapshot, market_index
                    )
            for entry_index, task in stateless_tasks:
                entry_results[entry_index] = await task
            for result in entry_results:
                envelopes.extend(result)
    envelopes.extend(_evaluate_cross_market_entries(scheduler, entries, snapshots))
    return envelopes


def _manual_strategy_skip_reason(
    scheduler: PolySignalScheduler, entry: StrategyScheduleEntry
) -> str | None:
    pipeline = getattr(scheduler, "signal_pipeline", None)
    if pipeline is None or not hasattr(pipeline, "skip_reason_for"):
        return None
    return pipeline.skip_reason_for(entry.name)


def _persist_inactive_strategy(
    scheduler: PolySignalScheduler,
    entry: StrategyScheduleEntry,
    snapshot: MarketSnapshot,
    reason: str,
) -> None:
    from polysignal_lab.strategies.readiness import StrategyMarketStatus

    status = StrategyMarketStatus(
        strategy=entry.name,
        asset=snapshot.market.asset.upper(),
        timeframe=snapshot.market.timeframe,
        status="inactive",
        reason=reason,
    )
    persistence = getattr(scheduler, "persistence", _LegacyRejectionPersistence(scheduler))
    try:
        persistence.append_log("strategy_status", status)
        persistence.insert_strategy_status(status)
    except Exception:
        scheduler.logger.exception(
            "Failed to persist strategy status for market %s strategy %s status %s",
            snapshot.market.market_slug,
            entry.name,
            status.status,
        )


def _strategy_market_active(
    scheduler: PolySignalScheduler, entry: StrategyScheduleEntry, snapshot: MarketSnapshot
) -> bool:
    manual_reason = _manual_strategy_skip_reason(scheduler, entry)
    if manual_reason is not None:
        _persist_inactive_strategy(scheduler, entry, snapshot, manual_reason)
        return False
    readiness = getattr(entry.strategy, "readiness", None)
    if readiness is None:
        return True
    status = check_strategy_market(readiness, snapshot)
    if status.status == "active":
        return True
    persistence = getattr(scheduler, "persistence", _LegacyRejectionPersistence(scheduler))
    try:
        persistence.append_log("strategy_status", status)
        persistence.insert_strategy_status(status)
    except Exception:
        scheduler.logger.exception(
            "Failed to persist strategy status for market %s strategy %s status %s",
            snapshot.market.market_slug,
            entry.name,
            status.status,
        )
    return False


def _evaluate_entry_serial(
    scheduler: PolySignalScheduler,
    entry: StrategyScheduleEntry,
    snapshot: MarketSnapshot,
    market_index: int,
) -> list[CandidateEnvelope]:
    if not _strategy_market_active(scheduler, entry, snapshot):
        return []
    try:
        candidates = entry.strategy.evaluate(snapshot)
    except Exception:
        scheduler.logger.exception("Strategy %s evaluate failed", entry.name)
        return []
    return _candidate_envelopes(entry, snapshot, market_index, candidates)


async def _evaluate_stateless_entry(
    scheduler: PolySignalScheduler,
    entry: StrategyScheduleEntry,
    snapshot: MarketSnapshot,
    market_index: int,
) -> list[CandidateEnvelope]:
    if not _strategy_market_active(scheduler, entry, snapshot):
        return []
    try:
        candidates = await asyncio.to_thread(entry.strategy.evaluate, snapshot)
    except Exception:
        scheduler.logger.exception("Strategy %s evaluate failed", entry.name)
        return []
    return _candidate_envelopes(entry, snapshot, market_index, candidates)

def _evaluate_cross_market_entries(
    scheduler: PolySignalScheduler,
    entries: list[StrategyScheduleEntry],
    snapshots: list[tuple[int, MarketSnapshot]],
) -> list[CandidateEnvelope]:
    if not snapshots:
        return []
    batch = _snapshot_batch(snapshots)
    snapshots_by_market_id = {
        snapshot.market.market_id: (market_index, snapshot)
        for market_index, snapshot in snapshots
    }
    envelopes: list[CandidateEnvelope] = []
    for entry in entries:
        if entry.execution_mode != "cross_market":
            continue
        skew_threshold_ms = _cross_market_skew_threshold_ms(scheduler)
        for context in _cross_market_contexts(entry, batch):
            context_max_source_skew_ms = max(
                (
                    snapshot.freshness.max_ms or 0
                    for snapshot in context.snapshots_by_condition_id.values()
                ),
                default=0,
            )
            if context_max_source_skew_ms > skew_threshold_ms:
                scheduler.logger.info(
                    "Skipping cross-market strategy %s relation %s for stale relation context %s: "
                    "max_source_skew_ms=%d threshold_ms=%d",
                    entry.name,
                    context.relation_id,
                    batch.batch_id,
                    context_max_source_skew_ms,
                    skew_threshold_ms,
                )
                continue
            try:
                evaluate_group = getattr(entry.strategy, "evaluate_group")
                candidates = evaluate_group(context)
            except Exception:
                scheduler.logger.exception("Strategy %s evaluate_group failed", entry.name)
                continue
            for candidate_index, candidate in enumerate(candidates):
                market_index, snapshot = snapshots_by_market_id[candidate.market_id]
                envelopes.append(
                    CandidateEnvelope(
                        candidate=candidate,
                        snapshot=snapshot,
                        strategy_name=entry.name,
                        strategy_config_index=entry.strategy_config_index,
                        market_config_index=market_index,
                        candidate_index=candidate_index,
                        strategy=entry.strategy,
                    )
                )
    return envelopes


def _snapshot_batch(snapshots: list[tuple[int, MarketSnapshot]]) -> SnapshotBatch:
    ordered = sorted(snapshots, key=lambda item: item[0])
    return SnapshotBatch(
        batch_id=f"batch_{utc_now().strftime('%Y%m%d%H%M%S%f')}",
        as_of=utc_now(),
        market_order=tuple(snapshot.market.market_id for _, snapshot in ordered),
        snapshots={snapshot.market.market_id: snapshot for _, snapshot in ordered},
        max_source_skew_ms=max(
            (snapshot.freshness.max_ms or 0 for _, snapshot in ordered),
            default=0,
        ),
    )


def _cross_market_skew_threshold_ms(scheduler: PolySignalScheduler) -> int:
    return max(
        scheduler.settings.data.polymarket.max_book_staleness_ms,
        scheduler.settings.data.binance.max_price_staleness_ms,
    )


def _cross_market_contexts(
    entry: StrategyScheduleEntry, batch: SnapshotBatch
) -> list[CrossMarketEvaluationContext]:
    snapshots_by_condition_id = {
        snapshot.market.condition_id: snapshot for snapshot in batch.snapshots.values()
    }
    relations = getattr(entry.strategy, "_relations", ())
    if not relations:
        return [
            CrossMarketEvaluationContext(
                relation_id="all_markets",
                snapshots_by_condition_id=snapshots_by_condition_id,
                batch=batch,
            )
        ]
    contexts: list[CrossMarketEvaluationContext] = []
    for relation in relations:
        if not all(
            condition_id in snapshots_by_condition_id
            for condition_id in relation.condition_ids
        ):
            continue
        relation_snapshots = {
            condition_id: snapshots_by_condition_id[condition_id]
            for condition_id in relation.condition_ids
        }
        contexts.append(
            CrossMarketEvaluationContext(
                relation_id=relation.relation_id,
                snapshots_by_condition_id=relation_snapshots,
                batch=batch,
            )
        )
    return contexts


def _candidate_envelopes(
    entry: StrategyScheduleEntry,
    snapshot: MarketSnapshot,
    market_index: int,
    candidates: list[SignalCandidate],
) -> list[CandidateEnvelope]:
    return [
        CandidateEnvelope(
            candidate=candidate,
            snapshot=snapshot,
            strategy_name=entry.name,
            strategy_config_index=entry.strategy_config_index,
            market_config_index=market_index,
            candidate_index=candidate_index,
            strategy=entry.strategy,
        )
        for candidate_index, candidate in enumerate(candidates)
    ]


def _note_signal_gate_accepted(scheduler: PolySignalScheduler) -> None:
    health = getattr(scheduler, "health", None)
    if health is None:
        return
    health.inc_metric("signal_gate", "accepted_count")
    health.mark_ok("signal_gate")


def _note_signal_gate_rejected(scheduler: PolySignalScheduler, reason_code: str) -> None:
    health = getattr(scheduler, "health", None)
    if health is None:
        return
    health.inc_metric("signal_gate", f"rejected_{reason_code}")
    health.mark_ok("signal_gate")


def commit_candidates_serial(
    scheduler: PolySignalScheduler, envelopes: list[CandidateEnvelope]
) -> list[SignalCandidate]:
    accepted: list[SignalCandidate] = []
    for envelope in envelopes:
        decision = scheduler.gate.evaluate(envelope.candidate, envelope.snapshot)
        if decision.accepted and decision.signal:
            if hasattr(envelope.strategy, "notify_signal_accepted"):
                envelope.strategy.notify_signal_accepted(decision.signal)
            _note_signal_gate_accepted(scheduler)
            accepted.append(decision.signal)
            consensus = scheduler.consensus.add(decision.signal)
            if consensus:
                accepted.append(consensus)
        elif decision.rejected:
            if hasattr(envelope.strategy, "notify_signal_rejected"):
                envelope.strategy.notify_signal_rejected(
                    decision.rejected.candidate, decision.rejected
                )
            _note_signal_gate_rejected(scheduler, decision.rejected.reason_code)
            try:
                persistence = getattr(
                    scheduler, "persistence", _LegacyRejectionPersistence(scheduler)
                )
                persistence.append_log("rejected_signals", decision.rejected)
                persistence.insert_rejected_signal(decision.rejected)
            except Exception:
                scheduler.logger.exception(
                    "Failed to persist rejected signal for market %s strategy %s reason %s",
                    envelope.snapshot.market.market_slug,
                    envelope.strategy_name,
                    decision.rejected.reason_code,
                )
    return accepted


async def evaluate_once(scheduler: PolySignalScheduler) -> list[SignalCandidate]:
    markets = scheduler.ctx.markets.active()
    snapshots = await build_snapshots_bounded(scheduler, markets)
    envelopes = await evaluate_candidates_ordered(scheduler, snapshots)
    envelopes = _arbitrate_envelopes(scheduler, envelopes)
    return commit_candidates_serial(scheduler, envelopes)


def _strategy_schedule(scheduler: PolySignalScheduler) -> list[StrategyScheduleEntry]:
    schedule = getattr(scheduler, "strategy_schedule", None)
    strategies = list(getattr(scheduler, "strategies", ()))
    if schedule is not None and [entry.strategy for entry in schedule] == strategies:
        return order_strategy_schedule(schedule)
    return [
        StrategyScheduleEntry(
            strategy=strategy,
            name=strategy.name if hasattr(strategy, "name") else f"strategy_{index}",
            priority=100,
            depends_on=(),
            execution_mode="stateful",
            strategy_config_index=index,
        )
        for index, strategy in enumerate(scheduler.strategies)
    ]


def _strategy_schedule_levels(
    entries: list[StrategyScheduleEntry],
) -> list[list[StrategyScheduleEntry]]:
    levels: list[list[StrategyScheduleEntry]] = []
    levels_by_name: dict[str, int] = {}
    for entry in entries:
        level = max(
            (
                levels_by_name[dependency_name] + 1
                for dependency_name in entry.depends_on
                if dependency_name in levels_by_name
            ),
            default=0,
        )
        while len(levels) <= level:
            levels.append([])
        levels[level].append(entry)
        levels_by_name[entry.name] = level
    return levels


def _arbitrate_envelopes(
    scheduler: PolySignalScheduler, envelopes: list[CandidateEnvelope]
) -> list[CandidateEnvelope]:
    arbiter = getattr(scheduler, "arbiter", None)
    if arbiter is None or not envelopes:
        return envelopes
    by_identity = {id(envelope.candidate): envelope for envelope in envelopes}
    market_config_indexes = {
        envelope.candidate.market_id: envelope.market_config_index
        for envelope in envelopes
    }
    schedule = _strategy_schedule(scheduler)
    strategy_order_indexes = {
        entry.name: index for index, entry in enumerate(schedule)
    }
    ordered = arbiter.arbitrate(
        [envelope.candidate for envelope in envelopes],
        strategy_priorities=strategy_order_indexes,
        strategy_config_indexes=strategy_order_indexes,
        market_config_indexes=market_config_indexes,
    )
    kept_ids = {id(candidate) for candidate in ordered}
    for envelope in envelopes:
        if id(envelope.candidate) not in kept_ids:
            _notify_arbitration_rejected(scheduler, envelope)
    return [by_identity[id(candidate)] for candidate in ordered]


def _notify_arbitration_rejected(
    scheduler: PolySignalScheduler, envelope: CandidateEnvelope
) -> None:
    rejected = RejectedSignal(
        candidate=envelope.candidate,
        gate_name="signal_arbiter",
        reason_code="ARBITRATION_SUPPRESSED",
        details={
            "strategy": envelope.strategy_name,
            "conflict_policy": getattr(scheduler.arbiter, "conflict_policy", None),
        },
    )
    if hasattr(envelope.strategy, "notify_signal_rejected"):
        envelope.strategy.notify_signal_rejected(envelope.candidate, rejected)
    _note_signal_gate_rejected(scheduler, "ARBITRATION_SUPPRESSED")


def _log_snapshot(
    scheduler: PolySignalScheduler, market: Market, snapshot: MarketSnapshot
) -> None:
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


async def process_signal(
    scheduler: PolySignalScheduler, signal: SignalCandidate
) -> ProcessSignalResult:
    result = ProcessSignalResult(
        signal_id=signal.signal_id,
        stored=False,
        published=False,
        publish_status=None,
    )

    try:
        _append_persistence_log(scheduler, "signals", signal)
        _write_persistence_sqlite(scheduler, scheduler.persistence.insert_signal, signal)
        result["stored"] = True
    except Exception as exc:
        scheduler.logger.error("Failed to store signal %s: %s", signal.signal_id, exc)

    if scheduler.settings.telegram.send_signals:
        try:
            publish = await scheduler.publish_service.publish_signal(
                signal, scheduler.settings.paper_trading.fixed_stake_usdc
            )
            scheduler_health.note_publish_result(scheduler, publish.as_dict())
            result["published"] = True
            result["publish_status"] = publish.status
        except Exception as exc:
            scheduler.health.inc_metric("telegram", "failed")
            scheduler.health.mark_degraded("telegram", str(exc))
            scheduler.logger.error(
                "Failed to publish signal %s: %s: %s",
                signal.signal_id,
                type(exc).__name__,
                exc,
            )

    return result


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
        filled=0,
    )