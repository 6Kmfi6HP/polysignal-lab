"""Safe stub for the Nautilus runtime CLI entry point.

This module is the platform boundary between the default paper-safe PolySignal
runtime and the optional Nautilus engine. It deliberately contains NO live
Polymarket execution classes, NO execution-client registries, NO credential
environment variable names, and NO allowance/API-key helper script references,
so the default source tree never gains a live-execution surface.

Task 13 replaces this stub with the real Nautilus node wiring. Until then
calling ``run_nautilus_cli`` raises a clear ``RuntimeError``.
"""
from __future__ import annotations

from polysignal_lab.config import Settings, load_settings


def run_nautilus_cli(settings: Settings | None = None) -> None:
    """Entry point for the ``nautilus`` CLI mode.

    Loads settings when called without arguments (e.g. from the
    ``polysignal-nautilus`` script), then raises because the Nautilus runtime
    is not wired yet. Real implementation lands in Task 13.
    """
    if settings is None:
        settings = load_settings()
    raise RuntimeError("Nautilus runtime is not wired yet")


def main() -> int:
    """``polysignal-nautilus`` script entry point."""
    try:
        run_nautilus_cli()
    except RuntimeError as exc:
        print(f"nautilus: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
