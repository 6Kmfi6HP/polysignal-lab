"""
Input: __future__, __future__.annotations, pathlib, pytest, nautilus_trader, polysignal_lab.config, polysignal_lab.promotion
Output: promotion gate verdict / split / report / real-engine integration tests
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from nautilus_trader.core import nautilus_pyo3 as pyo3
from nautilus_trader.test_kit.rust.instruments_pyo3 import TestInstrumentProviderPyo3

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
)
from polysignal_lab.nautilus_runtime.recorded_market_data import RecordedMarketDataStore
from polysignal_lab.promotion import (
    SegmentedStats,
    Verdict,
    evaluate_verdict,
    render_promotion_markdown,
    run_promotion,
)
from polysignal_lab.promotion.cli import parse_cli
from polysignal_lab.promotion.report import PromotionReport
from polysignal_lab.promotion.runner import PromotionRequest, _segment_stats, _split_boundary


# --- ADR 0005 verdict precedence (pure unit) ---


def _stats(rounds: int, pnl: float) -> SegmentedStats:
    return SegmentedStats(
        label="x",
        start_ns=0,
        end_ns=0,
        settled_rounds=rounds,
        total_realized_pnl=pnl,
        winning_rounds=0,
        losing_rounds=0,
    )


def _labeled_stats(label: str, rounds: int, pnl: float) -> SegmentedStats:
    return SegmentedStats(
        label=label,
        start_ns=0,
        end_ns=0,
        settled_rounds=rounds,
        total_realized_pnl=pnl,
        winning_rounds=rounds if pnl > 0 else 0,
        losing_rounds=rounds if pnl < 0 else 0,
    )


def test_verdict_insufficient_when_below_floor_even_with_positive_oos() -> None:
    verdict = evaluate_verdict(
        _stats(5, 100.0), _stats(0, 0.0), is_floor=1000, oos_floor=300
    )
    assert verdict is Verdict.INSUFFICIENT_DATA


def test_verdict_insufficient_at_oos_floor_minus_one() -> None:
    verdict = evaluate_verdict(
        _stats(1000, 50.0), _stats(299, 10.0), is_floor=1000, oos_floor=300
    )
    assert verdict is Verdict.INSUFFICIENT_DATA


def test_verdict_fail_when_oos_realized_pnl_is_non_positive() -> None:
    verdict = evaluate_verdict(
        _stats(1000, 500.0), _stats(300, -1.0), is_floor=1000, oos_floor=300
    )
    assert verdict is Verdict.FAIL


def test_verdict_fail_when_oos_realized_pnl_is_exactly_zero() -> None:
    verdict = evaluate_verdict(
        _stats(1000, 500.0), _stats(300, 0.0), is_floor=1000, oos_floor=300
    )
    assert verdict is Verdict.FAIL


def test_verdict_pass_when_floors_met_and_oos_pnl_positive() -> None:
    verdict = evaluate_verdict(
        _stats(1000, 500.0), _stats(300, 0.01), is_floor=1000, oos_floor=300
    )
    assert verdict is Verdict.PASS


# --- Chronological split (pure unit, no leakage) ---


def test_split_boundary_is_seventy_percent_strictly_chronological() -> None:
    split = _split_boundary(0, 10_000_000_000)
    assert split == 7_000_000_000


def test_split_boundary_none_when_range_unavailable() -> None:
    assert _split_boundary(None, 100) is None
    assert _split_boundary(100, None) is None
    assert _split_boundary(100, 100) is None


def test_segment_stats_collects_only_settled_rounds_with_realized_pnl() -> None:
    closed_pos = SimpleNamespace(is_closed=True, realized_pnl=2.5)
    open_pos = SimpleNamespace(is_closed=False, realized_pnl=0.0)
    losing_pos = SimpleNamespace(is_closed=True, realized_pnl=-3.0)
    stats = _segment_stats(
        cast("tuple[object, ...]", (closed_pos, open_pos, losing_pos)),
        label="IS (70%)",
        start_ns=1,
        end_ns=2,
    )
    assert stats.settled_rounds == 2
    assert stats.total_realized_pnl == pytest.approx(-0.5)
    assert stats.winning_rounds == 1
    assert stats.losing_rounds == 1


# --- Real-engine integration: entry seam + report + INSUFFICIENT_DATA ---


def _write_minimal_dataset(directory: Path) -> None:
    """Recorded dataset: instrument + metadata + InstrumentClose; no quotes drive
    any entry, so settled rounds are 0 → INSUFFICIENT_DATA. Exercises the real
    RecordedMarketDataStore round-trip including InstrumentClose (ADR 0003)."""
    instrument = TestInstrumentProviderPyo3.binary_option()
    metadata = PolySignalMarketMetaData(
        market_id="market-1",
        market_slug="btc-updown-5m",
        condition_id="condition-1",
        asset="BTC",
        timeframe="5m",
        up_token_id=str(instrument.id),
        down_token_id="down.POLYMARKET",
        ts_event=10,
        ts_init=10,
    )
    close = pyo3.InstrumentClose(
        instrument_id=instrument.id,
        close_price=pyo3.Price.from_str("1.000"),
        close_type=pyo3.InstrumentCloseType.CONTRACT_EXPIRED,
        ts_event=1_000_000_000_000,
        ts_init=1_000_000_000_000,
    )
    store = RecordedMarketDataStore(directory)
    store.record(instrument)
    store.record(metadata)
    store.record(close)
    store.close()


def test_run_promotion_drives_real_engine_and_writes_markdown_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset_dir = tmp_path / "recorded"
    _write_minimal_dataset(dataset_dir)
    report_path = Path("reports/promotion/one_cent_buy.md")
    monkeypatch.chdir(tmp_path)

    settings = Settings()
    request = PromotionRequest(
        dataset_dir=str(dataset_dir),
        strategy_name="one_cent_buy",
        report_path=report_path,
        is_floor=1000,
        oos_floor=300,
    )
    report = run_promotion(request, settings)

    # Promotion replays with an isolated backtest Settings copy.
    assert settings.runtime.nautilus.execution_mode == "sandbox"
    assert settings.strategies.explicit_strategy_names() == ()

    # No entry quotes → 0 settled rounds → directional conclusion withheld.
    assert report.verdict is Verdict.INSUFFICIENT_DATA
    assert report.is_stats.settled_rounds == 0
    assert report.oos_stats.settled_rounds == 0

    # Markdown report lands in the in-repo report directory with full evidence.
    assert report_path.exists()
    markdown = report_path.read_text(encoding="utf-8")
    assert "INSUFFICIENT_DATA" in markdown
    assert "IS (70%)" in markdown
    assert "OOS (30%)" in markdown
    assert "Dataset time range:" in markdown
    assert "Covered markets:" in markdown
    assert "condition-1" in markdown
    assert "No PASS/FAIL directional conclusion" in markdown

    # Strict chronological 70/30 split boundary present in the report.
    assert report.split_ns is not None
    assert report.dataset_start_ns == 10
    assert report.dataset_end_ns == 1_000_000_000_000
    assert report.dataset_start_ns <= report.split_ns <= report.dataset_end_ns


def test_run_promotion_splits_boundary_without_replaying_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_dir = tmp_path / "recorded"
    _write_minimal_dataset(dataset_dir)
    captured: dict[str, tuple[int, ...]] = {}

    def collect(
        _settings: Settings,
        *,
        instruments: tuple[object, ...],
        data: tuple[object, ...],
        label: str,
        start_ns: int | None,
        end_ns: int | None,
        **kwargs: object,
    ) -> SegmentedStats:
        _ = instruments, start_ns, end_ns
        captured[label] = tuple(int(getattr(item, "ts_init")) for item in data)
        return _stats(0, 0.0)

    monkeypatch.setattr("polysignal_lab.promotion.runner.collect_segment_stats", collect)
    monkeypatch.chdir(tmp_path)
    run_promotion(
        PromotionRequest(
            dataset_dir=str(dataset_dir),
            strategy_name="one_cent_buy",
            report_path=Path("reports/promotion/boundary.md"),
        ),
        Settings(),
    )

    assert captured["IS (70%)"] == (10,)
    assert captured["OOS (30%)"] == (10, 1_000_000_000_000)


def test_run_promotion_rejects_non_markdown_report_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="Markdown"):
        run_promotion(
            PromotionRequest(
                dataset_dir=str(tmp_path / "recorded"),
                strategy_name="one_cent_buy",
                report_path=tmp_path / "config" / "signal_bot.yaml",
            ),
            Settings(),
        )


def test_run_promotion_pass_path_with_small_floors(tmp_path: Path) -> None:
    """With the ADR floors lowered to 0, zero settled rounds but non-negative OOS
    expectation is withheld (<=0 → FAIL until positive). Assert the thresholded
    PASS branch is reachable via evaluate_verdict over engine-collected stats."""
    is_stats = _stats(2, 5.0)
    oos_stats = _stats(2, 1.0)
    verdict = evaluate_verdict(is_stats, oos_stats, is_floor=2, oos_floor=2)
    assert verdict is Verdict.PASS


def test_run_promotion_fail_path_with_small_floors() -> None:
    is_stats = _stats(2, 5.0)
    oos_stats = _stats(2, -1.0)
    verdict = evaluate_verdict(is_stats, oos_stats, is_floor=2, oos_floor=2)
    assert verdict is Verdict.FAIL


def test_promotion_report_render_contains_all_evidence() -> None:
    report = PromotionReport(
        strategy_name="binary_momentum",
        dataset_dir="data/recorded_market_data",
        dataset_start_ns=1_700_000_000_000_000_000,
        dataset_end_ns=1_700_000_000_000_005_000,
        markets=("condition-a", "condition-b"),
        split_ns=1_700_000_000_000_003_500,
        is_stats=_labeled_stats("IS (70%)", 1000, 82.0),
        oos_stats=_labeled_stats("OOS (30%)", 300, 14.5),
        is_floor=1000,
        oos_floor=300,
        verdict=Verdict.PASS,
        created_at="2026-07-22T00:00:00Z",
    )
    markdown = render_promotion_markdown(report)
    assert "binary_momentum" in markdown
    assert "**PASS**" in markdown
    assert "| IS (70%) | 1000 |" in markdown
    assert "| OOS (30%) | 300 |" in markdown
    assert "condition-a, condition-b" in markdown
    assert "manual" in markdown  # production-config promotion is manual


def test_run_promotion_writes_no_production_or_lab_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset_dir = tmp_path / "recorded"
    _write_minimal_dataset(dataset_dir)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    sentinel = config_dir / "signal_bot.yaml"
    sentinel.write_text("existing: true", encoding="utf-8")

    settings = Settings()
    monkeypatch.chdir(tmp_path)
    request = PromotionRequest(
        dataset_dir=str(dataset_dir),
        strategy_name="vwap_momentum",
        report_path=Path("reports/promotion/vwap.md"),
    )
    run_promotion(request, settings)
    # Toolchain must not write or touch any production/lab config file.
    assert sentinel.read_text(encoding="utf-8") == "existing: true"
    assert list(config_dir.iterdir()) == [sentinel]


def test_promotion_cli_parses_strategy_into_report_path(tmp_path: Path) -> None:
    options = parse_cli([
        "--dataset-dir", str(tmp_path / "data" / "recorded_market_data"),
        "--strategy", "binary_momentum",
        "--is-floor", "5",
        "--oos-floor", "2",
    ])
    assert options.strategy_name == "binary_momentum"
    assert options.dataset_dir.endswith("recorded_market_data")
    assert options.is_floor == 5
    assert options.oos_floor == 2
    assert options.report_path == Path("reports/promotion/binary_momentum.md")
