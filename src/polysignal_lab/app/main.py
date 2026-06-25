"""PolySignal Lab main entry point."""
from __future__ import annotations

import argparse
import signal
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, assert_never

import anyio
import uvicorn

from polysignal_lab.app.readonly_smoke import ReadonlySmokeRequest, collect_readonly_smoke
from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.config import Settings, load_settings
from polysignal_lab.dashboard.app import create_dashboard_app
from polysignal_lab.observability.logger import configure_logging
from polysignal_lab.storage.sqlite_store import SQLiteStore


class RuntimeMode(StrEnum):
    SCHEDULER = "scheduler"
    DASHBOARD = "dashboard"
    SMOKE = "smoke"
    NAUTILUS = "nautilus"


MODE_VALUES: Final = tuple(mode.value for mode in RuntimeMode)


@dataclass(frozen=True, slots=True)
class CliOptions:
    config: Path
    mode: RuntimeMode
    once: bool
    real_readonly_smoke: bool
    evidence: Path | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PolySignal Lab runtime",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "command",
        choices=MODE_VALUES,
        nargs="?",
        help="Optional runtime mode command.",
    )
    parser.add_argument(
        "--mode",
        choices=MODE_VALUES,
        help="Runtime mode to execute.",
    )
    parser.add_argument("--config", default="config/signal_bot.yaml")
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Compatibility alias for --mode dashboard.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one bounded readiness pass instead of the scheduler loop.",
    )
    parser.add_argument(
        "--real-readonly-smoke",
        action="store_true",
        help="Run bounded public read-only market, scheduler, dashboard, and safety checks.",
    )
    parser.add_argument(
        "--evidence",
        help="Optional path for bounded smoke evidence JSON.",
    )
    return parser


def parse_cli(argv: Sequence[str] | None = None) -> CliOptions:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command
    mode_arg = args.mode

    if args.dashboard:
        if command or mode_arg:
            parser.error("--dashboard cannot be combined with command or --mode")
        mode = RuntimeMode.DASHBOARD
    else:
        selected = mode_arg or command or RuntimeMode.SCHEDULER.value
        mode = RuntimeMode(selected)

    if mode is RuntimeMode.DASHBOARD and (args.once or args.real_readonly_smoke):
        parser.error("dashboard mode cannot be combined with --once or smoke flags")
    if args.real_readonly_smoke and not args.once and mode is not RuntimeMode.SMOKE:
        parser.error("--real-readonly-smoke requires --once outside smoke mode")

    return CliOptions(
        config=Path(args.config),
        mode=mode,
        once=bool(args.once or mode is RuntimeMode.SMOKE),
        real_readonly_smoke=bool(args.real_readonly_smoke or mode is RuntimeMode.SMOKE),
        evidence=Path(args.evidence) if args.evidence else None,
    )


def _sigterm_handler(_signum: int, _frame: object) -> None:
    """Convert Docker SIGTERM into KeyboardInterrupt so anyio/finally runs."""
    raise KeyboardInterrupt()


def run_scheduler_cli(settings: Settings) -> None:
    configure_logging(settings.app.log_level)

    # Docker sends SIGTERM to PID 1. Python PID 1 exits immediately without
    # running cleanup handlers. Override to raise KeyboardInterrupt, which
    # asyncio translates into task cancellation → finally block executes.
    signal.signal(signal.SIGTERM, _sigterm_handler)

    scheduler = PolySignalScheduler(settings)
    anyio.run(scheduler.run)


def run_dashboard_cli(settings: Settings) -> None:
    configure_logging(settings.app.log_level)
    store = SQLiteStore(settings.storage.sqlite_path)
    app = create_dashboard_app(store)
    uvicorn.run(app, host=settings.dashboard.host, port=settings.dashboard.port)


def run_readonly_smoke(settings: Settings, options: CliOptions) -> None:
    configure_logging(settings.app.log_level)
    request = ReadonlySmokeRequest(
        settings=settings,
        config_path=options.config,
        evidence_path=options.evidence,
        base_dir=Path(".omo/evidence/readonly-smoke-runtime"),
    )
    evidence = anyio.run(collect_readonly_smoke, request)
    status = "passed" if evidence["passed"] else f"completed with {evidence['failure_count']} degraded surface(s)"
    print(f"Bounded read-only smoke {status}")


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_cli(argv)
    settings = load_settings(options.config)
    settings.validate_runtime_environment()

    match options.mode:
        case RuntimeMode.SCHEDULER:
            if options.once or options.real_readonly_smoke:
                run_readonly_smoke(settings, options)
                return 0
            run_scheduler_cli(settings)
            return 0
        case RuntimeMode.DASHBOARD:
            run_dashboard_cli(settings)
            return 0
        case RuntimeMode.SMOKE:
            run_readonly_smoke(settings, options)
            return 0
        case RuntimeMode.NAUTILUS:
            from polysignal_lab.nautilus_runtime.node import run_nautilus_cli

            run_nautilus_cli(settings)
            return 0
        case unreachable:
            assert_never(unreachable)


if __name__ == "__main__":
    raise SystemExit(main())
