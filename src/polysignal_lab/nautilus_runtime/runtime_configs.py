from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from pydantic import TypeAdapter

from polysignal_lab.config import Settings
from polysignal_lab.domain.market import Market


_MARKETS_ADAPTER: Final = TypeAdapter(tuple[Market, ...])


@dataclass(frozen=True, slots=True)
class PolySignalStrategyConfig:
    settings_json: str
    markets_json: str
    condition_ids: tuple[str, ...]
    strategy_names: tuple[str, ...]
    strategy_name: str = "polysignal"
    strategy_id: str = "PolySignal-polysignal"
    order_id_tag: str = "polysignal"

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
        )

    def settings(self) -> Settings:
        settings = Settings.model_validate_json(self.settings_json)
        settings.strategies.set_explicit_strategy_names(tuple(self.strategy_names))
        return settings

    def markets(self) -> tuple[Market, ...]:
        return _MARKETS_ADAPTER.validate_json(self.markets_json)


@dataclass(frozen=True, slots=True)
class MarketRotationActorConfig:
    settings_json: str
    markets_json: str
    actor_id: str = "PolySignal-MarketRotation"

    @classmethod
    def build(
        cls,
        settings: Settings,
        markets: tuple[Market, ...],
    ) -> MarketRotationActorConfig:
        return cls(
            settings_json=settings.model_dump_json(),
            markets_json=_MARKETS_ADAPTER.dump_json(markets).decode(),
        )

    def settings(self) -> Settings:
        return Settings.model_validate_json(self.settings_json)

    def markets(self) -> tuple[Market, ...]:
        return _MARKETS_ADAPTER.validate_json(self.markets_json)
