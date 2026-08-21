from __future__ import annotations

import json
import os
import re
from pathlib import Path
import subprocess
import time


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


# ---------------------------------------------------------------------------
# issue69 entrypoint stale-heartbeat recovery
#
# Regression scope: `state/` is a persistent volume, so a stopped process
# leaves a heartbeat file behind. The old supervisor judged staleness purely
# by file mtime, so a freshly started process inherited the previous boot's
# frozen age and was SIGKILLed before it could write its first heartbeat —
# `restart: unless-stopped` then respawned it and the loop repeated
# (RestartCount 3 -> 506, ExitCode=137 on 2026-08-20).
#
# Fix contract under test here:
#   * every app spawn carries a fresh boot generation (random boot_id passed
#     via POLYSIGNAL_HEARTBEAT_BOOT_ID) and heartbeat payloads record
#     pid + boot_id;
#   * the supervisor only treats a heartbeat whose pid AND boot_id both match
#     the process it spawned as "current";
#   * a process gets a bounded startup grace to produce its first
#     current-generation heartbeat before any kill can be considered;
#   * a truly wedged current-generation heartbeat still SIGKILLs after the
#     stale threshold;
#   * SIGKILL is additionally rate-limited per rolling window so no root
#     cause can produce an unbounded kill-recycle loop.
# Tests are deterministic: thresholds are injected via env and the app is a
# fake "python" on PATH, so no real nautilus runtime runs and no long sleeps
# are used.
# ---------------------------------------------------------------------------

FAKE_PYTHON_SOURCE = r"""#!/bin/bash
# Test double for `python -m polysignal_lab.app.main ...` under the entrypoint
# supervisor. Emulates the runtime heartbeat contract: writes
# state/runtime_heartbeat.json with THIS process's pid and the boot id the
# entrypoint exported, optionally with a delayed first write, a freeze after
# N beats, a lifetime limit, or no writes at all.
set -u
mode="${FAKE_APP_MODE:-write}"
hb="state/runtime_heartbeat.json"
mkdir -p "$(dirname "${hb}")"
if [ "${mode}" = "never-writes" ]; then
  # exec: the process itself is replaced, so a SIGKILL from the supervisor
  # leaves no orphaned child holding inherited stdout/stderr pipes open.
  exec sleep 3600
fi
if [ -n "${FAKE_APP_FIRST_DELAY:-}" ]; then
  sleep "${FAKE_APP_FIRST_DELAY}"
fi
beat=0
while :; do
  boot="${FAKE_APP_BOOT_ID_OVERRIDE:-${POLYSIGNAL_HEARTBEAT_BOOT_ID:-}}"
  printf '{"boot_id":"%s","pid":%s,"updated_at":"%s","phase":"fake"}\n' \
    "${boot}" "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${hb}"
  beat=$(( beat + 1 ))
  if [ -n "${FAKE_APP_FREEZE_AFTER:-}" ] && [ "${beat}" -ge "${FAKE_APP_FREEZE_AFTER}" ]; then
    exec sleep 3600
  fi
  if [ -n "${FAKE_APP_MAX_BEATS:-}" ] && [ "${beat}" -ge "${FAKE_APP_MAX_BEATS}" ]; then
    exit "${FAKE_APP_EXIT_CODE:-0}"
  fi
  sleep "${FAKE_APP_BEAT_INTERVAL:-0.15}"
done
"""


def _entrypoint() -> Path:
    return Path(__file__).parents[1] / "docker-entrypoint.sh"


def _write_fake_python(workdir: Path) -> Path:
    bin_dir = workdir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "python"
    fake.write_text(FAKE_PYTHON_SOURCE, encoding="utf-8")
    fake.chmod(0o755)
    return fake


def _base_env(workdir: Path) -> dict[str, str]:
    return {
        "APP_DIR": str(workdir),
        "POLYSIGNAL_ENTRYPOINT_SOURCED": "1",
        "PATH": f"{workdir / 'bin'}:{os.environ['PATH']}",
        "POLYSIGNAL_HEARTBEAT_POLL_SEC": "0.15",
    }


