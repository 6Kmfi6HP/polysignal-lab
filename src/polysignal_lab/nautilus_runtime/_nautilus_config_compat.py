# Project-side compatibility implementation of configuration symbols removed
# in nautilus_trader 2.0.0rc3 (upgrade migration, issue69 root fix).
#
# The 2.0 wheel removed the Python config modules `nautilus_trader.common.config`
# and `nautilus_trader.trading.config` and their `ActorConfig` / `StrategyConfig`
# base models (1.x: msgspec.Struct subclasses with `json()` serialization).
# Project configs (`MarketRotationActorConfig`, `RecordedMarketDataActorConfig`,
# `PolySignalStrategyConfig`) subclass them, so minimal equivalents are
# re-provided here. The pyo3 `StrategyConfig` that now lives in
# `_libnautilus.trading` cannot be subclassed with `frozen=True`, so it is not
# usable as a base — the msgspec version is.
#
# Field types are JSON-primitive (str instead of the 1.x StrategyId/TimeInForce
# newtypes) so `json()` needs no encoding hook.
#
# Never modify upstream / @refs; this module is project-owned.

from __future__ import annotations

from typing import Any

import msgspec


def _json(self: msgspec.Struct) -> bytes:
    """Return serialized JSON encoded bytes."""
    return msgspec.json.encode(self)


class ActorConfig(msgspec.Struct, kw_only=True, frozen=True):
    """
    The base model for all actor configurations.

    Mirrors the 1.x `nautilus_trader.common.config.ActorConfig` contract
    (msgspec.Struct with kw_only + frozen; `component_id` typed as str here
    because 2.0 removed the ComponentId newtype from this surface).
    """

    component_id: str | None = None
    log_events: bool = True
    log_commands: bool = True

    json = _json

    @classmethod
    def parse(cls, raw: bytes | str) -> Any:
        """Return a decoded object of the given `cls`."""
        return msgspec.json.decode(raw, type=cls)


class StrategyConfig(msgspec.Struct, kw_only=True, frozen=True):
    """
    The base model for all trading strategy configurations.

    Mirrors the 1.x `nautilus_trader.trading.config.StrategyConfig` contract
    with JSON-primitive field types.
    """

    strategy_id: str | None = None
    order_id_tag: str | None = None
    use_uuid_client_order_ids: bool = False
    use_hyphens_in_client_order_ids: bool = True
    oms_type: str | None = None
    external_order_claims: list[str] | None = None
    manage_contingent_orders: bool = False
    manage_gtd_expiry: bool = False
    manage_stop: bool = False
    market_exit_interval_ms: int = 100
    market_exit_max_attempts: int = 100
    market_exit_time_in_force: str = "GTC"
    market_exit_reduce_only: bool = True
    log_events: bool = True
    log_commands: bool = True
    log_rejected_due_post_only_as_warning: bool = True

    json = _json

    @classmethod
    def parse(cls, raw: bytes | str) -> Any:
        """Return a decoded object of the given `cls`."""
        return msgspec.json.decode(raw, type=cls)
