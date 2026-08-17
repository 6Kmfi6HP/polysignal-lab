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

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from polysignal_lab.nautilus_runtime.strategy import lifecycle as life
from polysignal_lab.nautilus_runtime.strategy.constants import (
    EVALUATION_HEARTBEAT_INTERVAL,
)


def _now() -> datetime:
    return datetime.now(UTC)


class _DiscoveryStrategy:
    """Minimal duck-typed strategy for the discovery integration point."""

    def __init__(self) -> None:
        self.registry: Any | None = None
        self._active_condition_ids: set[str] = set()
        self._subscription_assets = frozenset({"BTC"})
        self._subscription_timeframes = frozenset({"5m"})
        self._last_market_discovery_at: datetime | None = None
        self._market_discovery_enabled = True
        self.subscribed: list[str] = []
        self.cache: Any | None = None

    def _require_registry(self) -> Any:
        return self.registry

    def _refresh_asset_conditions(self) -> None:
        pass

    def _subscribe_market_conditions(self, condition_ids: list[str]) -> None:
        self.subscribed.extend(condition_ids)


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
    from types import SimpleNamespace

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
    monkeypatch.setattr(life, "_reconcile_awaiting_books_from_cache", lambda s, c, now: None)
    monkeypatch.setattr(life, "_recover_book_subscriptions", lambda s, c, now: None)
    monkeypatch.setattr(life, "trading_state_from_cache", lambda *a, **k: None)

    # The FakeClock does not implement set_timer; the heartbeat only runs its
    # body synchronously, so patch framework_now to a fixed value as well.
    monkeypatch.setattr(life, "framework_now", lambda h: _now())

    setattr(strategy, "_note_runtime_progress", lambda phase, **k: None)
    life.on_evaluation_heartbeat(cast(Any, strategy), None)

    assert "discovered" in strategy.subscribed