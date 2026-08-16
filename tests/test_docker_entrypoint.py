from pathlib import Path


def _script() -> str:
    return Path("docker-entrypoint.sh").read_text(encoding="utf-8")


def test_entrypoint_defaults_to_nautilus() -> None:
    source = _script()
    assert 'case "${1:-nautilus}" in' in source
    assert "--mode nautilus" in source


def test_dockerfile_defaults_to_nautilus() -> None:
    source = Path("Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["nautilus"]' in source
    assert 'CMD ["scheduler"]' not in source


def test_entrypoint_retires_scheduler_execution_mode() -> None:
    source = _script()
    scheduler = source.split("scheduler)", 1)[1].split(";;", 1)[0]
    assert "retired" in scheduler.lower()
    assert "python -m polysignal_lab.app.main" not in scheduler
    assert "exit 2" in scheduler
    assert (
        "Usage: $0 {nautilus|sandbox|live|backtest|dashboard|test|shell|smoke|maintenance}"
        in source
    )


def test_entrypoint_wires_execution_mode_env_overrides() -> None:
    """docker {sandbox|live|backtest} must select runtime.nautilus.execution_mode."""
    source = _script()
    assert "POLYSIGNAL_LAB__RUNTIME__NAUTILUS__EXECUTION_MODE" in source
    assert "_set_execution_mode sandbox" in source
    assert "_set_execution_mode live" in source
    assert "_set_execution_mode backtest" in source

    live = source.split("live)", 1)[1].split(";;", 1)[0]
    assert "_set_execution_mode live" in live
    assert "ALLOW_LIVE_POLYMARKET_EXECUTION" not in live
    assert "ALLOW_LIVE_MARKET_ACTIONS" not in live

    backtest = source.split("backtest)", 1)[1].split(";;", 1)[0]
    assert "_set_execution_mode backtest" in backtest
    assert "ALLOW_LIVE_POLYMARKET_EXECUTION" not in backtest


def test_entrypoint_supervises_nautilus_app_from_outside_python() -> None:
    """PyO3 run() can hold the GIL indefinitely with no data arriving, which
    starves every Python thread (watchdog and the SIGKILL fallback alike).
    The entrypoint must supervise the heartbeat file mtime from bash — no GIL
    involved — and SIGKILL a wedged app so `restart: unless-stopped` closes
    the supervision loop."""
    source = _script()
    assert "_run_nautilus_app" in source
    assert "state/runtime_heartbeat.json" in source
    assert "stat -c %Y" in source
    assert "kill -9" in source
    assert "POLYSIGNAL_HEARTBEAT_KILL_AGE_SEC" in source

    live = source.split("live)", 1)[1].split(";;", 1)[0]
    assert "exec python" not in live
    assert "_run_nautilus_app" in live

    backtest = source.split("backtest)", 1)[1].split(";;", 1)[0]
    assert "exec python" in backtest  # offline mode stays simple


def test_entrypoint_runs_retention_maintenance() -> None:
    source = _script()
    maintenance = source.split("maintenance)", 1)[1].split(";;", 1)[0]

    assert "python -m scripts.retention_maintenance" in maintenance
    assert "--config config/signal_bot.yaml" in maintenance
    assert '"${@:2}"' in maintenance
