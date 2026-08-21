"""Self-sufficient market rotation regression tests.

MarketRotation's expiry timer does not fire under ``LiveNode.poll()``
(nautilus 1.231, verified live), so expired market slots are never rotated
out and new windows never enter any strategy's active set — the fleet
eventually has zero active conditions and goes dark. The recovery heartbeat
now discovers current markets directly and subscribes new conditions,
gated on the production ``POLYSIGNAL_MARKET_DISCOVERY=1`` opt-in so unit
tests and probe strategies never call Gamma from the event loop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from polysignal_lab.nautilus_runtime.strategy import lifecycle as life
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    ConditionSubscriptionPhase,
    MarketSubscriptionState,
    _NO_BOOK_SUPPRESS_SEC,
    _subscribe_suppressed,
)


def _now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture(autouse=True)
def _reset_adapter_refresh_gate() -> None:
    life._ADAPTER_REFRESH_AT_BY_CLIENT.clear()


class _DiscoveryStrategy:
    """Minimal duck-typed strategy for the discovery integration point."""

    def __init__(self) -> None:
        self.registry: Any | None = None
        self._active_condition_ids: set[str] = set()
        self._subscription_assets = frozenset({"BTC"})
        self._subscription_timeframes = frozenset({"5m"})
        self._last_market_discovery_at: datetime | None = None
        self._last_market_data_evaluation_at: dict[str, datetime] = {}
        self.strategy_id: str | None = None
        self._market_discovery_enabled = True
        self.subscribed: list[str] = []
        self.cache: Any | None = None
        self.instrument_requests: list[tuple[str, str | None]] = []
        self.assembler: Any | None = None
        self._stale_orderbook_recovery_by_condition: dict[str, dict[str, float]] = {}
        self._no_book_abandoned_at_by_condition: dict[str, datetime] = {}

    def _require_registry(self) -> Any:
        return self.registry

    def _note_runtime_progress(self, phase: str, **kwargs: Any) -> None:
        pass

    def _refresh_asset_conditions(self) -> None:
        pass

    def _subscribe_market_conditions(self, condition_ids: list[str]) -> None:
        self.subscribed.extend(condition_ids)

    def evaluate_condition(self, condition_id: str, **kwargs: Any) -> None:
        pass

    def request_instruments(self, venue: Any, client_id: Any = None) -> Any:
        self.instrument_requests.append(
            (str(venue), None if client_id is None else str(client_id))
        )
        return None


class _FakeRegistry:
    def __init__(self) -> None:
        self.registered: list[Any] = []
        self._known: set[str] = set()

    def by_condition(self, condition_id: str) -> Any | None:
        return "known" if condition_id in self._known else None

    def register(self, pair: Any) -> None:
        self.registered.append(pair)


class _FakeMarket:
    def __init__(self, condition_id: str, asset: str, timeframe: str) -> None:
        self.condition_id = condition_id
        self.asset = asset
        self.timeframe = timeframe


def test_discovery_skips_without_optin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLYSIGNAL_MARKET_DISCOVERY", raising=False)
    called: list[bool] = []
    monkeypatch.setattr(
        life,
        "_discover_new_conditions",
        lambda *a, **k: called.append(True) or ["new-cond"],
    )
    strategy = _DiscoveryStrategy()
    strategy.registry = _FakeRegistry()

    life._discover_and_subscribe_new_markets(cast(Any, strategy), now=_now())

    assert called == []
    assert strategy.subscribed == []


def test_discovery_skips_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    called: list[bool] = []
    monkeypatch.setattr(
        life,
        "_discover_new_conditions",
        lambda *a, **k: called.append(True) or ["new-cond"],
    )
    strategy = _DiscoveryStrategy()
    strategy.registry = _FakeRegistry()
    strategy._market_discovery_enabled = False

    life._discover_and_subscribe_new_markets(cast(Any, strategy), now=_now())

    assert called == []
    assert strategy.subscribed == []


def test_discovery_subscribes_new_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    monkeypatch.setattr(
        life,
        "_discover_new_conditions",
        lambda registry, assets, timeframes: ["cond-1", "cond-2"],
    )
    strategy = _DiscoveryStrategy()
    strategy.registry = _FakeRegistry()

    life._discover_and_subscribe_new_markets(cast(Any, strategy), now=_now())

    assert sorted(strategy.subscribed) == ["cond-1", "cond-2"]
    assert "cond-1" in strategy._active_condition_ids
    # New slots rotate in beyond the startup load_ids; the adapter instrument
    # load must be driven so their wire subscriptions actually land (issue69
    # post-rotation starvation until restart).
    assert strategy.instrument_requests == [("POLYMARKET", "POLYMARKET-5M")]


def test_discovery_no_refresh_without_new_conditions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    monkeypatch.setattr(
        life,
        "_discover_new_conditions",
        lambda registry, assets, timeframes: [],
    )
    strategy = _DiscoveryStrategy()
    strategy.registry = _FakeRegistry()

    life._discover_and_subscribe_new_markets(cast(Any, strategy), now=_now())

    assert strategy.subscribed == []
    assert strategy.instrument_requests == []


def test_data_stall_refresh_drives_adapter_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """issue69: after a venue silent stop (reconnect restore carries resolved
    markets), the running refresh must re-drive the adapter instrument load
    so wire subscriptions rebuild for the current window set."""
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    monkeypatch.setattr(
        life,
        "_discover_new_conditions",
        lambda registry, assets, timeframes: ["cond-1"],
    )
    strategy = _DiscoveryStrategy()
    strategy.registry = _FakeRegistry()
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        MarketSubscriptionState,
    )

    state = MarketSubscriptionState()
    state.awaiting_book_sides_by_condition["cond-1"] = ("UP",)
    strategy._subscription_state = state

    life.on_evaluation_heartbeat(cast(Any, strategy), None)

    # Discovery drives the first adapter load; the process-global throttle
    # prevents the immediate stall refresh from duplicating it in the same
    # 300s window.
    assert strategy.instrument_requests == [("POLYMARKET", "POLYMARKET-5M")]


def test_data_stall_refresh_throttled() -> None:
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        MarketSubscriptionState,
    )

    strategy = _DiscoveryStrategy()
    state = MarketSubscriptionState()
    state.awaiting_book_sides_by_condition["cond-1"] = ("UP",)
    strategy._subscription_state = state
    t0 = _now()

    assert life._data_stall_refresh_due(cast(Any, strategy), now=t0) is True
    # A successful refresh consumes the due data client's bucket.
    assert life._request_instrument_refresh(cast(Any, strategy), now=t0) == 1
    assert strategy.instrument_requests == [("POLYMARKET", "POLYMARKET-5M")]
    # Throttled until the refresh interval elapses: the stall remains but the
    # 5m client's bucket was just consumed.
    assert (
        life._data_stall_refresh_due(cast(Any, strategy), now=t0 + timedelta(seconds=1))
        is False
    )
    # Once the bucket has elapsed the stall is due again.
    assert (
        life._data_stall_refresh_due(
            cast(Any, strategy), now=t0 + timedelta(seconds=301)
        )
        is True
    )


def test_data_stall_ignored_when_books_flowing() -> None:
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        MarketSubscriptionState,
    )

    strategy = _DiscoveryStrategy()
    strategy._subscription_state = MarketSubscriptionState()
    t0 = _now()

    # No condition is awaiting a first book: the venue is not stalled.
    assert life._data_stall_refresh_due(cast(Any, strategy), now=t0) is False


def test_data_stall_detects_stale_book_recovery() -> None:
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        MarketSubscriptionState,
    )

    strategy = _DiscoveryStrategy()
    strategy._subscription_state = MarketSubscriptionState()
    # READY condition whose book later went stale: it is under stale-book
    # recovery, not awaiting a first book — must still count as a stall.
    strategy._stale_orderbook_recovery_by_condition = {"cond-9": {}}
    t0 = _now()

    assert life._data_stall_refresh_due(cast(Any, strategy), now=t0) is True


def test_discovery_throttles_to_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    calls: list[int] = []
    monkeypatch.setattr(
        life,
        "_discover_new_conditions",
        lambda registry, assets, timeframes: calls.append(1) or [],
    )
    strategy = _DiscoveryStrategy()
    strategy.registry = _FakeRegistry()
    t0 = _now()

    life._discover_and_subscribe_new_markets(cast(Any, strategy), now=t0)
    # Immediate re-entry is throttled.
    life._discover_and_subscribe_new_markets(cast(Any, strategy), now=t0)

    assert len(calls) == 1


def test_discover_new_conditions_filters_and_registers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePair:
        pass

    markets = [
        _FakeMarket("cond-btc-5m", "BTC", "5m"),
        _FakeMarket("cond-eth-5m", "ETH", "5m"),  # asset not in scope
        _FakeMarket("cond-btc-15m", "BTC", "15m"),  # timeframe not in scope
    ]
    import polysignal_lab.config as config_mod
    import polysignal_lab.data.polymarket_market_discovery as discovery_mod

    monkeypatch.setattr(
        config_mod,
        "load_settings",
        lambda: SimpleNamespace(
            data=SimpleNamespace(polymarket=object()),
            markets=object(),
        ),
    )

    class _FakeDiscovery:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def discover_sync(self, **_: object) -> list[Any]:
            return markets

    monkeypatch.setattr(discovery_mod, "MarketDiscovery", _FakeDiscovery)
    monkeypatch.setattr(life.MarketPairMeta, "from_market", lambda m: FakePair())

    registry = _FakeRegistry()
    result = life._discover_new_conditions(
        cast(Any, registry),
        frozenset({"BTC"}),
        frozenset({"5m"}),
    )

    assert result == ["cond-btc-5m"]
    assert len(registry.registered) == 1


def test_discover_new_conditions_updates_known_condition_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Known conditions must be re-registered so Gamma's latest end_ts overwrites
    stale registry metadata. Without this, retire_expired_condition can never
    fire when the initial registration had end_ts=None or a future end_ts that
    has since passed — the condition stays in the active set forever (issue69)."""

    class FakePair:
        def __init__(self, condition_id: str) -> None:
            self.condition_id = condition_id

    markets = [_FakeMarket("cond-btc-5m", "BTC", "5m")]
    import polysignal_lab.config as config_mod
    import polysignal_lab.data.polymarket_market_discovery as discovery_mod

    monkeypatch.setattr(
        config_mod,
        "load_settings",
        lambda: SimpleNamespace(
            data=SimpleNamespace(polymarket=object()),
            markets=object(),
        ),
    )

    class _FakeDiscovery:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def discover_sync(self, **_: object) -> list[Any]:
            return markets

    monkeypatch.setattr(discovery_mod, "MarketDiscovery", _FakeDiscovery)
    monkeypatch.setattr(
        life.MarketPairMeta, "from_market", lambda m: FakePair(m.condition_id)
    )

    # Registry already knows this condition — by_condition returns a non-None pair.
    class _KnownRegistry:
        def __init__(self) -> None:
            self.registered: list[Any] = []
            self._known: set[str] = {"cond-btc-5m"}

        def by_condition(self, condition_id: str) -> Any | None:
            return "old-pair" if condition_id in self._known else None

        def register(self, pair: Any) -> None:
            self.registered.append(pair)

    registry = _KnownRegistry()
    result = life._discover_new_conditions(
        cast(Any, registry),
        frozenset({"BTC"}),
        frozenset({"5m"}),
    )

    # The known condition is still in the result (it's in-scope).
    assert result == ["cond-btc-5m"]
    # Registry.register was called to update the known condition's metadata.
    assert len(registry.registered) == 1
    assert registry.registered[0].condition_id == "cond-btc-5m"


