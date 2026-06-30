# Container Healthcheck Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current SQLite-only Docker healthcheck with conservative runtime liveness, while preserving business readiness and adding a non-aggressive restart recommendation gate.

**Architecture:** Add a small stdlib-only runtime health module that owns heartbeat file I/O, liveness evaluation, and restart-gate evaluation. Add a `python -m polysignal_lab.healthcheck liveness` CLI for Docker, wire Nautilus runtime to maintain the heartbeat, and update compose/config to use the liveness probe with a longer startup window.

**Tech Stack:** Python 3.11+, Pydantic v2 settings, stdlib `json`/`threading`/`datetime`/`pathlib`, pytest, Docker Compose healthcheck.

## Global Constraints

- Docker healthcheck must not treat short external API/data-feed degradation as container death.
- Liveness failure is limited to fatal runtime state, stale/missing heartbeat after grace, unreadable/corrupt probe state, or unavailable probe code.
- Readiness continues to use existing `HealthRegistry` and `ok | degraded | down` semantics.
- Restart gate is recommendation-only by default; Docker healthcheck must not consume it unless explicitly configured.
- Default values: `startup_grace_sec=180`, `heartbeat_max_age_sec=120`, `critical_down_sec=300`, `min_consecutive_failures=5`, `docker_healthcheck_fails_on_restart_recommended=false`.
- Do not add dependencies.
- Do not change strategy logic, market discovery, Telegram publishing, PTB/anchor logic, or Nautilus trading semantics.
- Keep implementation minimal and focused; no Prometheus/Grafana, no dashboard UI rebuild, no automatic infinite restart loop.

---

## File Structure

- Create `src/polysignal_lab/observability/runtime_health.py`
  - Owns `RuntimeHeartbeat`, `LivenessResult`, `RestartGateResult`, heartbeat read/write helpers, liveness evaluation, and restart-gate evaluation. It must not contain a blind background heartbeat loop that can keep liveness fresh while Nautilus is wedged.
- Create `src/polysignal_lab/healthcheck.py`
  - Module CLI used by Docker: `python -m polysignal_lab.healthcheck liveness --config config/signal_bot.yaml`.
- Modify `src/polysignal_lab/config.py`
  - Adds `HealthConfig`, `HealthLivenessConfig`, `HealthRestartGateConfig`, and `Settings.health`.
- Modify `src/polysignal_lab/nautilus_runtime/node.py`
  - Provides heartbeat path/progress callback wiring and records fatal heartbeat before raising on unexpected `TradingNode.run()` return.
- Modify `config/signal_bot.yaml`
  - Declares the health defaults explicitly for production readability.
- Modify `docker-compose.yml`
  - Replaces SQLite-only healthcheck with the liveness CLI and increases `start_period`.
- Test `tests/test_healthcheck.py`
  - Pure liveness, CLI, config, and restart-gate coverage.
- Modify `tests/test_nautilus_node.py`
  - Verifies Nautilus CLI writes heartbeat and records fatal state on unexpected node return.

---

### Task 1: Health configuration models

**Files:**
- Modify: `src/polysignal_lab/config.py`
- Modify: `tests/test_nautilus_runtime_config.py`
- Modify: `config/signal_bot.yaml`

**Interfaces:**
- Produces: `Settings.health: HealthConfig`
- Produces: `HealthConfig.startup_grace_sec: int`
- Produces: `HealthConfig.liveness.heartbeat_max_age_sec: int`
- Produces: `HealthConfig.restart_gate.enabled: bool`
- Produces: `HealthConfig.restart_gate.critical_components: tuple[str, ...]`
- Produces: `HealthConfig.restart_gate.critical_down_sec: int`
- Produces: `HealthConfig.restart_gate.min_consecutive_failures: int`
- Produces: `HealthConfig.restart_gate.docker_healthcheck_fails_on_restart_recommended: bool`

- [ ] **Step 1: Write failing config default test**

Add to `tests/test_nautilus_runtime_config.py`:

```python
def test_health_config_defaults_are_conservative() -> None:
    settings = Settings()

    assert settings.health.startup_grace_sec == 180
    assert settings.health.liveness.heartbeat_max_age_sec == 120
    assert settings.health.restart_gate.enabled is True
    assert settings.health.restart_gate.critical_components == (
        "runtime",
        "scheduler",
        "sqlite",
    )
    assert settings.health.restart_gate.critical_down_sec == 300
    assert settings.health.restart_gate.min_consecutive_failures == 5
    assert (
        settings.health.restart_gate.docker_healthcheck_fails_on_restart_recommended
        is False
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/pytest tests/test_nautilus_runtime_config.py::test_health_config_defaults_are_conservative -q
```

Expected: FAIL with `AttributeError` or Pydantic validation error because `Settings.health` does not exist.

