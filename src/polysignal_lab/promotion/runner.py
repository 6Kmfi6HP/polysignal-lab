from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.backtest_node import build_backtest_engine
from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketMetaData
from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module
from polysignal_lab.nautilus_runtime.projections import project_position
from polysignal_lab.nautilus_runtime.recorded_market_data import RecordedMarketDataStore
from polysignal_lab.promotion.report import (
    ComboStats,
    PromotionReport,
    SegmentedStats,
    evaluate_verdict,
    render_promotion_markdown,
)
from polysignal_lab.utils import utc_iso

nautilus_pyo3 = load_nautilus_module("nautilus_trader.core.nautilus_pyo3")
_adapters_polymarket = load_nautilus_module("nautilus_trader.adapters.polymarket")
get_polymarket_instrument_id = _adapters_polymarket.get_polymarket_instrument_id

ADR_IS_FLOOR = 1000
ADR_OOS_FLOOR = 300
_IS_RATIO = 0.70
_REPORT_ROOT = Path("reports") / "promotion"


@dataclass(frozen=True, slots=True)
class PromotionRequest:
    dataset_dir: str
    strategy_name: str
    report_path: Path
    is_floor: int = ADR_IS_FLOOR
    oos_floor: int = ADR_OOS_FLOOR

    def __post_init__(self) -> None:
        if self.is_floor < ADR_IS_FLOOR or self.oos_floor < ADR_OOS_FLOOR:
            raise ValueError("Promotion sample floors cannot be lowered below ADR 0005")


def _instrument_context(
    data: tuple[object, ...],
) -> dict[str, tuple[str, tuple[str, str]]]:
    context: dict[str, tuple[str, tuple[str, str]]] = {}
    for item in data:
        if not isinstance(item, PolySignalMarketMetaData):
            continue
        combination = (item.asset.upper(), item.timeframe)
        for token_id in (item.up_token_id, item.down_token_id):
            if not token_id:
                continue
            try:
                instrument_id = str(
                    get_polymarket_instrument_id(item.condition_id, token_id)
                )
            except (RuntimeError, TypeError, ValueError):
                continue
            context[instrument_id] = (item.condition_id, combination)
    return context


def _known_combinations(
    data: tuple[object, ...],
    strategy: object,
) -> tuple[tuple[str, str], ...]:
    combinations = {
        (item.asset.upper(), item.timeframe)
        for item in data
        if isinstance(item, PolySignalMarketMetaData)
    }
    assets = getattr(strategy, "assets", None)
    timeframes = getattr(strategy, "timeframes", None)
    if assets is None or timeframes is None:
        return tuple(sorted(combinations))
    allowed = {
        (str(asset).upper(), str(timeframe))
        for asset in assets
        for timeframe in timeframes
    }
    return tuple(sorted(allowed))


def _settlement_rounds(
    data: tuple[object, ...],
    context: Mapping[str, tuple[str, tuple[str, str]]],
    known_combinations: tuple[tuple[str, str], ...],
) -> dict[str, tuple[str, str]]:
    rounds: dict[str, tuple[str, str]] = {}
    allowed = set(known_combinations)
    for item in data:
        if not isinstance(item, nautilus_pyo3.InstrumentClose):
            continue
        instrument_id = str(item.instrument_id)
        condition, combination = context.get(
            instrument_id,
            (f"UNKNOWN:{instrument_id}", ("UNKNOWN", "UNKNOWN")),
        )
        if combination in allowed:
            rounds[condition] = combination
        elif combination == ("UNKNOWN", "UNKNOWN"):
            rounds[condition] = combination
    return rounds


