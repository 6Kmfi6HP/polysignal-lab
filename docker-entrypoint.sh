#!/bin/bash
set -e

cd "${APP_DIR:-/app}"
export PYTHONPATH=src

case "${1:-scheduler}" in
  scheduler)
    echo "[entrypoint] Starting PolySignal Lab scheduler loop (real Polymarket data)..."
    exec python -m polysignal_lab.app.main --mode scheduler --config config/signal_bot.yaml
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
    echo "Usage: $0 {scheduler|dashboard|test|shell|smoke}"
    exit 1
    ;;
esac