- [ ] **Step 3: Add config models**

In `src/polysignal_lab/config.py`, insert after `DashboardConfig`:

```python
class HealthLivenessConfig(BaseModel):
    heartbeat_max_age_sec: int = 120


class HealthRestartGateConfig(BaseModel):
    enabled: bool = True
    critical_components: tuple[str, ...] = ("runtime", "scheduler", "sqlite")
    critical_down_sec: int = 300
    min_consecutive_failures: int = 5
    docker_healthcheck_fails_on_restart_recommended: bool = False


class HealthConfig(BaseModel):
    startup_grace_sec: int = 180
    liveness: HealthLivenessConfig = Field(default_factory=HealthLivenessConfig)
    restart_gate: HealthRestartGateConfig = Field(default_factory=HealthRestartGateConfig)
```

Then add to `Settings` after `dashboard`:

```python
    health: HealthConfig = Field(default_factory=HealthConfig)
```

- [ ] **Step 4: Add YAML override test**

Add to `tests/test_nautilus_runtime_config.py`:

```python
def test_health_config_accepts_yaml_overrides(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(
        "\n".join(
            [
                "health:",
                "  startup_grace_sec: 240",
                "  liveness:",
                "    heartbeat_max_age_sec: 90",
                "  restart_gate:",
                "    enabled: true",
                "    critical_components:",
                "      - runtime",
                "      - sqlite",
                "    critical_down_sec: 600",
                "    min_consecutive_failures: 7",
                "    docker_healthcheck_fails_on_restart_recommended: true",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings.from_yaml(path)

    assert settings.health.startup_grace_sec == 240
    assert settings.health.liveness.heartbeat_max_age_sec == 90
    assert settings.health.restart_gate.critical_components == ("runtime", "sqlite")
    assert settings.health.restart_gate.critical_down_sec == 600
    assert settings.health.restart_gate.min_consecutive_failures == 7
    assert settings.health.restart_gate.docker_healthcheck_fails_on_restart_recommended is True
```

- [ ] **Step 5: Add production YAML block**

Add this block to `config/signal_bot.yaml` at top level near `dashboard` or `runtime`:

```yaml
health:
  startup_grace_sec: 180
  liveness:
    heartbeat_max_age_sec: 120
  restart_gate:
    enabled: true
    critical_components:
      - runtime
      - scheduler
      - sqlite
    critical_down_sec: 300
    min_consecutive_failures: 5
    docker_healthcheck_fails_on_restart_recommended: false
```

- [ ] **Step 6: Run config tests**

Run:

```bash
.venv/bin/pytest tests/test_nautilus_runtime_config.py::test_health_config_defaults_are_conservative tests/test_nautilus_runtime_config.py::test_health_config_accepts_yaml_overrides tests/test_nautilus_runtime_config.py::test_production_yaml_declares_nautilus_runtime_section -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/polysignal_lab/config.py tests/test_nautilus_runtime_config.py config/signal_bot.yaml
git commit -m "feat: add health probe config"
```

---

### Task 2: Runtime health pure functions

**Files:**
- Create: `src/polysignal_lab/observability/runtime_health.py`
- Create: `tests/test_healthcheck.py`

**Interfaces:**
- Consumes: `HealthConfig` from `polysignal_lab.config`
- Consumes: `HealthSnapshot`, `ComponentHealth` from `polysignal_lab.observability.health`
- Produces: `RuntimeHeartbeat`
- Produces: `LivenessResult`
- Produces: `RestartGateResult`
- Produces: `write_runtime_heartbeat(path: Path, *, phase: str, fatal: bool = False, fatal_reason: str | None = None, now: datetime | None = None) -> RuntimeHeartbeat`
- Produces: `read_runtime_heartbeat(path: Path) -> RuntimeHeartbeat`
- Produces: `evaluate_liveness(path: Path, *, max_age_sec: int, now: datetime | None = None) -> LivenessResult`
- Produces: `evaluate_restart_gate(snapshot: HealthSnapshot, *, critical_components: tuple[str, ...], critical_down_sec: int, min_consecutive_failures: int, previous: RestartGateResult | None = None, now: datetime | None = None) -> RestartGateResult`

- [ ] **Step 1: Write failing heartbeat/liveness tests**

Create `tests/test_healthcheck.py` with:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polysignal_lab.observability.health import ComponentHealth, HealthSnapshot
from polysignal_lab.observability.runtime_health import (
    RestartGateResult,
    evaluate_liveness,
    evaluate_restart_gate,
    read_runtime_heartbeat,
    write_runtime_heartbeat,
)


def _dt(second: int) -> datetime:
    return datetime(2026, 6, 30, 12, 0, second, tzinfo=UTC)