def test_heartbeat_calls_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """on_evaluation_heartbeat invokes the discovery path."""
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    strategy = _DiscoveryStrategy()
    strategy.registry = _FakeRegistry()

    def fake_discover(_s: Any, *, now: datetime) -> None:
        strategy.subscribed.append("discovered")

    monkeypatch.setattr(
        life,
        "_discover_and_subscribe_new_markets",
        fake_discover,
    )
    # Stub out the rest of the heartbeat's dependencies.
    monkeypatch.setattr(life, "_active_unexpired_condition_ids", lambda s, now: ())
    monkeypatch.setattr(life, "_flush_pending_book_restores", lambda s, now: None)
    monkeypatch.setattr(
        life, "_reconcile_awaiting_books_from_cache", lambda s, c, now: None
    )
    monkeypatch.setattr(life, "_recover_book_subscriptions", lambda s, c, now: None)
    monkeypatch.setattr(life, "trading_state_from_cache", lambda *a, **k: None)

    # The FakeClock does not implement set_timer; the heartbeat only runs its
    # body synchronously, so patch framework_now to a fixed value as well.
    monkeypatch.setattr(life, "framework_now", lambda h: _now())

    setattr(strategy, "_note_runtime_progress", lambda phase, **k: None)
    life.on_evaluation_heartbeat(cast(Any, strategy), None)

    assert "discovered" in strategy.subscribed


