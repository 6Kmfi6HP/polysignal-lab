#!/bin/bash
set -e

cd "${APP_DIR:-/app}"
export PYTHONPATH=src

# Map entrypoint command → runtime.nautilus.execution_mode via Settings env overrides.
# POLYSIGNAL_LAB__SECTION__KEY is applied in Settings.from_yaml after YAML load.
_set_execution_mode() {
  export POLYSIGNAL_LAB__RUNTIME__NAUTILUS__EXECUTION_MODE="$1"
}

case "${1:-nautilus}" in
  scheduler)
    echo "[entrypoint] scheduler execution mode is retired; use nautilus"
    exit 2
    ;;
  nautilus|sandbox)
    echo "[entrypoint] Starting PolySignal Lab Nautilus sandbox runtime..."
    _set_execution_mode sandbox
    exec python -m polysignal_lab.app.main --mode nautilus --config config/signal_bot.yaml
    ;;
  live)
    echo "[entrypoint] Starting PolySignal Lab Nautilus LIVE runtime (explicit unlocks required)..."
    _set_execution_mode live
    exec python -m polysignal_lab.app.main --mode nautilus --config config/signal_bot.yaml
    ;;
  backtest)
    echo "[entrypoint] Starting PolySignal Lab Nautilus backtest runtime..."
    _set_execution_mode backtest
    exec python -m polysignal_lab.app.main --mode nautilus --config config/signal_bot.yaml
    ;;
  dashboard)
    echo "[entrypoint] Starting PolySignal Lab dashboard..."
    exec python -m polysignal_lab.app.main --mode dashboard --config config/signal_bot.yaml
    ;;
  test)
    echo "[entrypoint] Running test suite..."
    exec python -m pytest tests/ -q
    ;;
  smoke)
    echo "[entrypoint] Running bounded read-only smoke..."
    exec python -m polysignal_lab.app.main --mode smoke --config config/signal_bot.yaml "${@:2}"
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    echo "Usage: $0 {nautilus|sandbox|live|backtest|dashboard|test|shell|smoke}"
    exit 1
    ;;
esac