def _run_supervisor(
    workdir: Path,
    *,
    extra_env: dict[str, str],
    timeout: float = 20.0,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(_base_env(workdir))
    env.update(extra_env)
    return subprocess.run(
        ["bash", "-c", f"source '{_entrypoint()}' && _run_nautilus_app"],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _seed_foreign_heartbeat(
    workdir: Path,
    *,
    pid: int = 424242,
    boot_id: str = "pre-upgrade-boot",
    age_sec: int = 500,
) -> Path:
    """A previous boot's heartbeat: foreign generation, mtime frozen long ago."""
    heartbeat = workdir / "state" / "runtime_heartbeat.json"
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    heartbeat.write_text(
        json.dumps(
            {
                "updated_at": "2026-08-20T03:03:41+00:00",
                "phase": "running",
                "fatal": False,
                "fatal_reason": None,
                "last_data_at": None,
                "readiness_miss_started_at_by_key": {},
                "readiness_detail_by_key": {},
                "pid": pid,
                "boot_id": boot_id,
            }
        ),
        encoding="utf-8",
    )
    frozen = time.time() - age_sec
    os.utime(heartbeat, (frozen, frozen))
    return heartbeat


def _supervisor_boot_id(stdout: str) -> str:
    match = re.search(r"heartbeat_boot_id=(\S+)", stdout)
    assert match is not None, f"no heartbeat_boot_id in supervisor output: {stdout}"
    return match.group(1)


def _read_heartbeat(workdir: Path) -> dict[str, object]:
    return json.loads(
        (workdir / "state" / "runtime_heartbeat.json").read_text(encoding="utf-8")
    )


def test_entrypoint_gates_staleness_on_current_generation() -> None:
    """Static contract: the supervisor must not age-kill on a foreign file."""
    source = _script()
    assert "POLYSIGNAL_HEARTBEAT_BOOT_ID" in source
    assert "_heartbeat_belongs_to_current_process" in source
    assert "POLYSIGNAL_HEARTBEAT_STARTUP_GRACE_SEC" in source
    assert "no current-generation heartbeat" in source
    assert "SIGKILL suppressed" in source
    assert "POLYSIGNAL_HEARTBEAT_MAX_KILLS_PER_WINDOW" in source
    assert ".entrypoint_kill_history" in source


def test_entrypoint_decision_requires_pid_and_boot_id_match(tmp_path: Path) -> None:
    """The ownership predicate is the core of the fix: pid alone (e.g. after
    kernel PID reuse) or boot_id alone must never count as current."""
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    heartbeat = state / "runtime_heartbeat.json"

    def belongs(payload: str | None, pid: str, boot_id: str) -> bool:
        if payload is None:
            heartbeat.unlink(missing_ok=True)
        else:
            heartbeat.write_text(payload, encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "APP_DIR": str(tmp_path),
                "POLYSIGNAL_ENTRYPOINT_SOURCED": "1",
            }
        )
        result = subprocess.run(
            [
                "bash",
                "-c",
                "source '%s' && _heartbeat_belongs_to_current_process '%s' '%s'"
                % (_entrypoint(), pid, boot_id),
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    own = '{"pid": 321, "boot_id": "boot-A", "phase": "running"}'
    assert belongs(own, "321", "boot-A") is True
    # PID reuse: same pid, foreign boot generation -> NOT current.
    assert belongs(own, "321", "boot-B") is False
    # Same boot id cannot be claimed by another pid.
    assert belongs(own, "999", "boot-A") is False
    # pid-only (foreign/legacy) payload -> NOT current.
    assert belongs('{"pid": 321, "boot_id": null}', "321", "boot-A") is False
    # Legacy payload without identity fields -> NOT current.
    assert (
        belongs(
            '{"updated_at": "2026-08-20T03:03:41+00:00", "phase": "running"}',
            "321",
            "boot-A",
        )
        is False
    )
    # Missing file -> NOT current.
    assert belongs(None, "321", "boot-A") is False


def test_entrypoint_kill_rate_guard_caps_sigkills(tmp_path: Path) -> None:
    """Rolling-window guard: at most N kills per window; window decays."""
    env = os.environ.copy()
    env.update(
        {
            "APP_DIR": str(tmp_path),
            "POLYSIGNAL_ENTRYPOINT_SOURCED": "1",
            "POLYSIGNAL_HEARTBEAT_MAX_KILLS_PER_WINDOW": "2",
            "POLYSIGNAL_HEARTBEAT_KILL_WINDOW_SEC": "100",
        }
    )
    script = (
        f"source '{_entrypoint()}' && "
        "_heartbeat_kill_allowed && _heartbeat_kill_allowed"
    )
    allowed = subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert allowed.returncode == 0
    denied = subprocess.run(
        ["bash", "-c", f"source '{_entrypoint()}' && _heartbeat_kill_allowed"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert denied.returncode == 1
    history = tmp_path / "state" / ".entrypoint_kill_history"
    assert history.exists()
    lines = [line for line in history.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 2


def test_old_stale_heartbeat_does_not_instant_kill_recovering_app(
    tmp_path: Path,
) -> None:
    """Requirement 1: an age >420s heartbeat from the previous boot must not
    SIGKILL the new process before its first current-generation heartbeat."""
    _write_fake_python(tmp_path)
    _seed_foreign_heartbeat(tmp_path, age_sec=500)
    started = time.monotonic()
    result = _run_supervisor(
        tmp_path,
        extra_env={
            "POLYSIGNAL_HEARTBEAT_KILL_AGE_SEC": "6",
            "POLYSIGNAL_HEARTBEAT_STARTUP_GRACE_SEC": "60",
            "POLYSIGNAL_HEARTBEAT_KILL_WINDOW_SEC": "60",
            "FAKE_APP_FIRST_DELAY": "1.0",
            "FAKE_APP_MAX_BEATS": "12",
            "FAKE_APP_BEAT_INTERVAL": "0.10",
        },
        timeout=20.0,
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SIGKILL" not in result.stdout
    assert elapsed >= 1.5, f"app was recycled too early: {elapsed:.2f}s"
    # The app's own heartbeat now claims the CURRENT boot generation.
    boot_id = _supervisor_boot_id(result.stdout)
    heartbeat = _read_heartbeat(tmp_path)
    assert heartbeat["boot_id"] == boot_id
    assert heartbeat["pid"] is not None
    assert (tmp_path / "state" / ".entrypoint_kill_history").exists() is False


def test_old_stale_heartbeat_never_pollutes_three_restart_rounds(
    tmp_path: Path,
) -> None:
    """Requirements 3+4: a persistent old-generation heartbeat must not
    contaminate repeated restarts; three healthy rounds recover every time."""
    for _round in range(3):
        _write_fake_python(tmp_path)
        _seed_foreign_heartbeat(tmp_path, age_sec=500)
        started = time.monotonic()
        result = _run_supervisor(
            tmp_path,
            extra_env={
                "POLYSIGNAL_HEARTBEAT_KILL_AGE_SEC": "6",
                "POLYSIGNAL_HEARTBEAT_STARTUP_GRACE_SEC": "60",
                "FAKE_APP_FIRST_DELAY": "0.3",
                "FAKE_APP_MAX_BEATS": "10",
                "FAKE_APP_BEAT_INTERVAL": "0.10",
            },
            timeout=20.0,
        )
        elapsed = time.monotonic() - started
        assert result.returncode == 0, result.stdout + result.stderr
        assert "SIGKILL" not in result.stdout
        assert elapsed >= 0.8
    assert (tmp_path / "state" / ".entrypoint_kill_history").exists() is False


def test_current_generation_stale_heartbeat_still_sigkills(tmp_path: Path) -> None:
    """Requirements 2+5: after the app owns the heartbeat and it freezes
    (wedged process), the original stale-age SIGKILL still fires."""
    _write_fake_python(tmp_path)
    started = time.monotonic()
    result = _run_supervisor(
        tmp_path,
        extra_env={
            "POLYSIGNAL_HEARTBEAT_KILL_AGE_SEC": "2",
            "POLYSIGNAL_HEARTBEAT_STARTUP_GRACE_SEC": "60",
            "FAKE_APP_MODE": "write",
            "FAKE_APP_FREEZE_AFTER": "3",
            "FAKE_APP_BEAT_INTERVAL": "0.10",
        },
        timeout=20.0,
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 137, result.stdout + result.stderr
    assert "heartbeat frozen" in result.stdout
    assert elapsed >= 1.0
    boot_id = _supervisor_boot_id(result.stdout)
    heartbeat = _read_heartbeat(tmp_path)
    assert heartbeat["boot_id"] == boot_id  # evidence stays from the killed gen


def test_boot_with_no_current_heartbeat_killed_only_after_bounded_grace(
    tmp_path: Path,
) -> None:
    """A boot that never writes a heartbeat is wedged-at-boot: it must NOT be
    killed on the old file's mtime, but must be killed after a bounded grace."""
    _write_fake_python(tmp_path)
    _seed_foreign_heartbeat(tmp_path, age_sec=500)
    started = time.monotonic()
    result = _run_supervisor(
        tmp_path,
        extra_env={
            "POLYSIGNAL_HEARTBEAT_KILL_AGE_SEC": "1",
            "POLYSIGNAL_HEARTBEAT_STARTUP_GRACE_SEC": "2",
            "FAKE_APP_MODE": "never-writes",
        },
        timeout=20.0,
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 137, result.stdout + result.stderr
    assert "no current-generation heartbeat" in result.stdout
    # Not an instant recycle: the app lived through the full bounded grace.
    assert elapsed >= 1.5, f"killed before grace: {elapsed:.2f}s"


def test_kill_rate_guard_breaks_deterministic_restart_loop(tmp_path: Path) -> None:
    """Requirement 4: repeated wedged boots must not SIGKILL forever; after
    N kills in the rolling window the supervisor holds off."""
    _write_fake_python(tmp_path)
    env = {
        "POLYSIGNAL_HEARTBEAT_KILL_AGE_SEC": "1",
        "POLYSIGNAL_HEARTBEAT_STARTUP_GRACE_SEC": "1",
        "POLYSIGNAL_HEARTBEAT_MAX_KILLS_PER_WINDOW": "2",
        "POLYSIGNAL_HEARTBEAT_KILL_WINDOW_SEC": "6",
        "FAKE_APP_MODE": "never-writes",
    }
    first = _run_supervisor(tmp_path, extra_env=env, timeout=20.0)
    assert first.returncode == 137, first.stdout + first.stderr
    second = _run_supervisor(tmp_path, extra_env=env, timeout=20.0)
    assert second.returncode == 137, second.stdout + second.stderr
    history = tmp_path / "state" / ".entrypoint_kill_history"
    assert len(history.read_text(encoding="utf-8").splitlines()) == 2

    # Round 3: the guard is open -> the supervisor must NOT kill.
    third_env = os.environ.copy()
    third_env.update(_base_env(tmp_path))
    third_env.update(env)
    third = subprocess.Popen(
        ["bash", "-c", f"source '{_entrypoint()}' && _run_nautilus_app"],
        cwd=tmp_path,
        env=third_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        time.sleep(3.0)
        assert third.poll() is None, "supervisor died instead of holding off"
    finally:
        third.terminate()
        third.wait(timeout=10.0)
    output = ""
    if third.stdout is not None:
        output = third.stdout.read()
    assert third.returncode == 0, output
    assert "SIGKILL suppressed" in output
    assert len(history.read_text(encoding="utf-8").splitlines()) == 2


def test_supervisor_mints_fresh_generation_despite_leaked_boot_env(
    tmp_path: Path,
) -> None:
    """Requirement 1: every spawn gets a NEW boot generation. A
    POLYSIGNAL_HEARTBEAT_BOOT_ID that leaks into the container environment
    (compose env/.env/operator export) must never be inherited: a reused
    generation plus kernel PID reuse is exactly the combination that lets a
    previous boot's frozen heartbeat age-kill the fresh process."""
    _write_fake_python(tmp_path)
    _seed_foreign_heartbeat(
        tmp_path,
        boot_id="leaked-boot-id",
        age_sec=500,
    )
    result = _run_supervisor(
        tmp_path,
        extra_env={
            "POLYSIGNAL_HEARTBEAT_BOOT_ID": "leaked-boot-id",
            "POLYSIGNAL_HEARTBEAT_KILL_AGE_SEC": "2",
            "POLYSIGNAL_HEARTBEAT_STARTUP_GRACE_SEC": "60",
            "FAKE_APP_FIRST_DELAY": "0.4",
            "FAKE_APP_MAX_BEATS": "10",
            "FAKE_APP_BEAT_INTERVAL": "0.10",
        },
        timeout=20.0,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SIGKILL" not in result.stdout
    boot_id = _supervisor_boot_id(result.stdout)
    assert boot_id != "leaked-boot-id", "supervisor reused a leaked generation"
    # The app's payload is attributed to the freshly minted generation.
    heartbeat = _read_heartbeat(tmp_path)
    assert heartbeat["boot_id"] == boot_id


def test_app_normal_exit_propagates_exit_code(tmp_path: Path) -> None:
    """Requirement 4 (no regression): a supervised app that exits on its own
    is never SIGKILLed, and the supervisor exits with the app's own code so
    `restart: unless-stopped` sees the real status."""
    _write_fake_python(tmp_path)
    _seed_foreign_heartbeat(tmp_path, age_sec=500)
    started = time.monotonic()
    result = _run_supervisor(
        tmp_path,
        extra_env={
            "POLYSIGNAL_HEARTBEAT_KILL_AGE_SEC": "2",
            "POLYSIGNAL_HEARTBEAT_STARTUP_GRACE_SEC": "60",
            "FAKE_APP_FIRST_DELAY": "0.3",
            "FAKE_APP_MAX_BEATS": "4",
            "FAKE_APP_BEAT_INTERVAL": "0.10",
            "FAKE_APP_EXIT_CODE": "7",
        },
        timeout=20.0,
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 7, result.stdout + result.stderr
    assert "SIGKILL" not in result.stdout
    assert elapsed < 5.0, f"supervisor hung after app exit: {elapsed:.2f}s"