def test_discovery_does_not_reattach_known_active_condition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    monkeypatch.setattr(
        life,
        "_discover_new_conditions",
        lambda registry, assets, timeframes: [],
    )
    strategy = _DiscoveryStrategy()
    strategy.registry = _FakeRegistry()
    strategy._active_condition_ids = {"cond-1"}
    t0 = _now()

    life._discover_and_subscribe_new_markets(cast(Any, strategy), now=t0)

    assert strategy.subscribed == []
    assert strategy.instrument_requests == []


def test_ready_condition_with_no_recent_receipt_is_recovery_candidate() -> None:
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        MarketSubscriptionState,
    )

    strategy = _DiscoveryStrategy()
    state = MarketSubscriptionState()
    state.condition_phases["cond-1"] = ConditionSubscriptionPhase.READY
    state.first_bilateral_book_ever_at_by_condition["cond-1"] = _now() - timedelta(
        minutes=10
    )
    state.last_book_received_at_by_condition["cond-1"] = {
        Side.UP: _now() - timedelta(seconds=400),
        Side.DOWN: _now() - timedelta(seconds=400),
    }
    strategy._subscription_state = state
    strategy._active_condition_ids = {"cond-1"}
    t0 = _now()

    assert life._ready_condition_stalled(strategy, "cond-1", now=t0) is True


