#!/bin/bash
set -e

cd "${APP_DIR:-/app}"
export PYTHONPATH=src

# Map entrypoint command → runtime.nautilus.execution_mode via Settings env overrides.
# POLYSIGNAL_LAB__SECTION__KEY is applied in Settings.from_yaml after YAML load.
_set_execution_mode() {
  export POLYSIGNAL_LAB__RUNTIME__NAUTILUS__EXECUTION_MODE="$1"
}

# 进程外监督（nautilus/sandbox/live）：
# PyO3 run() 在数据停滞时可能长期占用 GIL（它的 with_gil 主循环从不交还），
# watchdog 线程与 Python 兜底线程随之饿死，SIGINT 停止意图永不执行——实测
# 表现为容器卡 unhealthy 数十秒到数分钟才响应重启。bash 定期读 heartbeat
# 文件的 mtime（不依赖 GIL），冻结超过阈值即 SIGKILL 并退出，让 compose 的
# `restart: unless-stopped` 完成有界监督重启。数据流动期 heartbeat 持续
# 更新，本路径永不触发。
_HEARTBEAT_KILL_AGE_SEC="${POLYSIGNAL_HEARTBEAT_KILL_AGE_SEC:-420}"
_HEARTBEAT_POLL_SEC=30

_run_nautilus_app() {
  python -m polysignal_lab.app.main --mode nautilus --config config/signal_bot.yaml &
  local app_pid=$!
  echo "[entrypoint] nautilus app pid=${app_pid}"
  trap 'kill -TERM "${app_pid}" 2>/dev/null; exit 0' TERM INT
  while kill -0 "${app_pid}" 2>/dev/null; do
    if [ -f state/runtime_heartbeat.json ]; then
      local age=$(( $(date +%s) - $(stat -c %Y state/runtime_heartbeat.json) ))
      if [ "${age}" -gt "${_HEARTBEAT_KILL_AGE_SEC}" ]; then
        echo "[entrypoint] heartbeat frozen ${age}s (>${_HEARTBEAT_KILL_AGE_SEC}s) - SIGKILL wedged app"
        kill -9 "${app_pid}"
        break
      fi
    fi
    sleep "${_HEARTBEAT_POLL_SEC}"
  done
  wait "${app_pid}"
  exit $?
}

case "${1:-nautilus}" in
  scheduler)
    echo "[entrypoint] scheduler execution mode is retired; use nautilus"
    exit 2
    ;;
  nautilus|sandbox)
    echo "[entrypoint] Starting PolySignal Lab Nautilus sandbox runtime..."
    _set_execution_mode sandbox
    _run_nautilus_app
    ;;
  live)
    echo "[entrypoint] Starting PolySignal Lab Nautilus LIVE runtime (explicit unlocks required)..."
    _set_execution_mode live
    _run_nautilus_app
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
  maintenance)
    echo "[entrypoint] Running data retention maintenance..."
    exec python -m scripts.retention_maintenance --config config/signal_bot.yaml "${@:2}"
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    echo "Usage: $0 {nautilus|sandbox|live|backtest|dashboard|test|shell|smoke|maintenance}"
    exit 1
    ;;
esac
