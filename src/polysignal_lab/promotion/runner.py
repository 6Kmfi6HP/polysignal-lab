"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, dataclasses, dataclasses.dataclass, pathlib, pathlib.Path, typing, typing.Any, typing.cast, nautilus_trader.adapters.polymarket, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.nautilus_runtime.backtest_node, polysignal_lab.nautilus_runtime.custom_data_types, polysignal_lab.nautilus_runtime.projections, polysignal_lab.nautilus_runtime.recorded_market_data, polysignal_lab.promotion.report, polysignal_lab.utils
Output: run_promotion, PromotionRequest, collect_segment_stats
Pos: Application code — single promotion entry function (highest test seam)

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from nautilus_trader.adapters.polymarket import get_polymarket_instrument_id

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.backtest_node import build_backtest_engine
from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketMetaData
from polysignal_lab.nautilus_runtime.projections import project_position
from polysignal_lab.nautilus_runtime.recorded_market_data import (
    RecordedMarketDataStore,
)
from polysignal_lab.promotion.report import (
    ComboStats,
    PromotionReport,
    SegmentedStats,
    evaluate_verdict,
    render_promotion_markdown,
)
from polysignal_lab.utils import utc_iso

ADR_IS_FLOOR = 1000
ADR_OOS_FLOOR = 300
_IS_RATIO = 0.70
_REPORT_ROOT = Path("reports") / "promotion"


@dataclass(frozen=True, slots=True)
class PromotionRequest:
    """One (strategy, recorded dataset, single param combo) review request."""

    dataset_dir: str
    strategy_name: str
    report_path: Path
    is_floor: int = ADR_IS_FLOOR
    oos_floor: int = ADR_OOS_FLOOR

    def __post_init__(self) -> None:
        if self.is_floor < ADR_IS_FLOOR:
            raise ValueError(f"IS sample floor cannot be lower than {ADR_IS_FLOOR}")
        if self.oos_floor < ADR_OOS_FLOOR:
            raise ValueError(f"OOS sample floor cannot be lower than {ADR_OOS_FLOOR}")


def _instrument_combinations(data: tuple[object, ...]) -> dict[str, tuple[str, str]]:
    mappings: dict[str, tuple[str, str]] = {}
    for item in data:
        if not isinstance(item, PolySignalMarketMetaData):
            continue
        combination = (item.asset.upper(), item.timeframe)
        for token_id in (item.up_token_id, item.down_token_id):
            if not token_id:
                continue
            try:
                instrument_id = str(get_polymarket_instrument_id(item.condition_id, token_id))
            except (RuntimeError, TypeError, ValueError):
                continue
            mappings[instrument_id] = combination
    return mappings


def _known_combinations(data: tuple[object, ...]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                (item.asset.upper(), item.timeframe)
                for item in data
                if isinstance(item, PolySignalMarketMetaData)
            }
        )
    )


def _segment_stats(
    positions: tuple[object, ...],
    *,
    label: str,
    start_ns: int | None,
    end_ns: int | None,
    instrument_combinations: Mapping[str, tuple[str, str]] | None = None,
    known_combinations: tuple[tuple[str, str], ...] = (),
) -> SegmentedStats:
    closed = [project_position(p) for p in positions if bool(p) and _is_closed(p)]
    realized = [
        float(cast(Any, p["realized_pnl"]))
        for p in closed
        if p["realized_pnl"] is not None
    ]
    winners = sum(1 for value in realized if value > 0)
    losers = sum(1 for value in realized if value < 0)
    combo_totals: dict[tuple[str, str], list[float]] = {
        combination: [0.0, 0.0, 0.0, 0.0] for combination in known_combinations
    }
    mappings_by_id = instrument_combinations or {}
    for position in closed:
        combination = mappings_by_id.get(
            str(position.get("instrument_id") or ""), ("UNKNOWN", "UNKNOWN")
        )
        values = combo_totals.setdefault(combination, [0.0, 0.0, 0.0, 0.0])
        values[0] += 1
        pnl = position["realized_pnl"]
        if pnl is None:
            continue
        value = float(cast(Any, pnl))
        values[1] += value
        values[2] += value > 0
        values[3] += value < 0
    combinations = tuple(
        ComboStats(
            asset=asset,
            timeframe=timeframe,
            settled_rounds=int(values[0]),
            total_realized_pnl=values[1],
            winning_rounds=int(values[2]),
            losing_rounds=int(values[3]),
        )
        for (asset, timeframe), values in sorted(combo_totals.items())
    )
    return SegmentedStats(
        label=label,
        start_ns=start_ns,
        end_ns=end_ns,
        settled_rounds=len(closed),
        total_realized_pnl=sum(realized),
        winning_rounds=winners,
        losing_rounds=losers,
        combinations=combinations,
    )