def test_ready_condition_with_fresh_receipt_is_not_stalled() -> None:
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        MarketSubscriptionState,
    )

    strategy = _DiscoveryStrategy()
    state = MarketSubscriptionState()
    state.condition_phases["cond-1"] = ConditionSubscriptionPhase.READY
    state.first_bilateral_book_ever_at_by_condition["cond-1"] = _now() - timedelta(
        minutes=10
    )
    state.last_book_received_at_by_condition["cond-1"] = {
        Side.UP: _now() - timedelta(seconds=10),
        Side.DOWN: _now() - timedelta(seconds=10),
    }
    strategy._subscription_state = state
    strategy._active_condition_ids = {"cond-1"}
    t0 = _now()

    assert life._ready_condition_stalled(strategy, "cond-1", now=t0) is False


def test_recovery_candidate_requires_active_condition() -> None:
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        MarketSubscriptionState,
    )

    strategy = _DiscoveryStrategy()
    state = MarketSubscriptionState()
    state.condition_phases["cond-1"] = ConditionSubscriptionPhase.READY
    state.first_bilateral_book_ever_at_by_condition["cond-1"] = _now() - timedelta(
        minutes=10
    )
    state.last_book_received_at_by_condition["cond-1"] = {
        Side.UP: _now() - timedelta(seconds=400),
        Side.DOWN: _now() - timedelta(seconds=400),
    }
    strategy._subscription_state = state
    strategy._active_condition_ids = set()
    t0 = _now()

    assert life._ready_condition_stalled(strategy, "cond-1", now=t0) is False