def _segment_stats(
    positions: tuple[object, ...],
    *,
    label: str,
    start_ns: int | None,
    end_ns: int | None,
    instrument_combinations: Mapping[str, tuple[str, tuple[str, str]]] | None = None,
    known_combinations: tuple[tuple[str, str], ...] = (),
    settlement_rounds: Mapping[str, tuple[str, str]] | None = None,
) -> SegmentedStats:
    mappings = instrument_combinations or {}
    closed = [project_position(p) for p in positions if bool(p) and _is_closed(p)]
    totals: dict[tuple[str, str], list[float]] = {
        key: [0.0, 0.0, 0.0, 0.0] for key in known_combinations
    }
    if settlement_rounds is None:
        counted: set[tuple[tuple[str, str], str]] = set()
        realized: list[float] = []
        winners = losers = 0
        for position in closed:
            value_raw = position["realized_pnl"]
            if value_raw is None:
                continue
            value = float(cast(Any, value_raw))
            instrument_id = str(position.get("instrument_id") or "")
            combination = mappings.get(instrument_id, ("", ("UNKNOWN", "UNKNOWN")))[1]
            values = totals.setdefault(combination, [0.0, 0.0, 0.0, 0.0])
            identity = str(
                position.get("report_position_id")
                or position.get("closed_at")
                or position.get("ts")
                or id(position)
            )
            round_key = (combination, identity)
            if round_key in counted:
                continue
            counted.add(round_key)
            realized.append(value)
            winners += value > 0
            losers += value < 0
            values[0] += 1
            values[1] += value
            values[2] += value > 0
            values[3] += value < 0
    else:
        pnl_by_round = {condition: 0.0 for condition in settlement_rounds}
        for position in closed:
            value_raw = position["realized_pnl"]
            if value_raw is None:
                continue
            instrument_id = str(position.get("instrument_id") or "")
            condition = mappings.get(instrument_id, ("", ("UNKNOWN", "UNKNOWN")))[0]
            if condition in pnl_by_round:
                pnl_by_round[condition] += float(cast(Any, value_raw))
        counted = set()
        realized = []
        winners = losers = 0
        for condition, combination in settlement_rounds.items():
            value = pnl_by_round[condition]
            values = totals.setdefault(combination, [0.0, 0.0, 0.0, 0.0])
            counted.add((combination, condition))
            realized.append(value)
            winners += value > 0
            losers += value < 0
            values[0] += 1
            values[1] += value
            values[2] += value > 0
            values[3] += value < 0
    combinations = tuple(
        ComboStats(
            asset=asset,
            timeframe=timeframe,
            settled_rounds=int(v[0]),
            total_realized_pnl=v[1],
            winning_rounds=int(v[2]),
            losing_rounds=int(v[3]),
            valid=asset != "UNKNOWN" and timeframe != "UNKNOWN",
        )
        for (asset, timeframe), v in sorted(totals.items())
    )
    return SegmentedStats(
        label,
        start_ns,
        end_ns,
        len(counted),
        sum(realized),
        winners,
        losers,
        combinations,
    )


def _is_closed(position: object) -> bool:
    return bool(getattr(position, "is_closed", False))


def _replay_segment(
    settings: Settings,
    *,
    instruments: tuple[object, ...],
    data: tuple[object, ...],
) -> tuple[Any, tuple[object, ...]]:
    engine = cast(
        Any, build_backtest_engine(settings, instruments=instruments, data=data)
    )
    try:
        engine.run()
        return engine, tuple(engine.cache.positions())
    except Exception:
        dispose = getattr(engine, "dispose", None)
        if callable(dispose):
            _ = dispose()
        raise


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
    instrument_combinations: Mapping[str, tuple[str, tuple[str, str]]] | None = None,
    known_combinations: tuple[tuple[str, str], ...] = (),
    settlement_rounds: Mapping[str, tuple[str, str]] | None = None,
) -> SegmentedStats:
    engine, positions = _replay_segment(settings, instruments=instruments, data=data)
    try:
        return _segment_stats(
            positions,
            label=label,
            start_ns=start_ns,
            end_ns=end_ns,
            instrument_combinations=instrument_combinations,
            known_combinations=known_combinations,
            settlement_rounds=settlement_rounds,
        )
    finally:
        dispose = getattr(engine, "dispose", None)
        if callable(dispose):
            _ = dispose()


