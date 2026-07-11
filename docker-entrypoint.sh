#!/bin/bash
set -e

cd "${APP_DIR:-/app}"
export PYTHONPATH=src

case "${1:-nautilus}" in
  scheduler)
    echo "[entrypoint] scheduler execution mode is retired; use nautilus"
    exit 2
    ;;
  nautilus)
    echo "[entrypoint] Starting PolySignal Lab on Nautilus runtime..."
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
    echo "Usage: $0 {nautilus|dashboard|test|shell|smoke}"
    exit 1
    ;;
esac