class _TwoTimeframeStrategy(_DiscoveryStrategy):
    """Discovery host spanning two data clients (5m + 15m) for bucketed-gate tests."""

    def __init__(self) -> None:
        super().__init__()
        self._subscription_timeframes = frozenset({"5m", "15m"})
        self.subscribe_calls: list[tuple[str, str | None]] = []
        self.unsubscribe_calls: list[tuple[str, str | None]] = []
        self._raise_on_request = False
        self._last_adapter_refresh_at: datetime | None = None

    def subscribe_instruments(self, venue: Any, client_id: Any = None) -> Any:
        self.subscribe_calls.append(
            (str(venue), None if client_id is None else str(client_id))
        )
        return None

    def unsubscribe_instruments(self, venue: Any, client_id: Any = None) -> Any:
        self.unsubscribe_calls.append(
            (str(venue), None if client_id is None else str(client_id))
        )
        return None

    def request_instruments(self, venue: Any, client_id: Any = None) -> Any:
        if self._raise_on_request:
            raise RuntimeError("injected refresh failure")
        self.instrument_requests.append(
            (str(venue), None if client_id is None else str(client_id))
        )
        return None


def test_adapter_refresh_gate_is_bucketed_per_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5m and 15m share one Polymarket adapter per timeframe but the refresh
    throttle must be bucketed per client: refreshing 15m reject does not suppress
    the 5m client's load, and vice versa."""
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    strategy = _TwoTimeframeStrategy()
    strategy.registry = _FakeRegistry()
    t0 = _now()

    # Seed the 15m bucket as freshly consumed but leave 5m bucket never refreshed.
    life._ADAPTER_REFRESH_AT_BY_CLIENT["POLYMARKET-15M"] = t0
    refreshed = life._request_instrument_refresh(cast(Any, strategy), now=t0)
    # Only the never-refreshed 5m client is due; 15m is inside its window.
    assert refreshed == 1
    assert strategy.instrument_requests == [("POLYMARKET", "POLYMARKET-5M")]

    # Now flip: 5m recently consumed, 15m elapsed. Only 15m refreshes.
    strategy.instrument_requests.clear()
    life._ADAPTER_REFRESH_AT_BY_CLIENT["POLYMARKET-5M"] = t0
    life._ADAPTER_REFRESH_AT_BY_CLIENT["POLYMARKET-15M"] = t0 - timedelta(seconds=301)
    refreshed = life._request_instrument_refresh(cast(Any, strategy), now=t0)
    assert refreshed == 1
    assert strategy.instrument_requests == [("POLYMARKET", "POLYMARKET-15M")]

    # An already-refreshed client stays throttled even when the other re-arms.
    refreshed = life._request_instrument_refresh(cast(Any, strategy), now=t0)
    assert refreshed == 0


def test_failed_refresh_does_not_consume_per_client_throttle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A request_instruments failure must not consume that client's throttle:
    the next heartbeat can retry immediately instead of waiting out 300s."""
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    strategy = _TwoTimeframeStrategy()
    strategy.registry = _FakeRegistry()
    t0 = _now()

    strategy._raise_on_request = True
    assert life._request_instrument_refresh(cast(Any, strategy), now=t0) == 0
    strategy._raise_on_request = False

    # No throttle was consumed: a fresh dispatch one second later succeeds.
    assert (
        life._request_instrument_refresh(
            cast(Any, strategy), now=t0 + timedelta(seconds=1)
        )
        == 2
    )
    assert len(strategy.instrument_requests) == 2


def test_single_refresh_serves_many_awaiting_conditions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple conditions under one reconnect episode must coalesce into a
    single adapter refresh per client — never one full venue pop per condition."""
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        MarketSubscriptionState,
    )

    strategy = _TwoTimeframeStrategy()
    strategy.registry = _FakeRegistry()
    state = MarketSubscriptionState()
    for i in range(40):
        state.awaiting_book_sides_by_condition[f"cond-{i}"] = ("UP",)
    strategy._subscription_state = state
    t0 = _now()

    assert life._data_stall_refresh_due(cast(Any, strategy), now=t0) is True
    refreshed = life._request_instrument_refresh(cast(Any, strategy), now=t0)
    # 40 conditions, 2 clients -> exactly 2 refresh dispatches, not 40.
    assert refreshed == 2
    assert len(strategy.instrument_requests) == 2


