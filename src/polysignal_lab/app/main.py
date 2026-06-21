"""PolySignal Lab main entry point."""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys

import uvicorn

from polysignal_lab.app.scheduler import PolySignalScheduler, run_scheduler
from polysignal_lab.config import load_settings
from polysignal_lab.dashboard.app import create_dashboard_app
from polysignal_lab.observability.logger import configure_logging
from polysignal_lab.storage.sqlite_store import SQLiteStore


def run_scheduler_cli(settings):
    """Run the scheduler loop with graceful shutdown."""
    configure_logging(settings.app.log_level)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    scheduler = PolySignalScheduler(settings)
    
    # Handle graceful shutdown
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(scheduler.stop()))
    
    try:
        loop.run_until_complete(scheduler.run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(scheduler.stop())
        loop.close()


def run_dashboard_cli(settings):
    """Run the dashboard server."""
    configure_logging(settings.app.log_level)
    store = SQLiteStore(settings.storage.sqlite_path)
    app = create_dashboard_app(store)
    uvicorn.run(app, host=settings.dashboard.host, port=settings.dashboard.port)


def main() -> None:
    parser = argparse.ArgumentParser(description="PolySignal Lab")
    parser.add_argument("--config", default="config/signal_bot.yaml")
    parser.add_argument("--dashboard", action="store_true")
    args = parser.parse_args()
    
    settings = load_settings(args.config)
    settings.validate_runtime_environment()
    
    if args.dashboard:
        run_dashboard_cli(settings)
    else:
        run_scheduler_cli(settings)


if __name__ == "__main__":
    main()
