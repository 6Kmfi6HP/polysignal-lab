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
#
# issue69 终态恢复：state/ 是持久卷，被停止的旧进程会留下“上一代”heartbeat。
# 仅按 mtime 判断会让刚启动的新进程继承上一代的冻结年龄，在它写出第一份
# heartbeat 前就被 SIGKILL，形成确定性 kill-recycle loop（8/20 实测
# RestartCount 3→506、ExitCode=137）。因此每次 spawn 都会产生一个新的 boot
# generation（随机 boot_id，经 POLYSIGNAL_HEARTBEAT_BOOT_ID 传给子进程），
# Python writer 在 heartbeat payload 中记录 pid + boot_id。监督循环只把
# pid 与 boot_id 都匹配的文件视为“当前进程 heartbeat”；旧代文件、PID 复用
# 的 stale pidfile、无身份字段的 legacy 文件一律视为尚无当前代心跳，进入
# 有界 startup grace。超过 grace 仍无当前级 heartbeat 才判定启动即 wedged
# 并 SIGKILL；kill 前再经过滚动窗口限流（每窗口 ≤ N 次），保证任何根因下
# 都不会出现无界 kill-recycle。当前代 heartbeat 真正冻结（stale）时仍按原
# 阈值 SIGKILL，原有 wedged 检测能力保持不变。
_HEARTBEAT_KILL_AGE_SEC="${POLYSIGNAL_HEARTBEAT_KILL_AGE_SEC:-420}"
_HEARTBEAT_STARTUP_GRACE_SEC="${POLYSIGNAL_HEARTBEAT_STARTUP_GRACE_SEC:-300}"
_HEARTBEAT_POLL_SEC="${POLYSIGNAL_HEARTBEAT_POLL_SEC:-30}"
_HEARTBEAT_MAX_KILLS_PER_WINDOW="${POLYSIGNAL_HEARTBEAT_MAX_KILLS_PER_WINDOW:-3}"
_HEARTBEAT_KILL_WINDOW_SEC="${POLYSIGNAL_HEARTBEAT_KILL_WINDOW_SEC:-1800}"
_HEARTBEAT_KILL_HISTORY="state/.entrypoint_kill_history"

