from __future__ import annotations

import json

from nautilus_trader.common.config import ActorConfig
from nautilus_trader.trading.config import StrategyConfig
from pydantic import TypeAdapter

from polysignal_lab.config import Settings
from polysignal_lab.domain.market import Market


_MARKETS_ADAPTER = TypeAdapter(tuple[Market, ...])


def importable_config_dict(config: StrategyConfig | ActorConfig) -> dict[str, object]:
    """JSON-safe dict for ImportableStrategy/ActorConfig payloads."""
    return json.loads(config.json())


class PolySignalStrategyConfig(StrategyConfig, frozen=True):
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
    ) -> PolySignalStrategyConfig:
        return cls(
            settings_json=settings.model_dump_json(),
            markets_json=_MARKETS_ADAPTER.dump_json(markets).decode(),
            condition_ids=tuple(condition_ids),
            strategy_names=tuple(settings.strategies.explicit_strategy_names()),
            strategy_id="PolySignal-polysignal",
            order_id_tag="polysignal",
        )

    def settings(self) -> Settings:
        settings = Settings.model_validate_json(self.settings_json)
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
