"""
Input: __future__, __future__.annotations, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.nautilus_runtime.backtest_node, polysignal_lab.nautilus_runtime.recorded_market_data, polysignal_lab.promotion.report, polysignal_lab.utils
Output: run_promotion, PromotionRequest, collect_segment_stats
Pos: Application code — single promotion entry function (highest test seam)

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.backtest_node import build_backtest_engine
from polysignal_lab.nautilus_runtime.projections import project_position
from polysignal_lab.nautilus_runtime.recorded_market_data import (
    RecordedMarketDataStore,
)
from polysignal_lab.promotion.report import (
    PromotionReport,
    SegmentedStats,
    evaluate_verdict,
    render_promotion_markdown,
)
from polysignal_lab.utils import utc_iso

ADR_IS_FLOOR = 1000
ADR_OOS_FLOOR = 300
_IS_RATIO = 0.70


@dataclass(frozen=True, slots=True)
class PromotionRequest:
    """One (strategy, recorded dataset, single param combo) review request."""

    dataset_dir: str
    strategy_name: str
    report_path: Path
    is_floor: int = ADR_IS_FLOOR
    oos_floor: int = ADR_OOS_FLOOR


def _segment_stats(
    positions: tuple[object, ...],
    *,
    label: str,
    start_ns: int | None,
    end_ns: int | None,
) -> SegmentedStats:
    closed = [project_position(p) for p in positions if bool(p) and _is_closed(p)]
    realized = [
        float(cast(Any, p["realized_pnl"]))
        for p in closed
        if p["realized_pnl"] is not None
    ]
    winners = sum(1 for value in realized if value > 0)
    losers = sum(1 for value in realized if value < 0)
    return SegmentedStats(
        label=label,
        start_ns=start_ns,
        end_ns=end_ns,
        settled_rounds=len(closed),
        total_realized_pnl=sum(realized),
        winning_rounds=winners,
        losing_rounds=losers,
    )


def _is_closed(position: object) -> bool:
    return bool(getattr(position, "is_closed", False))


def _replay_segment(
    settings: Settings,
    *,
    instruments: tuple[object, ...],
    data: tuple[object, ...],
) -> tuple[Any, tuple[object, ...]]:
    """Assemble the real BacktestEngine with sandbox-shared components and run it.

    Reuses ``build_backtest_engine`` → ``register_runtime_components`` (real
    PolySignalNativeStrategy / DecisionPipeline / SignalGate / MarketRotationActor),
    per ADR 0005. Backtest mode does not attach the sandbox recorder.
    """
    engine = cast(Any, build_backtest_engine(settings, instruments=instruments, data=data))
    try:
        engine.run()
        positions = tuple(engine.cache.positions())
    except Exception:
        dispose = getattr(engine, "dispose", None)
        if callable(dispose):
            _ = dispose()
        raise
    return engine, positions


def _split_boundary(start_ns: int | None, end_ns: int | None) -> int | None:
    if start_ns is None or end_ns is None or end_ns <= start_ns:
        return None
    return start_ns + int((end_ns - start_ns) * _IS_RATIO)


def collect_segment_stats(
    settings: Settings,
    *,
    instruments: tuple[object, ...],
    data: tuple[object, ...],
    label: str,
    start_ns: int | None,
    end_ns: int | None,
) -> SegmentedStats:
    """Run one replay segment through the real engine and return its settled stats."""
    engine, positions = _replay_segment(
        settings, instruments=instruments, data=data
    )
    try:
        return _segment_stats(
            positions, label=label, start_ns=start_ns, end_ns=end_ns
        )
    finally:
        dispose = getattr(engine, "dispose", None)
        if callable(dispose):
            _ = dispose()


def run_promotion(
    request: PromotionRequest,
    settings: Settings,
) -> PromotionReport:
    """Single promotion entry: read, split, replay both segments through the real
    engine, evaluate sample floor + OOS expectation, write the Markdown report.

    Does not mutate any production or lab configuration.
    """
    settings.runtime.nautilus.execution_mode = "backtest"
    # Recorded data carries quotes/custom-data/InstrumentClose (no L2 book deltas),
    # so promotion replays at L1_MBP — the book type that matches top-of-book data.
    settings.runtime.nautilus.sandbox_book_type = "L1_MBP"
    settings.strategies.set_explicit_strategy_names((request.strategy_name,))

    if request.report_path.suffix.lower() != ".md":
        raise ValueError("Promotion Report path must use the .md Markdown suffix")

    store = RecordedMarketDataStore(request.dataset_dir)
    full = store.read()
    split_ns = _split_boundary(full.start_ns, full.end_ns)

    is_window = store.read(end_ns=split_ns - 1 if split_ns is not None else None)
    oos_window = store.read(start_ns=split_ns)

    is_stats = collect_segment_stats(
        settings,
        instruments=full.instruments,
        data=is_window.data,
        label="IS (70%)",
        start_ns=full.start_ns,
        end_ns=split_ns,
    )
    oos_stats = collect_segment_stats(
        settings,
        instruments=full.instruments,
        data=oos_window.data,
        label="OOS (30%)",
        start_ns=split_ns,
        end_ns=full.end_ns,
    )

    verdict = evaluate_verdict(
        is_stats, oos_stats, is_floor=request.is_floor, oos_floor=request.oos_floor
    )

    report = PromotionReport(
        strategy_name=request.strategy_name,
        dataset_dir=request.dataset_dir,
        dataset_start_ns=full.start_ns,
        dataset_end_ns=full.end_ns,
        markets=full.markets,
        split_ns=split_ns,
        is_stats=is_stats,
        oos_stats=oos_stats,
        is_floor=request.is_floor,
        oos_floor=request.oos_floor,
        verdict=verdict,
        created_at=utc_iso(),
    )

    request.report_path.parent.mkdir(parents=True, exist_ok=True)
    _ = request.report_path.write_text(
        render_promotion_markdown(report), encoding="utf-8"
    )
    return report