def test_liveness_passes_for_fresh_heartbeat(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(path, phase="running", now=_dt(0))

    result = evaluate_liveness(path, max_age_sec=120, now=_dt(30))

    assert result.ok is True
    assert result.reason is None
    assert result.heartbeat_age_sec == 30


def test_liveness_fails_for_stale_heartbeat(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(path, phase="running", now=_dt(0))

    result = evaluate_liveness(path, max_age_sec=120, now=_dt(121))

    assert result.ok is False
    assert result.reason == "heartbeat_stale"
    assert result.heartbeat_age_sec == 121


def test_liveness_fails_for_fatal_heartbeat(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(
        path,
        phase="fatal",
        fatal=True,
        fatal_reason="TradingNode.run returned unexpectedly",
        now=_dt(0),
    )

    result = evaluate_liveness(path, max_age_sec=120, now=_dt(1))

    assert result.ok is False
    assert result.reason == "fatal"
    assert result.fatal_reason == "TradingNode.run returned unexpectedly"


def test_liveness_fails_for_missing_heartbeat(tmp_path) -> None:
    result = evaluate_liveness(
        tmp_path / "runtime_heartbeat.json",
        max_age_sec=120,
        now=_dt(0),
    )

    assert result.ok is False
    assert result.reason == "heartbeat_missing"


def test_liveness_fails_for_corrupt_heartbeat(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    path.write_text("not-json", encoding="utf-8")

    result = evaluate_liveness(path, max_age_sec=120, now=_dt(0))

    assert result.ok is False
    assert result.reason == "heartbeat_unreadable"


def test_read_runtime_heartbeat_round_trips(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    written = write_runtime_heartbeat(path, phase="running", now=_dt(0))

    read = read_runtime_heartbeat(path)

    assert read == written
    assert read.updated_at == "2026-06-30T12:00:00+00:00"
    assert read.phase == "running"
    assert read.fatal is False
```

- [ ] **Step 2: Run liveness tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/test_healthcheck.py::test_liveness_passes_for_fresh_heartbeat -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'polysignal_lab.observability.runtime_health'`.

- [ ] **Step 3: Implement runtime health dataclasses and heartbeat helpers**

Create `src/polysignal_lab/observability/runtime_health.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

from polysignal_lab.observability.health import HealthSnapshot


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class RuntimeHeartbeat:
    updated_at: str
    phase: str
    fatal: bool = False
    fatal_reason: str | None = None


@dataclass(frozen=True, slots=True)
class LivenessResult:
    ok: bool
    reason: str | None = None
    heartbeat_age_sec: int | None = None
    fatal_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RestartGateResult:
    restart_recommended: bool
    reason: str | None = None
    critical_down_components: tuple[str, ...] = ()
    first_down_at: str | None = None
    down_duration_sec: int = 0
    consecutive_failures: int = 0


def write_runtime_heartbeat(
    path: Path,
    *,
    phase: str,
    fatal: bool = False,
    fatal_reason: str | None = None,
    now: datetime | None = None,
) -> RuntimeHeartbeat:
    timestamp = (now or _utc_now()).astimezone(UTC).isoformat()
    heartbeat = RuntimeHeartbeat(
        updated_at=timestamp,
        phase=phase,
        fatal=bool(fatal),
        fatal_reason=fatal_reason,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(heartbeat.__dict__, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return heartbeat


def read_runtime_heartbeat(path: Path) -> RuntimeHeartbeat:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RuntimeHeartbeat(
        updated_at=str(payload["updated_at"]),
        phase=str(payload["phase"]),
        fatal=bool(payload.get("fatal", False)),
        fatal_reason=(
            str(payload["fatal_reason"])
            if payload.get("fatal_reason") is not None
            else None
        ),
    )


def evaluate_liveness(
    path: Path,
    *,
    max_age_sec: int,
    now: datetime | None = None,
) -> LivenessResult:
    try:
        heartbeat = read_runtime_heartbeat(path)
    except FileNotFoundError:
        return LivenessResult(ok=False, reason="heartbeat_missing")
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        return LivenessResult(ok=False, reason="heartbeat_unreadable")

    if heartbeat.fatal:
        return LivenessResult(
            ok=False,
            reason="fatal",
            fatal_reason=heartbeat.fatal_reason,
        )

    observed_at = (now or _utc_now()).astimezone(UTC)
    updated_at = datetime.fromisoformat(heartbeat.updated_at).astimezone(UTC)
    age = max(0, int((observed_at - updated_at).total_seconds()))
    if age > int(max_age_sec):
        return LivenessResult(
            ok=False,
            reason="heartbeat_stale",
            heartbeat_age_sec=age,
        )
    return LivenessResult(ok=True, heartbeat_age_sec=age)
```

- [ ] **Step 4: Run liveness tests**

Run:

```bash
.venv/bin/pytest tests/test_healthcheck.py::test_liveness_passes_for_fresh_heartbeat tests/test_healthcheck.py::test_liveness_fails_for_stale_heartbeat tests/test_healthcheck.py::test_liveness_fails_for_fatal_heartbeat tests/test_healthcheck.py::test_liveness_fails_for_missing_heartbeat tests/test_healthcheck.py::test_liveness_fails_for_corrupt_heartbeat tests/test_healthcheck.py::test_read_runtime_heartbeat_round_trips -q
```

Expected: PASS.

- [ ] **Step 5: Write restart gate tests**

Append to `tests/test_healthcheck.py`:

```python
def _snapshot(*components: ComponentHealth) -> HealthSnapshot:
    status = "ok"
    if any(component.status == "down" for component in components):
        status = "down"
    elif any(component.status == "degraded" for component in components):
        status = "degraded"
    return HealthSnapshot(
        status=status,
        generated_at="2026-06-30T12:00:00+00:00",
        components=list(components),
    )


def test_restart_gate_ignores_noncritical_down_component() -> None:
    result = evaluate_restart_gate(
        _snapshot(ComponentHealth(name="telegram", status="down")),
        critical_components=("runtime", "scheduler", "sqlite"),
        critical_down_sec=300,
        min_consecutive_failures=5,
        now=_dt(0),
    )

    assert result.restart_recommended is False
    assert result.critical_down_components == ()
    assert result.consecutive_failures == 0


def test_restart_gate_waits_for_duration_and_count() -> None:
    first = evaluate_restart_gate(
        _snapshot(ComponentHealth(name="runtime", status="down")),
        critical_components=("runtime",),
        critical_down_sec=300,
        min_consecutive_failures=5,
        now=_dt(0),
    )
    second = evaluate_restart_gate(
        _snapshot(ComponentHealth(name="runtime", status="down")),
        critical_components=("runtime",),
        critical_down_sec=300,
        min_consecutive_failures=5,
        previous=first,
        now=_dt(30),
    )

    assert first.restart_recommended is False
    assert first.first_down_at == "2026-06-30T12:00:00+00:00"
    assert first.consecutive_failures == 1
    assert second.restart_recommended is False
    assert second.down_duration_sec == 30
    assert second.consecutive_failures == 2


def test_restart_gate_recommends_after_sustained_critical_down() -> None:
    previous = RestartGateResult(
        restart_recommended=False,
        critical_down_components=("runtime",),
        first_down_at="2026-06-30T12:00:00+00:00",
        consecutive_failures=4,
    )

    result = evaluate_restart_gate(
        _snapshot(ComponentHealth(name="runtime", status="down")),
        critical_components=("runtime",),
        critical_down_sec=300,
        min_consecutive_failures=5,
        previous=previous,
        now=_dt(59) + timedelta(seconds=241),
    )

    assert result.restart_recommended is True
    assert result.reason == "critical_components_down"
    assert result.critical_down_components == ("runtime",)
    assert result.down_duration_sec == 300
    assert result.consecutive_failures == 5


def test_restart_gate_resets_after_recovery() -> None:
    previous = RestartGateResult(
        restart_recommended=False,
        critical_down_components=("runtime",),
        first_down_at="2026-06-30T12:00:00+00:00",
        consecutive_failures=4,
    )

    result = evaluate_restart_gate(
        _snapshot(ComponentHealth(name="runtime", status="ok")),
        critical_components=("runtime",),
        critical_down_sec=300,
        min_consecutive_failures=5,
        previous=previous,
        now=_dt(59),
    )

    assert result.restart_recommended is False
    assert result.critical_down_components == ()
    assert result.first_down_at is None
    assert result.down_duration_sec == 0
    assert result.consecutive_failures == 0
```

- [ ] **Step 6: Implement restart gate evaluator**

Append to `src/polysignal_lab/observability/runtime_health.py`:

```python
def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def evaluate_restart_gate(
    snapshot: HealthSnapshot,
    *,
    critical_components: tuple[str, ...],
    critical_down_sec: int,
    min_consecutive_failures: int,
    previous: RestartGateResult | None = None,
    now: datetime | None = None,
) -> RestartGateResult:
    critical = set(critical_components)
    down = tuple(
        component.name
        for component in snapshot.components
        if component.name in critical and component.status == "down"
    )
    if not down:
        return RestartGateResult(restart_recommended=False)

    observed_at = (now or _utc_now()).astimezone(UTC)
    same_down_set = previous is not None and previous.critical_down_components == down
    first_down_at = (
        previous.first_down_at
        if same_down_set and previous.first_down_at is not None
        else observed_at.isoformat()
    )
    consecutive = (previous.consecutive_failures + 1) if same_down_set and previous else 1
    duration = max(0, int((observed_at - _parse_iso(first_down_at)).total_seconds()))
    recommended = (
        duration >= int(critical_down_sec)
        and consecutive >= int(min_consecutive_failures)
    )
    return RestartGateResult(
        restart_recommended=recommended,
        reason="critical_components_down" if recommended else None,
        critical_down_components=down,
        first_down_at=first_down_at,
        down_duration_sec=duration,
        consecutive_failures=consecutive,
    )
```

- [ ] **Step 7: Run runtime health tests**

Run:

```bash
.venv/bin/pytest tests/test_healthcheck.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/polysignal_lab/observability/runtime_health.py tests/test_healthcheck.py
git commit -m "feat: add runtime health evaluation"
```

---

### Task 3: Healthcheck CLI

**Files:**
- Create: `src/polysignal_lab/healthcheck.py`
- Modify: `tests/test_healthcheck.py`

**Interfaces:**
- Consumes: `load_settings(config_path)`
- Consumes: `evaluate_liveness(path, max_age_sec=...)`
- Produces: `main(argv: Sequence[str] | None = None) -> int`
- Produces CLI command: `python -m polysignal_lab.healthcheck liveness --config config/signal_bot.yaml`

- [ ] **Step 1: Write failing CLI tests**

Append to `tests/test_healthcheck.py`:

```python
def test_healthcheck_cli_liveness_returns_zero_for_fresh_heartbeat(tmp_path) -> None:
    from polysignal_lab.healthcheck import main

    state_dir = tmp_path / "state"
    config = tmp_path / "settings.yaml"
    config.write_text(
        "\n".join(
            [
                "storage:",
                f"  state_dir: {state_dir.as_posix()}",
                "health:",
                "  liveness:",
                "    heartbeat_max_age_sec: 120",
            ]
        ),
        encoding="utf-8",
    )
    write_runtime_heartbeat(
        state_dir / "runtime_heartbeat.json",
        phase="running",
    )

    assert main(["liveness", "--config", str(config)]) == 0


def test_healthcheck_cli_liveness_returns_one_for_missing_heartbeat(tmp_path) -> None:
    from polysignal_lab.healthcheck import main

    state_dir = tmp_path / "state"
    config = tmp_path / "settings.yaml"
    config.write_text(
        "\n".join(
            [
                "storage:",
                f"  state_dir: {state_dir.as_posix()}",
                "health:",
                "  liveness:",
                "    heartbeat_max_age_sec: 120",
            ]
        ),
        encoding="utf-8",
    )

    assert main(["liveness", "--config", str(config)]) == 1
```

- [ ] **Step 2: Run CLI test to verify it fails**

Run:

```bash
.venv/bin/pytest tests/test_healthcheck.py::test_healthcheck_cli_liveness_returns_zero_for_fresh_heartbeat -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'polysignal_lab.healthcheck'`.

- [ ] **Step 3: Implement CLI**

Create `src/polysignal_lab/healthcheck.py`:

```python
from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from polysignal_lab.config import load_settings
from polysignal_lab.observability.runtime_health import evaluate_liveness


def _heartbeat_path(state_dir: str) -> Path:
    return Path(state_dir) / "runtime_heartbeat.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PolySignal Lab healthcheck")
    subcommands = parser.add_subparsers(dest="command", required=True)
    liveness = subcommands.add_parser("liveness")
    liveness.add_argument("--config", default="config/signal_bot.yaml")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.config)
    if args.command == "liveness":
        result = evaluate_liveness(
            _heartbeat_path(settings.storage.state_dir),
            max_age_sec=settings.health.liveness.heartbeat_max_age_sec,
        )
        if not result.ok:
            print(f"liveness failed: {result.reason}")
            return 1
        return 0
    raise AssertionError(f"unhandled healthcheck command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
.venv/bin/pytest tests/test_healthcheck.py::test_healthcheck_cli_liveness_returns_zero_for_fresh_heartbeat tests/test_healthcheck.py::test_healthcheck_cli_liveness_returns_one_for_missing_heartbeat -q
```

Expected: PASS.

- [ ] **Step 5: Verify module invocation works**

Run:

```bash
python -m polysignal_lab.healthcheck liveness --config config/signal_bot.yaml
```

Expected before runtime heartbeat exists: exit code `1` and output beginning `liveness failed:`. This proves the Docker command resolves; it does not claim runtime is healthy outside a running container.

- [ ] **Step 6: Commit**

```bash
git add src/polysignal_lab/healthcheck.py tests/test_healthcheck.py
git commit -m "feat: add healthcheck cli"
```

---

### Task 4: Wire Nautilus runtime progress heartbeat

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/node.py`
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Modify: `tests/test_nautilus_node.py`
- Modify: `tests/test_nautilus_strategy_base.py`

**Interfaces:**
- Consumes: `write_runtime_heartbeat(path, phase=...)`
- Produces helper in `node.py`: `_runtime_heartbeat_path(settings: Settings) -> Path`
- Produces helper in `node.py`: `_runtime_progress_callback(settings: Settings) -> Callable[[str], None]`
- Produces constructor parameter in `PolySignalNativeStrategy`: `progress_callback: Callable[[str], None] | None = None`
- Produces runtime strategy progress calls from internal Nautilus callbacks: `on_start`, `_on_evaluation_heartbeat`, `_evaluate_market_data_condition`, and order/fill event handlers.

**Important invariant:** Do not use a standalone background thread or timer that writes liveness without runtime progress. A blind writer can keep the heartbeat fresh while `TradingNode.run()` or the Nautilus scheduler is wedged. Market-data callbacks are also not sufficient alone because external market-data silence must be readiness degradation, not liveness death. The heartbeat must be updated by internal Nautilus callback execution, especially the existing evaluation heartbeat timer.

- [ ] **Step 1: Write failing native strategy progress callback test**

Append to `tests/test_nautilus_strategy_base.py`:

```python
def test_native_strategy_reports_progress_on_internal_evaluation_heartbeat() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    progress_events: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(object()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        **_native_projections(),
        progress_callback=progress_events.append,
    )

    strategy._on_evaluation_heartbeat(object())

    assert progress_events == ["evaluation_heartbeat"]
```

- [ ] **Step 2: Write failing non-data progress test**

Append to `tests/test_nautilus_strategy_base.py`:

```python
def test_native_strategy_reports_progress_on_start_without_market_data() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    progress_events: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        **_native_projections(),
        progress_callback=progress_events.append,
    )

    strategy.on_start()

    assert "start" in progress_events
```

- [ ] **Step 3: Run strategy progress tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/test_nautilus_strategy_base.py::test_native_strategy_reports_progress_on_internal_evaluation_heartbeat tests/test_nautilus_strategy_base.py::test_native_strategy_reports_progress_on_start_without_market_data -q
```

Expected: FAIL with `TypeError` because `progress_callback` is not accepted.

- [ ] **Step 4: Add progress callback to native strategy constructor**

In `src/polysignal_lab/nautilus_runtime/native_strategy.py`, update the dynamic class `__init__` signature inside `runtime_native_strategy_type(...)`:

```python
            progress_callback: Callable[[str], None] | None = None,
```

Pass it into `PolySignalNativeStrategy.__init__(...)`:

```python
                progress_callback=progress_callback,
```

Update `PolySignalNativeStrategy.__init__` signature:

```python
        progress_callback: Callable[[str], None] | None = None,
```

Store it after `self.observability`:

```python
        self.progress_callback: Callable[[str], None] | None = progress_callback
```

Add helper method near `_require_assembler`:

```python
    def _note_runtime_progress(self, phase: str) -> None:
        callback = self.progress_callback
        if callback is None:
            return
        callback(phase)
```

- [ ] **Step 5: Call progress helper from internal runtime callbacks**

In `PolySignalNativeStrategy.on_start`, add as the first line:

```python
        self._note_runtime_progress("start")
```

In `_on_evaluation_heartbeat`, add as the first line:

```python
        self._note_runtime_progress("evaluation_heartbeat")
```

In `_evaluate_market_data_condition`, add as the first line:

```python
        self._note_runtime_progress("market_data_evaluation")
```

In `on_order_submitted`, `on_order_accepted`, `on_order_denied`, `on_order_rejected`, `on_order_canceled`, `on_order_expired`, and `on_order_filled`, add this as each method's first line:

```python
        self._note_runtime_progress("order_event")
```

This intentionally uses one stable phase for all order/fill event callbacks; liveness only needs proof that Nautilus callback dispatch still executes.

- [ ] **Step 6: Run strategy progress tests**

Run:

```bash
.venv/bin/pytest tests/test_nautilus_strategy_base.py::test_native_strategy_reports_progress_on_internal_evaluation_heartbeat tests/test_nautilus_strategy_base.py::test_native_strategy_reports_progress_on_start_without_market_data -q
```

Expected: PASS.

- [ ] **Step 7: Write failing node progress callback test**

Append to `tests/test_nautilus_node.py`:

```python
def test_build_trading_node_injects_runtime_progress_callback(monkeypatch, tmp_path) -> None:
    from polysignal_lab.observability.runtime_health import read_runtime_heartbeat

    captured: dict[str, object] = {}

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append

        def add_data_client_factory(self, name, factory):
            return None

        def add_exec_client_factory(self, name, factory):
            return None

        def build(self):
            return None

    class FakeStrategy:
        strategy_name = "vwap_momentum"

        def __init__(self, **kwargs):
            captured.update(kwargs)

    settings = Settings()
    settings.storage.state_dir = str(tmp_path / "state")
    _patch_nautilus_placeholders(monkeypatch)
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.native_strategy.runtime_native_strategy_type",
        lambda _base, _config: FakeStrategy,
    )

    runtime = build_trading_node(settings=settings, condition_ids=("condition-btc-5m",))

    progress = captured["progress_callback"]
    assert callable(progress)
    progress("evaluation_heartbeat")
    heartbeat = read_runtime_heartbeat(tmp_path / "state" / "runtime_heartbeat.json")
    assert heartbeat.phase == "evaluation_heartbeat"
    assert runtime["strategies"][0].strategy_name == "vwap_momentum"
```

- [ ] **Step 8: Wire node progress callback into strategy construction**

In `src/polysignal_lab/nautilus_runtime/node.py`, add import:

```python
from pathlib import Path
from polysignal_lab.observability.runtime_health import write_runtime_heartbeat
```

If `Path` is already imported after current edits, do not duplicate it.

Add helpers near signal helpers:

```python
def _runtime_heartbeat_path(settings: Settings) -> Path:
    return Path(settings.storage.state_dir) / "runtime_heartbeat.json"


def _runtime_progress_callback(settings: Settings) -> Callable[[str], None]:
    path = _runtime_heartbeat_path(settings)

    def note_progress(phase: str) -> None:
        write_runtime_heartbeat(path, phase=phase)

    return note_progress
```

Update `_build_native_strategies(...)` call to each `strategy_type(...)` by adding:

```python
            progress_callback=_runtime_progress_callback(settings),
```

In `run_nautilus_cli_async`, after `bundle = await build_nautilus_runtime(settings)`, write startup heartbeat:

```python
    write_runtime_heartbeat(
        _runtime_heartbeat_path(bundle.scheduler.settings),
        phase="starting",
    )
```

In `run_nautilus_cli`, after `bundle = _build_nautilus_runtime_bundle(...)`, write startup heartbeat:

```python
    heartbeat_path = _runtime_heartbeat_path(bundle.scheduler.settings)
    write_runtime_heartbeat(heartbeat_path, phase="starting")
```

Before raising the existing unexpected-return `RuntimeError`, add:

```python
            write_runtime_heartbeat(
                heartbeat_path,
                phase="fatal",
                fatal=True,
                fatal_reason="TradingNode.run returned unexpectedly",
            )
```

Do not add a standalone heartbeat thread. The fresh heartbeat must come from strategy/runtime callback progress, not from an independent timer.

- [ ] **Step 9: Write fatal heartbeat test**

Append to `tests/test_nautilus_node.py`:

```python
def test_run_nautilus_cli_writes_fatal_heartbeat_on_unexpected_return(monkeypatch, tmp_path) -> None:
    from polysignal_lab.observability.runtime_health import read_runtime_heartbeat

    class FakeNode:
        def run(self, raise_exception=False):
            return None

        def dispose(self):
            return None

    settings = Settings()
    settings.storage.state_dir = str(tmp_path / "state")
    scheduler = SimpleNamespace(settings=settings, logger=SimpleNamespace(error=lambda *a, **k: None))
    observability = SimpleNamespace(
        notify_startup=AsyncMock(return_value=None),
        notify_shutdown=AsyncMock(return_value=None),
    )
    bundle = SimpleNamespace(
        scheduler=scheduler,
        components={"strategies": [SimpleNamespace(strategy_name="vwap_momentum")]},
        node=FakeNode(),
        observability=observability,
    )

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context", AsyncMock(return_value=(scheduler, [], observability)))
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node._rebind_market_discovery_client", lambda _scheduler: None)
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle", lambda *_args: bundle)
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node._stop_nautilus_scheduler", AsyncMock(return_value=None))

    with pytest.raises(RuntimeError, match="TradingNode.run returned unexpectedly"):
        run_nautilus_cli(settings)

    heartbeat = read_runtime_heartbeat(tmp_path / "state" / "runtime_heartbeat.json")
    assert heartbeat.fatal is True
    assert heartbeat.phase == "fatal"
    assert heartbeat.fatal_reason == "TradingNode.run returned unexpectedly"
```

- [ ] **Step 10: Run Nautilus heartbeat tests**

Run:

```bash
.venv/bin/pytest tests/test_nautilus_node.py::test_build_trading_node_injects_runtime_progress_callback tests/test_nautilus_node.py::test_run_nautilus_cli_writes_fatal_heartbeat_on_unexpected_return -q
```

Expected: PASS.

- [ ] **Step 11: Run focused runtime health tests**

Run:

```bash
.venv/bin/pytest tests/test_healthcheck.py tests/test_nautilus_strategy_base.py::test_native_strategy_reports_progress_on_internal_evaluation_heartbeat tests/test_nautilus_strategy_base.py::test_native_strategy_reports_progress_on_start_without_market_data tests/test_nautilus_node.py::test_build_trading_node_injects_runtime_progress_callback tests/test_nautilus_node.py::test_run_nautilus_cli_writes_fatal_heartbeat_on_unexpected_return -q
```

Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/node.py src/polysignal_lab/nautilus_runtime/native_strategy.py tests/test_nautilus_node.py tests/test_nautilus_strategy_base.py
git commit -m "feat: write nautilus runtime progress heartbeat"
```

---

### Task 5: Docker Compose healthcheck cutover

**Files:**
- Modify: `docker-compose.yml`
- Modify: `tests/test_healthcheck.py`

**Interfaces:**
- Consumes CLI: `python -m polysignal_lab.healthcheck liveness --config config/signal_bot.yaml`
- Produces compose healthcheck using liveness, not SQLite `SELECT 1`

- [ ] **Step 1: Write failing compose assertion test**

Append to `tests/test_healthcheck.py`:

```python
def test_docker_compose_main_healthcheck_uses_liveness_cli() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "polysignal_lab.healthcheck" in compose
    assert "liveness" in compose
    assert "sqlite3.connect" not in compose
    assert "start_period: 180s" in compose
```

Also add `from pathlib import Path` at the top of `tests/test_healthcheck.py` if Task 2 did not already add it.

- [ ] **Step 2: Run compose assertion to verify it fails**

Run:

```bash
.venv/bin/pytest tests/test_healthcheck.py::test_docker_compose_main_healthcheck_uses_liveness_cli -q
```

Expected: FAIL because `docker-compose.yml` still contains `sqlite3.connect` and `start_period: 10s`.

- [ ] **Step 3: Update main service healthcheck**

In `docker-compose.yml`, replace the `polysignal-lab` healthcheck with:

```yaml
    healthcheck:
      test: ["CMD", "python", "-m", "polysignal_lab.healthcheck", "liveness", "--config", "config/signal_bot.yaml"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 180s
```

Leave the dashboard healthcheck unchanged.

- [ ] **Step 4: Run compose assertion**

Run:

```bash
.venv/bin/pytest tests/test_healthcheck.py::test_docker_compose_main_healthcheck_uses_liveness_cli -q
```

Expected: PASS.

- [ ] **Step 5: Verify Docker Compose parses**

Run:

```bash
docker compose config --quiet
```

Expected: exit code `0`.

- [ ] **Step 6: Run all focused health tests**

Run:

```bash
.venv/bin/pytest tests/test_healthcheck.py tests/test_nautilus_runtime_config.py tests/test_health_metrics.py::test_health_registry_aggregates_component_status_and_transitions -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml tests/test_healthcheck.py
git commit -m "fix: use runtime liveness healthcheck"
```

---

### Task 6: Final verification

**Files:**
- No code files should change in this task.

**Interfaces:**
- Verifies all acceptance criteria from `docs/superpowers/specs/2026-06-30-container-healthcheck-design.md`.

- [ ] **Step 1: Run focused test set**

Run:

```bash
.venv/bin/pytest tests/test_healthcheck.py tests/test_nautilus_runtime_config.py tests/test_health_metrics.py tests/test_nautilus_node.py::test_run_nautilus_cli_writes_fatal_heartbeat_on_unexpected_return -q
```

Expected: PASS.

- [ ] **Step 2: Run compose config validation**

Run:

```bash
docker compose config --quiet
```

Expected: exit code `0`.

- [ ] **Step 3: Verify healthcheck module resolves**

Run:

```bash
python -m polysignal_lab.healthcheck liveness --config config/signal_bot.yaml
```

Expected when no runtime heartbeat exists in local `state/`: exit code `1` with output beginning `liveness failed:`. This validates import/CLI wiring, not runtime health.

- [ ] **Step 4: Verify no acceptance-scope drift**

Run:

```bash
.venv/bin/pytest tests/test_healthcheck.py::test_docker_compose_main_healthcheck_uses_liveness_cli -q
```

Expected: PASS. This specific test asserts that `docker-compose.yml` uses `polysignal_lab.healthcheck`, includes `liveness`, removes `sqlite3.connect`, and sets `start_period: 180s`.

- [ ] **Step 5: Commit final verification note only if files changed**

This task should not change files. If `git status --short` shows no changes after verification, do not commit. If a verification failure required a fix, commit only the concrete files changed by that fix with a message naming the fix, for example:

```bash
git add docker-compose.yml tests/test_healthcheck.py
git commit -m "test: verify runtime healthcheck"
```
