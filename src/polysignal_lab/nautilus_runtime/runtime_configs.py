from __future__ import annotations

import hashlib
import json

from pydantic import TypeAdapter

from polysignal_lab.config import Settings
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module

_common_config = load_nautilus_module("nautilus_trader.common.config")
_trading_config = load_nautilus_module("nautilus_trader.trading.config")
ActorConfig = _common_config.ActorConfig
StrategyConfig = _trading_config.StrategyConfig


_MARKETS_ADAPTER = TypeAdapter(tuple[Market, ...])


def _order_id_tag(name: str) -> str:
    canonical = name.strip()
    base = canonical.replace("_", "") or "alpha"
    # Hash long names so legacy 20-char truncation cannot silently collide,
    # including underscore-heavy spellings with the same stripped base.
    if len(canonical) <= 14:
        return base
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:6]
    return f"{base[:14]}{digest}"


def importable_config_dict(config: StrategyConfig | ActorConfig) -> dict[str, object]:
    """Return JSON-safe data for ImportableStrategy/ActorConfig payloads."""
    return json.loads(config.json())


class PolySignalStrategyConfig(StrategyConfig, frozen=True):
    """One Importable config per enabled alpha (not a composite multi-alpha host)."""

    settings_json: str
    markets_json: str
    condition_ids: tuple[str, ...] = ()
    strategy_names: tuple[str, ...] = ()
    strategy_name: str = "polysignal"

    @classmethod
    def build(
        cls,
        settings: Settings,
        markets: tuple[Market, ...],
        condition_ids: tuple[str, ...],
        *,
        strategy_name: str,
    ) -> PolySignalStrategyConfig:
        name = str(strategy_name).strip()
        if not name:
            raise ValueError("strategy_name is required for PolySignalStrategyConfig")
        # Nautilus order_id_tag must be short and unique per strategy instance
        order_tag = _order_id_tag(name)
        return cls(
            settings_json=settings.model_dump_json(),
            markets_json=_MARKETS_ADAPTER.dump_json(markets).decode(),
            condition_ids=tuple(condition_ids),
            strategy_names=(name,),
            strategy_name=name,
            strategy_id=f"PolySignal-{name}",
            order_id_tag=order_tag,
        )

    def settings(self) -> Settings:
        settings = Settings.model_validate_json(self.settings_json)
        # Keep full enabled list on Settings for observability; this host owns one alpha
        settings.strategies.set_explicit_strategy_names(tuple(self.strategy_names))
        return settings

    def markets(self) -> tuple[Market, ...]:
        return _MARKETS_ADAPTER.validate_json(self.markets_json)

    def importable_dict(self) -> dict[str, object]:
        return importable_config_dict(self)


class MarketRotationActorConfig(ActorConfig, frozen=True):
    settings_json: str
    markets_json: str
    actor_id: str = "PolySignal-MarketRotation"

    @classmethod
    def build(
        cls,
        settings: Settings,
        markets: tuple[Market, ...],
    ) -> MarketRotationActorConfig:
        actor_id = "PolySignal-MarketRotation"
        return cls(
            settings_json=settings.model_dump_json(),
            markets_json=_MARKETS_ADAPTER.dump_json(markets).decode(),
            actor_id=actor_id,
            component_id=actor_id,
        )

    def settings(self) -> Settings:
        return Settings.model_validate_json(self.settings_json)

    def markets(self) -> tuple[Market, ...]:
        return _MARKETS_ADAPTER.validate_json(self.markets_json)

    def importable_dict(self) -> dict[str, object]:
        return importable_config_dict(self)