def _empty_stats(label: str) -> SegmentedStats:
    return SegmentedStats(label, None, None, 0, 0.0, 0, 0)


def _repository_root() -> Path:
    # Derive from the module location first: the working directory may be a
    # test tmpdir (promotion tests chdir), and probing outward from there can
    # either hit an unrelated .git (e.g. /tmp/.git on some hosts) or none at
    # all on CI. The module's own path pins the repo root regardless of cwd.
    start = Path(__file__).resolve()
    for candidate in (start.parent, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise ValueError("Promotion Report must be run from inside the repository")


def _validated_report_path(path: Path) -> Path:
    if path.suffix.lower() != ".md":
        raise ValueError("Promotion Report path must use the .md Markdown suffix")
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Promotion Report must be written under reports/promotion")
    root = _repository_root() / _REPORT_ROOT
    if root.exists() and root.is_symlink():
        raise ValueError(
            "Promotion report directory must be a real in-repository directory"
        )
    candidate_raw = _repository_root() / path
    if candidate_raw.exists() and candidate_raw.is_symlink():
        raise ValueError("Promotion report target must not be a symlink")
    candidate = candidate_raw.resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(
            "Promotion Report must be written under reports/promotion"
        ) from exc
    root.mkdir(parents=True, exist_ok=True)
    return candidate


def run_promotion(request: PromotionRequest, settings: Settings) -> PromotionReport:
    report_path = _validated_report_path(request.report_path)
    promotion_settings = settings.model_copy(deep=True)
    promotion_settings.runtime.nautilus.execution_mode = "backtest"
    promotion_settings.runtime.nautilus.sandbox_book_type = "L1_MBP"
    promotion_settings.strategies.set_explicit_strategy_names((request.strategy_name,))
    store = RecordedMarketDataStore(request.dataset_dir)
    full = store.read()
    split_ns = _split_boundary(full.start_ns, full.end_ns)
    if split_ns is None:
        is_stats = _empty_stats("IS (70%)")
        oos_stats = _empty_stats("OOS (30%)")
    else:
        context = _instrument_context(full.data)
        strategy = getattr(promotion_settings.strategies, request.strategy_name)
        known_combinations = _known_combinations(full.data, strategy)
        is_window = store.read(end_ns=split_ns - 1)
        oos_window = store.read(start_ns=split_ns, include_prior_context=True)
        is_stats = collect_segment_stats(
            promotion_settings,
            instruments=full.instruments,
            data=is_window.data,
            label="IS (70%)",
            start_ns=full.start_ns,
            end_ns=split_ns,
            instrument_combinations={
                instrument_id: (condition, combo)
                for instrument_id, (condition, combo) in context.items()
            },
            known_combinations=known_combinations,
            settlement_rounds=_settlement_rounds(
                is_window.data, context, known_combinations
            ),
        )
        oos_stats = collect_segment_stats(
            promotion_settings,
            instruments=full.instruments,
            data=oos_window.data,
            label="OOS (30%)",
            start_ns=split_ns,
            end_ns=full.end_ns,
            instrument_combinations={
                instrument_id: (condition, combo)
                for instrument_id, (condition, combo) in context.items()
            },
            known_combinations=known_combinations,
            settlement_rounds=_settlement_rounds(
                oos_window.data, context, known_combinations
            ),
        )
    report = PromotionReport(
        request.strategy_name,
        request.dataset_dir,
        full.start_ns,
        full.end_ns,
        full.markets,
        split_ns,
        is_stats,
        oos_stats,
        request.is_floor,
        request.oos_floor,
        evaluate_verdict(
            is_stats, oos_stats, is_floor=request.is_floor, oos_floor=request.oos_floor
        ),
        utc_iso(),
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _ = report_path.write_text(render_promotion_markdown(report), encoding="utf-8")
    return report
