#!/bin/bash
set -e

cd /app
export PYTHONPATH=src

case "${1:-scheduler}" in
  scheduler)
    echo "[entrypoint] Starting PolySignal Lab scheduler loop (real Polymarket data)..."
    exec python -m polysignal_lab.app.main --config config/signal_bot.yaml
    ;;
  demo)
    echo "[entrypoint] Running one-shot demo (fake data)..."
    exec python -m polysignal_lab.app.demo
    ;;
  dashboard)
    echo "[entrypoint] Starting PolySignal Lab dashboard..."
    exec python -m polysignal_lab.app.main --config config/signal_bot.yaml --dashboard
    ;;
  test)
    echo "[entrypoint] Running test suite..."
    pip install --no-cache-dir pytest pytest-asyncio 2>/dev/null
    exec python -m pytest tests/ -v
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    echo "Usage: $0 {scheduler|demo|dashboard|test|shell}"
    exit 1
    ;;
esac
