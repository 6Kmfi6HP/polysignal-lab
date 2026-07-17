"""
Input: __future__, __future__.annotations, argparse, collections.abc, collections.abc.Sequence, dataclasses, dataclasses.dataclass, enum, enum.StrEnum, pathlib
Output: build_parser, parse_cli, run_dashboard_cli, run_readonly_smoke, main, RuntimeMode, CliOptions
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, assert_never

import anyio
import uvicorn

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.app.readonly_smoke_types import ReadonlySmokeEvidence, ReadonlySmokeRequest
from polysignal_lab.dashboard.app import create_dashboard_app
from polysignal_lab.dashboard.reporting_read import FileRuntimeHealthReader
from polysignal_lab.observability.logger import configure_logging
from polysignal_lab.storage.sqlite_store import SQLiteStore


class RuntimeMode(StrEnum):
    DASHBOARD = "dashboard"
    SMOKE = "smoke"
    NAUTILUS = "nautilus"
    SANDBOX = "sandbox"
    LIVE = "live"
    BACKTEST = "backtest"


MODE_VALUES: Final = tuple(mode.value for mode in RuntimeMode)


@dataclass(frozen=True, slots=True)
class CliOptions:
    config: Path
    mode: RuntimeMode
    use_config_default_runtime: bool
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
        help="Explicit runtime mode.",
    )
    parser.add_argument(
        "--mode",
        choices=MODE_VALUES,
        help="Explicit runtime mode.",
    )
    parser.add_argument("--config", default="config/signal_bot.yaml")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one bounded readiness pass.",
    )
    parser.add_argument(
        "--real-readonly-smoke",
        action="store_true",
        help="Run bounded public read-only market and retired-surface readiness checks.",
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
    if command and mode_arg:
        parser.error("runtime command cannot be combined with --mode")

    runtime_selected = bool(mode_arg or command)
    selected = mode_arg or command or RuntimeMode.NAUTILUS.value
    mode = RuntimeMode(selected)

    if (args.once or args.real_readonly_smoke) and mode is not RuntimeMode.SMOKE:
        parser.error("smoke flags require the explicit 'smoke' mode")

    return CliOptions(
        config=Path(args.config),
        mode=mode,
        use_config_default_runtime=not runtime_selected and not args.once and not args.real_readonly_smoke,
        once=bool(args.once or mode is RuntimeMode.SMOKE),
        real_readonly_smoke=bool(args.real_readonly_smoke or mode is RuntimeMode.SMOKE),
        evidence=Path(args.evidence) if args.evidence else None,
    )


def _sigterm_handler(_signum: int, _frame: object) -> None:
    """Convert Docker SIGTERM into KeyboardInterrupt so anyio/finally runs."""
    raise KeyboardInterrupt()


def run_dashboard_cli(settings: Settings) -> None:
    configure_logging(settings.app.log_level)

    # Dashboard mounts ./data read-only and can race host volume readiness.
    store = SQLiteStore(
        settings.storage.sqlite_path,
        connect_retries=10,
        retry_delay_sec=0.2,
    )
    runtime_health = FileRuntimeHealthReader(
        Path(settings.storage.state_dir) / "runtime_heartbeat.json",
        max_age_sec=settings.health.liveness.heartbeat_max_age_sec,
        max_readiness_miss_sec=settings.health.liveness.max_readiness_miss_sec,
    )
    app = create_dashboard_app(store, runtime_health)
    uvicorn.run(app, host=settings.dashboard.host, port=settings.dashboard.port)


async def _collect_readonly_smoke(request: ReadonlySmokeRequest) -> ReadonlySmokeEvidence:
    from polysignal_lab.app.readonly_smoke import collect_readonly_smoke

    return await collect_readonly_smoke(request)


def run_readonly_smoke(settings: Settings, options: CliOptions) -> None:
    configure_logging(settings.app.log_level)
    request = ReadonlySmokeRequest(
        settings=settings,
        config_path=options.config,
        evidence_path=options.evidence,
        base_dir=Path(".omo/evidence/readonly-smoke-runtime"),
    )
    evidence = anyio.run(_collect_readonly_smoke, request)
    status = "passed" if evidence["passed"] else f"completed with {evidence['failure_count']} degraded surface(s)"
    print(f"Bounded read-only smoke {status}")

def _resolve_runtime_mode(settings: Settings, options: CliOptions) -> RuntimeMode:
    _ = settings
    if options.use_config_default_runtime:
        return RuntimeMode.NAUTILUS
    return options.mode


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_cli(argv)
    settings = load_settings(options.config)
    settings.validate_runtime_environment()
    mode = _resolve_runtime_mode(settings, options)

    match mode:
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
        case RuntimeMode.SANDBOX | RuntimeMode.LIVE | RuntimeMode.BACKTEST:
            settings.runtime.nautilus.execution_mode = mode.value
            from polysignal_lab.nautilus_runtime.node import run_nautilus_cli

            run_nautilus_cli(settings)
            return 0
        case unreachable:
            assert_never(unreachable)


if __name__ == "__main__":
    raise SystemExit(main())