def test_discovery_attach_skips_suppressed_no_book_condition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An abandoned (no-book) condition inside the suppression window must not
    be re-added to the active set by discovery.

    issue69: abandon leaves a _NO_BOOK_SUPPRESS_SEC marker; discovery used to
    unconditionally add every returned condition to _active_condition_ids, so
    the next heartbeat found an active condition with no subscribe intent and
    every readiness miss / recovery attempt was an invalid active-but-
    unsubscribed state.
    """
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    monkeypatch.setattr(
        life,
        "_discover_new_conditions",
        lambda registry, assets, timeframes: ["cond-1"],
    )
    strategy = _DiscoveryStrategy()
    strategy.registry = _FakeRegistry()
    strategy._no_book_abandoned_at_by_condition["cond-1"] = _now()
    t0 = _now()

    attached = life._attach_discovered_conditions(cast(Any, strategy), ["cond-1"], now=t0)

    assert attached == 0
    assert "cond-1" not in strategy._active_condition_ids
    assert strategy.subscribed == []
    assert strategy.instrument_requests == []


def test_discovery_attach_skips_suppressed_and_keeps_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    monkeypatch.setattr(
        life,
        "_discover_new_conditions",
        lambda registry, assets, timeframes: ["cond-suppressed", "cond-fresh"],
    )
    strategy = _DiscoveryStrategy()
    strategy.registry = _FakeRegistry()
    strategy._no_book_abandoned_at_by_condition["cond-suppressed"] = _now()
    t0 = _now()

    attached = life._attach_discovered_conditions(
        cast(Any, strategy),
        ["cond-suppressed", "cond-fresh"],
        now=t0,
    )

    assert attached == 1
    assert "cond-suppressed" not in strategy._active_condition_ids
    assert "cond-fresh" in strategy._active_condition_ids
    assert strategy.subscribed == ["cond-fresh"]


def test_discovery_attach_readds_after_suppression_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the no-book suppression window elapses, discovery may attach the
    condition again and establish subscribe intent (fresh book generation)."""
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    monkeypatch.setattr(
        life,
        "_discover_new_conditions",
        lambda registry, assets, timeframes: ["cond-1"],
    )
    strategy = _DiscoveryStrategy()
    strategy.registry = _FakeRegistry()
    abandoned_at = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    strategy._no_book_abandoned_at_by_condition["cond-1"] = abandoned_at

    late = abandoned_at + timedelta(seconds=_NO_BOOK_SUPPRESS_SEC + 1)
    attached = life._attach_discovered_conditions(cast(Any, strategy), ["cond-1"], now=late)

    assert attached == 1
    assert "cond-1" in strategy._active_condition_ids
    assert strategy.subscribed == ["cond-1"]
    assert "cond-1" not in strategy._no_book_abandoned_at_by_condition


def test_discovery_attach_skips_suppression_via_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end heartbeat path: suppressed condition stays inactive and no
    wire/venue refresh is issued; a fresh condition still attaches."""
    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    monkeypatch.setattr(
        life,
        "_discover_new_conditions",
        lambda registry, assets, timeframes: ["cond-suppressed", "cond-fresh"],
    )
    strategy = _DiscoveryStrategy()
    strategy.registry = _FakeRegistry()
    strategy._no_book_abandoned_at_by_condition["cond-suppressed"] = _now()
    t0 = _now()

    life._discover_and_subscribe_new_markets(cast(Any, strategy), now=t0)

    assert "cond-suppressed" not in strategy._active_condition_ids
    assert "cond-fresh" in strategy._active_condition_ids
    assert strategy.subscribed == ["cond-fresh"]
    # Only fresh condition drives the shared venue instrument refresh.
    assert strategy.instrument_requests == [("POLYMARKET", "POLYMARKET-5M")]



def test_refresh_failure_logs_pending_and_last_request_observability(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A failed instrument refresh must keep failure observability: the client,
    pending instrument count and last request time flow into the log."""
    import logging

    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    strategy = _TwoTimeframeStrategy()
    strategy.registry = _FakeRegistry()
    t0 = _now()
    strategy._raise_on_request = True
    # Two active conditions with pending instruments for the 5m client.
    strategy._active_condition_ids = {"cond-a", "cond-b"}
    state = MarketSubscriptionState()
    state.pending_instrument_ids = {
        "cond-a-up.POLYMARKET",
        "cond-b-up.POLYMARKET",
    }
    strategy._subscription_state = state

    with caplog.at_level(logging.INFO, logger=life.logger.name):
        assert life._request_instrument_refresh(cast(Any, strategy), now=t0) == 0

    failed = [r for r in caplog.records if r.message == "adapter_instrument_refresh_failed"]
    assert failed
    rec = failed[0]
    assert rec.client_id == "POLYMARKET-5M" or rec.client_id == "POLYMARKET-15M"
    # Both clients are due; their failure logs each carry the pending count.
    assert all("pending_instrument_count" in r.__dict__ for r in failed)
    # Request never succeeded, so last_request_at stays None (retry immediate).
    assert all(r.__dict__.get("last_request_at") is None for r in failed)