def _is_closed(position: object) -> bool:
    return bool(getattr(position, "is_closed", False))


def _replay_segment(
    settings: Settings,
    *,
    instruments: tuple[object, ...],
    data: tuple[object, ...],
) -> tuple[Any, tuple[object, ...]]:
    """Assemble the real BacktestEngine with sandbox-shared components and run it."""
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
    instrument_combinations: Mapping[str, tuple[str, str]] | None = None,
    known_combinations: tuple[tuple[str, str], ...] = (),
) -> SegmentedStats:
    """Run one replay segment through the real engine and return its settled stats."""
    engine, positions = _replay_segment(settings, instruments=instruments, data=data)
    try:
        return _segment_stats(
            positions,
            label=label,
            start_ns=start_ns,
            end_ns=end_ns,
            instrument_combinations=instrument_combinations,
            known_combinations=known_combinations,
        )
    finally:
        dispose = getattr(engine, "dispose", None)
        if callable(dispose):
            _ = dispose()


def _collect_with_combinations(
    settings: Settings,
    *,
    instruments: tuple[object, ...],
    data: tuple[object, ...],
    label: str,
    start_ns: int | None,
    end_ns: int | None,
    instrument_combinations: Mapping[str, tuple[str, str]],
    known_combinations: tuple[tuple[str, str], ...],
) -> SegmentedStats:
    try:
        return collect_segment_stats(
            settings,
            instruments=instruments,
            data=data,
            label=label,
            start_ns=start_ns,
            end_ns=end_ns,
            instrument_combinations=instrument_combinations,
            known_combinations=known_combinations,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        return collect_segment_stats(
            settings,
            instruments=instruments,
            data=data,
            label=label,
            start_ns=start_ns,
            end_ns=end_ns,
        )


def _empty_stats(label: str) -> SegmentedStats:
    return SegmentedStats(label, None, None, 0, 0.0, 0, 0)


def _validated_report_path(path: Path) -> Path:
    if path.suffix.lower() != ".md":
        raise ValueError("Promotion Report path must use the .md Markdown suffix")
    candidate = (path if path.is_absolute() else Path.cwd() / path).resolve()
    root = candidate.parents[1] if path.is_absolute() else (Path.cwd() / _REPORT_ROOT).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Promotion Report must be written under reports/promotion") from exc
    return candidate


def run_promotion(request: PromotionRequest, settings: Settings) -> PromotionReport:
    """Replay one strategy/dataset through the real engine and write its report."""
    report_path = _validated_report_path(request.report_path)
    settings.runtime.nautilus.execution_mode = "backtest"
    settings.runtime.nautilus.sandbox_book_type = "L1_MBP"
    settings.strategies.set_explicit_strategy_names((request.strategy_name,))
    promotion_settings = settings

    store = RecordedMarketDataStore(request.dataset_dir)
    full = store.read()
    split_ns = _split_boundary(full.start_ns, full.end_ns)
    combination_map = _instrument_combinations(full.data)
    known_combinations = _known_combinations(full.data)
    if split_ns is None:
        is_stats = _empty_stats("IS (70%)")
        oos_stats = _empty_stats("OOS (30%)")
    else:
        is_window = store.read(end_ns=split_ns - 1)
        oos_window = store.read(start_ns=split_ns, include_prior_context=False)
        is_stats = _collect_with_combinations(
            promotion_settings,
            instruments=full.instruments,
            data=is_window.data,
            label="IS (70%)",
            start_ns=full.start_ns,
            end_ns=split_ns,
            instrument_combinations=combination_map,
            known_combinations=known_combinations,
        )
        oos_stats = _collect_with_combinations(
            promotion_settings,
            instruments=full.instruments,
            data=oos_window.data,
            label="OOS (30%)",
            start_ns=split_ns,
            end_ns=full.end_ns,
            instrument_combinations=combination_map,
            known_combinations=known_combinations,
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
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _ = report_path.write_text(render_promotion_markdown(report), encoding="utf-8")
    return report
