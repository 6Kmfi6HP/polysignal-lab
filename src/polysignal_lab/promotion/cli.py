from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from polysignal_lab.config import load_settings
from polysignal_lab.promotion.runner import (
    ADR_IS_FLOOR,
    ADR_OOS_FLOOR,
    PromotionRequest,
    run_promotion,
)


@dataclass(frozen=True, slots=True)
class PromotionCliOptions:
    config: Path
    dataset_dir: str
    strategy_name: str
    report_path: Path
    is_floor: int
    oos_floor: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PolySignal Lab promotion gate: replay recorded market data "
        "through the real BacktestEngine and emit a Promotion Report (ADR 0005).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", default="config/signal_bot.yaml")
    parser.add_argument(
        "--dataset-dir",
        required=True,
        help="Directory containing the recorded market_data.jsonl dataset (#42).",
    )
    parser.add_argument(
        "--strategy",
        required=True,
        help="Single strategy name to promote (one enabled ParamCombo).",
    )
    parser.add_argument(
        "--report-path",
        default="reports/promotion/{strategy}.md",
        help="Markdown report output path. '{strategy}' is substituted.",
    )
    parser.add_argument(
        "--is-floor",
        type=int,
        default=ADR_IS_FLOOR,
        help="Minimum IS settled rounds (ADR 0005 floor; cannot be lowered).",
    )
    parser.add_argument(
        "--oos-floor",
        type=int,
        default=ADR_OOS_FLOOR,
        help="Minimum OOS settled rounds (ADR 0005 floor; cannot be lowered).",
    )
    return parser


def parse_cli(argv: Sequence[str] | None = None) -> PromotionCliOptions:
    args = build_parser().parse_args(argv)
    is_floor = int(args.is_floor)
    oos_floor = int(args.oos_floor)
    report_path = Path(args.report_path.format(strategy=args.strategy))
    if report_path.is_absolute() or ".." in report_path.parts:
        raise ValueError("Promotion Report must be written under reports/promotion")
    return PromotionCliOptions(
        config=Path(args.config),
        dataset_dir=args.dataset_dir,
        strategy_name=args.strategy,
        report_path=report_path,
        is_floor=is_floor,
        oos_floor=oos_floor,
    )


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_cli(argv)
    settings = load_settings(options.config)
    report = run_promotion(
        PromotionRequest(
            dataset_dir=options.dataset_dir,
            strategy_name=options.strategy_name,
            report_path=options.report_path,
            is_floor=options.is_floor,
            oos_floor=options.oos_floor,
        ),
        settings,
    )
    print(
        f"promotion {report.verdict.value}: "
        f"{report.is_stats.settled_rounds}/{options.is_floor} IS, "
        f"{report.oos_stats.settled_rounds}/{options.oos_floor} OOS settled rounds → "
        f"{options.report_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