_heartbeat_file_generation() {
  # Echo "<pid> <boot_id>" declared by the heartbeat payload; exit 1 when the
  # file is missing or carries no identity fields (legacy payloads).
  [ -f state/runtime_heartbeat.json ] || return 1
  local pid boot_id
  pid="$(sed -n 's/.*"pid": *\([0-9][0-9]*\).*/\1/p' state/runtime_heartbeat.json | tail -n 1)"
  boot_id="$(sed -n 's/.*"boot_id": *"\([^"]*\)".*/\1/p' state/runtime_heartbeat.json | tail -n 1)"
  if [ -z "${pid}" ] || [ -z "${boot_id}" ]; then
    return 1
  fi
  printf '%s %s\n' "${pid}" "${boot_id}"
}

_heartbeat_belongs_to_current_process() {
  # 0 (true) iff the heartbeat payload was written by THIS spawn: pid and
  # boot_id must both match. A previous boot's file — or a stale pidfile whose
  # pid happens to be reused by the new process — never counts as the current
  # process's heartbeat.
  local expected_pid="$1" expected_boot_id="$2"
  [ "$(_heartbeat_file_generation)" = "${expected_pid} ${expected_boot_id}" ]
}

_heartbeat_kill_allowed() {
  # Rolling-window rate limit on SIGKILL across entrypoint invocations
  # (persisted in state/.entrypoint_kill_history). Once N kills land inside
  # the window the supervisor stops killing and leaves the container to the
  # healthcheck/operator instead of spinning forever. Entries older than the
  # window age out, so a genuinely recovered runtime can restart normally.
  # If the history file cannot be written (no state dir), fail open: the
  # heartbeat gate above still does the real supervision.
  local now cutoff ts
  local -a recent=()
  now="$(date +%s)"
  cutoff=$(( now - _HEARTBEAT_KILL_WINDOW_SEC ))
  if [ -f "${_HEARTBEAT_KILL_HISTORY}" ]; then
    while IFS= read -r ts; do
      case "${ts}" in
        ''|*[!0-9]*) continue ;;
      esac
      if [ "${ts}" -ge "${cutoff}" ]; then
        recent+=("${ts}")
      fi
    done < "${_HEARTBEAT_KILL_HISTORY}"
  fi
  if [ "${#recent[@]}" -ge "${_HEARTBEAT_MAX_KILLS_PER_WINDOW}" ]; then
    return 1
  fi
  recent+=("${now}")
  mkdir -p "$(dirname "${_HEARTBEAT_KILL_HISTORY}")" 2>/dev/null || true
  { printf '%s\n' "${recent[@]}"; } > "${_HEARTBEAT_KILL_HISTORY}" 2>/dev/null || return 0
  return 0
}

_run_nautilus_app() {
  # One boot generation per spawn: the child and the supervisor share the
  # boot_id, so only the child it actually started can ever look "current".
  # Re-generating on every entrypoint invocation also makes any heartbeat
  # left by an earlier container permanently foreign, and a leaked
  # POLYSIGNAL_HEARTBEAT_BOOT_ID in the environment is never inherited.
  local heartbeat_boot
  # Mint a fresh generation unconditionally: inheriting a value leaked into
  # the container environment (compose env, .env, operator export) would make
  # every restart reuse ONE generation, and together with kernel PID reuse a
  # previous boot's frozen heartbeat would age-kill the fresh process again.
  heartbeat_boot="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || printf 'boot-%s-%s' "$$" "$(date +%s%N)")"
  local app_pid spawned_at
  POLYSIGNAL_HEARTBEAT_BOOT_ID="${heartbeat_boot}" \
    python -m polysignal_lab.app.main --mode nautilus --config config/signal_bot.yaml &
  app_pid=$!
  spawned_at="$(date +%s)"
  echo "[entrypoint] nautilus app pid=${app_pid} heartbeat_boot_id=${heartbeat_boot}"
  trap 'kill -TERM "${app_pid}" 2>/dev/null; exit 0' TERM INT
  while kill -0 "${app_pid}" 2>/dev/null; do
    if _heartbeat_belongs_to_current_process "${app_pid}" "${heartbeat_boot}"; then
      # Current generation owns the heartbeat: the original mtime staleness
      # gate applies unchanged.
      local age=$(( $(date +%s) - $(stat -c %Y state/runtime_heartbeat.json) ))
      if [ "${age}" -gt "${_HEARTBEAT_KILL_AGE_SEC}" ]; then
        if _heartbeat_kill_allowed; then
          echo "[entrypoint] heartbeat frozen ${age}s (>${_HEARTBEAT_KILL_AGE_SEC}s) - SIGKILL wedged app"
          kill -9 "${app_pid}"
          break
        fi
        echo "[entrypoint] heartbeat frozen ${age}s but SIGKILL suppressed by kill rate guard - leaving app to healthcheck"
      fi
    else
      # Old-generation / legacy / missing heartbeat: the new process gets a
      # bounded startup grace to produce its FIRST current-generation
      # heartbeat. Only after grace may a boot that never wrote one be
      # considered wedged and killed — never on an old file's mtime.
      local elapsed=$(( $(date +%s) - spawned_at ))
      if [ "${_HEARTBEAT_STARTUP_GRACE_SEC}" -gt 0 ] && [ "${elapsed}" -gt "${_HEARTBEAT_STARTUP_GRACE_SEC}" ]; then
        if _heartbeat_kill_allowed; then
          echo "[entrypoint] no current-generation heartbeat after ${elapsed}s (>${_HEARTBEAT_STARTUP_GRACE_SEC}s grace) - SIGKILL wedged app"
          kill -9 "${app_pid}"
          break
        fi
        echo "[entrypoint] no current-generation heartbeat after ${elapsed}s but SIGKILL suppressed by kill guard - leaving app to healthcheck"
      fi
    fi
    sleep "${_HEARTBEAT_POLL_SEC}"
  done
  wait "${app_pid}"
  exit $?
}

# Sourcing guard: tests import this script (POLYSIGNAL_ENTRYPOINT_SOURCED=1)
# to drive the supervision helpers directly; in the container it always runs.
if [ "${POLYSIGNAL_ENTRYPOINT_SOURCED:-}" != "1" ]; then
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
fi
