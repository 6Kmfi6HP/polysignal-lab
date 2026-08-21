"""Cross-module integration regressions for the issue-69 recovery stack.

The unit suites cover the watchdog with hand-crafted heartbeat payloads
(``subscription_state: "ready"`` etc.) and the strategy with mock
callbacks, but nobody drives the *real* composition: subscriptions state
machine -> ``readiness.readiness_detail`` -> ``write_runtime_heartbeat``
(the exact writer node_probes uses) -> ``LivenessWatchdog`` poll ->
restart callback.

These tests pin that chain so a regression at any seam fails loudly:
a state that never reaches the heartbeat file, a generation timestamp lost
through JSON serialization, a fleet clock that survives a real READY
recovery, or a restart reason that is not machine-parseable.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from polysignal_lab.config import HealthConfig, Settings, StorageConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.strategy import readiness as readiness_mod
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    MarketSubscriptionState,
    begin_market_book_generation,
    observe_market_book_side,
)
from polysignal_lab.observability.liveness_watchdog import LivenessWatchdog
from polysignal_lab.observability.runtime_health import (
    read_runtime_heartbeat,
    write_runtime_heartbeat,
)

T0 = datetime(2026, 8, 18, 0, 0, 0, tzinfo=UTC)


def _settings(state_dir: str) -> Settings:
    return Settings(
        storage=StorageConfig(state_dir=state_dir),
        health=HealthConfig(startup_grace_sec=0),
    )


class _IntegrationStrategy:
    """Minimal duck-typed strategy exposing the REAL readiness surface.

    Uses the REAL ``readiness.readiness_detail`` producer and the REAL
    subscription transition functions; no heartbeat payload is hand-written.
    """

    def __init__(self) -> None:
        self.strategy_name: str = "issue69-integration"
        self.policy: object = object()
        self._subscription_state = MarketSubscriptionState()
        self._stale_orderbook_recovery_by_condition: dict[str, dict[Side, float]] = {}
        self._runtime_readiness_reason_by_condition: dict[str, str] = {}
        self._runtime_readiness_miss_condition_ids: set[str] = set()
        self._untradable_quote_sides_by_condition: dict[str, frozenset[Side]] = {}
        self._active_condition_ids: set[str] = set()
        self.registry: MarketCatalog | None = MarketCatalog(
            instrument_id_resolver=lambda _condition, token: f"{token}.POLYMARKET"
        )

    def _require_registry(self) -> MarketCatalog:
        assert self.registry is not None
        return self.registry

    def register(self, condition_id: str) -> None:
        assert self.registry is not None
        self.registry.register(
            MarketPairMeta(
                market_id=f"market-{condition_id}",
                market_slug=f"{condition_id}-updown-5m",
                condition_id=condition_id,
                asset="BTC",
                timeframe="5m",
                start_ts=None,
                end_ts=None,
                up=InstrumentTokenMeta(f"{condition_id}-up", Side.UP),
                down=InstrumentTokenMeta(f"{condition_id}-down", Side.DOWN),
            )
        )
        self._active_condition_ids.add(condition_id)


class _TemporaryStateDir:
    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        return Path(self._tmp.name)

    def __exit__(self, *exc: object) -> None:
        self._tmp.cleanup()


CONDITION = "btc-5m"


def _readiness_detail(
    strategy: _IntegrationStrategy, now: datetime
) -> dict[str, object]:
    """The exact producer call chain the runtime uses for the heartbeat."""
    return readiness_mod.readiness_detail(
        cast(Any, strategy),
        CONDITION,
        now=now,
    )


def _write_miss_heartbeat(
    state_dir: Path,
    strategy: _IntegrationStrategy,
    *,
    now: datetime,
) -> dict[str, object]:
    """Write the heartbeat exactly like node_probes does on a readiness miss."""
    detail = _readiness_detail(strategy, now)
    write_runtime_heartbeat(
        state_dir / "runtime_heartbeat.json",
        phase="readiness_miss",
        readiness_key=CONDITION,
        readiness_ok=False,
        readiness_detail=detail,
        now=now,
        pid=os.getpid(),
    )
    return detail


def _write_ready_heartbeat(
    state_dir: Path,
    strategy: _IntegrationStrategy,
    *,
    now: datetime,
) -> None:
    """Recovery write: the real writer clears READY conditions from the
    details map (producer-side contract the watchdog relies on)."""
    detail = _readiness_detail(strategy, now)
    write_runtime_heartbeat(
        state_dir / "runtime_heartbeat.json",
        phase="readiness_ok",
        readiness_key=CONDITION,
        readiness_ok=True,
        readiness_detail=detail,
        now=now,
        pid=os.getpid(),
    )


def _arm_and_fire(
    state_dir: Path,
    strategy: _IntegrationStrategy,
    clock: dict[str, datetime],
) -> tuple[list[str], LivenessWatchdog]:
    """Drive the real chain to one supervised fleet restart.

    Timing mirrors the real replay grace (240s) and restart threshold (300s):
      t0      : replay grace active -> nothing armed
      t0+301  : grace expired -> fleet clock armed
      t0+602  : elapsed > 300s -> one fleet_never_ready restart
    """
    restarts: list[str] = []
    watchdog = LivenessWatchdog(
        _settings(str(state_dir)),
        lambda _message: None,
        now=lambda: clock["now"],
        restart=restarts.append,
    )
    _write_miss_heartbeat(state_dir, strategy, now=T0)
    _ = watchdog.poll_once()
    assert restarts == []
    clock["now"] = T0 + timedelta(seconds=301)
    _write_miss_heartbeat(state_dir, strategy, now=clock["now"])
    _ = watchdog.poll_once()
    assert restarts == []
    clock["now"] = T0 + timedelta(seconds=602)
    _write_miss_heartbeat(state_dir, strategy, now=clock["now"])
    _ = watchdog.poll_once()
    return restarts, watchdog


def test_stalled_fleet_restart_evidence_flows_through_real_chain() -> None:
    """Full real chain: subscription machinery -> readiness detail -> heartbeat
    file -> watchdog poll -> one structured restart reason.

    This scenario is the issue-69 stall: a condition waits for its first book
    (generation open, both sides awaiting). The adapter gate never rotates it
    in, so the monitoring layer must restart the runtime.
    """
    strategy = _IntegrationStrategy()
    strategy.register(CONDITION)
    begin_market_book_generation(
        strategy,  # pyright: ignore[reportArgumentType]
        CONDITION,
        now=T0,
    )
    with _TemporaryStateDir() as state_dir:
        clock: dict[str, datetime] = {"now": T0}
        restarts, _watchdog = _arm_and_fire(state_dir, strategy, clock)

    assert len(restarts) == 1
    reason = restarts[0]
    assert reason.startswith("fleet_never_ready ")
    evidence = json.loads(reason.split(" ", 1)[1])
    # strategy-produced generation timestamp must survive the JSON heartbeat.
    assert evidence["generation_started_iso"] == T0.isoformat()
    assert evidence["buckets"] == {"awaiting_first_book": 1}
    assert evidence["no_progress"] == 1
    assert evidence["fleet"] == 1
    assert evidence["in_flight"] == 1


def test_ready_recovery_clears_heartbeat_details_and_resets_fleet_clock() -> None:
    """A real READY transition (both books observed) must make the condition
    vanish from the heartbeat details map, and the watchdog must NOT restart
    a runtime that recovered -- the SAME watchdog instance sees the fleet
    clock reset through the real file."""
    strategy = _IntegrationStrategy()
    strategy.register(CONDITION)
    begin_market_book_generation(
        strategy,  # pyright: ignore[reportArgumentType]
        CONDITION,
        now=T0,
    )
    with _TemporaryStateDir() as state_dir:
        clock: dict[str, datetime] = {"now": T0}
        restarts: list[str] = []
        watchdog = LivenessWatchdog(
            _settings(str(state_dir)),
            lambda _message: None,
            now=lambda: clock["now"],
            restart=restarts.append,
        )
        _write_miss_heartbeat(state_dir, strategy, now=T0)
        _ = watchdog.poll_once()  # grace active; nothing armed
        assert restarts == []

        # Books arrive on both sides -> the real subscription machinery marks
        # the condition READY.
        clock["now"] = T0 + timedelta(seconds=100)
        observe_market_book_side(
            strategy,  # pyright: ignore[reportArgumentType]
            CONDITION,
            Side.UP,
            received_at=clock["now"],
            book_at=clock["now"],
        )
        observe_market_book_side(
            strategy,  # pyright: ignore[reportArgumentType]
            CONDITION,
            Side.DOWN,
            received_at=clock["now"],
            book_at=clock["now"],
        )
        assert market_book_generation_readiness(strategy, CONDITION) is True
        _write_ready_heartbeat(state_dir, strategy, now=clock["now"])

        heartbeat = read_runtime_heartbeat(state_dir / "runtime_heartbeat.json")
        assert CONDITION not in heartbeat.readiness_detail_by_key

        # The recovered runtime keeps trading: books keep flowing, so the
        # data clock advances (no data_starvation) and the condition stays
        # READY. Even far past the restart threshold the same watchdog stays
        # silent -- no broken detail remains to arm the fleet clock.
        for _ in range(2):
            clock["now"] = clock["now"] + timedelta(seconds=1000)
            observe_market_book_side(
                strategy,  # pyright: ignore[reportArgumentType]
                CONDITION,
                Side.UP,
                received_at=clock["now"],
                book_at=clock["now"],
            )
            observe_market_book_side(
                strategy,  # pyright: ignore[reportArgumentType]
                CONDITION,
                Side.DOWN,
                received_at=clock["now"],
                book_at=clock["now"],
            )
            _write_ready_heartbeat(state_dir, strategy, now=clock["now"])
            _ = watchdog.poll_once()
            assert restarts == []
        assert watchdog._fleet_never_ready_started_at is None  # pyright: ignore[reportPrivateUsage]


def test_restart_reason_stays_json_parseable_under_real_stall() -> None:
    """The restart reason must remain a machine-parseable ``fleet_never_ready
    <json>`` line and never embed secrets or non-JSON material. It is parsed
    by the supervisor logs and the issue69 monitor."""
    strategy = _IntegrationStrategy()
    strategy.register(CONDITION)
    begin_market_book_generation(
        strategy,  # pyright: ignore[reportArgumentType]
        CONDITION,
        now=T0,
    )
    with _TemporaryStateDir() as state_dir:
        clock: dict[str, datetime] = {"now": T0}
        restarts, _watchdog = _arm_and_fire(state_dir, strategy, clock)

    reason = restarts[0]
    prefix, payload = reason.split(" ", 1)
    assert prefix == "fleet_never_ready"
    data = json.loads(payload)
    assert isinstance(data["buckets"], dict)
    assert data["oldest_wait_age_sec"] is not None
    assert data["transport_states"] == []
    assert data["connection_epoch"] == []
    assert "credential" not in payload.lower() and "token" not in payload.lower()


def market_book_generation_readiness(
    strategy: _IntegrationStrategy, condition_id: str
) -> bool:
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        market_book_generation_ready,
    )

    return market_book_generation_ready(cast(Any, strategy), condition_id)