def test_discovery_error_is_warning_not_debug(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A discovery failure must be visibly warn-level (previous debug hid it)."""
    import logging

    monkeypatch.setenv("POLYSIGNAL_MARKET_DISCOVERY", "1")
    calls: list[int] = []

    def boom(registry: object, assets: object, timeframes: object) -> list[str]:
        calls.append(1)
        raise RuntimeError("gamma down")

    monkeypatch.setattr(life, "_discover_new_conditions", boom)
    strategy = _DiscoveryStrategy()
    strategy.registry = _FakeRegistry()

    with caplog.at_level(logging.WARNING, logger=life.logger.name):
        life._discover_and_subscribe_new_markets(cast(Any, strategy), now=_now())

    assert calls == [1]
    assert strategy.subscribed == []
    assert strategy.instrument_requests == []
    warning = next(
        (r for r in caplog.records if r.message == "market_discovery_error"), None
    )
    assert warning is not None
    assert warning.levelno == logging.WARNING


def test_timeout_conditions_shorten_adapter_refresh_cadence() -> None:
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        MarketSubscriptionState,
    )

    strategy = _TwoTimeframeStrategy()
    strategy.registry = _FakeRegistry()
    state = MarketSubscriptionState()
    condition_id = "cond-1"
    state.awaiting_book_sides_by_condition[condition_id] = ("UP",)
    state.adapter_replay_started_at_by_condition[condition_id] = _now()
    state.book_recovery_attempt_count_by_condition[condition_id] = 1
    strategy._subscription_state = state
    t0 = _now()

    # Initial refresh still due immediately; then the timeout cadence is 120s.
    assert life._data_stall_refresh_due(cast(Any, strategy), now=t0) is True
    life._request_instrument_refresh(cast(Any, strategy), now=t0)
    assert (
        life._data_stall_refresh_due(
            cast(Any, strategy), now=t0 + timedelta(seconds=90)
        )
        is False
    )
    assert (
        life._data_stall_refresh_due(
            cast(Any, strategy), now=t0 + timedelta(seconds=121)
        )
        is True
    )


def test_non_timeout_stall_keeps_five_minute_cadence() -> None:
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        MarketSubscriptionState,
    )

    strategy = _TwoTimeframeStrategy()
    strategy.registry = _FakeRegistry()
    state = MarketSubscriptionState()
    state.awaiting_book_sides_by_condition["cond-1"] = ("UP",)
    strategy._subscription_state = state
    t0 = _now()

    assert life._data_stall_refresh_due(cast(Any, strategy), now=t0) is True
    life._request_instrument_refresh(cast(Any, strategy), now=t0)
    assert (
        life._data_stall_refresh_due(
            cast(Any, strategy), now=t0 + timedelta(seconds=121)
        )
        is False
    )
    assert (
        life._data_stall_refresh_due(
            cast(Any, strategy), now=t0 + timedelta(seconds=301)
        )
        is True
    )
