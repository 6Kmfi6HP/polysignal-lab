"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, enum, enum.StrEnum
Output: Verdict, SegmentedStats, PromotionReport, render_promotion_markdown
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class SegmentedStats:
    """Settled-round statistics for one IS/OOS segment.

    Settled rounds are engine-native closed Positions; ``realized_pnl`` is the
    Nautilus portfolio truth, not a synthetic settlement (ADR 0003/0005).
    """

    label: str
    start_ns: int | None
    end_ns: int | None
    settled_rounds: int
    total_realized_pnl: float
    winning_rounds: int
    losing_rounds: int

    @property
    def average_realized_pnl(self) -> float:
        return self.total_realized_pnl / self.settled_rounds if self.settled_rounds else 0.0


@dataclass(frozen=True, slots=True)
class PromotionReport:
    """Evidence for a single (strategy, recorded dataset, param combo) review."""

    strategy_name: str
    dataset_dir: str
    dataset_start_ns: int | None
    dataset_end_ns: int | None
    markets: tuple[str, ...]
    split_ns: int | None
    is_stats: SegmentedStats
    oos_stats: SegmentedStats
    is_floor: int
    oos_floor: int
    verdict: Verdict
    created_at: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def with_datetime(self, *, created_at: str) -> "PromotionReport":
        return PromotionReport(
            strategy_name=self.strategy_name,
            dataset_dir=self.dataset_dir,
            dataset_start_ns=self.dataset_start_ns,
            dataset_end_ns=self.dataset_end_ns,
            markets=self.markets,
            split_ns=self.split_ns,
            is_stats=self.is_stats,
            oos_stats=self.oos_stats,
            is_floor=self.is_floor,
            oos_floor=self.oos_floor,
            verdict=self.verdict,
            created_at=created_at,
            notes=self.notes,
        )


def evaluate_verdict(
    is_stats: SegmentedStats,
    oos_stats: SegmentedStats,
    *,
    is_floor: int,
    oos_floor: int,
) -> Verdict:
    """ADR 0005 precedence: insufficient → no directional conclusion; else OOS expectation."""
    if is_stats.settled_rounds < is_floor or oos_stats.settled_rounds < oos_floor:
        return Verdict.INSUFFICIENT_DATA
    if oos_stats.total_realized_pnl <= 0.0:
        return Verdict.FAIL
    return Verdict.PASS


def _format_ns(ns: int | None) -> str:
    if ns is None:
        return "n/a"
    return datetime.fromtimestamp(ns / 1e9, tz=UTC).isoformat().replace("+00:00", "Z")


def render_promotion_markdown(report: PromotionReport) -> str:
    lines: list[str] = [
        f"# Promotion Report — {report.strategy_name}",
        "",
        f"- Verdict: **{report.verdict.value}**",
        f"- Created at: {report.created_at}",
        f"- Recorded dataset: `{report.dataset_dir}`",
        f"- Dataset time range: {_format_ns(report.dataset_start_ns)} → {_format_ns(report.dataset_end_ns)}",
        f"- Covered markets: {', '.join(report.markets) if report.markets else 'n/a'}",
        f"- IS/OOS split boundary: {_format_ns(report.split_ns)} (strict chronological 70/30)",
        f"- Sample floors: IS ≥ {report.is_floor}, OOS ≥ {report.oos_floor} settled rounds",
        "",
        "## Segment evidence",
        "",
        "| Segment | Settled rounds | Winning | Losing | Total realized PnL (USDC) | Avg realized PnL (USDC) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for stats in (report.is_stats, report.oos_stats):
        lines.append(
            f"| {stats.label} | {stats.settled_rounds} | {stats.winning_rounds} | "
            f"{stats.losing_rounds} | {stats.total_realized_pnl:.4f} | {stats.average_realized_pnl:.4f} |"
        )
    lines.append("")
    if report.verdict is Verdict.INSUFFICIENT_DATA:
        lines.append(
            "## Directional conclusion: withheld\n\n"
            "One or both segments are below the minimum settled-round sample floor. "
            "No PASS/FAIL directional conclusion is issued per ADR 0005."
        )
    elif report.verdict is Verdict.FAIL:
        lines.append("## Directional conclusion: FAIL\n\nOOS realized PnL is not positive.")
    else:
        lines.append("## Directional conclusion: PASS\n\nOOS realized PnL is positive.")
    lines.append("")
    if report.notes:
        lines.append("## Notes")
        lines.extend(f"- {note}" for note in report.notes)
        lines.append("")
    lines.append(
        "> Promotion action (modifying production config) is always manual; this toolchain only "
        "produces the report and writes no production or lab configuration."
    )
    lines.append("")
    return "\n".join(lines)
